"""Cargo integration tests through the existing fixed-input and isolated runner path."""
import os
import re
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.adapters.runners.experiment import local_package
from consensus_assurance.adapters.runners.toolchains import cargo_tool, cargo_environment


class CargoBackend:
    name = "cargo"
    version = "4"
    harness_kind = "rust_test"
    harness_instructions = "Write Rust #[test] integration tests using the captured crate's public API and existing dependencies. Select any captured crate through execution_package. The controller fixes the workspace lock and tools; build reuse is specific to a manifest, integration test target, feature selection and saved build basis. Switching crates or features may require a first heavy dependency build. Consult research.json build_inputs for preparation evidence and current seed availability; unlisted targets are not known to be prepared, and available seeds still require execution-time validation. Only the generated test target runs, serially with --nocapture and --locked --offline. Optional test_names selects exact full test names; omission runs the whole generated target. Unselected code still compiles. Emit complete CA_EVENT JSON lines. Helpers are workspace-relative; never replace manifests, locks, build scripts or Cargo configuration. Optional features selects named Cargo features, default_features=false disables defaults, and all_features=true enables all features; omission preserves Cargo defaults. Original dependency and dev-dependency feature unification still applies. Actual compiler-artifact records describe reuse; declaration syntax does not establish active cfg branches or private-state reachability."

    def __init__(self, target=None, timeout=90, seed_cache_dir=None):
        self.seed_cache_dir = Path(seed_cache_dir).expanduser().absolute() if seed_cache_dir is not None else None
        self.package = local_package(target.execution_package if target else ".")
        self.harness_filename = (target.harness_path if target else None) or str(Path(self.package)/"tests/assurance_generated.rs")
        self.destination(self.package,self.harness_filename)
        self.cargo = cargo_tool()
        self.cache = Path(os.environ.get("CARGO_HOME",Path.home()/".cargo")).expanduser().resolve()

    @staticmethod
    def destination(package,filename):
        path = Path(filename)
        if path.parent != Path(package)/"tests" or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.rs",path.name):
            raise ValueError("Rust harness_path must be a named .rs integration test in the selected crate's tests directory")
        return path

    def resolve_harness(self,harness,source,target_files):
        self.test_filters(harness.test_names)
        self.feature_flags(harness.features,harness.default_features,harness.all_features)
        harness.features=sorted(harness.features)
        package = local_package(harness.execution_package if harness.execution_package is not None else self.package)
        filename = str(Path(package)/"tests"/Path(self.harness_filename).name)
        manifest = str(Path(package)/"Cargo.toml")
        if manifest not in target_files:raise ValueError("Rust execution requires a captured Cargo.toml for the selected crate")
        if any(p.is_symlink() for p in [source/manifest,*(source/manifest).parents] if p.is_relative_to(source)):
            raise ValueError("Rust package path traverses a symlink")
        with (source/manifest).open('rb') as stream:metadata=tomllib.load(stream)
        if not metadata.get('package',{}).get('name') or metadata['package'].get('autotests') is False:
            raise ValueError("Select a concrete Rust crate with automatic integration tests enabled")
        if any(t.get('name')==Path(filename).stem for t in metadata.get('test',[])):
            raise ValueError("Generated test target conflicts with an existing Cargo target")
        harness.execution_package=package
        return filename

    def read_only_roots(self):
        return [self.cargo.parent.parent,*[self.cache/name for name in ('registry','git')]]

    def environment(self,workspace):
        scratch=workspace/'.execution'
        if any(p.is_symlink() for p in [scratch,*scratch.parents] if p.is_relative_to(workspace)):
            raise ValueError("Cargo scratch directory traverses a symlink")
        return cargo_environment(scratch,self.cargo,self.cache)

    @staticmethod
    def test_filters(test_names):
        if test_names is None:return []
        if not test_names or len(set(test_names))!=len(test_names) or any(
                not all(part.isidentifier() for part in name.split('::')) for name in test_names):
            raise ValueError('Rust test_names must be distinct exact full test names, not flags or patterns')
        return ['--exact',*test_names]

    @staticmethod
    def feature_flags(features=None,default_features=True,all_features=False):
        features=features or []
        if len(set(features))!=len(features) or any(not name or name.startswith('-') or
                any(c.isspace() or c in ',\x00' for c in name) for name in features):
            raise ValueError('Rust features must be distinct feature names, not flags or comma-separated lists')
        return ([*(['--no-default-features'] if not default_features else []),
            *(['--all-features'] if all_features else []),
            *(['--features',','.join(sorted(features))] if features else [])])

    def experiment_command(self,execution_package=None,harness_filename=None,test_names=None,*,
            features=None,default_features=True,all_features=False):
        if harness_filename is not None and execution_package is None:raise ValueError("Accepted Rust input lacks a fixed execution_package")
        package=local_package(execution_package if execution_package is not None else self.package)
        filename=self.destination(package,harness_filename or self.harness_filename)
        return [str(self.cargo),'test','--locked','--offline','--manifest-path',str(Path(package)/'Cargo.toml'),
            '--test',filename.stem,'--message-format=json',*self.feature_flags(features,default_features,all_features),
            '--','--nocapture','--test-threads=1',*self.test_filters(test_names)]

    def version_command(self):
        return [str(self.cargo.parent/'rustc'),'--version','--verbose']

    def prepare_run(self,runner,snapshot_id,timeout,mode):
        import time
        from .cargo_build import inputs, PreparationFailed
        if mode!='bwrap':raise ValueError('Prepared Cargo execution requires bubblewrap')
        try:
            return inputs(self,runner,snapshot_id,self.experiment_command(),
                min(time.monotonic()+timeout,runner.deadline or float('inf')))[0]
        except PreparationFailed as exc:
            raise ValueError('Cargo build-input preparation failed; inspect '+str(exc.check.stderr)) from exc

    def validate_builds(self,root,snapshot_id,deadline=None):
        from .cargo_build import verify
        verify(self,root,snapshot_id,deadline)

    def build_inputs(self,root,state,read):
        from .cargo_build import build_inputs
        return build_inputs(self,root,state,read)

    def execute(self,*args):
        from .cargo_build import execute
        return execute(self,*args)

    def cleanup(self,workspace):
        from .cargo_build import cleanup
        cleanup(workspace)

    def parse_test_result(self,check,text):
        from .cargo_build import retain_diagnostics
        facts=retain_diagnostics(check,text)
        observed=check.parameters.pop('observed_tests',[])
        requested=check.command[check.command.index('--exact')+1:] if '--exact' in check.command else None
        unobserved=[name for name in requested or [] if not any(t['name']==name for t in observed)]
        all_passed=bool(observed) and not unobserved and all(t['status']=='passed' for t in observed)
        check.parameters['test_selection']={'requested':requested,'observed':observed,'unobserved':unobserved}
        if check.status != ExecutionStatus.COMPLETED:return
        if check.exit_code==0:
            check.outcome='tests_passed' if all_passed and facts['test_summary_recorded'] else 'unknown' if facts['test_passed'] else 'not_applicable'
            if check.outcome!='tests_passed':check.reason='Selected Rust tests were absent, ignored or lacked a completed result; inspect test_selection'
        else:
            failure='test_failure' if facts['test_started'] else 'build_or_setup' if facts['build_finished'] is False else 'execution_unclassified'
            check.parameters['failure_class']=failure
            if failure=='build_or_setup':check.status=ExecutionStatus.ERROR
            if facts['test_started']:check.outcome='tests_failed'
            check.reason='Rust execution failed; inspect retained Cargo diagnostics and actual test observations'
