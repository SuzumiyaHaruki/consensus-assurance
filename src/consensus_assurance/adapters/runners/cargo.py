"""Cargo integration tests through the existing fixed-input and isolated runner path."""
import os
import re
import shutil
import subprocess
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.adapters.runners.experiment import local_package


class CargoBackend:
    name = "cargo"
    version = "3"
    harness_kind = "rust_test"
    harness_instructions = "Write Rust #[test] integration tests using the captured crate's public API and existing dependencies. The controller fixes the workspace lock and tools; build reuse is specific to a manifest, integration test target and saved build basis. Switching crates may require a first heavy dependency build. Consult research.json build_inputs for preparation evidence and current seed availability; unlisted targets are not known to be prepared, and available seeds still require execution-time validation. Only the generated test target runs, serially with --nocapture and --locked --offline. Emit complete CA_EVENT JSON lines. Helpers are workspace-relative; never replace manifests, locks, build scripts or Cargo configuration. No extra feature flags are added; original dev-dependencies can enable additional features. Actual compiler-artifact records describe reuse; declaration syntax does not establish active cfg branches or private-state reachability."

    def __init__(self, target=None, timeout=90, seed_cache_dir=None):
        self.seed_cache_dir = Path(seed_cache_dir).expanduser().absolute() if seed_cache_dir is not None else None
        self.package = local_package(target.execution_package if target else ".")
        self.harness_filename = (target.harness_path if target else None) or str(Path(self.package)/"tests/assurance_generated.rs")
        self.destination(self.package,self.harness_filename)
        executable = shutil.which("cargo")
        if not executable:raise ValueError("Cargo is required; add the Rust toolchain bin directory to PATH")
        if executable and Path(executable).resolve().name == "rustup":
            executable = subprocess.check_output(
                [str(Path(executable).resolve()),"which","cargo"],text=True,timeout=10).strip()
        self.cargo = Path(executable).resolve()
        self.cache = Path(os.environ.get("CARGO_HOME",Path.home()/".cargo")).expanduser().resolve()

    @staticmethod
    def destination(package,filename):
        path = Path(filename)
        if path.parent != Path(package)/"tests" or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.rs",path.name):
            raise ValueError("Rust harness_path must be a named .rs integration test in the selected crate's tests directory")
        return path

    def resolve_harness(self,harness,source,target_files):
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
        home=workspace/'.execution/cargo-home'
        if any(p.is_symlink() for p in [home,*home.parents] if p.is_relative_to(workspace)):
            raise ValueError("Cargo scratch directory traverses a symlink")
        home.mkdir(parents=True,exist_ok=True)
        for name in ('registry','git'):
            source=self.cache/name;dest=home/name
            if not source.is_dir():continue
            if dest.is_symlink() and dest.resolve()==source.resolve():continue
            if dest.exists() or dest.is_symlink():raise ValueError("Cargo scratch cache differs from the configured read-only dependency cache")
            dest.symlink_to(source,target_is_directory=True)
        # Preserve PATH: Codex injects its sandbox helper directory at launch.
        return {'CARGO_HOME':str(home),'CARGO_TARGET_DIR':str(workspace/'.execution/cargo-target'),
            'CARGO_NET_OFFLINE':'true','CARGO_TERM_COLOR':'never','CARGO_BUILD_JOBS':'2',
            'RUSTC':str(self.cargo.parent/'rustc'),'RUSTDOC':str(self.cargo.parent/'rustdoc')}

    def experiment_command(self,execution_package=None,harness_filename=None):
        if harness_filename is not None and execution_package is None:raise ValueError("Accepted Rust input lacks a fixed execution_package")
        package=local_package(execution_package if execution_package is not None else self.package)
        filename=self.destination(package,harness_filename or self.harness_filename)
        return [str(self.cargo),'test','--locked','--offline','--manifest-path',str(Path(package)/'Cargo.toml'),
            '--test',filename.stem,'--message-format=json','--','--nocapture','--test-threads=1']

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

    def parse_test_result(self,check,text):
        from .cargo_build import retain_diagnostics
        facts=retain_diagnostics(check,text)
        if check.status != ExecutionStatus.COMPLETED:return
        if check.exit_code==0:
            check.outcome='tests_passed' if facts['test_passed'] else 'not_applicable'
            if check.outcome=='not_applicable':check.reason='No selected Rust tests passed; tests were absent or ignored'
        else:
            failure='test_failure' if facts['test_started'] else 'build_or_setup' if facts['build_finished'] is False else 'execution_unclassified'
            check.parameters['failure_class']=failure
            if failure=='build_or_setup':check.status=ExecutionStatus.ERROR
            if facts['test_started']:check.outcome='tests_failed'
            check.reason='Rust execution failed; inspect retained Cargo diagnostics and actual test observations'
