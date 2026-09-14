import json
import os
import shutil
import sys
from pathlib import Path
from consensus_assurance.core.types import ExecutionStatus, CheckRun
from consensus_assurance.adapters.runners.process import output


def clean_environment(workspace, adapter=None):
    result = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "JAVA_HOME") if k in os.environ}
    cache = workspace / ".execution"
    cache.mkdir(exist_ok=True)
    result.update({"HOME": str(cache), "TMPDIR": str(cache), "PYTHONDONTWRITEBYTECODE": "1"})
    if adapter:
        result.update(adapter.environment(workspace))
    return result


def sandbox_command(command, workspace, mode, read_only_roots=()):
    if mode == "workspace":
        return command
    executable = shutil.which("bwrap")
    if not executable:
        raise FileNotFoundError("bubblewrap is required by execution_isolation=bwrap")
    args = [executable, "--die-with-parent", "--new-session", "--ro-bind", "/", "/",
            "--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc"]
    # Only the experiment workspace is writable; raw run logs and source repositories are hidden.
    args += ["--bind", str(workspace), str(workspace)]
    for cache in read_only_roots:
        if cache.is_dir():
            args += ["--ro-bind", str(cache), str(cache)]
    exe = Path(shutil.which(command[0]) or command[0]).resolve()
    if str(exe).startswith(str(Path.home())):
        tool_root = exe.parent.parent
        args += ["--ro-bind", str(tool_root), str(tool_root)]
    args += ["--chdir", str(workspace), "--", str(exe), *command[1:]]
    return args


def run_experiment(runner, command, workspace, snapshot_id, timeout, mode, action="experiment", adapter=None):
    try:
        argv = sandbox_command(command, workspace, mode, adapter.read_only_roots() if adapter else ())
    except FileNotFoundError as exc:
        return CheckRun(action=action, cwd=str(workspace), snapshot_id=snapshot_id,
            status=ExecutionStatus.TOOL_MISSING, reason=str(exc))
    check = runner.run(argv, workspace, action, snapshot_id, timeout, env=clean_environment(workspace, adapter))
    if check.status == ExecutionStatus.COMPLETED:
        text = output(check)
        if "bwrap:" in text:
            check.status = ExecutionStatus.ERROR; check.reason = "Execution isolation, build or dependency error"
        elif adapter:
            adapter.parse_test_result(check, text)
        elif check.exit_code == 0:
            check.outcome = "tests_passed"
        else:
            check.outcome = "tests_failed"
    return check


def extract_events(check):
    events = []
    if not check.stdout or not Path(check.stdout).is_file():
        return events
    for line in Path(check.stdout).read_text().splitlines():
        if line.startswith("{"):
            try:
                outer = json.loads(line)
                line = outer.get("Output", "")
            except (ValueError, AttributeError):
                continue
        marker = "CA_EVENT "
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        try:
            event = json.loads(raw)
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                raise ValueError("Event must be an object with an event name")
            events.append(event)
        except ValueError:
            events.append({"event": "invalid_observation", "raw": raw})
    return events


def prerequisites(events, ordered):
    if ordered and not isinstance(ordered[0],str):
        from consensus_assurance.workflow.observations import match_prerequisites
        result = match_prerequisites(events,ordered)
        return result["status"] == "matched", result["reason"]
    names = [e["event"] for e in events]
    cursor = 0
    for required in ordered:
        try:
            cursor = names.index(required, cursor) + 1
        except ValueError:
            return False, "Required event order was not established: " + " -> ".join(ordered)
    return True, "Required event order observed; legality still requires source and environment review"
