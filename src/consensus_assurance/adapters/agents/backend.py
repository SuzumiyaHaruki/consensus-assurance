import json
import re
from pathlib import Path
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Origin
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import write_json, redact

def strict_schema(schema):
    """Encode open dictionaries as explicit JSON-valued key entries, preserving their values."""
    import copy
    schema = copy.deepcopy(schema)
    maps = {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
    children = {"items", "additionalProperties", "contains", "not", "if", "then", "else", "propertyNames"}
    alternatives = {"anyOf", "oneOf", "allOf", "prefixItems"}
    def visit(node):
        if isinstance(node, list):
            return [visit(v) for v in node]
        if not isinstance(node, dict):
            return node
        if node.get("type") == "object" and "properties" not in node:
            typed=isinstance(node.get("additionalProperties"),dict) and bool(node["additionalProperties"])
            field="value" if typed else "value_json"
            return {"type":"array", "description":node.get("description", "")+" Dictionary entries; keys must be unique. "+("Use typed values." if typed else "value_json encodes a JSON value."), "items":
                {"type":"object","properties":{"key":visit({"type":"string",**node.get("propertyNames",{})}),field:visit(node["additionalProperties"]) if typed else {"type":"string"}},
                 "required":["key",field],"additionalProperties":False}}
        out = {}
        for key, value in node.items():
            # Defaults are local model annotations, not constraints on wire values.
            # Preserve properties actually named "default" and literal enum/const data.
            if key in {"default", "x-controller-derived"}:
                continue
            if key in maps and isinstance(value, dict):
                out[key] = {name:visit(child) for name,child in value.items() if not (key=="properties" and child.get("x-controller-derived"))}
            elif key in children or key in alternatives:
                out[key] = visit(value)
            else:
                out[key] = value
        if out.get("type") == "object":
            out["required"] = list(out.get("properties",{}))
            out["additionalProperties"] = False
        return out
    return visit(schema)


def wire_value(value, schema, decode=False, root=None):
    root = root or schema
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].split("/")[1:]: target = target[part]
        return wire_value(value,target,decode,root)
    if "anyOf" in schema:
        if value is None: return None
        options = [x for x in schema["anyOf"] if x.get("type") != "null"]
        for item in options:
            if "$ref" in item or item.get("type") in {"object","array"}:
                return wire_value(value,item,decode,root)
        return value
    if schema.get("type") == "object" and "properties" not in schema:
        typed=isinstance(schema.get("additionalProperties"),dict) and bool(schema["additionalProperties"])
        field="value" if typed else "value_json"
        if decode:
            if not isinstance(value,list) or any(not isinstance(x,dict) or set(x)!={"key",field} for x in value):
                raise ValueError("Expected dictionary key/value_json entries")
            if any(not isinstance(x["key"],str) or (not typed and not isinstance(x[field],str)) for x in value):
                raise ValueError("Dictionary wire keys and JSON encodings must be strings")
            if len({x["key"] for x in value}) != len(value): raise ValueError("Duplicate dictionary key")
            return {x["key"]:wire_value(x[field],schema["additionalProperties"],True,root) if typed else json.loads(x[field]) for x in value}
        return [{"key":k,field:wire_value(v,schema["additionalProperties"],False,root) if typed else json.dumps(v,ensure_ascii=False)} for k,v in value.items()]
    if schema.get("type") == "object" and isinstance(value,dict):
        return {k:wire_value(v,schema.get("properties",{}).get(k,{}),decode,root) for k,v in value.items() if decode or not schema.get("properties",{}).get(k,{}).get("x-controller-derived")}
    if schema.get("type") == "array" and isinstance(value,list):
        return [wire_value(v,schema.get("items",{}),decode,root) for v in value]
    return value


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

    def __init__(self, reasoning_effort: str | None = None):
        self.reasoning_effort = reasoning_effort

    def probe(self, runner):
        version = runner.run(["codex", "--version"], runner.root, "agent_probe", "environment", 10)
        help_run = runner.run(["codex", "exec", "--help"], runner.root, "agent_capabilities", "environment", 10)
        text = output(help_run)
        required = ["--sandbox", "--output-schema", "--output-last-message", "--skip-git-repo-check", "--ephemeral"]
        self.available = version.status == ExecutionStatus.COMPLETED and version.exit_code == 0 and all(s in text for s in required)
        self.version = output(version).strip()
        self.missing = version.status == ExecutionStatus.TOOL_MISSING
        return {"available": self.available, "version": self.version, "checks": [version, help_run], "reason": "Required CLI flags detected" if self.available else "Codex missing or required capabilities unavailable"}

    def analyze(self, runner, prompt, directory, snapshot_id, timeout, response_type):
        directory.mkdir(parents=True, exist_ok=True)
        schema = directory / "proposal.schema.json"
        write_json(schema, strict_schema(response_type.model_json_schema()))
        (directory / "prompt.txt").write_text(prompt)
        # This directory contains no target AGENTS.md; use the existing authentication only.
        if not getattr(self, "available", False):
            return CheckRun(action="agent", cwd=str(directory), snapshot_id=snapshot_id,
                status=ExecutionStatus.TOOL_MISSING if getattr(self, "missing", False) else ExecutionStatus.ERROR,
                reason="Codex capability probe failed"), None
        result_path = directory / "response.json"
        command = ["codex", "exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
                   "--output-schema", str(schema), "--output-last-message", str(result_path)]
        if self.reasoning_effort is not None:
            command.extend(["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)])
        command.append("-")
        check = runner.run(command, directory, "agent", snapshot_id, timeout, stdin=prompt)
        check.tool_version = self.version
        if check.stderr and Path(check.stderr).is_file():
            reported=Path(check.stderr).read_text(errors='replace')
            model=re.search(r'(?m)^model:\s*(\S.*?)\s*$',reported)
            effort=re.search(r'(?m)^reasoning effort:\s*(\S.*?)\s*$',reported)
            if model:check.parameters['agent_model']=model.group(1)
            if effort:check.parameters['agent_reasoning_effort']=effort.group(1)
        if check.status != ExecutionStatus.COMPLETED:
            return check, None
        if check.exit_code != 0:
            text = output(check)
            check.status = classify_failure(text)
            check.reason = failure_reason(text)
            return check, None
        raw = result_path.read_text() if result_path.exists() else ""
        (directory / "raw-response.txt").write_text(redact(raw))
        if result_path.exists():
            result_path.write_text(redact(raw))
        try:
            decoded = wire_value(json.loads(raw), response_type.model_json_schema(), decode=True)
            write_json(directory / "decoded-response.json", decoded)
            return check, response_type.model_validate(decoded)
        except ValueError as exc:
            if hasattr(exc, "errors"):
                write_json(directory / "validation-details.json", exc.errors(include_url=False, include_context=False))
            (directory / "validation-error.txt").write_text(str(exc))
            check.status = ExecutionStatus.ERROR
            check.reason = "Structured agent output is invalid"
            return check, None


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
