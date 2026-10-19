"""Tool selection and timeout boundaries, without a real Codex or target process."""
import json
from pathlib import Path
import pytest
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.types import Harness


pytestmark = pytest.mark.real

@pytest.mark.parametrize('upstream_lock',[False,True])
def test_cargo_preparation_retains_lock_origin(tmp_path,rust_workspace,upstream_lock):
    import shutil
    from support.audit import cargo_engine
    from consensus_assurance.adapters.storage.snapshot import capture
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    engine,repo=cargo_engine(tmp_path,rust_workspace)
    if upstream_lock:
        (repo/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "increment"\nversion = "0.1.0"\n\n[[package]]\nname = "sample"\nversion = "0.1.0"\ndependencies = ["increment"]\n')
    original=capture(repo).files
    engine.start(repo,plan_only=True)
    engine.implementation.prepare_run(engine.runner,engine.state.snapshot.id,60,'bwrap')
    basis=json.loads(next((engine.root/'build-inputs/targets').rglob('basis.json')).read_text())
    lock=engine.root/basis['lock']['record']
    assert basis['lock']['origin']==('source' if upstream_lock else 'prepared') and lock.is_file()
    if upstream_lock:assert lock.read_bytes()==(repo/'Cargo.lock').read_bytes()
    assert capture(repo).files==original and not (engine.root/'.execution/cargo-seeds').exists()
    assert not engine.state.checks and not engine.state.usage.get('experiments')


def test_cargo_feature_variants_and_repeat_keep_exact_build_inputs(tmp_path,rust_workspace):
    import shutil
    from support.audit import cargo_engine, stop
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.adapters.storage.snapshot import capture
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    manifest=rust_workspace/'sample/Cargo.toml'
    manifest.write_text(manifest.read_text()+'[features]\ndefault=["base"]\nbase=[]\nextra=["increment/alternate"]\nspare=[]\n')
    source='''#[test] fn measured() {
        println!("CA_EVENT {{\\"event\\":\\"variant\\",\\"base\\":{},\\"extra\\":{},\\"spare\\":{},\\"value\\":{}}}",
            cfg!(feature="base"), cfg!(feature="extra"), cfg!(feature="spare"), sample::step(2, 3));
    }
    #[test] fn unselected() { panic!("must not run"); }
    '''
    variants=[({},[True,False,False,3]),({'features':['extra']},[True,True,False,4]),
        ({'features':['extra'],'default_features':False},[False,True,False,4]),
        ({'all_features':True},[True,True,True,4])]
    def submit(index):
        def step(state):
            selection,_=variants[index]
            request=dict(investigation_id=state['investigations'][0]['id'] if index else '@q',
                harness_path='check.rs',source_ids=['code'],scope={'description':'Captured feature variant'},
                prefix='Call the original public API under the selected Cargo features.',
                test_names=['measured'],**selection)
            sub={'rationale':'Observe the actual selected build','experiment':request}
            if index:
                request.update(previous_id=state['experiments'][-1]['id'],revision_reason='Select a different supported feature combination')
            else:
                sub.update(sources=[dict(id='code',file='sample/src/lib.rs',start_line=1,end_line=3,kind='code_observation')],
                    investigations=[dict(ref='@q',question='Which public behavior does this feature selection execute?',source_ids=['code'])])
            return sub,{'check.rs':source}
        return step
    def repeat(state):
        return {'rationale':'Repeat the saved extra-feature experiment','repeat_experiment_id':state['experiments'][1]['id']}, {
            'check.rs':'invalid Rust; drafts must not change a repeat',
            'selection.json':'{"all_features":true}'}
    engine,repo=cargo_engine(tmp_path,rust_workspace,[*(submit(i) for i in range(4)),repeat,stop],tmp_path/'shared-seeds')
    engine.config.budget.experiments=5;engine.config.budget.total_seconds=180
    original=capture(repo).files
    state=engine.start(repo)
    checks=[c for c in state.checks if c.action=='experiment']
    assert len(state.experiments)==4 and len(checks)==5,state.stop_reason
    assert all(c.outcome=='tests_passed' for c in checks),[(c.reason,Path(c.stderr).read_text()) for c in checks]
    observed=[[e[k] for k in ('base','extra','spare','value')] for c in checks for e in extract_events(c)]
    assert observed==[value for _,value in variants]+[variants[1][1]]
    assert len({c.parameters['build_inputs'] for c in checks})==4
    assert checks[1].parameters['seed_record']==checks[-1].parameters['seed_record']
    assert checks[1].experiment_id==checks[-1].experiment_id
    feedback=json.loads((engine.root/'research.json').read_text())['build_inputs']
    for artifact,check in zip(state.experiments,checks):
        selected={key:getattr(artifact.basis.harness,key) for key in ('features','default_features','all_features')}
        basis=json.loads((engine.root/check.parameters['build_inputs']).read_text())
        view=next(item for item in feedback if item['record']==check.parameters['build_inputs'])
        assert basis['feature_selection']==view['feature_selection']==selected
        assert all(f in basis['resolved_features'] for f in selected['features'])
        assert check.parameters['lock_unchanged'] and check.parameters['changed_target_files']==[]
    assert len(list((tmp_path/'shared-seeds').glob('*/ready.json')))==4
    assert capture(repo).files==original and not (repo/'Cargo.lock').exists()


def test_cargo_selected_target_phases_and_read_only_source(tmp_path,rust_workspace):
    import shutil
    from consensus_assurance.core.config import TargetConfig
    from consensus_assurance.core.types import ExecutionStatus
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    from consensus_assurance.adapters.runners.experiment import run_experiment,extract_events
    from consensus_assurance.adapters.storage.snapshot import capture
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    backend=CargoBackend(TargetConfig(execution_package='sample'))
    shutil.copytree(rust_workspace,tmp_path/'source')
    files=capture(rust_workspace).files;workspace=tmp_path/'workspace';shutil.copytree(rust_workspace,workspace)
    harness=Harness(kind='rust_test',source='#[test] fn measured() { println!("CA_EVENT {{\\"event\\":\\"returned\\",\\"value\\":{}}}",sample::step(2,3)); }\n'
        '#[test] fn control() {}\n#[test] fn unrelated() { panic!("must not run"); }',
        description='Observe an actual public library call',semantic_changes=[],test_names=['measured','control'])
    filename=backend.resolve_harness(harness,rust_workspace,files)
    assert filename=='sample/tests/assurance_generated.rs' and harness.execution_package=='./sample'
    install_harness(workspace,filename,harness,files)
    runner=ProcessRunner(tmp_path)
    command=backend.experiment_command(harness.execution_package,filename,harness.test_names)
    backend.package='.'
    assert backend.experiment_command(harness.execution_package,filename,harness.test_names)==command
    check=run_experiment(runner,command,workspace,'rust-fixture',60,'bwrap',adapter=backend)
    assert check.outcome=='tests_passed',Path(check.stderr).read_text()
    assert {t['name'] for t in check.parameters['test_selection']['observed']}=={'measured','control'}
    assert extract_events(check)[0]['value']==3
    assert capture(rust_workspace).files==files and not (rust_workspace/'Cargo.lock').exists()
    assert (workspace/'Cargo.lock').exists()
    assert backend.cache not in backend.read_only_roots()
    retained={Path(path):Path(path).read_bytes() for path in (check.stdout,check.stderr)}
    seed=tmp_path/check.parameters['seed_record']
    backend.cleanup(workspace)
    assert not (workspace/'.execution/cargo-target').exists() and seed.is_file()
    assert all(path.read_bytes()==data for path,data in retained.items())
    command=backend.experiment_command(harness.execution_package,filename)
    for source,outcome,failure in [
        ('invalid Rust', 'unknown','build_or_setup'),
        ('#[test] fn failed() { panic!("actual failure"); }','tests_failed','test_failure'),
        ('// No tests here\n','not_applicable',None),
        ('#[test] #[ignore] fn ignored() {}','not_applicable',None)]:
        (workspace/filename).write_text(source)
        check=run_experiment(runner,command,workspace,'rust-fixture',60,'bwrap',adapter=backend)
        assert (check.outcome,check.parameters.get('failure_class'))==(outcome,failure),Path(check.stderr).read_text()
        backend.cleanup(workspace)
        assert not (workspace/'.execution/cargo-target').exists() and seed.is_file()
    (workspace/filename).write_text('#[test] fn slow() { std::thread::sleep(std::time::Duration::from_secs(5)); }')
    check=run_experiment(runner,command,workspace,'rust-fixture',1,'bwrap',adapter=backend)
    assert check.status==ExecutionStatus.TIMEOUT and check.outcome=='unknown' and check.parameters['test_started']
    for package in ('../escape','/tmp','--workspace','sample/...'):
        with pytest.raises(ValueError):backend.resolve_harness(harness.model_copy(update={'execution_package':package}),rust_workspace,files)
    for name in ('Cargo.toml','Cargo.lock','sample/build.rs','.cargo/config.toml','rust-toolchain.toml'):
        with pytest.raises(ValueError,match='dependency definitions'):
            install_harness(rust_workspace,filename,harness.model_copy(update={'files':{name:'override'}}),files,write=False)
    (rust_workspace/'linked').symlink_to(rust_workspace/'sample',target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):
        backend.resolve_harness(harness.model_copy(update={'execution_package':'linked'}),rust_workspace,{**files,'linked/Cargo.toml':'untrusted'})
    (workspace/'.execution/escape').symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):backend.environment(workspace/'.execution/escape')
