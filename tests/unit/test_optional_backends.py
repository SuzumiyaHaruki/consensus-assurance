"""Tool selection and timeout boundaries, without a real Codex or target process."""
import json
import sys
import time
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.audit import add_support
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.types import Harness


@pytest.mark.real
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
    roots=[Path('/home/toolchain'),Path('/home/cargo/registry')]
    adapter=SimpleNamespace(seed_cache_dir=cache,read_only_roots=lambda:roots);runner=ProcessRunner(root)
    seed=root/'seed';seed.mkdir();(seed/'artifact').write_bytes(b'neutral fixture bytes')
    basis=dict(source_files={'lib.rs':'source'},source_modes={'lib.rs':420},manifest='Cargo.toml',
        test_target='check',workspace_manifest='Cargo.toml',package_id='local',package_name='local',
        tools=[{'version':'fixture'}],policy={'jobs':2,'inherited_environment':{
            'PATH':'/home/hidden:/usr/bin:/bin:/usr/bin:/home/toolchain/bin','LANG':'C'}},
        resolved_features=[],lock={'path':'Cargo.lock','digest':'lock'})
    command=['cargo','test','--','--nocapture']
    expected=cargo_build.compatibility(basis,command)
    assert cargo_build.compatibility(basis,command+['--exact','one','two'])==expected
    for field in ('source_files','source_modes','lock','tools','policy','test_target'):
        changed=copy.deepcopy(basis);changed[field]='different'
        if field=='lock':changed[field]={'path':'Cargo.lock','digest':'different'}
        assert cargo_build.compatibility(changed,command)!=expected
    def access(**kwargs):
        return cargo_build.shared_seed(adapter,runner,'fixture',command,basis,seed,time.monotonic()+5,**kwargs)
    published=access(origin={'selected_features':[]});assert published['status']=='published'
    key=published['key'];entry=cache/key
    normalized=cargo_build.seed_search_path(expected,roots)
    assert normalized['policy']['inherited_environment']['PATH']=='/usr/bin:/bin:/home/toolchain/bin'
    assert expected['policy']==basis['policy']  # Preserve the recorded raw environment.
    environment=basis['policy']['inherited_environment'];original_path=environment['PATH']
    environment['PATH']='/usr/bin:/root/hidden:/bin:/home/toolchain/bin:/usr/bin'
    assert access()['status']=='hit' and (seed/'artifact').read_bytes()==b'neutral fixture bytes'
    for changed in ('/bin:/usr/bin:/home/toolchain/bin','/usr/bin:/bin',
            '/home/cargo/registry/bin:/usr/bin:/bin:/home/toolchain/bin',
            ':/usr/bin:/bin:/home/toolchain/bin','relative:/usr/bin:/bin:/home/toolchain/bin',
            '/home/hidden', '',
            '/tmp/consensus-cargo/bin:/usr/bin:/bin:/home/toolchain/bin'):
        environment['PATH']=changed
        assert access()['status']=='miss'
    environment['PATH']=original_path;environment['LANG']='different'
    assert access()['status']=='miss'
    environment['LANG']='C'
    # Existing raw-PATH receipts remain usable without rewriting their provenance.
    marker=entry/'ready.json';legacy=json.loads(marker.read_text());legacy['compatibility']=expected
    marker.write_text(json.dumps(legacy));saved=marker.read_bytes()
    key=cargo_build.digest(json.dumps(expected,sort_keys=True).encode())
    entry.rename(cache/key);entry=cache/key
    assert access()['status']=='hit' and access()['key']==key
    assert (entry/'ready.json').read_bytes()==saved
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
    from types import SimpleNamespace
    backend=SimpleNamespace(harness_filename='check.py',support_files=lambda:{'support.py':'value = 1\n'})
    harness=Harness(kind='python',source='import support\n',description='Helper input boundary',semantic_changes=[])
    add_support(backend,harness)
    expected=backend.support_files()
    assert harness.files==expected and len(expected)==1
    with pytest.raises(ValueError,match='replace selected'):add_support(backend,harness)
    with pytest.raises(ValueError,match='replace target'):install_harness(tmp_path,backend.harness_filename,harness,expected)
    install_harness(tmp_path,backend.harness_filename,harness,{})
    assert all((tmp_path/name).read_text()==content for name,content in expected.items())
    harness.files['support.py']='value = 2\n'
    with pytest.raises(ValueError,match='saved artifact'):install_harness(tmp_path,backend.harness_filename,harness,{})


@pytest.mark.parametrize('limit,action,timeout,remaining,reason',[
    ('total_seconds','agent_turn',1,.02,'Total runtime budget exhausted'),
    ('agent_turn_timeout','agent_turn',.02,None,'Agent turn timeout exceeded'),
    ('action_timeout','direct_check',.02,None,'Action timeout exceeded')])
def test_actual_limiting_timeout_is_recorded(tmp_path,limit,action,timeout,remaining,reason):
    runner=ProcessRunner(tmp_path)
    if remaining is not None:runner.deadline=time.monotonic()+remaining
    check=runner.run([sys.executable,'-c','import time; time.sleep(2)'],tmp_path,action,'fixture',timeout)
    assert check.status.value=='timeout' and check.parameters['timeout_limit']==limit
    assert Path(check.stdout).exists() and check.reason==reason+'; process group killed'
    assert json.loads((Path(check.stdout).parent/'check.json').read_text())['reason']==check.reason


@pytest.mark.parametrize('selection',[
    {'execution_package':'/tmp'}, {'execution_package':'../outside'}, {'execution_package':'-args'},
    {'execution_package':'./...'}, {'execution_package':'. ./internal/core'}, {'execution_package':'.;true'},
    {'execution_package':'example.org/other'}, {'execution_package':'internal/escape'},
    {'execution_package':'internal/core/value.go'},
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
    from support.audit import engine_for
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
    from support.audit import first
    sub, _ = first({})
    sub['experiment'] = dict(investigation_id='@q',harness_path='check.go',source_ids=['code'],
        scope={'description':'Local placement'},prefix='No execution during preflight',**selection)
    (draft/'submission.json').write_text(json.dumps(sub));(draft/'check.go').write_text('package service\n')
    (draft/'helper.go').write_text('package service\n')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:pytest.fail('Validation cannot execute'))
    saved=engine.state.model_dump(mode='json')
    result=validate_submission(engine.state,engine.root,'submission.json',engine.implementation)
    assert not result['valid'] and result['diagnostics']
    assert engine.state.model_dump(mode='json')==saved
    with pytest.raises(ValueError):prepare_submission(engine,AuditSubmission.model_validate(sub),Inputs(draft),'invalid')
    assert not (engine.root/'experiments').exists() and not engine.state.checks and not engine.state.experiments


def test_exact_test_selection_validation():
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    from consensus_assurance.core.submissions import ExperimentRequest
    from pydantic import TypeAdapter
    from consensus_assurance.core.types import TestNames
    for names in ([],[''],['a','a'],[' a'],[1]):
        with pytest.raises(ValueError):TypeAdapter(TestNames).validate_python(names)
    assert 'test_names' in ExperimentRequest.model_json_schema()['properties']
    for names in (['TestOther'],['TestAssurance.*'],['TestAssurance/child'],['--run']):
        with pytest.raises(ValueError):GoModuleBackend.test_pattern(names)
    for names in (['module::*'],['--ignored'],['module::'],['module/test']):
        with pytest.raises(ValueError):CargoBackend.test_filters(names)
    assert CargoBackend.test_filters(['module::case','control'])==['--exact','module::case','control']


@pytest.mark.parametrize('backend_name',['go','rust'])
@pytest.mark.parametrize('case,expected',[
    ('passed','tests_passed'),('missing','unknown'),('absent','not_applicable'),
    ('skipped','unknown'),('failed','tests_failed'),('timeout','unknown')])
def test_selected_native_results_preserve_partial_and_unknown_status(backend_name,case,expected):
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    from consensus_assurance.core.types import CheckRun,ExecutionStatus
    names=['TestAssuranceOne','TestAssuranceTwo'] if backend_name=='go' else ['module::one','control']
    backend=GoModuleBackend() if backend_name=='go' else CargoBackend.__new__(CargoBackend)
    if backend_name=='rust':backend.cargo=Path('/usr/bin/cargo');backend.package='.';backend.harness_filename='tests/check.rs'
    check=CheckRun(action='experiment',cwd='/tmp',snapshot_id='fixture',
        command=backend.experiment_command(test_names=names),
        status=ExecutionStatus.TIMEOUT if case=='timeout' else ExecutionStatus.COMPLETED,
        exit_code=None if case=='timeout' else 1 if case=='failed' else 0)
    endings=[('pass' if backend_name=='go' else 'ok')]*2
    endings[1]={'skipped':'skip' if backend_name=='go' else 'ignored',
        'failed':'fail' if backend_name=='go' else 'FAILED','timeout':None}.get(case,endings[1])
    count=0 if case=='absent' else 1 if case=='missing' else 2
    if backend_name=='go':
        events=[]
        for name,end in zip(names[:count],endings):
            events.append({'Action':'run','Test':name,'Package':'fixture'})
            if end:events.append({'Action':end,'Test':name,'Package':'fixture'})
        text='\n'.join(json.dumps(event) for event in events)
    else:
        text=f'running {count} tests\n'
        for name,end in zip(names[:count],endings):
            text+=f'test {name} ... CA_EVENT {{"event":"measured"}}\n'
            if name==names[1] and case in {'failed','timeout'}:text+='ok\n'
            text+=end+'\n' if end else ''
        if case!='timeout':text+=f'test result: {"FAILED" if case=="failed" else "ok"}. {0 if count==0 else 2 if case=="passed" else 1} passed; {int(case=="failed")} failed;\n'
    backend.parse_test_result(check,text)
    selection=check.parameters['test_selection']
    assert selection['requested']==names and check.outcome==expected
    assert selection['unobserved']==names[count:]
    if case=='failed':assert selection['observed'][-1]['status']=='failed'
    if case=='timeout':
        assert check.status==ExecutionStatus.TIMEOUT and selection['observed'][-1]['status']=='unfinished'
