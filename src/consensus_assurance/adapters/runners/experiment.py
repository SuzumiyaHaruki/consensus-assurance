import json
import os
import shutil
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
    source=workspace.parent.parent.parent/'source'
    input_manifest=None
    if source.is_dir() and workspace.name=='workspace':
        from consensus_assurance.adapters.storage.workspace_delta import save_delta
        input_manifest=save_delta(source,workspace,snapshot_id)
    try:
        argv = sandbox_command(command, workspace, mode, adapter.read_only_roots() if adapter else ())
    except FileNotFoundError as exc:
        return CheckRun(action=action, cwd=str(workspace), snapshot_id=snapshot_id,
            status=ExecutionStatus.TOOL_MISSING, reason=str(exc),artifacts=[str(input_manifest)] if input_manifest else [])
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
    if input_manifest:
        check.artifacts.extend([str(input_manifest),str(save_delta(source,workspace,snapshot_id,phase='outcome'))])
    return check


def extract_events(check):
    """Extract complete CA_EVENT lines, preserving runner-provided stream ownership."""
    events = []
    if not check.stdout or not Path(check.stdout).is_file():
        return events

    marker = "CA_EVENT "
    buffers = {}

    def parse_line(line, stream=None, location=None):
        if marker not in line:
            return
        raw = line.split(marker, 1)[1].strip()
        provenance = {'stream':stream,'location':location}
        try:
            event = json.loads(raw)
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                raise ValueError("Event must be an object with an event name")
            if stream is not None:
                event['_ca_stream'] = stream
            event['_ca_observation'] = provenance
            events.append(event)
        except ValueError as exc:
            events.append({"event":"invalid_observation","raw":raw,"reason":str(exc),
                "_ca_stream":stream,"_ca_observation":provenance})

    for physical, line in enumerate(Path(check.stdout).read_text().splitlines(keepends=True), 1):
        try:
            outer = json.loads(line)
        except (ValueError, TypeError):
            parse_line(line.rstrip('\r\n'), location={'line':physical})
            continue
        if not isinstance(outer,dict) or not isinstance(outer.get('Output'),str):
            continue
        # Package-level output is a real, separate stream. Never guess that it
        # belongs to a concurrently reported test stream.
        stream = json.dumps([outer.get('Package'),outer.get('Test') if 'Test' in outer else None],
            ensure_ascii=False,separators=(',',':'))
        buffers[stream] = buffers.get(stream,'') + outer['Output']
        while '\n' in buffers[stream]:
            complete,buffers[stream] = buffers[stream].split('\n',1)
            parse_line(complete.rstrip('\r'),stream,{'line':physical,'stream':stream})
    for stream,tail in buffers.items():
        if marker in tail:
            parse_line(tail,stream,{'line':'end-of-stream','stream':stream})
    return events
