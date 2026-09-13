import re
from pathlib import Path
from consensus_assurance.core.types import ExecutionStatus, CheckRun
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import digest


def parse(check: CheckRun) -> CheckRun:
    if check.status != ExecutionStatus.COMPLETED:
        return check
    text = output(check)
    # An invariant violation is a normal semantic result, including TLC exit code 12.
    if re.search(r"Invariant \w+ is violated", text) and ("State 1:" in text or "violated by the initial state" in text):
        check.outcome = "counterexample"
    elif check.exit_code == 0 and "Model checking completed. No error has been found." in text:
        check.outcome = "holds"
    else:
        check.status = ExecutionStatus.ERROR
        check.reason = "Model syntax error" if any(x in text for x in ("Parsing or semantic analysis failed", "Lexical error", "Semantic errors", "Parse Error", "Unknown operator")) else "TLC execution failed or produced no complete recognized result"
    return check


class TLCVerifier:
    name = "tlc"
    def __init__(self, jar: str | None):
        self.jar = Path(jar).expanduser().resolve() if jar else None
        self.version = "unprobed"

    def probe(self, runner):
        java = runner.run(["java", "-version"], runner.root, "java_probe", "environment", 10)
        checks = [java]
        if self.jar and self.jar.is_file():
            version = runner.run(["java", "-cp", str(self.jar), "tlc2.TLC", "-help"], runner.root, "verifier_probe", "environment", 10)
            checks.append(version)
            lines = output(version).splitlines()
            self.version = next((s for s in lines if "Version" in s or "TLC2" in s), "TLC " + digest(self.jar.read_bytes()))
            available = java.exit_code == 0 and "TLC" in output(version) and version.status == ExecutionStatus.COMPLETED
        else:
            available = False
            self.version = "TLC JAR missing; set tlc_jar or TLC_JAR"
        self.available = available
        return {"available": available, "version": self.version, "checks": checks, "reason": "Ready" if available else self.version}

    def check(self, runner, model, timeout):
        directory = Path(model.path).parent
        if not getattr(self, "available", False):
            return CheckRun(action="model_check", cwd=str(directory), status=ExecutionStatus.TOOL_MISSING,
                snapshot_id=model.snapshot_id, model_id=model.id, parameters=model.scope.parameters,
                reason="Java or TLC JAR unavailable", tool_version=self.version)
        command = ["java", "-Xmx512m", "-cp", str(self.jar), "tlc2.TLC", "-workers", "1",
                   "-config", str(model.config_path), str(model.path)]
        check = runner.run(command, directory, "model_check", model.snapshot_id, timeout)
        check.tool_version = self.version
        check.model_id = model.id
        check.parameters = model.scope.parameters
        check.artifacts = [model.path, model.config_path]
        check.input_versions = model.artifact_digests
        parsed = parse(check)
        text = output(parsed)
        for key, pattern in {"states": r"(\d[\d,]*) distinct states found", "generated": r"(\d[\d,]*) states generated", "depth": r"depth of the complete state graph search is (\d+)"}.items():
            match = re.search(pattern, text)
            if match:
                parsed.search_statistics[key] = match[1]
        return parsed

    def calibrate(self, runner, model, bundle, experiment, timeout):
        from .trace import calibrate
        return calibrate(self, runner, model, bundle, experiment, timeout)
