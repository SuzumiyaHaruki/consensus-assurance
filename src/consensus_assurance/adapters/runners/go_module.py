import json
import re
from pathlib import Path
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.adapters.runners.experiment import local_package


def go_test_diagnostics(text):
    """Read tool/test phase evidence without attributing a semantic result."""
    events, diagnostics = [], []
    for line in text.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):events.append(event)
        except ValueError:diagnostics.append(line)
    started = {(e.get('Package'), e['Test']) for e in events if e.get('Action') == 'run' and e.get('Test')}
    passed = any(e.get('Action') == 'pass' and (e.get('Package'), e.get('Test')) in started for e in events)
    output = ''.join(e.get('Output', '') for e in events if e.get('Action') == 'output')
    if started:
        panic = re.search(r'(?m)^panic: .+[\s\S]*^goroutine [0-9]+ \[', output)
        failure = 'panic_unattributed' if panic else 'test_failure'
    elif (any(e.get('Action') == 'build-fail' for e in events)
            or (any(line.startswith('# ') for line in diagnostics)
                and re.search(r'(?m)^FAIL\s+.+\[build failed\]$', output))
            or any(re.match(r'^(?:found packages \S+ \(.+\) and \S+ \(.+\) in .+|.*module lookup disabled by GOPROXY=off)$', line) for line in diagnostics)):
        failure = 'build_or_setup'
    else:failure = 'execution_unclassified'
    return {'test_started':bool(started), 'test_passed':passed, 'failure_class':failure}


class GoModuleBackend:
    name = "go_module"
    version = "3"
    harness_kind = "go_test"
    harness_filename = "assurance_generated_test.go"
    harness_instructions = "Use TestAssurance-prefixed Go tests in the selected local package; derive its declaration from actual source, including valid external test packages. The controller runs Go directly. Emit CA_EVENT JSON using fmt.Println or t.Log. Dependencies are offline; inspect actual source before using internal APIs."

    def environment(self, workspace):
        return {"GOCACHE": str(workspace / ".execution/go-build"), "GOPROXY": "off", "GOSUMDB": "off",
            "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly", "GOWORK": "off", "GOMODCACHE": str(Path.home() / "go/pkg/mod")}

    def read_only_roots(self):
        return [Path.home() / "go/pkg/mod"]

    def resolve_harness(self, harness, source, target_files):
        package = local_package(harness.execution_package if harness.execution_package is not None else self.package)
        filename = str(Path(package) / Path(self.harness_filename).name) if harness.execution_package is not None else self.harness_filename
        if 'go.mod' not in target_files:
            raise ValueError("Go execution requires the captured module's go.mod")
        # All generated helpers stay in the same module too. Installation checks collisions and symlinks.
        for name in [package, *harness.files]:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or 'vendor' in relative.parts:
                raise ValueError("Generated paths must stay in the captured module")
            directory = relative if name == package else relative.parent
            for parent in [directory, *directory.parents]:
                path = source / parent
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    raise ValueError("Package path traverses a symlink or non-directory")
                if (parent != Path('.') and str(parent / 'go.mod') in target_files) or str(parent / 'go.work') in target_files:
                    raise ValueError("Nested modules and Go workspaces are not supported")
        if not any(Path(name).parent == Path(package) and name.endswith('.go') for name in target_files):
            raise ValueError("execution_package must select an existing captured Go package")
        harness.execution_package = package
        return filename

    def parse_test_result(self, check, text):
        if check.status != ExecutionStatus.COMPLETED:return
        facts = go_test_diagnostics(text)
        check.parameters['test_started'] = facts['test_started']
        if check.exit_code == 0:
            check.outcome = 'tests_passed' if facts['test_passed'] else 'not_applicable'
            if not facts['test_passed']:check.reason = 'No selected tests passed; tests were absent or skipped'
        else:
            failure = facts['failure_class']
            check.parameters['failure_class'] = failure
            if failure == 'build_or_setup':check.status = ExecutionStatus.ERROR
            elif facts['test_started']:check.outcome = 'tests_failed'
            check.reason = ('Package discovery, build or dependency preparation failed before selected tests' if failure == 'build_or_setup'
                else 'Test execution failed; semantic attribution requires actual evidence' if facts['test_started']
                else 'Execution failed without a selected test run; inspect startup and raw diagnostics')

    def __init__(self, target=None, timeout=90):
        self.package = local_package(target.execution_package if target else ".")
        self.harness_filename = (target.harness_path if target else None) or str(Path(self.package) / "assurance_generated_test.go")
        if Path(self.harness_filename).parent != Path(self.package):
            raise ValueError("target.harness_path must lie in target.execution_package")
        self.timeout = timeout

    def experiment_command(self, execution_package=None, harness_filename=None):
        if harness_filename is not None and execution_package is None:
            raise ValueError("Accepted Go input lacks a fixed execution_package; historical artifacts are read-only")
        package = local_package(execution_package if execution_package is not None else self.package)
        return ["go", "test", "-json", "-count=1", f"-timeout={self.timeout}s", "-run", "^TestAssurance", package]

    def version_command(self):
        return ["go", "version"]
