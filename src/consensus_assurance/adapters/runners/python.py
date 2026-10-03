import sys


class PythonBackend:
    name = "python"
    version = "3"
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
    def resolve_harness(self, harness, source, target_files):
        if harness.execution_package is not None:
            raise ValueError("Python does not support execution_package overrides")
        return self.harness_filename
    def experiment_command(self, execution_package=None, harness_filename=None):
        if execution_package is not None:raise ValueError("Python does not support execution_package overrides")
        return [sys.executable, harness_filename or self.harness_filename]
    def version_command(self):
        return [sys.executable, "--version"]
