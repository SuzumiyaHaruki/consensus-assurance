import json
import os
import re
import shutil
from pathlib import Path
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Origin
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import write_json, redact


def strict_schema(schema):
    """Legacy mock-stage schema conversion retained until its offline fixtures migrate."""
    import copy
    schema = copy.deepcopy(schema)
    maps = {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
    children = {"items", "additionalProperties", "contains", "not", "if", "then", "else", "propertyNames"}
    alternatives = {"anyOf", "oneOf", "allOf", "prefixItems"}
    def visit(node):
        if isinstance(node, list):return [visit(v) for v in node]
        if not isinstance(node, dict):return node
        if node.get("type") == "object" and "properties" not in node:
            typed=isinstance(node.get("additionalProperties"),dict) and bool(node["additionalProperties"])
            field="value" if typed else "value_json"
            return {"type":"array", "description":node.get("description", "")+" Dictionary entries; keys must be unique. "+("Use typed values." if typed else "value_json encodes a JSON value."), "items":
                {"type":"object","properties":{"key":visit({"type":"string",**node.get("propertyNames",{})}),field:visit(node["additionalProperties"]) if typed else {"type":"string"}},
                 "required":["key",field],"additionalProperties":False}}
        out = {}
        for key, value in node.items():
            if key in {"default", "x-controller-derived"}:continue
            if key in maps and isinstance(value, dict):
                out[key] = {name:visit(child) for name,child in value.items() if not (key=="properties" and child.get("x-controller-derived"))}
            elif key in children or key in alternatives:out[key] = visit(value)
            else:out[key] = value
        if out.get("type") == "object":
            out["required"] = list(out.get("properties",{}))
            out["additionalProperties"] = False
        return out
    return visit(schema)


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
        required = ["--output-schema", "--output-last-message", "--skip-git-repo-check", "--json", "--ignore-user-config", "--ignore-rules"]
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
            str(root/"state.json"):"read",str(root/"native-submission.schema.json"):"read",
            str(codex_home/"tmp"/"arg0"):"read",str(Path(executable).resolve().parent):"read"}
        inline="{"+",".join(json.dumps(key)+"="+json.dumps(value) for key,value in filesystem.items())+"}"
        environment={"GOCACHE":str(directory/"go-cache"),"GOMODCACHE":str(directory/"go-mod-cache")}
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
        """Fail closed before model access if the local CLI cannot enforce this profile."""
        source=runner.root/"native-source"
        sample=next((p for p in source.rglob("*") if p.is_file() and not p.is_symlink()),None)
        if sample is None:
            return False, []
        canary=runner.root/"native-private-canary"
        forbidden=source/".native-write-canary"
        allowed=directory/".native-write-canary"
        canary.write_text("private probe")
        def run(args):
            return runner.run([*self.sandbox_command(runner.root),"sandbox","-P","ca_native",*options,"-C",str(directory),*args],
                directory,"native_permission_probe",snapshot_id,10)
        try:
            checks=[run(["cat",str(sample)]),run(["cat",str(canary)]),
                run(["sh","-c",'printf blocked > "$1"',"sh",str(forbidden)]),
                run(["sh","-c",'printf allowed > "$1"',"sh",str(allowed)])]
            permitted=(checks[0].status==ExecutionStatus.COMPLETED and checks[0].exit_code==0 and
                checks[1].exit_code!=0 and checks[2].exit_code!=0 and
                checks[3].status==ExecutionStatus.COMPLETED and checks[3].exit_code==0 and
                allowed.read_text()=="allowed" and not forbidden.exists())
            return permitted,checks
        finally:
            canary.unlink(missing_ok=True)
            allowed.unlink(missing_ok=True)
            forbidden.unlink(missing_ok=True)

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
        permitted,permission_checks=self.permission_probe(runner,directory,snapshot_id,options)
        if not permitted:
            check=CheckRun(action="native_agent",cwd=str(directory),snapshot_id=snapshot_id,
                status=ExecutionStatus.ERROR,reason="Native filesystem profile could not be verified; no model payload sent")
            check.parameters["permission_probe"]=[{"id":probe.id,"status":probe.status.value,"exit_code":probe.exit_code} for probe in permission_checks]
            check.artifacts=[p for probe in permission_checks for p in [probe.stdout,probe.stderr] if p]
            return check,session_id,None
        response = runner.root / "native-last-response.json"
        response.unlink(missing_ok=True)
        command = [*self.sandbox_command(runner.root), "exec"]
        if session_id:
            command += ["resume", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "--json",
                "--output-schema", str(schema), "--output-last-message", str(response)]
            command += options
            if self.reasoning_effort is not None:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            if self.model:
                command += ["-m", self.model]
            command += [session_id, "-"]
        else:
            command += ["--skip-git-repo-check",
                "--ignore-user-config", "--ignore-rules", "--json", "--output-schema", str(schema),
                "--output-last-message", str(response)]
            command += options
            if self.reasoning_effort is not None:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            if self.model:
                command += ["-m", self.model]
            command += ["-"]
        check = runner.run(command, directory, "native_agent", snapshot_id, timeout, stdin=prompt)
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
        check.parameters.update({"native_session_id":actual_id or session_id,
            "native_turn_completed":bool(completed),
            "native_tool_events":sum(e.get("type", "").startswith("item.") for e in events),
            "native_usage":completed[-1].get("usage") if completed else None,
            "native_sandbox":"ca_native: root deny, captured source/evidence read, draft write, tool network off",
            "permission_probe":[{"id":probe.id,"status":probe.status.value,"exit_code":probe.exit_code} for probe in permission_checks],
            "agent_model":self.model or "CLI default; inspect raw native events",
            "agent_reasoning_effort":self.reasoning_effort or "CLI default"})
        if check.status != ExecutionStatus.COMPLETED or not completed:
            if check.status == ExecutionStatus.COMPLETED:
                check.status = ExecutionStatus.ERROR
                check.reason = "Native turn lacked a completed event"
            return check, actual_id or session_id, None
        try:
            result = json.loads(response.read_text())
            if not isinstance(result, dict) or set(result) != {"submission", "summary"}:
                raise ValueError("Native final response has the wrong shape")
            return check, actual_id or session_id, result
        except (OSError, ValueError) as exc:
            check.status = ExecutionStatus.ERROR
            check.reason = "Native final response invalid: " + str(exc)
            return check, actual_id or session_id, None

class MockAgent:
    name = "mock"
    mock = True
    def __init__(self, fixture=None):
        self.fixture = Path(fixture).resolve() if fixture else None
        self.cursor = 0
        self.responses = json.loads(self.fixture.read_text()) if self.fixture else []

    def probe(self, runner):
        return {"available": bool(self.responses), "version": "mock/2", "checks": [], "reason": "Explicit fixture playback; framework testing only"}

    def analyze(self, runner, prompt, directory, snapshot_id, timeout, response_type):
        import sys
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "prompt.txt").write_text(prompt)
        if self.cursor >= len(self.responses):
            return CheckRun(action="agent", cwd=str(directory), snapshot_id=snapshot_id, origin=Origin.MOCK,
                status=ExecutionStatus.ERROR, reason="Mock fixture exhausted or unspecified"), None
        item = self.responses[self.cursor]; self.cursor += 1
        if response_type.__name__ == "BuildReply" and "behavior" in item:
            item={"bundle":item,"gap":"","requests":[]}
        check = runner.run([sys.executable, "-c", "print('explicit mock fixture playback')"], directory, "agent", snapshot_id, timeout)
        check.origin = Origin.MOCK; check.tool_version = "mock/2"
        write_json(directory / "response.json", item)
        write_json(directory / "decoded-response.json", item)
        try:
            return check, response_type.model_validate(item)
        except ValueError as exc:
            if hasattr(exc, "errors"):
                write_json(directory / "validation-details.json", exc.errors(include_url=False, include_context=False))
            check.status = ExecutionStatus.ERROR; check.reason = "Structured agent output is invalid"
            (directory / "validation-error.txt").write_text(str(exc))
            return check, None
