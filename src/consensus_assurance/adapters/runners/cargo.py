"""Cargo integration tests through the existing fixed-input and isolated runner path."""
import json
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
    version = "1"
    harness_kind = "rust_test"
    harness_instructions = "Write Rust #[test] integration tests in the selected crate's tests directory, using the captured crate's public API and existing dependencies. The controller runs only the generated test target, serially, with --nocapture and offline Cargo. Emit complete CA_EVENT JSON lines with println!. Helpers are workspace-relative; do not submit manifests, build scripts or Cargo configuration. Default crate features apply; private internals and disabled features are not automatically exposed."

    def __init__(self, target=None, timeout=90):
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
        return [str(self.cargo),'test','--offline','--manifest-path',str(Path(package)/'Cargo.toml'),
            '--test',filename.stem,'--message-format=json','--','--nocapture','--test-threads=1']

    def version_command(self):
        return [str(self.cargo.parent/'rustc'),'--version','--verbose']

    def parse_test_result(self,check,text):
        if check.status != ExecutionStatus.COMPLETED:return
        events=[]
        for line in text.splitlines():
            try:
                event=json.loads(line)
                if isinstance(event,dict):events.append(event)
            except ValueError:pass
        result=re.search(r'(?m)^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;',text)
        started=bool(re.search(r'(?m)^running [1-9][0-9]* tests?$',text))
        check.parameters['test_started']=started
        if check.exit_code==0:
            check.outcome='tests_passed' if result and int(result[1])>0 else 'not_applicable'
            if check.outcome=='not_applicable':check.reason='No selected Rust tests passed; tests were absent or ignored'
        else:
            build_failed=any(e.get('reason')=='build-finished' and e.get('success') is False for e in events)
            failure='test_failure' if started else 'build_or_setup' if build_failed else 'execution_unclassified'
            check.parameters['failure_class']=failure
            if failure=='build_or_setup':check.status=ExecutionStatus.ERROR
            if started:check.outcome='tests_failed'
            check.reason='Rust execution failed; inspect retained Cargo diagnostics and actual test observations'
