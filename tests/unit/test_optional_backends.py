"""Tool selection and timeout boundaries, without a real Codex or target process."""
import ast
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.audit import add_support
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.proposals import Harness


@pytest.mark.parametrize('upstream_lock',[False,True])
def test_cargo_preparation_retains_lock_origin(tmp_path,rust_workspace,upstream_lock):
    import shutil
    from audit_support import cargo_engine
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
    harness=Harness(kind='rust_test',source='#[test] fn measured() { println!("CA_EVENT {{\\"event\\":\\"returned\\",\\"value\\":{}}}",sample::step(2,3)); }',
        description='Observe an actual public library call',semantic_changes=[])
    filename=backend.resolve_harness(harness,rust_workspace,files)
    assert filename=='sample/tests/assurance_generated.rs' and harness.execution_package=='./sample'
    install_harness(workspace,filename,harness,files)
    runner=ProcessRunner(tmp_path)
    command=backend.experiment_command(harness.execution_package,filename)
    backend.package='.'
    assert backend.experiment_command(harness.execution_package,filename)==command
    check=run_experiment(runner,command,workspace,'rust-fixture',60,'bwrap',adapter=backend)
    assert check.outcome=='tests_passed',Path(check.stderr).read_text()
    assert extract_events(check)[0]['value']==3
    assert capture(rust_workspace).files==files and not (rust_workspace/'Cargo.lock').exists()
    assert (workspace/'Cargo.lock').exists()
    assert backend.cache not in backend.read_only_roots()
    for source,outcome,failure in [
        ('invalid Rust', 'unknown','build_or_setup'),
        ('#[test] fn failed() { panic!("actual failure"); }','tests_failed','test_failure'),
        ('// No tests here\n','not_applicable',None),
        ('#[test] #[ignore] fn ignored() {}','not_applicable',None)]:
        (workspace/filename).write_text(source)
        check=run_experiment(runner,command,workspace,'rust-fixture',60,'bwrap',adapter=backend)
        assert (check.outcome,check.parameters.get('failure_class'))==(outcome,failure),Path(check.stderr).read_text()
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


def test_default_assembly_respects_plugin_dependency_boundary():
    root=Path(__file__).resolve().parents[2]/'src/consensus_assurance'
    for package in ('core','workflow'):
        for path in (root/package).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):assert 'plugins' not in (node.module or '').split('.')
                if isinstance(node,ast.Import):assert all('plugins' not in a.name.split('.') for a in node.names)
    code='''import sys
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
backend, agent, knowledge = assemble(Config(execution_backend="python",agent_backend="mock"))
assert not any("plugins.targets" in name for name in sys.modules)
'''
    subprocess.run([sys.executable,'-c',code],check=True)
    assert Config().activity_focus==[]


def test_cargo_shared_seed_configuration_and_private_paths(tmp_path,monkeypatch):
    import shutil
    from consensus_assurance.cli import load_config
    from consensus_assurance.adapters.runners import cargo_build
    from consensus_assurance.adapters.agents.backend import CodexAgent
    if not shutil.which('cargo'):pytest.skip('Local Rust is required')
    assert Config().cargo_seed_cache_dir is None
    for data in ({'cargo_seed_cache_dir':'seeds'}, {'execution_backend':'cargo','cargo_seed_cache_dir':''},
            {'execution_backend':'cargo','runs_dir':str(tmp_path/'runs'),'cargo_seed_cache_dir':str(tmp_path/'runs/seeds')}):
        with pytest.raises(ValueError,match='[Cc]argo'):Config.model_validate(data)
    config=tmp_path/'cargo.yaml';config.write_text('execution_backend: cargo\nagent_backend: mock\ncargo_seed_cache_dir: seeds\n')
    cfg=load_config(config);backend=assemble(cfg)[0]
    assert cfg.cargo_seed_cache_dir==str(tmp_path/'seeds')==str(backend.seed_cache_dir)
    for path in ('~/.cache/consensus-assurance/cargo-seeds',str(tmp_path/'seeds')):
        config.write_text('execution_backend: cargo\ncargo_seed_cache_dir: '+path+'\n')
        assert load_config(config).model_dump()['cargo_seed_cache_dir']==str(Path(path).expanduser())
    root=tmp_path/'run';root.mkdir();source=tmp_path/'original';source.mkdir()
    (root/'snapshot.json').write_text(json.dumps({'repo':str(source)}))
    link=tmp_path/'link';link.symlink_to(source,target_is_directory=True)
    public=tmp_path/'public';public.mkdir(mode=0o755)
    for path in (root/'draft/cache',source/'cache',tmp_path,link/'cache',public,cargo_build.VIEW/'cache'):
        backend.seed_cache_dir=path
        with pytest.raises(ValueError,match='Cargo seed cache'):backend.prepare_run(ProcessRunner(root),'snapshot',1,'bwrap')
    backend.seed_cache_dir=Path(cfg.cargo_seed_cache_dir)
    assert cargo_build.cache_directory(backend,root)==backend.seed_cache_dir
    assert not backend.seed_cache_dir.exists()  # Path validation does not prewarm.
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/'+name)
    agent=CodexAgent();agent.read_only_roots=backend.read_only_roots()
    options='\n'.join(agent.permission_options(root,root/'draft'))
    assert json.dumps(str(backend.seed_cache_dir)) not in options
    assert '":root"="deny"' in options and json.dumps(str(root/'draft'))+'="write"' in options


def test_shared_seed_identity_and_directory_boundaries(tmp_path):
    import copy,fcntl
    from types import SimpleNamespace
    from consensus_assurance.adapters.runners import cargo_build
    # Minimal controller cache fixture; these bytes are not claimed to be compiled target evidence.
    root=tmp_path/'run';root.mkdir();cache=tmp_path/'cache'
    adapter=SimpleNamespace(seed_cache_dir=cache);runner=ProcessRunner(root)
    seed=root/'seed';seed.mkdir();(seed/'artifact').write_bytes(b'neutral fixture bytes')
    basis=dict(source_files={'lib.rs':'source'},source_modes={'lib.rs':420},manifest='Cargo.toml',
        test_target='check',workspace_manifest='Cargo.toml',package_id='local',package_name='local',
        tools=[{'version':'fixture'}],policy={'jobs':2},resolved_features=[],lock={'path':'Cargo.lock','digest':'lock'})
    command=['cargo','test','--','--nocapture']
    expected=cargo_build.compatibility(basis,command)
    for field in ('source_files','source_modes','lock','tools','policy','test_target'):
        changed=copy.deepcopy(basis);changed[field]='different'
        if field=='lock':changed[field]={'path':'Cargo.lock','digest':'different'}
        assert cargo_build.compatibility(changed,command)!=expected
    def access(**kwargs):
        return cargo_build.shared_seed(adapter,runner,'fixture',command,basis,seed,time.monotonic()+5,**kwargs)
    published=access(origin={'selected_features':[]});assert published['status']=='published'
    key=published['key'];entry=cache/key
    assert access()['status']=='hit' and (seed/'artifact').read_bytes()==b'neutral fixture bytes'
    with (cache/(key+'.lock')).open() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);assert 'in use' in access()['reason']
    marker=entry/'ready.json';saved=marker.read_bytes();marker.unlink()
    assert access()['status']=='miss'
    marker.write_bytes(saved)
    link=entry/'seed/link';link.symlink_to(tmp_path)
    assert 'link' in access()['reason'];link.unlink()
    (entry/'seed/artifact').chmod(0o600)
    assert 'bytes or modes differ' in access()['reason']
    with pytest.raises(TimeoutError):cargo_build.seed_inventory(entry/'seed',time.monotonic()-1)


def test_selected_support_is_captured_once_and_cannot_replace_target(tmp_path):
    backend=assemble(Config(execution_backend='hashicorp_raft',agent_backend='mock'))[0]
    harness=Harness(kind='go_test',source='package raft\n',description='Helper input boundary',semantic_changes=[])
    add_support(backend,harness)
    expected=backend.support_files()
    assert harness.files==expected and len(expected)==1
    with pytest.raises(ValueError,match='replace selected'):add_support(backend,harness)
    with pytest.raises(ValueError,match='replace target'):install_harness(tmp_path,backend.harness_filename,harness,expected)
    install_harness(tmp_path,backend.harness_filename,harness,{})
    assert all((tmp_path/name).read_text()==content for name,content in expected.items())
    harness.files[next(iter(expected))]='package raft\n'
    with pytest.raises(ValueError,match='saved artifact'):install_harness(tmp_path,backend.harness_filename,harness,{})


@pytest.mark.parametrize('limit,action,timeout,remaining',[
    ('total_seconds','agent_turn',1,.02),('agent_turn_timeout','agent_turn',.02,None),('action_timeout','direct_check',.02,None)])
def test_actual_limiting_timeout_is_recorded(tmp_path,limit,action,timeout,remaining):
    runner=ProcessRunner(tmp_path)
    if remaining is not None:runner.deadline=time.monotonic()+remaining
    check=runner.run([sys.executable,'-c','import time; time.sleep(2)'],tmp_path,action,'fixture',timeout)
    assert check.status.value=='timeout' and check.parameters['timeout_limit']==limit
    assert Path(check.stdout).exists() and 'killed' in check.reason


def test_retired_configuration_and_products_are_rejected():
    from consensus_assurance.core.submissions import AuditSubmission
    from consensus_assurance.cli import load_config
    assert load_config() == Config()
    for legacy in ({'verifier_backend':'tlc'}, {'verifier_backend':'none'}, {'tlc_jar':'missing'}, {'budget':{'model_checks':1}}):
        with pytest.raises(ValueError, match='no longer supported'):Config.model_validate(legacy)
    with pytest.raises(ValueError):AuditSubmission.model_validate({'action':'model','rationale':'Removed product'})


@pytest.mark.parametrize('selection',[
    {'execution_package':'/tmp'}, {'execution_package':'../outside'}, {'execution_package':'-args'},
    {'execution_package':'./...'}, {'execution_package':'. ./internal/core'}, {'execution_package':'.;true'},
    {'execution_package':'example.org/other'}, {'execution_package':'internal/escape'},
    {'execution_package':'internal/child'}, {'execution_package':'internal/core/value.go'},
    {'files':{'value.go':'helper.go'}}, {'files':{'go.work':'helper.go'}},
    {'files':{'internal/core/go.mod':'helper.go'}},
    {'execution_package':'internal/core','files':{'internal/core/assurance_generated_test.go':'helper.go'}},
    {'files':{'internal/child/helper.go':'helper.go'}}, {'files':{'vendor/modules.txt':'helper.go'}},
])
def test_package_boundaries_match_preflight_and_admission_without_execution(tmp_path,go_module,selection,monkeypatch):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.workflow.audit import validate_submission, Inputs, prepare_submission
    from consensus_assurance.core.submissions import AuditSubmission
    from audit_support import engine_for
    from consensus_assurance.core.types import Analysis
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.budget import BudgetTracker
    engine,repo=engine_for(tmp_path,[])
    shutil.copytree(go_module,repo,dirs_exist_ok=True)
    nested=repo/'internal/child';nested.mkdir();(nested/'go.mod').write_text('module example.org/child\n')
    (nested/'value.go').write_text('package child\n')
    engine.implementation=GoModuleBackend();engine.config.execution_backend='go_module'
    engine.state=Analysis(mode='mock',config=engine.config.model_dump(mode='json'),snapshot=capture(repo,engine.root/'source'))
    engine.budget=BudgetTracker(engine.config.budget,engine.state)
    shutil.copytree(engine.root/'source',engine.root/'agent-source')
    # Captured snapshots normally exclude links; both validation paths must still reject a damaged source view.
    for folder in ('source','agent-source'):(engine.root/folder/'internal/escape').symlink_to(tmp_path,target_is_directory=True)
    draft=engine.root/'draft';draft.mkdir()
    sub=dict(action='explore',question='Check local placement only',harness_path='check.go',rationale='Boundary control',**selection)
    (draft/'submission.json').write_text(json.dumps(sub));(draft/'check.go').write_text('package service\n')
    (draft/'helper.go').write_text('package service\n')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:pytest.fail('Validation cannot execute'))
    saved=engine.state.model_dump(mode='json')
    result=validate_submission(engine.state,engine.root,'submission.json',engine.implementation)
    assert not result['valid'] and result['diagnostics']
    assert engine.state.model_dump(mode='json')==saved
    with pytest.raises(ValueError):prepare_submission(engine,AuditSubmission.model_validate(sub),Inputs(draft),'invalid')
    assert not (engine.root/'experiments').exists() and not engine.state.checks and not engine.state.direct_checks


def test_python_rejects_go_override_and_go_default_path_conflict(tmp_path):
    from consensus_assurance.adapters.runners.python import PythonBackend
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.core.config import TargetConfig
    harness=Harness(kind='python',source='print(1)',description='Local check',semantic_changes=[],execution_package='.')
    with pytest.raises(ValueError,match='does not support'):PythonBackend().resolve_harness(harness,tmp_path,{})
    with pytest.raises(ValueError,match='target.harness_path'):
        GoModuleBackend(TargetConfig(execution_package='internal/core',harness_path='assurance_generated_test.go'))
