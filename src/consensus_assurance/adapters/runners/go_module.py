import json
from pathlib import Path
from consensus_assurance.core.types import Capability, ExecutionStatus


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
                check.parameters["package_build"]=check.action=="capability_probe" and any(e.get("Package") and e.get("Action") in {"pass","skip"} for e in events)
                check.outcome="not_applicable";check.reason="Compile probe only" if check.parameters["package_build"] else "No tests passed; selected tests were absent or skipped"
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
            if 'panic:' in trace:
                import re
                frames=re.findall(r'(?m)^\s*(\S+\.go):\d+',trace)
                check.parameters['failure_class']='target_panic_candidate' if any(not p.endswith('_test.go') for p in frames) else 'harness_panic'
            else:check.parameters['failure_class']='test_failure'

    def __init__(self, target=None, timeout=90):
        self.package=target.execution_package if target else "."
        self.harness_filename=(target.harness_path if target else None) or str(Path(self.package)/"assurance_generated_test.go")
        self.timeout=timeout
    def probe_command(self):
        return ["go", "test", "-json", "-run", "^$", "./..."]
    def experiment_command(self):
        return ["go", "test", "-json", "-count=1", f"-timeout={self.timeout}s", "-run", "^TestAssurance", self.package]
    def version_command(self):
        return ["go", "version"]
    def capabilities(self, check):
        return [Capability(name="package_build", status="probe_confirmed" if check.status==ExecutionStatus.COMPLETED and check.exit_code==0 and check.parameters.get("package_build") else "unavailable",
            check_id=check.id, description="Offline package compilation; no protocol correctness or scheduling claim"),
            Capability(name="precise_schedule_replay", status="unavailable", check_id=None,
            description="No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites")]
