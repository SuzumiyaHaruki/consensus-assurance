import json
import os
import re
import shutil
from pathlib import Path
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Origin
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import write_json, redact


def classify_failure(text: str) -> ExecutionStatus:
    low = text.lower()
    if any(s in low for s in ["insufficient_quota", "quota exceeded", "usage limit", "rate limit", "quota exhausted", "credits exhausted"]):
        return ExecutionStatus.QUOTA_EXHAUSTED
    if any(s in low for s in ["login required", "not logged in", "please log in", "authentication required", "unauthorized", "401", "run codex login"]):
        return ExecutionStatus.LOGIN_REQUIRED
    return ExecutionStatus.ERROR


def failure_reason(text: str) -> str:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"(?m)^ERROR:\s*(?=\{)", text):
        try:
            payload, _ = decoder.raw_decode(text[match.end():])
        except ValueError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("code") == "invalid_json_schema":
            return "Agent output schema rejected (invalid_json_schema): " + redact(str(error.get("message", "")))[:1000]
    return "Agent execution blocked; inspect raw logs"


class CodexAgent:
    name = "codex"
    mock = False

    def __init__(self, reasoning_effort: str | None = None, model: str | None = None):
        self.reasoning_effort = reasoning_effort
        self.model = model

    def probe(self, runner):
        version = runner.run(["codex", "--version"], runner.root, "agent_probe", "environment", 10)
        help_run = runner.run(["codex", "exec", "--help"], runner.root, "agent_capabilities", "environment", 10)
        resume_run = runner.run(["codex", "exec", "resume", "--help"], runner.root, "agent_resume_capabilities", "environment", 10)
        text = output(help_run)
        required = ["--output-schema", "--output-last-message", "--skip-git-repo-check", "--json", "--ignore-user-config"]
        self.available = (version.status == ExecutionStatus.COMPLETED and version.exit_code == 0
            and all(s in text for s in required) and "SESSION_ID" in output(resume_run))
        self.version = output(version).strip()
        self.missing = version.status == ExecutionStatus.TOOL_MISSING
        return {"available": self.available, "version": self.version, "checks": [version, help_run, resume_run], "reason": "Native CLI session and JSONL capabilities detected" if self.available else "Codex missing or required native session capabilities unavailable"}

    def permission_options(self, root, directory):
        """Scope model-controlled commands to the captured source, draft, and retained evidence."""
        executable = shutil.which("codex")
        if not executable:
            raise FileNotFoundError("Codex executable is unavailable")
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
        filesystem={":root":"deny",":minimal":"read",":tmpdir":"deny",":slash_tmp":"deny",
            str(root/"native-source"):"read",str(directory):"write",
            str(root/"direct-checks"):"read",str(root/"native-submissions"):"read",
            str(root/"state.json"):"read",str(root/"research.json"):"read",
            str(root/"native-submission.schema.json"):"read",str(root/"product-schemas.json"):"read",
            str(root/"native-method.md"):"read",
            **{str(root/name):"read" for name in ("logs","models","findings","audit-spec","actions")},
            **{str(path):"read" for path in getattr(self,"read_only_roots",[]) if path.is_dir()},
            str(codex_home/"tmp"/"arg0"):"read",str(Path(executable).resolve().parent):"read"}
        inline="{"+",".join(json.dumps(key)+"="+json.dumps(value) for key,value in filesystem.items())+"}"
        environment={"GOCACHE":str(directory/"go-cache"),"GOMODCACHE":str(directory/"go-mod-cache"),
            "TMPDIR":str(directory/"tmp"),"GOPROXY":"off","GOSUMDB":"off","GOTOOLCHAIN":"local","GOFLAGS":"-mod=readonly"}
        environment.update(getattr(self,"tool_environment",{}))
        return ["-c",'default_permissions="ca_native"',
            "-c","permissions.ca_native.filesystem="+inline,
            "-c","permissions.ca_native.network.enabled=false",
            "-c",'shell_environment_policy.inherit="core"',
            "-c","shell_environment_policy.set={"+",".join(json.dumps(k)+"="+json.dumps(v) for k,v in environment.items())+"}",
            "-c","project_doc_max_bytes=0", "-c","tools.web_search=false"]

    def sandbox_command(self, root):
        """Hide non-path nsfs mount roots from affected Codex Linux sandbox builds."""
        try:
            affected=any(not line.split()[3].startswith("/") for line in
                Path("/proc/self/mountinfo").read_text().splitlines() if len(line.split())>4)
        except OSError:
            affected=False
        if not affected:
            return ["codex"]
        bubblewrap=shutil.which("bwrap")
        if not bubblewrap:
            raise RuntimeError("Codex sandbox requires Bubblewrap on this nsfs-mounted host")
        codex_home=Path(os.environ.get("CODEX_HOME",Path.home()/".codex")).resolve()
        return [bubblewrap,"--ro-bind","/","/","--bind","/tmp","/tmp",
            "--bind",str(root),str(root),"--bind",str(codex_home),str(codex_home),
            "--proc","/proc","--dev","/dev","--","codex"]

    def permission_probe(self, runner, directory, snapshot_id, options):
        """Positive controls and explicit denied operations; a crashed probe proves nothing."""
        source = next((p for p in (runner.root / "native-source").rglob("*") if p.is_file()), None)
        if source is None:
            return False, []
        private = runner.root / "native-private-canary"
        private.write_text("private permission canary")
        protected = [source]
        for folder in ("logs", "models", "direct-checks"):
            path = runner.root / folder / "permission-canary"
            path.parent.mkdir(exist_ok=True)
            path.write_text("retained permission canary")
            protected.append(path)
        script = directory / ".permission-probe.py"
        script.write_text(
            "import errno, pathlib, socket\n"
            "def denied(label, fn):\n"
            "    try: fn()\n"
            "    except OSError as exc:\n"
            "        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT): raise\n"
            "        print('DENIED:' + label)\n"
            "    else: raise RuntimeError('UNSAFE:' + label)\n"
            + "protected = " + repr([str(p) for p in protected]) + "\n"
            "for i, name in enumerate(protected):\n"
            "    path = pathlib.Path(name); path.read_bytes(); print('READ:' + str(i))\n"
            "    denied('write:' + str(i), lambda: path.open('a'))\n"
            + "denied('private', lambda: pathlib.Path(" + repr(str(private)) + ").read_bytes())\n"
            "denied('network', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', 9)))\n"
            + "pathlib.Path(" + repr(str(directory / '.write-control')) + ").write_text('allowed')\n"
            "print('PERMISSIONS_VERIFIED')\n")
        try:
            check = runner.run([*self.sandbox_command(runner.root), "sandbox", "-P", "ca_native", *options,
                "-C", str(directory), "/usr/bin/python3", str(script)], directory,
                "native_permission_probe", snapshot_id, 15)
            verified = check.status == ExecutionStatus.COMPLETED and check.exit_code == 0 and "PERMISSIONS_VERIFIED" in output(check)
            check.parameters['permission_result'] = 'verified' if verified else 'inconclusive_or_unsafe'
            return verified, [check]
        finally:
            for path in [private, script, directory / '.write-control', *protected[1:]]:
                path.unlink(missing_ok=True)

    def prepare(self, runner, directory, snapshot_id):
        (directory / "tmp").mkdir(parents=True, exist_ok=True)
        options = self.permission_options(runner.root, directory)
        key = (str(runner.root), tuple(options), getattr(self, 'version', 'unknown'))
        if getattr(self, '_permission_key', None) == key:
            return True, []
        permitted, checks = self.permission_probe(runner, directory, snapshot_id, options)
        if permitted:
            self._permission_key = key
        return permitted, checks

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        """Run one native Codex turn and retain the exact session and tool events."""
        directory.mkdir(parents=True, exist_ok=True)
        schema = runner.root / "native-final.schema.json"
        write_json(schema, {"type":"object","properties":{
            "submission":{"type":"string"},"summary":{"type":"string"}},
            "required":["submission","summary"],"additionalProperties":False})
        if not getattr(self, "available", False):
            return CheckRun(action="native_agent", cwd=str(directory), snapshot_id=snapshot_id,
                status=ExecutionStatus.TOOL_MISSING if getattr(self, "missing", False) else ExecutionStatus.ERROR,
                reason="Native Codex capability probe failed"), None, None
        options=self.permission_options(runner.root,directory)
        if getattr(self, '_permission_key', None) != (str(runner.root), tuple(options), getattr(self, 'version', 'unknown')):
            raise RuntimeError("Native permission profile must be prepared before reserving a model call")
        response = runner.root / "actions" / (runner.active_action_id or "standalone") / "native-response.json"
        response.parent.mkdir(parents=True, exist_ok=True)
        command = [*self.sandbox_command(runner.root), "exec"]
        if session_id:
            command += ["resume", "--skip-git-repo-check", "--ignore-user-config", "--json",
                "--output-schema", str(schema), "--output-last-message", str(response)]
            command += options
            if self.reasoning_effort is not None:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            if self.model:
                command += ["-m", self.model]
            command += [session_id, "-"]
        else:
            command += ["--skip-git-repo-check",
                "--ignore-user-config", "--json", "--output-schema", str(schema),
                "--output-last-message", str(response)]
            command += options
            if self.reasoning_effort is not None:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            if self.model:
                command += ["-m", self.model]
            command += ["-"]
        check = runner.run(command, directory, "native_agent", snapshot_id, timeout, stdin=prompt)
        return self.decode(check, response, session_id)

    def decode(self, check, response, session_id=None):
        """Decode a durable native receipt without invoking another model turn."""
        check.tool_version = getattr(self, "version", "unknown")
        events = []
        if check.stdout and Path(check.stdout).is_file():
            for line in Path(check.stdout).read_text(errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
        started = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
        actual_id = started[-1] if started else None
        if session_id and actual_id and actual_id != session_id:
            check.status = ExecutionStatus.ERROR
            check.reason = "Native session identity changed unexpectedly"
        if check.status == ExecutionStatus.COMPLETED and check.exit_code != 0:
            check.status = classify_failure(output(check))
            check.reason = failure_reason(output(check))
            if session_id and any(marker in output(check).lower() for marker in
                    ("session not found","thread not found","no session found")):
                check.parameters["native_session_unavailable"]=True
        completed = [e for e in events if e.get("type") == "turn.completed"]
        if completed and not (actual_id or session_id):
            check.status = ExecutionStatus.ERROR
            check.reason = "Native turn completed without a recoverable session identity"
        check.parameters.update({"native_session_id":actual_id or session_id,
            "native_response_path":str(response),
            "native_turn_completed":bool(completed),
            "native_tool_events":len({e['item']['id'] for e in events if e.get('type') == 'item.completed'
                and isinstance(e.get('item'),dict) and e['item'].get('id') and e['item'].get('type') in
                {'command_execution','file_change','mcp_tool_call','web_search'}}),
            "native_usage":completed[-1].get("usage") if completed else None,
            "native_sandbox":"ca_native: root deny, captured source/evidence read, draft write, tool network off",
            "permission_probe":"verified before model call; cached for this process/profile",
            "agent_model":self.model or "CLI default; inspect raw native events",
            "agent_reasoning_effort":self.reasoning_effort or "CLI default"})
        if check.status != ExecutionStatus.COMPLETED or not completed:
            if check.status == ExecutionStatus.COMPLETED:
                check.status = ExecutionStatus.ERROR
                check.reason = "Native turn lacked a completed event"
            return check, actual_id or session_id, None
        try:
            result = json.loads(response.read_text())
            if (not isinstance(result, dict) or set(result) != {"submission", "summary"}
                    or not all(isinstance(value, str) for value in result.values())):
                raise ValueError("Native final response has the wrong shape")
            return check, actual_id or session_id, result
        except (OSError, ValueError) as exc:
            check.reason = "Native final response invalid: " + str(exc)
            check.parameters["native_response_error"] = check.reason
            return check, actual_id or session_id, {"submission":"", "summary":check.reason}

class MockAgent:
    """Explicit file-product playback through the same native product boundary."""
    name = "mock"
    mock = True

    def __init__(self, fixture=None):
        self.fixture = Path(fixture).resolve() if fixture else None
        self.cursor = 0
        self.responses = json.loads(self.fixture.read_text()) if self.fixture else []
        self.available = bool(self.responses)

    def probe(self, runner):
        return {"available":self.available, "version":"native-fixture/1", "checks":[],
            "reason":"Explicit product playback; no autonomous discovery evidence"}

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        if self.cursor >= len(self.responses):
            return CheckRun(action="native_agent", status=ExecutionStatus.ERROR,
                snapshot_id=snapshot_id, origin=Origin.MOCK, reason="Native fixture exhausted"), session_id, None
        item = self.responses[self.cursor]
        self.cursor += 1
        from consensus_assurance.workflow.native import draft_file
        for name, content in item.get("files", {}).items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Fixture path escapes draft")
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            draft_file(directory, name)
        write_json(directory / "submission.json", item["submission"])
        return CheckRun(action="native_agent", cwd=str(directory), snapshot_id=snapshot_id,
            origin=Origin.MOCK, status=ExecutionStatus.COMPLETED, exit_code=0), session_id or "fixture-session", {
            "submission":"submission.json", "summary":"Explicit fixture product"}
