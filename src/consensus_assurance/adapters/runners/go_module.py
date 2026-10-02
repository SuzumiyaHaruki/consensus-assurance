import json
from pathlib import Path
from consensus_assurance.core.types import ExecutionStatus


class GoModuleBackend:
    name = "go_module"
    version = "2"
    harness_kind = "go_test"
    harness_filename = "assurance_generated_test.go"
    harness_instructions = "Use TestAssurance-prefixed Go tests in the configured package directory; derive its package declaration from actual source. Emit CA_EVENT JSON using fmt.Println or t.Log. Build dependencies are offline. Inspect actual source before using internal APIs."
    def environment(self, workspace):
        return {"GOCACHE": str(workspace / ".execution/go-build"), "GOPROXY": "off", "GOSUMDB": "off",
            "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly", "GOMODCACHE": str(Path.home() / "go/pkg/mod")}
    def read_only_roots(self):
        return [Path.home() / "go/pkg/mod"]
    def parse_test_result(self, check, text):
        if any(x in text for x in ["[build failed]", "setup failed", "module lookup disabled"]):
            check.status = ExecutionStatus.ERROR; check.reason = "Build or dependency error"
        elif check.exit_code == 0:
            events = []
            for line in text.splitlines():
                try:
                    event=json.loads(line)
                    if isinstance(event,dict):events.append(event)
                except ValueError:
                    continue
            if not any(e.get("Action") == "pass" and e.get("Test") for e in events):
                check.outcome="not_applicable";check.reason="No tests passed; selected tests were absent or skipped"
            else:
                check.outcome = "tests_passed"
        else:
            check.outcome = "tests_failed"
            outputs=[]
            for line in text.splitlines():
                try:
                    item=json.loads(line)
                    if isinstance(item,dict) and isinstance(item.get('Output'),str):outputs.append(item['Output'])
                except ValueError:continue
            trace=''.join(outputs)
            check.parameters['failure_class']='panic_unattributed' if 'panic:' in trace else 'test_failure'


    def __init__(self, target=None, timeout=90):
        self.package=target.execution_package if target else "."
        self.harness_filename=(target.harness_path if target else None) or str(Path(self.package)/"assurance_generated_test.go")
        self.timeout=timeout
    def experiment_command(self):
        return ["go", "test", "-json", "-count=1", f"-timeout={self.timeout}s", "-run", "^TestAssurance", self.package]
    def version_command(self):
        return ["go", "version"]
