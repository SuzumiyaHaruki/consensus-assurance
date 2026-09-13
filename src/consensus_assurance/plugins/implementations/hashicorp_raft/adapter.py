import re
import json
from pathlib import Path
from consensus_assurance.core.types import Capability, ExecutionStatus


class HashicorpRaft:
    name = "hashicorp_raft"
    version = "2"
    harness_kind = "go_test"
    harness_filename = "assurance_generated_test.go"
    harness_instructions = "Use package raft and TestAssurance-prefixed Go tests. Emit CA_EVENT JSON using fmt.Println or t.Log. Build dependencies are offline. Inspect actual source before using internal APIs."
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
                    events.append(json.loads(line))
                except ValueError:
                    continue
            if not any(e.get("Action") == "pass" and e.get("Test") for e in events):
                check.outcome = "not_applicable"; check.reason = "No tests passed; selected tests were absent or skipped"
            else:
                check.outcome = "tests_passed"
        else:
            check.outcome = "tests_failed"

    def identify(self, repo):
        path = repo / "go.mod"
        return path.is_file() and bool(re.search(r"^module github.com/hashicorp/raft\s*$", path.read_text(), re.M))
    def probe_command(self):
        return ["go", "test", "-json", "-count=1", "-timeout=90s", "-run", "^TestInmem(TransportImpl|SnapshotStoreImpl)$", "."]
    def experiment_command(self):
        return ["go", "test", "-json", "-count=1", "-timeout=90s", "-run", "^TestAssurance", "."]
    def version_command(self):
        return ["go", "version"]
    def capabilities(self, check):
        return [Capability(name="package_tests", status="probe_confirmed" if check.outcome == "tests_passed" else "unavailable",
            check_id=check.id, description="Package build and selected existing tests; not a full suite or scheduling probe"),
            Capability(name="precise_schedule_replay", status="unavailable", check_id=None,
            description="No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites")]
