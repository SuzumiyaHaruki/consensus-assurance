import sys


class PythonBackend:
    name = "python"
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

    def __init__(self, target=None, timeout=90):
        if target and target.harness_path:self.harness_filename=target.harness_path
    def experiment_command(self):
        return [sys.executable, self.harness_filename]
    def version_command(self):
        return [sys.executable, "--version"]
