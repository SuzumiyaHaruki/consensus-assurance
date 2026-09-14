import sys
from consensus_assurance.core.types import Capability


class ToyImplementation:
    name = "toy"
    version = "2"
    harness_kind = "python"
    harness_filename = "assurance_generated.py"
    harness_instructions = "Use Python imports from the current isolated workspace and print CA_EVENT JSON containing actual returned values."
    def environment(self, workspace):
        return {}
    def read_only_roots(self):
        return []
    def parse_test_result(self, check, text):
        if any(message in text for message in ("SyntaxError:", "ModuleNotFoundError:", "ImportError:")):
            from consensus_assurance.core.types import ExecutionStatus
            check.status = ExecutionStatus.ERROR
            check.reason = "Harness syntax or import error"
            return
        check.outcome = "tests_passed" if check.exit_code == 0 else "tests_failed"

    def identify(self, repo):
        return (repo / "counter.py").is_file()
    def probe_command(self):
        return [sys.executable, "counter.py"]
    def experiment_command(self):
        return [sys.executable, self.harness_filename]
    def version_command(self):
        return [sys.executable, "--version"]
    def capabilities(self, check):
        return [Capability(name="counter_execution", status="probe_confirmed" if check.outcome == "tests_passed" else "unavailable",
            check_id=check.id, description="Actual finite counter execution; not a production consensus protocol")]

    def required_inputs(self, repo):
        return ["counter.py"]

    def symbol_hints(self, file, lines):
        return []
