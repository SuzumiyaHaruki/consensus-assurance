import json
from importlib.resources import files
from pathlib import Path
from typing import Literal
from pydantic import Field
from consensus_assurance.core.types import Record, CheckRun, ExecutionStatus, Origin
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import write_json, redact


from consensus_assurance.workflow.prompts import render


def strict_schema(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            if "properties" not in schema:
                schema["properties"] = {}
            if "properties" in schema:
                schema["required"] = list(schema["properties"])
                schema["additionalProperties"] = False
        for value in schema.values():
            strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            strict_schema(value)
    return schema


def classify_failure(text: str) -> ExecutionStatus:
    low = text.lower()
    if any(s in low for s in ["insufficient_quota", "quota exceeded", "usage limit", "rate limit", "quota exhausted", "credits exhausted"]):
        return ExecutionStatus.QUOTA_EXHAUSTED
    if any(s in low for s in ["login required", "not logged in", "please log in", "authentication required", "unauthorized", "401", "run codex login"]):
        return ExecutionStatus.LOGIN_REQUIRED
    return ExecutionStatus.ERROR


class CodexAgent:
    name = "codex"
    mock = False

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
                   "--output-schema", str(schema), "--output-last-message", str(result_path), "-"]
        check = runner.run(command, directory, "agent", snapshot_id, timeout, stdin=prompt)
        check.tool_version = self.version
        if check.status != ExecutionStatus.COMPLETED:
            return check, None
        if check.exit_code != 0:
            check.status = classify_failure(output(check))
            check.reason = "Agent execution blocked; inspect raw logs"
            return check, None
        raw = result_path.read_text() if result_path.exists() else ""
        (directory / "raw-response.txt").write_text(redact(raw))
        if result_path.exists():
            result_path.write_text(redact(raw))
        try:
            return check, response_type.model_validate_json(raw)
        except ValueError as exc:
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
        check = runner.run([sys.executable, "-c", "print('explicit mock fixture playback')"], directory, "agent", snapshot_id, timeout)
        check.origin = Origin.MOCK; check.tool_version = "mock/2"
        write_json(directory / "response.json", item)
        try:
            return check, response_type.model_validate(item)
        except ValueError as exc:
            check.status = ExecutionStatus.ERROR; check.reason = "Structured agent output is invalid"
            (directory / "validation-error.txt").write_text(str(exc))
            return check, None
