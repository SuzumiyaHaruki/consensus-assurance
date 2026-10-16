"""Offline Maven reactor execution with retained Surefire case results."""
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from consensus_assurance.core.types import ExecutionStatus
from .experiment import local_package
from .toolchains import maven_tools, maven_environment


class MavenBackend:
    name = 'maven'
    version = '1'
    harness_kind = 'java_test'
    harness_instructions = ('Write Java tests with the selected module\'s existing test framework and dependencies. '
        'Place the generated class under src/test/java; its package must match that path. '
        'The offline Maven reactor builds the selected module and required upstream modules, but selects only the generated class. '
        'Optional test_names selects exact method names in that class; omission runs that class. Other sources still compile. '
        'Use the existing build configuration; no new POMs, plugins or .mvn settings. Emit complete CA_EVENT JSON lines. '
        'Surefire XML records actual test cases; skipped, absent or incomplete tests do not establish completion. '
        'Local communication and subprocesses must finish within the same isolated invocation.')

    def __init__(self, target=None, timeout=90, dependency_cache_dir=None):
        self.package = local_package(target.execution_package if target else '.')
        self.harness_filename = (target.harness_path if target else None) or str(Path(self.package) / 'src/test/java/AssuranceGeneratedTest.java')
        self.destination(self.package, self.harness_filename)
        self.maven, self.java_home = maven_tools()
        self.cache = Path(dependency_cache_dir or Path.home() / '.m2/repository').expanduser().resolve()

    @staticmethod
    def destination(package, filename):
        path = Path(filename)
        base = Path(package) / 'src/test/java'
        if (path.is_absolute() or '..' in path.parts or not path.is_relative_to(base)
                or path.suffix != '.java' or not all(re.fullmatch(r'[A-Za-z_$][\w$]*', p)
                    for p in path.relative_to(base).with_suffix('').parts)):
            raise ValueError('Java harness_path must name one class under the selected module src/test/java')
        return path

    @staticmethod
    def selection(filename, test_names):
        if test_names is not None and (not test_names or len(set(test_names)) != len(test_names)
                or any(not re.fullmatch(r'[A-Za-z_$][\w$]*', name) for name in test_names)):
            raise ValueError('Java test_names must be exact method names, not flags or patterns')
        relative = str(filename).rsplit('src/test/java/', 1)[1]
        class_name = '.'.join(Path(relative).with_suffix('').parts)
        return class_name + ('#' + '+'.join(test_names) if test_names else '')

    def resolve_harness(self, harness, source, target_files):
        package = local_package(harness.execution_package if harness.execution_package is not None else self.package)
        relative = Path(self.harness_filename).relative_to(Path(self.package) / 'src/test/java')
        filename = str(Path(package) / 'src/test/java' / relative)
        self.selection(filename, harness.test_names)
        manifest = Path(package) / 'pom.xml'
        if str(manifest) not in target_files:
            raise ValueError('Maven execution requires a captured pom.xml for the selected module')
        if any(p.is_symlink() for p in [source / manifest, *(source / manifest).parents] if p.is_relative_to(source)):
            raise ValueError('Maven module path traverses a symlink')
        harness.execution_package = package
        return filename

    def environment(self, workspace):
        scratch = workspace / '.execution'
        if any(p.is_symlink() for p in [scratch, *scratch.parents] if p.is_relative_to(workspace)):
            raise ValueError('Maven scratch directory traverses a symlink')
        return maven_environment(scratch, self.maven, self.java_home, self.cache)

    def read_only_roots(self):
        return [self.maven.parent.parent, self.java_home, self.cache]

    def experiment_command(self, execution_package=None, harness_filename=None, test_names=None):
        if harness_filename is not None and execution_package is None:
            raise ValueError('Accepted Java input lacks a fixed execution_package')
        package = local_package(execution_package if execution_package is not None else self.package)
        filename = self.destination(package, harness_filename or self.harness_filename)
        return [str(self.maven), '-o', '-B', '-ntp', '-pl', package, '-am',
                '-Dtest=' + self.selection(filename, test_names), '-Dsurefire.failIfNoSpecifiedTests=false',
                '-DfailIfNoTests=false', '-DforkCount=1', '-DreuseForks=true',
                '-Dsurefire.useFile=false', '-Dmaven.test.redirectTestOutputToFile=false',
                '-DredirectTestOutputToFile=false', 'test']

    def version_command(self):
        return [str(self.maven), '--version']

    def execute(self, runner, command, workspace, snapshot_id, timeout, mode, action):
        from .experiment import run_experiment
        # A failed build must not inherit a previous or captured Surefire success.
        for path in workspace.glob('**/target/surefire-reports'):
            if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(workspace)):
                raise ValueError('Surefire report path traverses a symlink')
            shutil.rmtree(path)
        return run_experiment(runner, command, workspace, snapshot_id, timeout, mode, action,
                              adapter=self, prepared=True)

    def parse_test_result(self, check, text):
        selected = next((x[len('-Dtest='):] for x in check.command if x.startswith('-Dtest=')), '')
        class_name, _, methods = selected.partition('#')
        requested = methods.split('+') if methods else None
        observed, errors = [], []
        workspace = Path(check.cwd)
        retained = Path(check.stdout).parent / 'surefire' if check.stdout else None
        for path in sorted(workspace.glob('**/target/surefire-reports/*')):
            if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents if p.is_relative_to(workspace)):
                continue
            if retained:
                dest = retained / path.relative_to(workspace)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                check.artifacts.append(str(dest))
            if not path.name.startswith('TEST-') or path.suffix != '.xml':
                continue
            try:
                tree = ET.parse(path)
                for case in tree.iter('testcase'):
                    name, owner = case.get('name', ''), case.get('classname', '')
                    status = 'failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
                    observed.append({'package': owner, 'name': name, 'status': status,
                                     'duration_seconds': case.get('time'), 'report': str(path.relative_to(workspace))})
            except (ET.ParseError, OSError) as exc:
                errors.append(str(exc))
        module = Path(check.command[check.command.index('-pl')+1])
        matching = [t for t in observed if t['package'] == class_name
                    and Path(t['report']).parent == module / 'target/surefire-reports']
        unobserved = [name for name in requested or [] if not any(t['name'] == name or t['name'].startswith(name + '[') for t in matching)]
        check.parameters['test_selection'] = {'class': class_name, 'requested': requested,
                                             'observed': observed, 'unobserved': unobserved}
        if errors:
            check.parameters['report_errors'] = errors
        if check.status != ExecutionStatus.COMPLETED:
            return
        if check.exit_code == 0:
            passed = bool(matching) and not unobserved and not errors and all(t['status'] == 'passed' for t in observed)
            check.outcome = 'tests_passed' if passed else 'not_applicable'
            if not passed:
                check.reason = 'Selected Java tests were absent, skipped or lacked complete Surefire results'
        else:
            failed = any(t['status'] == 'failed' for t in observed)
            check.parameters['failure_class'] = 'test_failure' if failed else 'build_or_setup'
            if failed:
                check.outcome = 'tests_failed'
            else:
                check.status = ExecutionStatus.ERROR
            check.reason = 'Maven execution failed; inspect raw output and retained Surefire reports'
