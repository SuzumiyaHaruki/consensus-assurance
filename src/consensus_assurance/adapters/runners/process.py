import os
import signal
import subprocess
import time
from pathlib import Path
from consensus_assurance.core.types import CheckRun, ExecutionStatus, now
from consensus_assurance.adapters.storage.files import redact, write_json


class ProcessRunner:
    """Run adapter-owned argv, never model-produced shell commands."""
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.deadline = None
        self.active_action_id = None

    def run(self, command: list[str], cwd: Path, action: str, snapshot_id: str,
            timeout: float = 60, stdin: str | None = None, env: dict | None = None) -> CheckRun:
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            return CheckRun(action=action, command=command, cwd=str(cwd), snapshot_id=snapshot_id,
                status=ExecutionStatus.CANCELLED, reason="Total runtime budget exhausted before execution")
        cwd = cwd.resolve()
        if not cwd.is_relative_to(self.root):
            raise ValueError("Execution directory must be inside the run directory")
        cwd.mkdir(parents=True, exist_ok=True)
        run = CheckRun(action=action, command=command, cwd=str(cwd), snapshot_id=snapshot_id, pending_action_id=self.active_action_id)
        logs = self.root / "logs" / run.id
        logs.mkdir(parents=True)
        run.transition(ExecutionStatus.RUNNING)
        run.started_at = now()
        write_json(logs / "check.json", run)
        process = None
        try:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                start_new_session=True, env=env)
            out, err = process.communicate(stdin, timeout=timeout)
            run.exit_code = process.returncode
            run.transition(ExecutionStatus.COMPLETED)
        except FileNotFoundError as exc:
            out, err = "", str(exc)
            run.transition(ExecutionStatus.TOOL_MISSING)
            run.reason = "Executable not found"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
            run.exit_code = process.returncode
            run.transition(ExecutionStatus.TIMEOUT)
            run.reason = "Action timeout exceeded; process group killed"
        except KeyboardInterrupt:
            if process:
                os.killpg(process.pid, signal.SIGKILL)
                out, err = process.communicate()
                run.exit_code = process.returncode
            else:
                out, err = "", "Interrupted before start"
            run.transition(ExecutionStatus.CANCELLED)
            run.reason = "User cancelled action"
        except OSError as exc:
            out, err = "", str(exc)
            run.transition(ExecutionStatus.ERROR)
            run.reason = "Process could not start"
        finally:
            if process:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        run.ended_at = now()
        run.stdout, run.stderr = str(logs / "stdout.log"), str(logs / "stderr.log")
        Path(run.stdout).write_text(redact(out))
        Path(run.stderr).write_text(redact(err))
        write_json(logs / "check.json", run)
        return run


def output(run: CheckRun) -> str:
    return "\n".join(Path(p).read_text() for p in (run.stdout, run.stderr) if p and Path(p).is_file())
