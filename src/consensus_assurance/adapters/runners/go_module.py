import json
import re
import os
import subprocess
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
    tests = {}
    for event in events:
        if not event.get('Test'):continue
        key = (event.get('Package'), event['Test'])
        action = event.get('Action')
        if action == 'run':tests[key] = {'package':key[0], 'name':key[1], 'status':'unfinished'}
        elif key in tests and action in {'pass','fail','skip'}:
            tests[key]['status'] = {'pass':'passed','fail':'failed','skip':'skipped'}[action]
            if 'Elapsed' in event:tests[key]['duration_seconds'] = event['Elapsed']
    started = set(tests)
    passed = any(t['status']=='passed' for t in tests.values())
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
    return {'test_started':bool(started), 'test_passed':passed, 'failure_class':failure,
        'observed_tests':list(tests.values())}


class GoModuleBackend:
    name = "go_module"
    version = "4"
    harness_kind = "go_test"
    harness_filename = "assurance_generated_test.go"
    harness_instructions = "Use TestAssurance-prefixed Go tests in the selected local package; derive its declaration from actual source, including valid external test packages. Optional test_names selects exact top-level names and their subtests; omission runs all TestAssurance tests. Unselected code still compiles and package initialization still runs. execution_package is repository-relative; the nearest captured go.mod selects the execution module. Local replacements must remain in the captured repository; Go workspaces are unsupported. The controller runs Go directly. Emit CA_EVENT JSON using fmt.Println or t.Log. Dependencies are offline; inspect actual source before using internal APIs."

    def environment(self, workspace):
        return {"GOCACHE": str(workspace / ".execution/go-build"), "GOPROXY": "off", "GOSUMDB": "off",
            "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly", "GOWORK": "off", "GOMODCACHE": str(Path.home() / "go/pkg/mod")}

    def read_only_roots(self):
        return [Path.home() / "go/pkg/mod"]

    @staticmethod
    def module_for(source, package):
        for parent in [Path(package), *Path(package).parents]:
            if (source/parent/'go.work').exists():
                raise ValueError('Go workspaces are not supported')
        for parent in [Path(package), *Path(package).parents]:
            if (source/parent/'go.mod').is_file():return parent
        raise ValueError('Selected package has no captured go.mod')

    @staticmethod
    def local_modules(source, module, target_files):
        pending, seen = [module], set()
        while pending:
            current = pending.pop()
            if current in seen:continue
            seen.add(current)
            path = source/current/'go.mod'
            if (str(current/'go.mod') not in target_files or not path.resolve().is_relative_to(source.resolve())
                    or any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(source))):
                raise ValueError('Local replacement requires a captured go.mod: ' + str(current))
            data = json.loads(subprocess.check_output(['go', 'mod', 'edit', '-json', str(path.resolve())],
                env={**os.environ, 'GOTOOLCHAIN':'local', 'GOWORK':'off'}, timeout=10))
            for replacement in data.get('Replace') or []:
                new = replacement['New']
                if new.get('Version'):continue
                relative = Path(new['Path'])
                destination = source/current/relative
                if relative.is_absolute() or not destination.resolve().is_relative_to(source.resolve()) or any(
                        p.is_symlink() for p in [destination, *destination.parents] if p.is_relative_to(source)):
                    raise ValueError('Local replacement escapes captured source: ' + new['Path'])
                pending.append(destination.resolve().relative_to(source.resolve()))
        return sorted(str(p) for p in seen)

    def resolve_harness(self, harness, source, target_files):
        self.test_pattern(harness.test_names)
        package = local_package(harness.execution_package if harness.execution_package is not None else self.package)
        filename = str(Path(package) / Path(self.harness_filename).name) if harness.execution_package is not None else self.harness_filename
        module = self.module_for(source, package)
        self.local_modules(source, module, target_files)
        # All generated helpers stay in the selected module. Installation checks collisions and symlinks.
        for name in [package, *harness.files]:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or 'vendor' in relative.parts:
                raise ValueError("Generated paths must stay in the captured module")
            directory = relative if name == package else relative.parent
            for parent in [directory, *directory.parents]:
                path = source / parent
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    raise ValueError("Package path traverses a symlink or non-directory")
                if str(parent / 'go.work') in target_files:
                    raise ValueError("Go workspaces are not supported")
            if self.module_for(source, str(directory)) != module:
                raise ValueError('Generated helpers must stay in the selected module')
        if not any(Path(name).parent == Path(package) and name.endswith('.go') for name in target_files):
            raise ValueError("execution_package must select an existing captured Go package")
        harness.execution_package = package
        return filename

    def execute(self, runner, command, workspace, snapshot_id, timeout, mode, action):
        from .experiment import run_experiment
        package = Path(local_package(command[-1]))
        module = self.module_for(workspace, str(package))
        modules = self.local_modules(workspace, module, {str(p.relative_to(workspace)) for p in workspace.rglob('go.mod')})
        if module != Path('.'):
            command = [command[0], '-C', str(module), *command[1:-1], local_package(str(package.relative_to(module)))]
        check = run_experiment(runner, command, workspace, snapshot_id, timeout, mode, action, adapter=self, prepared=True)
        check.parameters.update(module_directory=str(module), local_modules=modules,
                                module_execution_cwd=str(workspace/module))
        return check

    def parse_test_result(self, check, text):
        facts = go_test_diagnostics(text)
        check.parameters['test_started'] = facts['test_started']
        pattern = check.command[check.command.index('-run')+1] if '-run' in check.command else ''
        requested = pattern[2:-2].split('|') if pattern.startswith('^(') and pattern.endswith(')$') else None
        observed = facts['observed_tests']
        unobserved = [name for name in requested or [] if not any(t['name']==name for t in observed)]
        all_passed = bool(observed) and not unobserved and all(t['status']=='passed' for t in observed)
        check.parameters['test_selection'] = {'requested':requested, 'observed':observed, 'unobserved':unobserved}
        if check.status != ExecutionStatus.COMPLETED:return
        if check.exit_code == 0:
            check.outcome = 'tests_passed' if all_passed else 'unknown' if facts['test_passed'] else 'not_applicable'
            if not all_passed:check.reason = 'Selected tests were absent, skipped or lacked a completed result; inspect test_selection'
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

    @staticmethod
    def test_pattern(test_names):
        if test_names is None:return '^TestAssurance'
        if not test_names or len(set(test_names))!=len(test_names) or any(
                not name.isidentifier() or not name.startswith('TestAssurance') for name in test_names):
            raise ValueError('Go test_names must be distinct exact top-level TestAssurance names, not patterns or subtests')
        return '^('+'|'.join(test_names)+')$'

    def experiment_command(self, execution_package=None, harness_filename=None, test_names=None):
        if harness_filename is not None and execution_package is None:
            raise ValueError("Accepted Go input lacks a fixed execution_package; historical artifacts are read-only")
        package = local_package(execution_package if execution_package is not None else self.package)
        return ["go", "test", "-json", "-count=1", f"-timeout={self.timeout}s", "-run", self.test_pattern(test_names), package]

    def version_command(self):
        return ["go", "version"]
