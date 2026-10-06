"""Audit products with scripted transport and actual isolated local execution."""
import json
from pathlib import Path
import pytest
from audit_support import products, first, check_step, review_step, stop, engine_for, feedback, cargo_engine, diagnostics


@pytest.mark.parametrize('outcome',['violated','compile_timeout'])
def test_rust_formal_check_and_exploration_share_existing_audit_path(tmp_path,rust_workspace,outcome):
    import shutil
    from consensus_assurance.adapters.storage.workspace_delta import restore
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    def initial(state):
        sub,files=first(state);sub['sources'][0].update(file='sample/src/lib.rs',end_line=3)
        return sub,files
    source='''#[test]
fn actual_boundary() {
    println!("CA_EVENT {{\\"event\\":\\"admitted\\",\\"operation\\":\\"one\\",\\"state\\":{{\\"legal\\":true}}}}");
    let value=sample::step(3,3);
    println!("CA_EVENT {{\\"event\\":\\"returned\\",\\"operation\\":\\"one\\",\\"state\\":{{\\"in_range\\":{}}}}}", (0..=3).contains(&value));
}
'''
    def check(state):
        sub,files=check_step()(state);plan=json.loads(files['plan.json']);plan['harness']['kind']='rust_test'
        sub.update(harness_path='check.rs',files={})
        return sub,{'plan.json':json.dumps(plan),'check.rs':source}
    def explore(state):
        return dict(action='explore',question='What does a legal interior invocation return?',harness_path='check.rs',
            execution_package='sample',rationale='Observe without creating another property'),{'check.rs':source.replace('step(3,3)','step(2,3)')}
    e,repo=cargo_engine(tmp_path,rust_workspace,[initial,check,review_step(),explore,stop])
    e.agent.mock=False
    if outcome=='compile_timeout':
        (repo/'increment/build.rs').write_text('fn main() { std::thread::sleep(std::time::Duration::from_secs(10)); }')
        e.config.budget.action_timeout=2;e.agent.steps=[initial,check,stop]
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    result=state.monitor_results[0]
    if outcome=='compile_timeout':
        from consensus_assurance.workflow.research import comparison_observed
        from consensus_assurance.reporting.chinese import render_report
        check=next(c for c in state.checks if c.action=='direct_check')
        assert check.status.value=='timeout' and check.parameters['build_activity'] and not check.parameters['test_started']
        assert not result['confirmed'] and result['outcome']=='unknown' and comparison_observed(result) is False
        assert not state.semantic_reviews and '构建期间超时' in render_report(state,e.root).read_text()
        from consensus_assurance.workflow.research import current_view
        preparation=current_view(state,e.root,e.implementation)['build_inputs'][0]
        assert preparation['status']=='preparation_failed'
        assert preparation['latest_preparation']['stage']=='cargo_seed_build'
        assert preparation['latest_preparation']['status']=='timeout' and preparation['latest_preparation']['process_seconds']>0
        return
    assert result['confirmed']
    assert result['outcome']==outcome and result['reviewed_complete']
    checks=[c for c in state.checks if c.action in {'direct_check','exploration'}]
    assert [c.action for c in checks]==['direct_check','exploration']
    assert all(c.parameters['execution_package']=='./sample' and c.outcome=='tests_passed' for c in checks)
    assert not (repo/'Cargo.lock').exists() and not list(repo.glob('**/assurance_generated.rs'))
    for i,c in enumerate(checks):
        manifest=next(p for p in c.artifacts if p.endswith('workspace-outcome/manifest.json'))
        restored=tmp_path/f'restored-{i}';restore(e.root/'source',manifest,restored)
        assert (restored/'Cargo.lock').is_file() and (restored/'sample/tests/assurance_generated.rs').is_file()


def test_rust_cross_action_seed_isolation_inputs_and_recovery(tmp_path,rust_workspace,monkeypatch):
    import shutil
    from consensus_assurance.adapters.runners import cargo_build
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.core.proposals import Harness
    from consensus_assurance.workflow.direct_checks import execute_harness
    from consensus_assurance.core.types import CheckRun
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    shared=tmp_path/'shared-seeds'
    e,repo=cargo_engine(tmp_path,rust_workspace,seed_cache=shared)
    e.config.budget.experiments=6;e.config.budget.action_timeout=60
    build='fn main() { assert!(std::fs::write('+json.dumps(str(shared/'build-script-write'))+', "untrusted").is_err()); }'
    (rust_workspace/'increment/build.rs').write_text(build);(repo/'increment/build.rs').write_text(build)
    e.start(repo,plan_only=True)
    checks=[]
    from consensus_assurance.workflow.research import current_view
    def preparation():
        saved=e.state.model_dump(mode='json')
        files={p:p.read_bytes() for directory in ('build-inputs','logs') for p in (e.root/directory).rglob('*.json')}
        with monkeypatch.context() as patch:
            patch.setattr(e.runner,'run',lambda *a,**kw:pytest.fail('Status query executed a tool'))
            patch.setattr(cargo_build,'tool_inputs',lambda *a,**kw:pytest.fail('Status query verified tools'))
            index=current_view(e.state,e.root,e.implementation)['build_inputs']
        assert e.state.model_dump(mode='json')==saved and all(p.read_bytes()==b for p,b in files.items())
        return {p['manifest']:p for p in index}
    assert preparation()['sample/Cargo.toml']['status']=='unprepared'
    e.implementation.prepare_run(e.runner,e.state.snapshot.id,60,'bwrap')
    assert preparation()['sample/Cargo.toml']['status']=='inputs_fixed'
    def run(value,package='sample'):
        text='invalid Rust' if value is None else '''#[test] fn actual() {
assert!(!std::path::Path::new("runtime-db").exists());
assert!(!std::path::Path::new("../.execution/cargo-target/poison").exists());
std::fs::write("runtime-db", "private").unwrap();
std::fs::write("../.execution/cargo-target/poison", "private").unwrap();
println!("CA_EVENT {{\\"event\\":\\"value\\",\\"value\\":{}}}", sample::step(VALUE,9));
}'''.replace('VALUE',str(value))
        if value is not None:
            text=text.replace('assert!(!std::path::Path::new("runtime-db").exists());',
                'assert!(std::fs::write('+json.dumps(str(shared/'forbidden-write'))+', "untrusted").is_err());\n'+
                'assert!(!std::path::Path::new("runtime-db").exists());')
        if package=='increment':text=text.replace('sample::step(VALUE,9)'.replace('VALUE',str(value)),'increment::value()')
        h=Harness(kind='rust_test',execution_package=package,source=text,description='Actual changed input',semantic_changes=[])
        filename=e.implementation.resolve_harness(h,e.root/'source',e.state.snapshot.files)
        e.state.current_submission={'harness':h.model_dump(mode='json'),'harness_filename':filename}
        if package=='increment':assert preparation()['increment/Cargo.toml']['status']=='unprepared'
        c=CheckRun.model_validate(e.action('exploration','experiments',lambda:execute_harness(e,h,filename,'exploration'),{'version':len(checks)}))
        e.record(c);checks.append(c);return c
    first_check=run(1);e.advance('next');second=run(4)
    assert first_check.parameters['seed_build']==second.parameters['seed_build']
    assert preparation()['sample/Cargo.toml']['status']=='seed_available'
    e.advance('other_crate');other=run(0,'increment')
    assert extract_events(other)[0]['value']==1 and other.parameters['seed_build']!=first_check.parameters['seed_build']
    prepared=preparation()['increment/Cargo.toml']
    assert prepared['status']=='seed_available' and prepared['compilations'][0]['record']==other.parameters['seed_record']
    assert [extract_events(c)[0]['value'] for c in (first_check,second)]==[2,5]
    assert len({c.id for c in checks})==len({c.cwd for c in checks})==3
    assert len({c.parameters['build_inputs'] for c in checks})==2
    basis=json.loads((e.root/first_check.parameters['build_inputs']).read_text())
    lock=e.root/basis['lock']['record'];locked=lock.read_bytes()
    assert basis['lock']['origin']=='prepared' and not (repo/'Cargo.lock').exists()
    for c in checks:
        assert c.started_at>=c.parameters['action_started_at']
        artifacts=json.loads(Path(c.parameters['cargo_artifacts']).read_text())
        deps=[a for a in artifacts if a['target']['name']=='increment']
        if c!=other:assert deps and all(a['fresh'] and 'instrumented' in a['features'] for a in deps)
        assert (Path(c.cwd)/'Cargo.lock').read_bytes()==locked
    seed=e.root/'.execution/cargo-seeds'
    assert not list(seed.rglob('poison')) and not list(seed.rglob('runtime-db'))
    original=cargo_build.tool_inputs
    with monkeypatch.context() as patch:
        patch.setattr(cargo_build,'tool_inputs',lambda a,deadline=None:original(a,deadline)+[{'version':'changed'}])
        with pytest.raises(ValueError,match='changed'):e.action('exploration','experiments',lambda:pytest.fail('reused result'),{'version':2})
    lock.write_bytes(locked+b'\n# unauthorized change\n')
    with pytest.raises(ValueError,match='changed'):e.implementation.validate_builds(e.root,e.state.snapshot.id)
    lock.write_bytes(locked)
    manifest=e.root/'source/sample/Cargo.toml';saved=manifest.read_bytes();manifest.write_bytes(saved+b'\n# changed feature basis\n')
    with pytest.raises(ValueError,match='changed'):e.implementation.validate_builds(e.root,e.state.snapshot.id)
    manifest.write_bytes(saved)
    saved_receipt=(e.root/first_check.parameters['seed_record']).read_bytes()
    first_engine,first_repo=e,repo
    (tmp_path/'independent').mkdir()
    e,repo=cargo_engine(tmp_path/'independent',rust_workspace,seed_cache=shared)
    e.start(repo,plan_only=True)
    assert e.state.id!=first_engine.state.id and e.state.snapshot.id!=first_engine.state.snapshot.id
    assert not e.state.monitor_results and not e.state.semantic_reviews and not e.state.question_candidates
    class Crash(BaseException):pass
    runner=e.runner.run
    with monkeypatch.context() as patch:
        def interrupt(command,cwd,action,*args,**kwargs):
            check=runner(command,cwd,action,*args,**kwargs)
            if action=='cargo_seed_materialize':raise Crash()
            return check
        patch.setattr(e.runner,'run',interrupt)
        with pytest.raises(Crash):run(12)
    reused=run(12)
    assert e.state.usage['experiments']==1 and reused.parameters['action_seconds'] is None
    assert extract_events(reused)[0]['value']==13 and reused.parameters['seed_build'] is None
    receipt=json.loads((e.root/reused.parameters['seed_record']).read_text())
    assert receipt['shared_seed']['status']=='hit' and receipt['shared_seed']['origin']['build_id']==first_check.parameters['seed_build']
    assert (e.root/'logs'/receipt['shared_seed']['copy_check_id']/'check.json').is_file()
    assert not (e.root/'logs'/first_check.parameters['seed_build']).exists()
    assert preparation()['sample/Cargo.toml']['latest_preparation']['stage']=='cargo_seed_materialize'
    logs=[json.loads(p.read_text()) for p in (e.root/'logs').glob('*/check.json')]
    assert not any(c['action']=='cargo_seed_build' for c in logs)
    assert len([c for c in logs if c['action']=='cargo_seed_materialize'])==2
    assert all(c['snapshot_id']==e.state.snapshot.id for c in logs)
    e.advance('invalid');invalid=run(None)
    assert invalid.status.value=='error' and not invalid.parameters['test_started'] and not extract_events(invalid)
    assert not list(shared.rglob('poison')) and not list(shared.rglob('runtime-db')) and not (shared/'forbidden-write').exists()
    assert not (shared/'build-script-write').exists()
    from consensus_assurance.reporting.chinese import Archive,render_report
    moved=tmp_path/'portable';shutil.copytree(e.root,moved,ignore=shutil.ignore_patterns('.execution','workspace'))
    with monkeypatch.context() as patch:
        opened=Path.open
        def archive_only(path,*args,**kwargs):
            assert not path.is_relative_to(e.root) and not path.is_relative_to(first_engine.root)
            return opened(path,*args,**kwargs)
        patch.setattr(Path,'open',archive_only)
        patch.setattr(cargo_build,'tool_inputs',lambda *a,**kw:pytest.fail('Archive verified tools'))
        archive=Archive(e.state,moved)
        archived=cargo_build.build_inputs(e.implementation,moved,e.state,archive.read)[0]
        assert archived['status']=='seed_unavailable'
        assert (moved/archived['latest_preparation']['record']).is_file()
        assert archive.path(reused.stdout).read_bytes()
        assert '探索执行正常结束' in render_report(e.state,moved).read_text()
    key=receipt['shared_seed']['key'];entry=shared/key
    # Corruption must force the original neutral path, never run a retained binary.
    next((entry/'seed').rglob('libincrement*.rlib')).write_bytes(b'corrupt')
    e,repo=first_engine,first_repo
    old=[c.model_dump(mode='json') for c in checks]
    shutil.rmtree(seed)
    assert all(p['status']=='seed_unavailable' and p['compilations'] for p in preparation().values())
    assert [c.model_dump(mode='json') for c in checks]==old
    e.advance('cold');cold=run(7)
    assert extract_events(cold)[0]['value']==8 and cold.parameters['seed_build']!=first_check.parameters['seed_build']
    rebuilt=json.loads((e.root/'logs'/cold.parameters['seed_build']/'cargo-artifacts.json').read_text())
    assert any(a['target']['name']=='increment' and a['fresh'] is False for a in rebuilt)
    assert (e.root/cold.parameters['build_inputs']).read_bytes()==(e.root/first_check.parameters['build_inputs']).read_bytes()
    assert (repo/'sample/src/lib.rs').read_bytes()==(rust_workspace/'sample/src/lib.rs').read_bytes()
    assert (e.root/first_check.parameters['seed_record']).read_bytes()==saved_receipt
    saved=json.loads((e.root/cold.parameters['seed_record']).read_text())
    assert saved['shared_seed']['status']=='miss' and 'bytes or modes differ' in saved['shared_seed']['reason']
    assert saved['shared_seed']['publication']['status']=='published'
    (tmp_path/'variant').mkdir()
    e,repo=cargo_engine(tmp_path/'variant',rust_workspace,seed_cache=shared)
    manifest=repo/'sample/Cargo.toml';manifest.write_text(manifest.read_text().replace('["instrumented"]','["instrumented","alternate"]'))
    e.start(repo,plan_only=True)
    variant=run(1)
    assert extract_events(variant)[0]['value']==3
    artifacts=json.loads((e.root/'logs'/variant.parameters['seed_build']/'cargo-artifacts.json').read_text())
    assert any(a['target']['name']=='increment' and a['fresh'] is False and 'alternate' in a['features'] for a in artifacts)
    assert json.loads((e.root/variant.parameters['build_inputs']).read_text())['snapshot_id']!=basis['snapshot_id']
    assert json.loads((e.root/variant.parameters['seed_record']).read_text())['shared_seed']['status']=='miss'
    shutil.rmtree(shared)
    assert (first_engine.root/first_check.parameters['seed_record']).read_bytes()==saved_receipt


@pytest.mark.parametrize('cut',['copy','partial_copy','process','adapter','unknown_process'])
def test_rust_same_action_recovers_materialization_and_execution(tmp_path,rust_workspace,monkeypatch,cut):
    import shutil
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.core.proposals import Harness
    from consensus_assurance.core.types import CheckRun
    from consensus_assurance.workflow.direct_checks import execute_harness
    if not shutil.which('cargo') or not shutil.which('bwrap'):pytest.skip('Local Rust and bubblewrap are required')
    shared=tmp_path/'shared-seeds' if cut in {'copy','process','adapter'} else None
    e,repo=cargo_engine(tmp_path,rust_workspace,seed_cache=shared)
    e.start(repo,plan_only=True)
    harness=Harness(kind='rust_test',source='''#[test] fn actual() {
assert!(!std::path::Path::new("executed-once").exists());
std::fs::write("executed-once", "actual execution").unwrap();
println!("CA_EVENT {{\\"event\\":\\"value\\",\\"value\\":{}}}",sample::step(4,9));
}''',description='Actual public call across a controlled crash',semantic_changes=[])
    filename=e.implementation.resolve_harness(harness,e.root/'source',e.state.snapshot.files)
    class Crash(BaseException):pass
    original=e.runner.run;interrupted=[];target_runs=[]
    def run(command,cwd,action,*args,**kwargs):
        check=original(command,cwd,action,*args,**kwargs)
        if action=='exploration':target_runs.append(check.id)
        if not interrupted and action==('cargo_seed_copy' if cut in {'copy','partial_copy'} else 'exploration') and cut!='adapter':
            interrupted.append(check);e.checkpoint('controlled_crash_after_raw_receipt')
            raise Crash()
        return check
    monkeypatch.setattr(e.runner,'run',run)
    def perform():
        check=execute_harness(e,harness,filename,'exploration')
        if cut=='adapter' and not interrupted:
            interrupted.append(check);e.checkpoint('controlled_crash_after_adapter_return');raise Crash()
        return check
    def action():return e.action('exploration','experiments',perform,{'generation':1})
    with pytest.raises(Crash):action()
    operation=e.state.pending_action.id;workspace=e.workspace()
    assert not (e.root/'actions'/operation/'result.json').exists()
    if cut=='partial_copy':
        copied=Path(interrupted[0].command[-1])
        next(copied.rglob('libincrement*.rlib')).unlink()
    if cut=='process':(workspace/'Cargo.lock').write_text('unverified replacement after the process receipt')
    if cut=='unknown_process':
        path=e.root/'logs'/interrupted[0].id/'check.json';raw=json.loads(path.read_text())
        raw.update(ended_at=None,status='running');path.write_text(json.dumps(raw))
    frozen={p:p.read_bytes() for p in (e.root/'logs'/interrupted[0].id).glob('*.log')}
    if shared:shutil.rmtree(shared)  # A lost shared entry cannot trigger replay of a completed target.
    monkeypatch.setattr('consensus_assurance.workflow.audit.execute',lambda engine:action())
    if cut=='unknown_process':
        with pytest.raises(ValueError,match='outcome unknown'):e.resume()
        assert len(target_runs)==1 and e.state.usage['experiments']==1
        return
    recovered=CheckRun.model_validate(e.resume())
    assert e.state.pending_action.id==operation and e.state.usage['experiments']==1
    assert extract_events(recovered)[0]['value']==5 and len(target_runs)==1
    artifacts=json.loads(Path(recovered.parameters['cargo_artifacts']).read_text())
    assert all(a['fresh'] for a in artifacts if a['target']['name']=='increment')
    assert all(p.read_bytes()==value for p,value in frozen.items())
    if cut=='adapter':assert recovered.parameters['action_seconds']==interrupted[0].parameters['action_seconds']
    else:assert recovered.parameters['action_seconds'] is None
    if cut=='process':
        assert recovered.status.value=='error' and 'integrity postprocessing' in recovered.reason
        assert recovered.parameters['changed_target_files'] is None and 'lock_unchanged' not in recovered.parameters
        assert (workspace/'Cargo.lock').read_text()=='unverified replacement after the process receipt'
    else:assert recovered.status.value=='completed' and recovered.parameters['lock_unchanged']
    copies=[json.loads(p.read_text()) for p in (e.root/'logs').glob('*/check.json') if json.loads(p.read_text())['action']=='cargo_seed_copy']
    assert len(copies)==(2 if cut in {'copy','partial_copy'} else 1)
    assert len({c['id'] for c in copies})==len(copies)
    cached=action()
    assert cached['id']==recovered.id and e.state.usage['experiments']==1
    assert len(target_runs)==1 and not (repo/'Cargo.lock').exists()


@pytest.mark.parametrize('fault',['compile','observation','observation_violation'])
@pytest.mark.usefixtures('full_refresh_equivalence')
def test_existing_unit_actual_technical_repair_review_progress(tmp_path,fault):
    def check(state,revise=False):
        if revise:assert not any(r.get('confirmed') for r in state['monitor_results']) and not state['review_issues']
        sub,files=check_step(broken=fault=='compile' and not revise,revise=revise)(state)
        if fault!='compile':
            files['helper.py']+='def observe(values,index):\n    return '+('values[index] if index < len(values) else None' if revise else 'values[index]')+'\n'
            files['check.py']=files['check.py'].replace('from helper import legal','from helper import legal, observe\nvalues=[]\nassert observe(values,0) is None, "invalid observation prefix"')
            files['check.py']=files['check.py'].replace('value=step(3,3)','values.append(step(3,3))\nvalue=observe(values,0)')
        return sub,files
    e,repo=engine_for(tmp_path,[first,check,lambda s:check(s,True),review_step(),stop])
    original=(repo/'target.py').read_text()
    if fault=='observation_violation':
        original=original.replace('else 0','else value + 1');(repo/'target.py').write_text(original)
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    assert len(state.direct_checks)==2, state.current_submission
    old,new=state.direct_checks
    assert new.previous_id==old.id and new.version==2
    executions=[c for c in state.checks if c.direct_check_id]
    assert len(executions)==2
    assert executions[0].exit_code!=0 and ('SyntaxError' if fault=='compile' else 'IndexError') in Path(executions[0].stderr).read_text()
    assert executions[1].exit_code==0
    assert all(r.kind=='F4' and not r.after['encoding_revision'] for r in state.revisions)
    assert len(state.claims)==len(state.question_candidates)==1
    before,after=[json.loads(Path(a.plan_path).read_text()) for a in (old,new)]
    for key in ('observable_properties','monitors'):assert before[key]==after[key]
    assert len(after['monitors'])==1
    assert state.monitor_results[-1]['outcome']==('violated' if fault=='observation_violation' else 'holds')
    assert state.units[0].status=='checked', state.units[0]
    assert not state.units[0].remaining_obligation_ids
    assert not state.review_issues
    assert (repo/'target.py').read_text()==original
    assert not (repo/'helper.py').exists()
    index=json.loads((e.root/'research.json').read_text())
    assert index['units'] and index['claims'] and index['artifacts']
    assert index['implementation']['harness_kind']=='python'


@pytest.mark.parametrize('fault',[None,'missing','escape','symlink','unreliable'])
def test_deadline_retains_only_reliably_declared_bytes(tmp_path,fault):
    from consensus_assurance.core.types import ExecutionStatus
    from consensus_assurance.workflow.audit import Inputs
    saved={}
    def combined(state):
        candidate,files=first(state)
        _,plan,harness=products()
        sub=dict(action='check',candidate=candidate,plan_path='plan.json',harness_path='check.py',
            files={'helper.py':'helper.py'},rationale='Submit the complete local check')
        files.update({'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(v,n): return 0 <= v <= n\n'})
        if fault=='missing':files.pop('helper.py')
        if fault=='escape':sub['files']['helper.py']='../../outside.py'
        saved.update(files,**{'submission.json':json.dumps(sub)})
        if fault in {'escape','symlink'}:saved.pop('helper.py')
        return sub,files
    e,repo=engine_for(tmp_path,[combined,stop])
    (tmp_path/'outside.py').write_text('private sentinel')
    invoke=e.agent.investigate
    def investigate(*args,**kw):
        check,session,result=invoke(*args,**kw)
        if fault=='symlink':
            helper=e.root/'draft'/'helper.py';helper.unlink();helper.symlink_to(tmp_path/'outside.py')
        if fault=='unreliable':
            check.status=ExecutionStatus.TIMEOUT;check.reason='No reliable completed turn';result=None
        return check,session,result
    e.agent.investigate=investigate
    checkpoint=e.checkpoint
    def deadline(event):
        if event=='action_result_saved':e.budget.previous=e.config.budget.total_seconds
        checkpoint(event)
    e.checkpoint=deadline
    state=e.start(repo)
    archive=e.root/'submissions'/state.current_submission['operation_id']
    assert state.run_stop['reason']=='resource_limit' and state.usage['agent_calls']==1
    assert not state.claims and not state.evidence and not state.units and not state.applied_operations
    if fault=='unreliable':
        assert not (archive/'raw.json').exists() and not (archive/'inputs').exists()
        return
    assert state.current_submission['phase']=='received' and not (archive/'accepted.json').exists()
    assert json.loads((archive/'raw.json').read_text())==json.loads(saved['submission.json'])
    for name in saved:
        (e.root/'draft'/name).unlink()
        assert (archive/'inputs'/name).read_text()==saved[name]
    (e.root/'draft'/'helper.py').write_text('later replacement')
    if fault:
        errors=json.loads((archive/'diagnostics.json').read_text())
        assert errors['diagnostics'] and not (archive/'inputs'/'helper.py').exists()
        with pytest.raises(ValueError):Inputs(archive/'inputs').read('helper.py')
        assert 'private sentinel' not in ''.join(p.read_text() for p in archive.rglob('*') if p.is_file())
    e.checkpoint=checkpoint
    before={str(p.relative_to(archive)):p.read_bytes() for p in archive.rglob('*') if p.is_file()}
    state=e.resume()
    assert state.usage['agent_calls']==1 and not state.claims and not state.evidence
    assert before=={str(p.relative_to(archive)):p.read_bytes() for p in archive.rglob('*') if p.is_file()}


@pytest.mark.parametrize('product',[
    dict(action='research',map_path='map.json',graph_path='graph.json'),
    dict(action='research',map_path='map.json',scope_path='scope.json'),
    dict(action='semantic_revision',unit_id='unit',map_path='map.json',feedback_path='feedback.json'),
    dict(action='explore',question='Read actual local feedback',harness_path='probe.py',files={'helper.py':'helper.py'})])
def test_receipt_retains_all_explicit_product_files_without_acceptance(tmp_path,product):
    from consensus_assurance.workflow.audit import retain_receipt
    draft=tmp_path/'draft';draft.mkdir();archive=tmp_path/'archive'
    sub=dict(product,rationale='A completed receipt, not semantic acceptance')
    names=[v for k,v in product.items() if k.endswith('_path')]+list(product.get('files',{}).values())
    for name in names:(draft/name).write_text('First declared bytes')
    (draft/'unsubmitted.json').write_text('{"secret_path":"../outside"}')
    (draft/'submission.json').write_text(json.dumps(sub))
    result=dict(submission='submission.json',summary='Complete file product')
    retain_receipt(draft,archive,result)
    assert not (archive/'accepted.json').exists() and not (archive/'diagnostics.json').exists()
    assert {str(p.relative_to(archive/'inputs')) for p in (archive/'inputs').rglob('*')}==set(names+['submission.json'])
    for name in names:(draft/name).write_text('Changed later')
    retain_receipt(draft,archive,result)
    assert all((archive/'inputs'/name).read_text()=='First declared bytes' for name in names)


@pytest.mark.parametrize('interrupt',[False,True])
def test_rejected_receipt_recovery_pauses_only_the_draft(tmp_path,interrupt):
    malformed=lambda state:('{"action":',{})
    e,repo=engine_for(tmp_path,[malformed,malformed,first])
    e.config.budget.repair_attempts=2
    original=e.checkpoint
    def checkpoint(event):
        original(event)
        if interrupt and event=='agent_receipt_saved' and e.state.usage['agent_calls']==2:
            raise KeyboardInterrupt('Durable second malformed receipt')
    e.checkpoint=checkpoint
    if interrupt:
        with pytest.raises(KeyboardInterrupt):e.start(repo)
    else:e.start(repo)
    e.checkpoint=original
    state=e.resume()
    assert state.usage['agent_calls']==3 and len(state.units)==1
    assert all(Path(d['raw_path']).read_bytes()==b'{"action":' for d in diagnostics(e))
    rejected=[s for s in state.selections if s['action']=='rejected']
    assert len(rejected)==2 and rejected[-1]['draft_status']=='paused'
    assert rejected[0]['draft_id']==rejected[1]['draft_id']
    assert rejected[-1]['repeats']==2 and state.run_stop['reason']=='resource_limit'


def test_draft_symlinks_and_fixed_helper_bytes(tmp_path):
    from consensus_assurance.workflow.audit import Inputs,draft_file
    draft=tmp_path/'draft';draft.mkdir();archive=tmp_path/'archive'
    (draft/'real').mkdir();(draft/'real'/'helper.py').write_text('fixed')
    (draft/'alias').symlink_to(draft/'real',target_is_directory=True)
    (draft/'link').symlink_to(draft/'real'/'helper.py')
    for name in ('alias/helper.py','link','../outside'):
        with pytest.raises(ValueError):draft_file(draft,name)
    inputs=Inputs(draft)
    assert inputs.read('real/helper.py')=='fixed'
    (draft/'real'/'helper.py').write_text('modified')
    assert inputs.read('real/helper.py')=='fixed'


def test_accepted_check_recovers_without_remaining_model_call(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step()])
    original=e.checkpoint
    def checkpoint(event):
        original(event)
        if event=='semantic_operation_committed' and e.state.current_submission.get('direct_check_id'):
            raise KeyboardInterrupt('accepted before execution')
    e.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    assert e.state.usage['agent_calls']==2
    e.checkpoint=original
    state=e.resume()
    assert len([c for c in state.checks if c.direct_check_id])==1, state.stop_reason
    assert len(state.agent_turns)==2
    assert state.current_submission['phase']=='executed'


@pytest.mark.usefixtures('full_refresh_equivalence')
def test_same_version_reading_and_independent_issues(tmp_path):
    def original(state):
        sub,files=check_step()(state)
        plan=json.loads(files['plan.json'])
        plan['harness']['legality']['conflicts']=['The bound of this admitted invocation needs the documented contract']
        files['plan.json']=json.dumps(plan)
        return sub,files
    def issues(state):
        artifact=state['direct_checks'][-1]['id']
        return dict(action='review',artifact_id=artifact,rationale='Two distinct uncertainty sources',
            review_items=[dict(target_id=artifact,aspect='checker_correspondence',status='needs_reading',source_ids=['code'],rationale='Need the actual bound contract'),
                dict(target_id=artifact,aspect='applicability',status='disputed',source_ids=['doc'],rationale='External callers may supply illegal input',counterevidence=['The caller boundary remains outside this local test'])]),{}
    def resolve(state):
        from consensus_assurance.reporting.chinese import render_report
        text=render_report(e.state,e.root).read_text()
        for issue in e.state.review_issues:
            assert text.count(f'<a id="issue-{issue.id}"></a>')==1 and f'](#issue-{issue.id})' in text
        artifact=state['direct_checks'][-1]['id']
        issue=next(i for i in state['review_issues'] if i['aspect']=='checker_correspondence')
        other=next(i for i in state['review_issues'] if i['aspect']=='applicability' and not i['conditions'])
        condition=next(i for i in state['review_issues'] if i['conditions'])
        item=dict(target_id=artifact,aspect='checker_correspondence',status='no_issue_found',source_ids=['code','doc'],rationale='The actual README bounds the observed return for the explicitly admitted input')
        answer=dict(issue_id=issue['id'],source_ids=['code','doc'],rationale=item['rationale'],residual_issue_ids=[other['id']],scope_limitations=['Unrelated callers remain outside the observed invocation'])
        return dict(action='review',artifact_id=artifact,review_items=[item,{**item,'aspect':'applicability'}],rationale='Answer the named reading issue',
            resolutions=[answer,{**answer,'issue_id':condition['id'],'condition_dispositions':[dict(
                condition_id=condition['conditions'][0]['id'],applies_to='old_judgment',source_ids=['doc'],
                rationale='The documented legal bound applies to the actual admitted input; no input change is needed.')]}]),{}
    e,repo=engine_for(tmp_path,[first,original,issues,resolve,stop])
    state=e.start(repo)
    assert len(state.direct_checks)==1
    assert len(state.review_issues)==3
    assert next(i for i in state.review_issues if i.aspect=='checker_correspondence').resolved_by
    assert not next(i for i in state.review_issues if i.aspect=='applicability' and not i.conditions).resolved_by
    assert next(i for i in state.review_issues if i.conditions).resolved_by
    assert len([c for c in state.checks if c.direct_check_id])==1
    assert not any('needs the documented contract' in b for b in state.monitor_results[0]['blockers'])
    assert state.units[0].remaining_obligation_ids==['bounded']
    result = state.monitor_results[0]
    assert result['bounded_complete'] and not result['reviewed_complete'] and not result['confirmed']
    assert len(result['open_issue_ids']) == 1 and len(state.evidence) == 1 and not state.findings



@pytest.mark.parametrize('phase',['action_result_saved','agent_receipt_saved','runner_complete','agent_runner_complete'])
def test_recovery_does_not_repeat_model_or_target_execution(tmp_path,phase):
    e,repo=engine_for(tmp_path,[first,check_step()])
    original=e.checkpoint
    interrupted=False
    def checkpoint(event):
        nonlocal interrupted
        if (phase=='agent_runner_complete' and event=='action_result_saved'
                and e.state.pending_action.kind=='agent_turn' and e.state.usage['agent_calls']==2 and not interrupted):
            from consensus_assurance.adapters.agents.backend import CodexAgent
            from consensus_assurance.adapters.storage.files import write_json
            from consensus_assurance.core.types import now
            interrupted=True
            action=e.root/'actions'/e.state.pending_action.id
            raw=json.loads((action/'result.json').read_text())
            log=e.root/'logs'/raw[0]['id'];log.mkdir(parents=True,exist_ok=True)
            events=log/'stdout.log'
            events.write_text(json.dumps({'type':'thread.started','thread_id':'fixture-session'})+'\n'+json.dumps({'type':'turn.completed'}))
            raw[0].update(stdout=str(events),ended_at=now(),pending_action_id=e.state.pending_action.id)
            write_json(log/'check.json',raw[0]);write_json(action/'agent-response.json',raw[2])
            (action/'result.json').unlink()
            e.state.pending_action.status='running'
            e.agent.decode=CodexAgent().decode
            original('interruption_after_agent_raw_receipt')
            raise KeyboardInterrupt('Agent receipt before action result')
        if phase=='runner_complete' and event=='action_result_saved' and e.state.pending_action.kind=='direct_execute' and not interrupted:
            interrupted=True
            # Simulate receipt on disk before the action result manifest was saved.
            (e.root/'actions'/e.state.pending_action.id/'result.json').unlink()
            e.state.pending_action.status='running'
            original('interruption_after_raw_receipt')
            raise KeyboardInterrupt('receipt before action result')
        original(event)
        if event==phase and e.state.usage.get('agent_calls')==2 and not interrupted:
            interrupted=True
            raise KeyboardInterrupt('controlled interruption')
    e.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.checkpoint=original
    if phase=='agent_receipt_saved':
        for path in (e.root/'draft').iterdir():
            if path.is_file():path.write_text('Mutable draft replaced after reliable receipt')
    state=e.resume()
    assert len(state.agent_turns)==2
    assert state.usage['agent_calls']==2
    assert state.usage['experiments']==1
    assert len(state.direct_checks)==1
    assert len([c for c in state.checks if c.direct_check_id])==1
    receipts=[json.loads(p.read_text()) for p in (e.root/'logs').glob('*/check.json')]
    assert sum(r['action']=='direct_check' for r in receipts)==1


@pytest.mark.parametrize('fault',['malformed_final','missing_submission','session_lost','login','quota','service_refusal','timeout'])
def test_audit_receipt_failure_routes_preserve_or_stop_the_session(tmp_path,fault):
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.core.types import ExecutionStatus
    e,repo=engine_for(tmp_path,[first,lambda s:(dict(action='research',feedback=feedback(s),rationale='Retain sourced progress'),{}),check_step(),stop])
    original=e.agent.investigate
    sessions=[]
    def investigate(runner,prompt,directory,snapshot_id,timeout,session_id=None):
        sessions.append(session_id)
        check,_,receipt=original(runner,prompt,directory,snapshot_id,timeout,session_id)
        action=e.root/'actions'/runner.active_action_id
        response=action/'agent-response.json';response.write_text(json.dumps(receipt))
        events=action/'fixture-events.jsonl'
        events.write_text(json.dumps({'type':'thread.started','thread_id':session_id or 'fixture-session'})+'\n'+json.dumps({'type':'turn.completed'}))
        check.stdout=str(events)
        if len(sessions)==2:
            if fault=='malformed_final':response.write_text('{')
            elif fault=='missing_submission':response.write_text(json.dumps({'submission':'absent.json','summary':'Missing product'}))
            elif fault=='timeout':
                check.status=ExecutionStatus.TIMEOUT;check.exit_code=-9;check.reason='Single turn ended without a completion receipt'
                events.write_text(json.dumps({'type':'thread.started','thread_id':session_id}))
            else:
                check.exit_code=1
                events.write_text(json.dumps({'type':'turn.failed','error':{'message':{
                    'session_lost':'thread not found','login':'please log in; 401','quota':'insufficient_quota',
                    'service_refusal':'This content was flagged for possible cybersecurity risk.'}[fault]}}))
        return CodexAgent().decode(check,response,session_id)
    e.agent.investigate=investigate
    state=e.start(repo)
    assert len(state.units)==1
    if fault in {'login','quota','service_refusal','timeout'}:
        assert len(sessions)==2 and not state.direct_checks
        assert state.run_stop['origin']=='controller' and state.run_stop['reason']=='tool_gap'
        check=next(c for c in reversed(state.checks) if c.action=='agent_turn')
        assert check.status==({'login':ExecutionStatus.LOGIN_REQUIRED,'quota':ExecutionStatus.QUOTA_EXHAUSTED,'service_refusal':ExecutionStatus.ERROR,'timeout':ExecutionStatus.TIMEOUT}[fault])
        calls = state.usage['agent_calls']
        assert e.resume().usage['agent_calls'] == calls and len(sessions) == 2
    else:
        assert len(state.direct_checks)==1,state.current_submission
        assert sessions[2]==(None if fault=='session_lost' else 'fixture-session')
        if fault=='session_lost':assert any('session unavailable' in gap for gap in state.gaps)
        else:assert list((e.root/'submissions').glob('*/diagnostics.json'))


def test_explicit_resume_reads_executed_exploration_after_transport_timeout(tmp_path):
    import sys
    from audit_support import instance_products
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.reporting.chinese import render_report
    from consensus_assurance.core.types import ExecutionStatus
    source, spec = instance_products()
    def initial(state):
        sources = products()[0]['sources']
        sources[0]['end_line'] = len(source.splitlines())
        return dict(action='research', map_path='map.json', sources=sources,
            rationale='Retain the two connected instance paths'), {'map.json':json.dumps(spec)}
    def explore(state):
        return dict(action='explore', question='Does a decision survive a caller-selected context change?',
            harness_path='explore.py',
            rationale='Observe the retained decision under an explicit caller policy'), {
            'explore.py':
                "import json\nfrom target import create, change, support, read\n"
                "s=create(['a']); change(s,1); support(s,1,'a',7); change(s,2)\n"
                "print('CA_EVENT '+json.dumps({'event':'observed','value':read(s)}))\n"}
    def interpret(state):
        # Read the actual handoff written before invocation, never a closure-supplied result.
        assert e.state.pending_action.id != failed_action and state['usage']['agent_calls'] == 4
        index = json.loads((e.root/'research.json').read_text())
        entry, = index['explorations']
        product = json.loads((e.root/entry['submission']).read_text())
        assert product['question'].startswith('Does a decision survive')
        execution, = entry['executions']
        check = next(c for c in e.state.checks if c.id == execution['check_id'])
        assert extract_events(check)[0]['value'] == 7
        assert not entry['feedback'] and not index['pending_work']
        return dict(action='research', rationale='Interpret the retained execution without repeating it',
            feedback=dict(ref_ids=[check.id, 'code'], answered='Under the selected policy the observed decision remained 7',
                remaining=['External caller authorization remains outside scope'], understanding='unchanged',
                rationale='The existing map already retains this distinction')), {}
    e, repo = engine_for(tmp_path, [initial, explore, stop, interpret, stop])
    (repo/'target.py').write_text(source)
    original = e.agent.investigate
    sessions = []
    def investigate(runner, prompt, directory, snapshot_id, timeout, session_id=None):
        sessions.append(session_id)
        if len(sessions) != 3:
            return original(runner, prompt, directory, snapshot_id, timeout, session_id)
        e.agent.cursor += 1
        # A complete-looking draft is still unauthorized without a completed turn.
        (directory/'submission.json').write_text(json.dumps({'action':'research','rationale':'Unfinished draft'}))
        events = [{'type':'thread.started','thread_id':session_id},
            {'type':'error','message':'Reconnecting: stream disconnected: request timed out'}]
        command = [sys.executable, '-c', 'import time; print('+repr('\n'.join(map(json.dumps, events)))+', flush=True); time.sleep(10)']
        check = runner.run(command, directory, 'agent_turn', snapshot_id, .15)
        return CodexAgent().decode(check, runner.root/'actions'/runner.active_action_id/'agent-response.json', session_id)
    e.agent.investigate = investigate
    checkpoint = e.checkpoint
    def inspect_execution(event):
        checkpoint(event)
        if event == 'audit_execution_completed' and e.state.current_submission.get('action') == 'explore':
            index = json.loads((e.root/'research.json').read_text())
            assert e.state.pending_action.kind == 'exploration' and not index['pending_work']
            entry, = index['explorations']
            assert len(entry['executions']) == 1 and not entry['feedback']
            assert all((e.root/path).is_file() for path in entry['inputs'])
    e.checkpoint = inspect_execution
    state = e.start(repo)
    failed = next(c for c in state.checks if c.status == ExecutionStatus.TIMEOUT)
    assert state.current_submission['phase'] == 'failed' and len(sessions) == 3
    assert failed.parameters['timeout_limit'] == 'agent_turn_timeout'
    assert state.elapsed_seconds < e.config.budget.total_seconds and state.usage['agent_calls'] == 3
    assert not (e.root/'submissions'/failed.id).exists()
    assert state.usage['experiments'] == 1 and not state.claims and not state.evidence
    stopped_report = render_report(state, e.root).read_text()
    failed_action = state.pending_action.id
    elapsed = state.elapsed_seconds
    state = e.resume()
    assert state.usage['agent_calls'] == 5, 'Explicit resume must retire the failed attempt and request a fresh turn'
    assert sessions == [None] + ['fixture-session'] * 4
    assert state.elapsed_seconds >= elapsed and state.usage['experiments'] == 1
    assert any(a.id == failed_action for a in state.action_history) and state.pending_action.id != failed_action
    assert any(c.id == failed.id and c.status == ExecutionStatus.TIMEOUT for c in state.checks)
    assert not state.evidence and not state.claims and not (e.root/'submissions'/failed.id).exists()
    index = json.loads((e.root/'research.json').read_text())
    entry, = index['explorations']
    assert len(entry['executions']) == len(entry['feedback']) == 1
    assert '没有正式性质判定' in stopped_report and '| 问题 | 当前结果 |' not in stopped_report
    assert entry['executions'][0]['check_id'] in stopped_report and failed.id in stopped_report
    assert '后续受理解释（执行' not in stopped_report
    assert 'agent_turn_timeout' in stopped_report and '0.15' in stopped_report
    assert '双主线概览已就绪' in stopped_report
    continued = render_report(state, e.root).read_text()
    assert failed.id in continued and entry['feedback'][0]['submission'] in continued and 'observed decision remained 7' in continued


@pytest.mark.parametrize('boundary',['total','calls','config','snapshot','permissions','tools','repeat'])
def test_explicit_transport_resume_keeps_authority_and_global_limits(tmp_path,boundary):
    import sys
    from consensus_assurance.adapters.agents.backend import CodexAgent
    e,repo=engine_for(tmp_path,[stop,stop,stop])
    sessions=[]
    def disconnected(runner,prompt,directory,snapshot_id,timeout,session_id=None):
        sessions.append(session_id)
        events=[{'type':'thread.started','thread_id':'fixture-session'},
            {'type':'turn.failed','error':{'message':'stream disconnected: connection reset'}}]
        check=runner.run([sys.executable,'-c','print('+repr('\n'.join(map(json.dumps,events)))+'); raise SystemExit(1)'],
            directory,'agent_turn',snapshot_id,timeout)
        return CodexAgent().decode(check,runner.root/'actions'/runner.active_action_id/'agent-response.json',session_id)
    e.agent.investigate=disconnected
    state=e.start(repo)
    old=state.current_submission['operation_id']
    assert state.current_submission['phase']=='failed' and state.usage['agent_calls']==1
    if boundary=='total':e.budget.previous=e.config.budget.total_seconds;e.checkpoint('controlled_total_deadline')
    elif boundary=='calls':state.usage['agent_calls']=e.config.budget.agent_calls;e.checkpoint('controlled_call_limit')
    elif boundary=='config':e.config.allow_agent_materials=False
    elif boundary=='snapshot':(e.root/'agent-source'/'target.py').write_text('Changed captured bytes')
    elif boundary=='permissions':e.agent.prepare=lambda *args:(False,[])
    elif boundary=='tools':e.agent.probe=lambda runner:dict(available=True,version='changed-tool',checks=[],reason='Changed fixture')
    calls=state.usage['agent_calls']
    if boundary=='snapshot':
        with pytest.raises(ValueError,match='source view content changed'):e.resume()
    else:state=e.resume(agent_turn_timeout=120 if boundary=='total' else None)
    assert len(sessions)==(2 if boundary=='repeat' else 1)
    assert state.usage['agent_calls']==calls+(boundary=='repeat')
    assert any(c.id==old for c in state.checks) and not state.evidence
    if boundary=='repeat':
        assert state.current_submission['phase']=='failed' and state.current_submission['operation_id']!=old
        assert sessions==[None,'fixture-session']
    if boundary=='total':assert state.run_stop['reason']=='resource_limit' and e.budget.remaining()==0


def test_cancel_formal_tool_stops_before_another_agent_call(tmp_path,monkeypatch):
    import subprocess
    from consensus_assurance.core.types import ExecutionStatus
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    run=e.runner.run
    def interrupt(command,cwd,action,*args,**kwargs):
        if action!='direct_check':return run(command,cwd,action,*args,**kwargs)
        communicate=subprocess.Popen.communicate
        interrupted=False
        def cancel(process,*a,**kw):
            nonlocal interrupted
            if not interrupted:
                interrupted=True
                raise KeyboardInterrupt('Caller cancelled during formal execution')
            return communicate(process,*a,**kw)
        with monkeypatch.context() as patch:
            patch.setattr(subprocess.Popen,'communicate',cancel)
            return run(command,cwd,action,*args,**kwargs)
    e.runner.run=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    assert e.state.run_stop['reason']=='user_stop' and e.state.usage['agent_calls']==2
    receipts=[json.loads(p.read_text()) for p in (e.root/'logs').glob('*/check.json')]
    assert any(c['action']=='direct_check' and c['status']==ExecutionStatus.CANCELLED.value for c in receipts)
    assert not e.state.evidence


def test_candidate_parent_conflict_and_paused_return_keep_one_active_question(tmp_path):
    def initial(state):
        sub,files=first(state)
        sub.update(action='continue',obligation=None,bindings=[])
        sub['question'].update(disposition='needs_specific_evidence',unknowns=['Unexamined consumer'])
        return sub,files
    def pause(index):
        def step(state):
            current=state['question_candidates'][index]
            return dict(action='pause',candidate_id=current['id'],question=current['question'],
                resume_conditions=['Inspect the remaining consumer'],rationale='Retain this boundary',feedback=feedback(state)),{}
        return step
    def independent(state):
        sub,files=initial(state);sub['question']['question']='Is a different local caller bounded?'
        sub['feedback']=feedback(state)
        return sub,files
    def resume_parent(state):
        sub,files=initial(state);sub['candidate_id']=state['question_candidates'][0]['id']
        sub['feedback']=feedback(state)
        return sub,files
    def conflicting_child(state):
        sub=products()[0];sub['candidate_id']=sub['parent_candidate_id']=state['question_candidates'][0]['id']
        return sub,{}
    def child(state):
        assert len(state['question_candidates'])==2 and not state['units']
        sub=products()[0];sub['parent_candidate_id']=state['question_candidates'][0]['id']
        sub['feedback']=feedback(state)
        sub['result_implications']={k:'Refine the local return discriminator; unexecuted consumer remains unknown' for k in ('holds','violated','incomplete')}
        return sub,{}
    e,repo=engine_for(tmp_path,[initial,pause(0),independent,resume_parent,pause(1),resume_parent,conflicting_child,child,check_step(),review_step(),stop])
    state=e.start(repo)
    assert len(state.question_candidates)==3 and len(state.units)==1,state.current_submission
    assert state.usage['audit_units']==1 and len(state.direct_checks)==1
    assert state.question_candidates[0].question.unknowns==['Unexamined consumer']
    assert state.question_candidates[2].parent_candidate_id==state.question_candidates[0].id
    assert state.question_candidates[0].status=='paused' and state.units[0].status=='checked'
    assert not any(c.status=='active' for c in state.question_candidates)
    assert len(list((e.root/'submissions').glob('*/diagnostics.json')))==1


def test_accepted_execution_gap_is_not_reclassified_as_submission_rejection(tmp_path,monkeypatch):
    import consensus_assurance.workflow.audit as audit
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    monkeypatch.setattr(audit,'execute_direct_check',lambda *a: (_ for _ in ()).throw(OSError('workspace unavailable')))
    state=e.start(repo)
    assert len(state.direct_checks)==1
    assert not list((e.root/'submissions').glob('*/diagnostics.json'))
    assert any('Accepted operation execution failed' in g for g in state.gaps)


def test_unknown_execution_retries_with_a_new_identity_and_clean_workspace(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step()])
    original=e.checkpoint
    interrupted=[]
    def checkpoint(event):
        original(event)
        if event=='action_started' and e.state.pending_action.kind=='direct_execute' and not interrupted:
            interrupted.append(e.state.pending_action.id)
            (e.workspace()/'unknown-attempt.txt').write_text('Unreliable partial execution')
            raise KeyboardInterrupt('No completed raw receipt')
    e.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.checkpoint=original
    state=e.resume()
    check=next(c for c in state.checks if c.direct_check_id)
    assert check.pending_action_id!=interrupted[0]
    assert not (Path(check.cwd)/'unknown-attempt.txt').exists()
    assert next(a for a in state.action_history if a.id==interrupted[0]).status=='outcome_unknown'
    assert state.usage['experiments']==2 and state.usage['agent_calls']==2
    assert len(state.direct_checks)==1


@pytest.mark.usefixtures('full_refresh_equivalence')
def test_checker_correction_across_intermediate_harness_version(tmp_path):
    def flawed(state):
        sub,files=check_step()(state)
        raw=json.loads(files['plan.json'])
        raw['observable_properties'][0]['assertion']={'field':'state.success','value':True}
        raw['observable_properties'][0]['description']='A completed success requires a qualified result'
        files['plan.json']=json.dumps(raw)
        files['check.py']=files['check.py'].replace("'in_range':0 <= value <= 3", "'in_range':0 <= value <= 3,'success':value == 1")
        return sub,files
    def dispute(state):
        sub,_=review_step('revision_needed')(state)
        sub['review_items'][0].update(rationale='The oracle incorrectly requires success on every legal invocation',
            counterevidence=['The responsibility constrains success; it does not require success'])
        return sub,{}
    def ordinary(state):
        sub,files=flawed(state)
        sub.update(action='revise_check',previous_check_id=state['direct_checks'][-1]['id'])
        files['check.py']+='\n# Preserve all observed fields while repairing diagnostics.\n'
        return sub,files
    def corrected(state):
        sub,files=ordinary(state)
        issue=state['review_issues'][0]
        raw=json.loads(files['plan.json']);prop=raw['observable_properties'][0]
        prop.update(kind='event_implication',antecedent={'field':'state.success','value':True},assertion={'field':'state.in_range','value':True})
        files['plan.json']=json.dumps(raw)
        sub['encoding_revision']=dict(old_direct_check_id=state['direct_checks'][-1]['id'],issue_id=issue['id'],source_ids=['code','doc'],rationale='Translate the necessary condition in its actual direction')
        return sub,files
    def resolve(state):
        sub,_=review_step()(state);issue=state['review_issues'][0]
        sub['resolutions']=[dict(issue_id=issue['id'],source_ids=['code','doc'],rationale='The revised necessary predicate completed a new actual execution without demanding success',residual_issue_ids=[],scope_limitations=['No distributed consequence'])]
        return sub,{}
    e,repo=engine_for(tmp_path,[first,flawed,dispute,ordinary,resolve,corrected,resolve,stop])
    state=e.start(repo)
    assert len(state.direct_checks)==3,(state.stop_reason,state.current_submission)
    assert [a.version for a in state.direct_checks]==[1,2,3]
    assert state.review_issues[0].resolved_by
    assert len([c for c in state.checks if c.direct_check_id])==3
    assert state.monitor_results[0]['outcome']=='violated'
    assert state.monitor_results[-1]['outcome']=='holds'
    assert state.units[0].status=='checked'

    errors=[json.loads(p.read_text()) for p in (e.root/'submissions').glob('*/diagnostics.json')]
    assert len(errors)==1
    assert any(d['details'].get('unchanged_components')==['oracle'] for d in errors[0]['diagnostics'])


def test_isolated_runner_sees_fixed_submitted_helpers(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    e.config.execution_isolation='bwrap'
    original=e.checkpoint
    def mutate_after_acceptance(event):
        original(event)
        if event=='semantic_operation_committed' and e.state.current_submission.get('direct_check_id'):
            (e.root/'draft'/'check.py').write_text("raise RuntimeError('changed draft')")
            (e.root/'draft'/'helper.py').write_text("raise RuntimeError('changed helper')")
    e.checkpoint=mutate_after_acceptance
    state=e.start(repo)
    result=next(c for c in state.checks if c.direct_check_id)
    assert result.exit_code==0 and result.status.value=='completed'
    assert 'CA_EVENT' in Path(result.stdout).read_text()


@pytest.mark.parametrize('violated',[False,True])
def test_driver_repair_executes_reviews_and_continues_without_old_text_blockers(tmp_path,violated):
    from consensus_assurance.workflow.audit import validate_submission
    from audit_support import next_question, local_stop
    conflict='The private entry requires caller validation absent from this driver.'
    retained={}
    def original(state):
        sub,files=check_step()(state)
        plan=json.loads(files['plan.json'])
        plan['harness']['legality']['conflicts']=[conflict]
        files['plan.json']=json.dumps(plan)
        return sub,files
    def challenge(state):
        sub,_=review_step('revision_needed','applicability')(state)
        sub['review_items'][0].update(challenged_components=['driver'],counterevidence=[conflict])
        item=review_step()(state)[0]['review_items'][0]
        sub['review_items'].append(item)
        return sub,{}
    def repair(state):
        sub,files=check_step(revise=True)(state)
        issue=state['review_issues'][0]
        sub['repair_issue_ids']=[issue['id']]
        sub['sources']=[dict(id='entry',file='target.py',start_line=3,end_line=5,kind='code_observation')]
        plan=json.loads(files['plan.json'])
        plan['harness']['legality'].update(source_ids=['entry','code'],conflicts=[],
            applicability='The validating entry checks this legal input before delegating the same bounded operation.',
            derivation='checked_step performs the caller validation that was absent from the private-entry driver.')
        files['check.py']=files['check.py'].replace('from target import step','from target import checked_step as step')
        files['plan.json']=json.dumps(plan)
        return sub,files
    def pending(state):
        index=json.loads((e.root/'research.json').read_text())
        new=next(a for a in index['artifacts'] if a['version']==2)
        assert new['previous_id']==state['direct_checks'][0]['id']
        record=next(r for r in index['assessments'] if r['direct_check_id']==new['id'])
        assert record['bounded_complete'] and not record['reviewed_complete'] and record['correspondence'] is None
        assert record['open_issue_ids'] and any('unreviewed' in b for b in record['blockers'])
        old=json.loads((e.root/new['previous_record']['path']).read_text())
        retained['old']=next(a for a in old['direct_checks'] if a['id']==new['previous_id'])
        retained['bytes']=Path(retained['old']['plan_path']).read_bytes()
        assert conflict in retained['bytes'].decode()
        # A passing process and a new no-issue review cannot silently resolve old counterevidence.
        return review_step()(state)
    def resolve(state):
        assert not state['monitor_results'][-1]['reviewed_complete']
        sub,_=review_step()(state)
        sub['review_items'].append(dict(target_id=sub['artifact_id'],aspect='applicability',status='no_issue_found',
            source_ids=['entry','code','doc'],rationale='The fixed input uses the validator before the actual call; the oracle and input remain unchanged.'))
        issue=state['review_issues'][0]
        sub['resolutions']=[dict(issue_id=issue['id'],source_ids=['entry'],evidence_ids=[next(c['id'] for c in state['checks'] if c['direct_check_id']==sub['artifact_id'])],
            rationale='The executed validating entry removes the identified missing caller step only for v2.',
            condition_dispositions=[dict(condition_id=issue['conditions'][0]['id'],applies_to='old_judgment',
                source_ids=['entry'],rationale='The missing validation applies to the saved private-entry driver, not the executed validating entry.')],
            residual_issue_ids=[],scope_limitations=['Other inputs remain unchecked'])]
        sub['feedback']=feedback(state,question_updates={state['question_candidates'][0]['id']:dict(unknowns=[],resume_conditions=[])})
        return sub,{}
    def next_investigation(state):
        assert state['units'][0]['status']=='checked' and not state['question_candidates'][0]['question']['unknowns']
        return next_question(state)
    steps=[first,original,challenge,repair,pending,resolve,local_stop(),next_investigation,stop]
    e,repo=engine_for(tmp_path,steps)
    e.agent.mock=False;e.config.execution_isolation='bwrap'
    e.config.budget.semantic_reviews=5
    source=(repo/'target.py').read_text()
    if violated:source=source.replace('value < limit','value <= limit')
    (repo/'target.py').write_text(source+'def checked_step(value, limit):\n    if not 0 <= value <= limit or limit <= 0: raise ValueError("invalid input")\n    return step(value, limit)\n')
    invoke=e.agent.investigate
    def inspect(runner,prompt,directory,snapshot_id,timeout,session_id=None):
        check,session,receipt=invoke(runner,prompt,directory,snapshot_id,timeout,session_id)
        raw=json.loads((directory/'submission.json').read_text())
        if raw['action']=='revise_check':
            plan=json.loads((directory/'plan.json').read_text())
            for fault in ('issue','source','oracle','identity','prerequisite'):
                bad=json.loads(json.dumps(raw));modified=json.loads(json.dumps(plan))
                if fault=='issue':bad['repair_issue_ids']=[]
                if fault=='source':modified['harness']['legality']['source_ids']=[]
                if fault=='oracle':modified['observable_properties'][0]['assertion']['value']=False
                if fault=='identity':modified['observable_properties'][0]['identity_fields']=['participant']
                if fault=='prerequisite':modified['harness']['prerequisites'][0]['conditions'][0]['value']=False
                (directory/'submission.json').write_text(json.dumps(bad));(directory/'plan.json').write_text(json.dumps(modified))
                assert not validate_submission(e.state,e.root,'submission.json',e.implementation)['valid'],fault
            (directory/'submission.json').write_text(json.dumps(raw));(directory/'plan.json').write_text(json.dumps(plan))
        before=e.state.model_dump()
        result=validate_submission(e.state,e.root,'submission.json',e.implementation)
        assert result['valid'],result
        assert e.state.model_dump()==before
        return check,session,receipt
    e.agent.investigate=inspect
    checkpoint=e.checkpoint
    def interrupt(event):
        checkpoint(event)
        if event=='audit_execution_completed' and len(e.state.direct_checks)==2 and e.agent.cursor==4:
            raise KeyboardInterrupt('New driver executed, correspondence still pending')
    e.checkpoint=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.checkpoint=checkpoint
    state=e.resume()
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.current_submission
    assert len(state.direct_checks)==2 and state.usage['experiments']==2 and len(state.question_candidates)==2
    old,new=state.monitor_results
    assert old['bounded_complete'] and not old['reviewed_complete'] and old['open_issue_ids']
    assert new['bounded_complete'] and new['reviewed_complete'] and not new['open_issue_ids']
    assert new['confirmed']==violated and new['outcome']==('violated' if violated else 'holds')
    assert Path(retained['old']['plan_path']).read_bytes()==retained['bytes']
    index=json.loads((e.root/'research.json').read_text())
    assert index['conclusions'][0]['disposition']==('confirmed_in_scope' if violated else 'bounded_no_violation')
    assert not index['review_issues'] and index['artifacts'][-1]['version']==2
    assert (repo/'target.py').read_text().startswith(source)


def test_additional_source_can_answer_a_driver_dispute_without_reexecution(tmp_path):
    def challenge(state):
        sub,_=review_step('revision_needed','applicability')(state)
        sub['review_items'][0].update(challenged_components=['driver'],counterevidence=['The private entry might require a different caller permission.'])
        sub['review_items']+=review_step()(state)[0]['review_items']
        return sub,{}
    def resolve(state,additional=False):
        sub,_=review_step()(state)
        sources=['code','doc']+(['permission'] if additional else [])
        if additional:sub['sources']=[dict(id='permission',file='README.md',start_line=2,end_line=2,kind='interface_statement')]
        sub['review_items'].append(dict(aspect='applicability',status='no_issue_found',source_ids=sources,
            rationale='The permission explicitly covers this already-executed direct call on known legal input.'))
        sub['resolutions']=[dict(issue_id=state['review_issues'][0]['id'],source_ids=sources,
            rationale='The missing interface statement answers the caller question; fixed inputs need no change.',
            residual_issue_ids=[],scope_limitations=[])]
        if additional:sub['repair_of']=state['selections'][-1]['operation_id']
        return sub,{}
    e,repo=engine_for(tmp_path,[first,check_step(),challenge,resolve,lambda state:resolve(state,True),stop])
    with (repo/'README.md').open('a') as stream:stream.write('A caller with known legal input may invoke step directly without another validation entry.\n')
    state=e.start(repo)
    assert len(state.direct_checks)==state.usage['experiments']==1
    assert len(list((e.root/'submissions').glob('*/diagnostics.json')))==1
    assert state.units[0].status=='checked' and state.monitor_results[0]['reviewed_complete']
    assert state.review_issues[0].resolved_by and not state.revisions


def test_deadline_preserves_accepted_unexecuted_check_across_resume(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    original=e.checkpoint
    def checkpoint(event):
        if event=='semantic_operation_committed' and e.state.current_submission.get('direct_check_id'):
            # Simulate expiry between durable acceptance and formal execution.
            e.budget.previous=e.config.budget.total_seconds
        original(event)
    e.checkpoint=checkpoint
    state=e.start(repo)
    assert state.current_submission['phase']=='accepted' and len(state.direct_checks)==1
    assert not any(c.action=='direct_check' for c in state.checks)
    assert state.run_stop['reason']=='resource_limit' and state.usage.get('experiments',0)==0
    e.checkpoint=original
    recovered=e.resume()
    assert recovered.current_submission['phase']=='accepted'
    assert recovered.usage.get('experiments',0)==0 and recovered.usage['agent_calls']==2


def test_resolution_reports_independent_reference_errors_together(tmp_path):
    def dispute(state):
        return review_step('disputed')(state)
    def invalid(state):
        sub,_=review_step()(state)
        sub['resolutions']=[dict(issue_id=state['review_issues'][0]['id'],source_ids=['not-a-material'],
            evidence_ids=['not-an-execution'],rationale='Unresolved source claim',residual_issue_ids=[],scope_limitations=[])]
        return sub,{}
    e,repo=engine_for(tmp_path,[first,check_step(),dispute,invalid,stop]);state=e.start(repo)
    diagnostics=[json.loads(p.read_text()) for p in (e.root/'submissions').glob('*/diagnostics.json')]
    assert len(diagnostics)==1
    details=[d['details'] for d in diagnostics[0]['diagnostics']]
    assert any(d.get('unknown_material_ids')==['not-a-material'] for d in details)
    assert any(d.get('unknown_evidence_ids')==['not-an-execution'] for d in details)
    assert not state.review_issues[0].resolved_by


def test_feedback_only_retains_exploration_before_a_map_and_recovers_once(tmp_path):
    from consensus_assurance.workflow.audit import accept, Inputs, AuditSubmission
    from consensus_assurance.workflow.transactions import commit_graph
    def explore(state):
        return dict(action='explore',question='Under an explicit caller policy, compare interior and boundary returns before attributing a requirement',
            harness_path='explore.py',rationale='Use a real local call'),{
            'explore.py':"from target import step\nprint('observed', step(2,3), step(3,3))\n"}
    def retain(state):
        check=next(c for c in state['checks'] if c['action']=='exploration')
        return dict(action='research',rationale='Retain the construction observation',feedback=dict(
            ref_ids=[check['id']],answered='The selected input policy produced distinct returns 3 and 0.',remaining=['The caller policy responsibility is not yet established'],
            understanding='updated',rationale='No normative claim or map change is implied.')),{}
    def new_source(state):
        current=json.loads((e.root/'research.json').read_text())
        a,b=state['selections'][-2:]
        assert b['duplicate_of']==a['operation_id']==current['latest_decision']['duplicate_of']
        assert [h['operation_id'] for h in current['handoffs'] if h.get('feedback')]==[a['operation_id']]
        assert all((e.root/'submissions'/r['operation_id']/'accepted.json').is_file() for r in (a,b))
        raw,files=retain(state)
        raw['sources']=[dict(id='code',file='target.py',start_line=1,end_line=2,kind='code_observation')]
        raw['feedback']['ref_ids'].append('code')
        return raw,files
    def next_turn(state):
        current=json.loads((e.root/'research.json').read_text())
        assert current['handoffs'][-1]['feedback']['answered'].endswith('3 and 0.')
        assert not any(state[k] for k in ('question_candidates','units','evidence','findings'))
        assert state['audit_spec_version']==0
        from consensus_assurance.workflow.audit import validate_submission
        raw=retain(state)[0]
        raw['feedback']['ref_ids']=[current['handoffs'][-1]['operation_id']]
        (e.root/'draft'/'indirect.json').write_text(json.dumps(raw))
        assert validate_submission(e.state,e.root,'indirect.json',e.implementation)['valid']
        return first(state)
    steps=[explore,retain,lambda s:(json.dumps(retain(s)[0],indent=4),{}),new_source,next_turn,check_step(),review_step(),retain,stop]
    e,repo=engine_for(tmp_path,steps)
    e.agent.mock=False;e.config.execution_isolation='bwrap'
    old=e.graph_commit_hook
    def interrupt(key):
        if e.state.usage.get('agent_calls')==2:raise KeyboardInterrupt('Retained transaction before adoption')
    e.graph_commit_hook=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.graph_commit_hook=old
    state=e.resume()
    assert state.usage['experiments']==2
    exploratory=next(c for c in state.checks if c.action=='exploration')
    assert 'observed 3 0' in Path(exploratory.stdout).read_text()
    assert all(e.check_id!=exploratory.id for e in state.evidence)
    assert state.monitor_results[-1]['outcome']=='holds' and not state.findings
    handoffs=[s for s in state.selections if s['action']=='research']
    assert len(handoffs)==4 and sum(bool(s.get('duplicate_of')) for s in handoffs)==1
    assert 'duplicate_of' not in handoffs[-1] and state.usage['agent_calls']==len(steps)==len(state.agent_turns)
    from consensus_assurance.reporting.chinese import render_report
    assert '纯反馈重复受理 1 次，无新增认识' in render_report(state,e.root).read_text()
    counts=(dict(state.usage),len(state.selections))
    e.resume()
    assert (dict(state.usage),len(state.selections))==counts
    good=retain(state.model_dump(mode='json'))[0]
    for index,change in enumerate(({'answered':'   '},{'ref_ids':['unknown']},
            {'question_updates':{'missing':{'unknowns':[],'resume_conditions':[]}}})):
        raw=json.loads(json.dumps(good));raw['feedback'].update(change)
        before=state.model_dump(mode='json')
        with pytest.raises(ValueError):
            sub=AuditSubmission.model_validate(raw)
            commit_graph(e,'bad-feedback-'+str(index),raw,
                lambda proxy:accept(proxy,sub,Inputs(e.root/'draft'),'bad'))
        assert state.model_dump(mode='json')==before
    with pytest.raises(ValueError):AuditSubmission.model_validate({'action':'research','rationale':'Empty'})


def test_preflight_checks_current_inputs_without_writes_or_execution(tmp_path,monkeypatch):
    import copy
    from consensus_assurance.workflow.audit import validate_submission, prepare_agent_source, accept, Inputs, AuditSubmission
    from consensus_assurance.workflow.transactions import commit_graph
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True);prepare_agent_source(e)
    draft=e.root/'draft';draft.mkdir()
    candidate,files=first({});_,plan,harness=products()
    sub=dict(action='check',candidate=candidate,plan_path='plan.json',harness_path='check.py',rationale='A combined product')
    files.update({'plan.json':json.dumps(plan),'check.py':harness})
    for name,text in files.items():(draft/name).write_text(text)
    def validate(raw):
        (draft/'input.json').write_text(json.dumps(raw))
        before={str(p): (p.read_bytes(),p.stat().st_mtime_ns) for p in e.root.rglob('*') if p.is_file()}
        state=e.state.model_dump(mode='json')
        result=validate_submission(e.state,e.root,'input.json',e.implementation)
        assert e.state.model_dump(mode='json')==state
        assert before=={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in e.root.rglob('*') if p.is_file()}
        return result
    monkeypatch.setattr(e.runner,'run',lambda *a,**kw:pytest.fail('Preflight cannot run a process'))
    broken=copy.deepcopy(sub)
    broken['candidate']['sources'][0]['end_line']=999
    broken['candidate']['question']['behavior_ids']=['missing-behavior']
    rejected=validate(broken)
    assert not rejected['valid']
    assert any(d['category']=='material' and 'code' in d['object_ids'] for d in rejected['diagnostics'])
    assert any(d['category']=='semantic' for d in rejected['diagnostics'])
    with pytest.raises(ValueError) as formal:
        commit_graph(e,'bad-combined',broken,lambda proxy:accept(proxy,AuditSubmission.model_validate(broken),
            Inputs(draft),'bad-combined'))
    assert {d['code'] for d in rejected['diagnostics']}=={d.code for d in formal.value.diagnostics}
    assert validate(sub)['valid']
    assert not e.state.units and not e.state.direct_checks
    for fields in ({'derivation':''},{'applicability':''},{'source_ids':[],'expectation_ids':[]}):
        missing=copy.deepcopy(plan)
        missing['harness']['legality'].update(fields)
        (draft/'plan.json').write_text(json.dumps(missing))
        assert not validate(sub)['valid']
    (draft/'plan.json').write_text(json.dumps(plan))
    # Later byte and capacity changes must be checked again by the formal path.
    (draft/'check.py').write_text('changed harness bytes\n')
    e.state.usage['experiments']=e.config.budget.experiments
    assert not validate(sub)['valid']
    with pytest.raises(ValueError,match='experiments'):
        commit_graph(e,'capacity-change',sub,lambda proxy:accept(proxy,AuditSubmission.model_validate(sub),
            Inputs(draft),'capacity-change'))
    e.state.usage.pop('experiments')
    assert validate(sub)['valid']
    commit_graph(e,'fresh-bytes',sub,lambda proxy:accept(proxy,AuditSubmission.model_validate(sub),
        Inputs(draft),'fresh-bytes'))
    assert Path(e.state.direct_checks[0].harness_path).read_text()=='changed harness bytes\n'
    assert not e.state.checks and not e.state.evidence
    # A proposal based on v1 cannot overwrite a later map.
    update=dict(action='research',map_path='map.json',rationale='Check current map identity')
    old_map=json.loads((draft/'map.json').read_text());old_map['version']=0
    (draft/'map.json').write_text(json.dumps(old_map))
    assert not validate(update)['valid']
    for bad in ('../state.json',str(e.root/'state.json')):
        assert not validate_submission(e.state,e.root,bad,e.implementation)['valid']
    (draft/'escape.json').symlink_to(e.root/'state.json')
    assert not validate_submission(e.state,e.root,'escape.json',e.implementation)['valid']




def test_zero_review_budget_keeps_measured_violation_unconfirmed(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),stop])
    e.config.budget.semantic_reviews=0;e.agent.mock=False;e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1\n')
    state=e.start(repo)
    assert state.usage['experiments']==1 and state.usage.get('semantic_reviews',0)==0
    assert state.monitor_results[-1]['outcome']=='violated' and not state.monitor_results[-1]['confirmed']
    assert not state.semantic_reviews
    assert state.units[0].remaining_obligation_ids and state.usage['agent_calls']==4
    from consensus_assurance.reporting.chinese import render_report
    text=render_report(state,e.root).read_text()
    assert '**已确认违反**' not in text and '机械比较：观察到违反' in text and '对应性意见：尚未记录' in text


@pytest.mark.parametrize('selection',['diagnostic_control','formal_control','outside_only'])
def test_go_control_applicability_preserves_independent_witness(tmp_path,go_module,selection):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.core.config import TargetConfig
    from consensus_assurance.core.proposals import Comparison
    from consensus_assurance.workflow.direct_checks import load_plan,validate_plan
    if not shutil.which('go') or not shutil.which('bwrap'):pytest.skip('Local Go and bubblewrap required')
    def initial(state):
        sub,files=first(state);sub['sources'][0].update(file='value.go',end_line=4)
        sub['bindings'][0].update(symbol='Step',start_line=2,end_line=4)
        return sub,files
    def check(state):
        sub,files=check_step()(state);plan=json.loads(files['plan.json']);plan['harness']['kind']='go_test'
        if selection!='formal_control':plan['monitors'][0]['applicability_conditions']=[{'field':'scenario','value':'principal'}]
        principal='' if selection=='outside_only' else 'emit("admitted","principal",true); emit("returned","principal",Step(3,3)<=3);'
        text='''package service
import ("testing";"fmt")
func emit(event,scenario string,ok bool) {fmt.Printf("CA_EVENT {\\"event\\":\\"%s\\",\\"scenario\\":\\"%s\\",\\"operation\\":\\"%s\\",\\"state\\":{\\"legal\\":true,\\"in_range\\":%t}}\\n",event,scenario,scenario,ok)}
func TestAssurancePolicies(t *testing.T) { PRINCIPAL emit("returned","control",Step(2,3)<=3) }
'''.replace('PRINCIPAL',principal)
        sub.update(harness_path='check.go',files={})
        return sub,{'plan.json':json.dumps(plan),'check.go':text}
    e,repo=engine_for(tmp_path,[initial,check,review_step(),stop]);shutil.copytree(go_module,repo,dirs_exist_ok=True)
    e.config.execution_backend='go_module';e.config.execution_isolation='bwrap';e.config.target=TargetConfig()
    e.implementation=GoModuleBackend(e.config.target);e.agent.mock=False
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    result=state.monitor_results[0];prop=result['properties'][0]
    assert result['confirmed']==(selection!='outside_only')
    assert result['outcome']==('unknown' if selection=='outside_only' else 'violated')
    assert result['bounded_complete']==(selection=='diagnostic_control')
    assert bool(prop['missing_indices'])==(selection=='formal_control')
    assert bool(prop['outside_applicability_indices'])==(selection!='formal_control')
    if selection=='outside_only':assert not prop['evaluated_indices']
    artifact=state.direct_checks[0];plan=load_plan(artifact.plan_path)
    plan.monitors[0].applicability_conditions=[Comparison(field='state.in_range',value=False)]
    with pytest.raises(ValueError,match='cannot filter on the result field'):validate_plan(state,state.units[0],plan,e.implementation)


def test_one_investigation_fixes_packages_for_checks_exploration_and_revision(tmp_path,go_module):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.config import TargetConfig
    from consensus_assurance.workflow.direct_checks import load_plan, execute
    from consensus_assurance.workflow.encoding import direct_changes
    if not shutil.which('go') or not shutil.which('bwrap'):pytest.skip('Local Go and bubblewrap required')
    def initial(state):
        sub,files=first(state)
        sub['sources'][0]['file']='internal/core/value.go'
        sub['sources'][0]['end_line']=4
        sub['bindings'][0].update(symbol='Step',start_line=2,end_line=4)
        return sub,files
    def source(package,value=3):
        return f'''package {package}
import "testing"
func TestAssuranceBound(t *testing.T) {{
 emit("admitted", true)
 value := Step({value},3)
 emit("returned", value >= 0 && value <= 3)
}}
'''
    def helpers(directory,package):
        return {f'{directory}/observe_test.go'.removeprefix('./'):f'''package {package}
import "fmt"
func emit(event string, value bool) {{ fmt.Printf("CA_EVENT {{\\"event\\":\\"%s\\",\\"operation\\":\\"one\\",\\"state\\":{{\\"legal\\":true,\\"in_range\\":%t}}}}\\n",event,value) }}
'''}
    def check(package,revise=False,value=3):
        def step(state):
            sub,files=check_step(revise=revise)(state)
            plan=json.loads(files['plan.json'])
            plan['harness']['kind']='go_test'
            if package is not None:plan['harness']['execution_package']=package
            name=('engine_test' if revise else 'engine') if package else 'service'
            # Both root and core use the same actual bound implementation.
            body=source(name,value)
            if package is None or revise:
                body=body.replace('import "testing"','import ("testing"; core "example.org/local/internal/core")').replace('value := Step','value := core.Step')
            if revise:body+='// Keep the actual call and oracle unchanged.\n'
            helper,content=next(iter(helpers(package or '.',name).items()))
            sub.update(harness_path='primary.go',files={helper:'helper.go'})
            return sub,{'plan.json':json.dumps(plan),'primary.go':body,'helper.go':content}
        return step
    def explore(state):
        return dict(action='explore',question='Observe the storage package under one legal input',
            execution_package='internal/store',harness_path='storage.go',rationale='Independent conditional observation'),{
            'storage.go':'package storage\nimport("testing";"fmt")\nfunc TestAssuranceStore(t *testing.T) { fmt.Println(Step(1,3)); t.Error("fixture failure after observation") }\n'}
    steps=[initial,check(None,value=2),review_step(),check('internal/core'),review_step(),explore,check('./internal/core',revise=True),review_step()]
    e,repo=engine_for(tmp_path,steps)
    shutil.copytree(go_module,repo,dirs_exist_ok=True)
    e.config.execution_backend='go_module';e.config.execution_isolation='bwrap'
    e.config.target=TargetConfig(harness_path='custom_generated_test.go')
    e.config.budget.total_seconds=360;e.config.budget.action_timeout=120
    e.implementation=GoModuleBackend(e.config.target,120)
    before=capture(repo).files
    # Every product preflight reads fixed source; it must not run a build or consume a budget.
    invoke=e.agent.investigate
    def investigate(*args,**kwargs):
        result=invoke(*args,**kwargs)
        from consensus_assurance.workflow.audit import validate_submission
        saved=e.state.model_dump(mode='json')
        validation=validate_submission(e.state,e.root,'submission.json',e.implementation)
        assert validation['valid'],validation
        assert e.state.model_dump(mode='json')==saved
        return result
    e.agent.investigate=investigate
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    assert state.usage['experiments']==4 and len(state.direct_checks)==3
    root,old,new=state.direct_checks
    assert new.previous_id==old.id and new.version==2
    assert e.implementation.package=='.' and e.config.target.execution_package=='.'
    for artifact,package in [(root,'.'),(old,'./internal/core'),(new,'./internal/core')]:
        plan=load_plan(artifact.plan_path)
        assert plan.harness.execution_package==package
        check=next(c for c in state.checks if c.direct_check_id==artifact.id)
        assert check.exit_code==0 and check.parameters['test_started']
        assert check.command[-1]==package==check.parameters['execution_package']
        filename=str(Path(package)/'custom_generated_test.go')
        assert check.parameters['harness_filename']==filename
        assert Path(artifact.harness_path).relative_to(Path(artifact.plan_path).parent).as_posix()==filename
        assert (Path(check.cwd)/filename).read_text()==plan.harness.source
        assert all((Path(check.cwd)/name).read_text()==text for name,text in plan.harness.files.items())
        assert 'os/exec' not in plan.harness.source
    assert [r['outcome'] for r in state.monitor_results]==['holds','violated','violated']
    assert all(r['reviewed_complete'] for r in state.monitor_results)
    conditional=next(c for c in state.checks if c.action=='exploration')
    assert conditional.exit_code!=0 and conditional.parameters['test_started'] and '2' in Path(conditional.stdout).read_text()
    assert conditional.command[-1]=='./internal/store' and conditional.parameters['harness_filename']=='internal/store/custom_generated_test.go'
    assert conditional.tool_version==state.tools['implementation'] and conditional.direct_check_id is None
    from consensus_assurance.workflow.research import costs,execution_cost
    for check in [c for c in state.checks if c.action in {'direct_check','exploration'}]:
        timing=execution_cost(check)
        assert timing['action_seconds']>=timing['process_seconds']>=0
        assert check.parameters['action_started_at']<=check.started_at<check.ended_at
        assert json.loads((e.root/'logs'/check.id/'check.json').read_text())['parameters']['action_seconds']==timing['action_seconds']
    plan=load_plan(new.plan_path)
    moved=plan.model_copy(deep=True);moved.harness.execution_package='.'
    assert direct_changes(plan,moved)==dict(inputs=True,oracle=False,observation=False,contract=False,legality=False)
    moved.harness.prerequisites[0].event='different_prefix'
    assert direct_changes(plan,moved)['contract']
    from consensus_assurance.core.submissions import CheckSubmission
    from consensus_assurance.workflow.audit import validate_check_revision
    revision=CheckSubmission(action='revise_check',unit_id=new.unit_id,previous_check_id=new.id,
        plan_path='plan.json',harness_path='primary.go',rationale='Placement-only repair')
    with pytest.raises(ValueError,match='Ordinary repair'):validate_check_revision(state,new,moved,revision)
    moved=plan.model_copy(deep=True);moved.monitors[0].event='different_endpoint'
    with pytest.raises(ValueError,match='Ordinary repair'):validate_check_revision(state,new,moved,revision)
    assert capture(repo).files==before
    from consensus_assurance.reporting.chinese import render_report
    report=render_report(state,e.root).read_text()
    assert 'run 默认包 `.`' in report
    assert all(f'固定执行包 `{package}`' in report for package in ('.','./internal/core','./internal/store'))
    # An exact operation receipt survives mutable defaults/drafts and does not become another package's result.
    e.config.target.execution_package='./internal/store';e.implementation=GoModuleBackend(e.config.target.model_copy(update={'harness_path':None}),120)
    (e.root/'draft/primary.go').write_text('not Go')
    previous=next(c for c in state.checks if c.direct_check_id==new.id)
    original_cost=execution_cost(previous);original_times=(previous.started_at,previous.ended_at)
    original_output=Path(previous.stdout).read_bytes();original_totals=costs(state)
    state.pending_action=next(a for a in state.action_history if a.kind=='direct_execute' and a.logical_input.get('direct_check_id')==new.id)
    repeated=execute(e,new)
    assert repeated.id==previous.id and repeated.command[-1]=='./internal/core'
    # Recover an interrupted action with a durable tool receipt but no packed action result.
    (e.root/'actions'/state.pending_action.id/'result.json').unlink()
    recovered=execute(e,new)
    assert recovered.id==previous.id and recovered.command==previous.command
    assert recovered.parameters['harness_filename']=='internal/core/custom_generated_test.go'
    assert execution_cost(recovered)==original_cost and (recovered.started_at,recovered.ended_at)==original_times
    assert Path(previous.stdout).read_bytes()==original_output and state.usage['experiments']==4
    assert costs(state)['target_action_cost']==original_totals['target_action_cost']
    assert costs(state)['formal_execution_seconds']==original_totals['formal_execution_seconds']
    legacy=previous.model_copy(deep=True);legacy.id='legacy-go'
    for key in ('action_seconds','action_started_at'):legacy.parameters.pop(key)
    mixed=state.model_copy(update={'checks':[*state.checks,recovered,legacy]})
    assert costs(mixed)['target_action_cost']=={**original_totals['target_action_cost'],'unrecorded_check_ids':['legacy-go']}
    receipt=e.root/'logs'/previous.id/'check.json';raw=json.loads(receipt.read_text())
    for key in ('action_seconds','action_started_at'):raw['parameters'].pop(key)
    receipt.write_text(json.dumps(raw))
    (e.root/'actions'/state.pending_action.id/'result.json').unlink()
    raw_recovery=execute(e,new)
    assert raw_recovery.id==previous.id and execution_cost(raw_recovery)['action_seconds'] is None
    assert (raw_recovery.started_at,raw_recovery.ended_at)==original_times and Path(raw_recovery.stdout).read_bytes()==original_output
    assert state.usage['experiments']==4


@pytest.mark.parametrize('delivery',['accepted','deadline','blocked'])
def test_small_exploration_answer_is_independent_of_unfinished_large_product(tmp_path,delivery):
    from consensus_assurance.core.types import ExecutionStatus
    from consensus_assurance.workflow.audit import validate_submission
    from consensus_assurance.workflow.research import exploration_results
    def explore(state):
        return dict(action='explore',question='What does the second legal call return?',harness_path='probe.py',
            rationale='Keep an observation separate from a formal claim'),{'probe.py':'from target import step\nprint(step(2,3))\n'}
    def small(state):
        large,files=first(state)
        large['sources'][0]['end_line']=999
        files['unfinished.json']=json.dumps(large)
        check=next(c for c in state['checks'] if c['action']=='exploration')
        return dict(action='research',rationale='Retain only the understood conditional observation',
            feedback=dict(ref_ids=[check['id'],'code'],answered='The legal interior call returned 3; this observation creates no new obligation.',
                remaining=['Acquire the independent caller contract before formalizing another question'],
                understanding='unchanged',rationale='The larger draft still has an invalid citation')),files
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),explore,small,stop])
    e.agent.mock=False;e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1\n')
    old={};invoke=e.agent.investigate
    def investigate(*args,**kwargs):
        result=invoke(*args,**kwargs)
        if e.agent.cursor!=5:return result
        old.update({k:json.loads(json.dumps(e.state.model_dump(mode='json')[k])) for k in
            ('units','evidence','monitor_results','audit_spec_version','graph_version','question_candidates')})
        diagnostics=validate_submission(e.state,e.root,'unfinished.json',e.implementation)
        assert not diagnostics['valid'] and diagnostics['diagnostics']
        (e.root/'draft/unfinished-diagnostics.json').write_text(json.dumps(diagnostics))
        if delivery!='accepted':
            check,session,_=result
            check.status=ExecutionStatus.TIMEOUT if delivery=='deadline' else ExecutionStatus.ERROR
            check.reason='No reliable receipt before the deadline' if delivery=='deadline' else 'Service security refusal'
            if delivery=='deadline':e.budget.previous=e.config.budget.total_seconds
            return check,session,None
        return result
    e.agent.investigate=investigate
    checkpoint=e.checkpoint
    def expire(event):
        checkpoint(event)
        if event=='audit_execution_completed' and e.state.current_submission.get('action')=='research':
            e.budget.previous=e.config.budget.total_seconds
    e.checkpoint=expire
    state=e.start(repo)
    assert state.monitor_results[0]['confirmed'] and len(state.units)==1
    for key,value in old.items():assert state.model_dump(mode='json')[key]==value,key
    assert (e.root/'draft/unfinished.json').exists() and (e.root/'draft/unfinished-diagnostics.json').exists()
    entries=exploration_results(state,lambda name:json.loads((e.root/name).read_text()))
    entry,=entries
    assert len(entry['executions'])==1
    if delivery=='accepted':
        assert len(entry['feedback'])==1 and not entry['without_followup']
        accepted=json.loads((e.root/entry['feedback'][0]['submission']).read_text())
        assert accepted['action']=='research' and accepted['feedback']['remaining']
        assert entry['executions'][0]['check_id'] in accepted['feedback']['ref_ids']
    else:
        assert not entry['feedback'] and entry['without_followup']==[entry['executions'][0]['check_id']]
        assert state.current_submission['phase']=='failed'
    assert not any((p/'accepted.json').exists() and 'unfinished.json' in (p/'accepted.json').read_text() for p in (e.root/'submissions').iterdir())
    from consensus_assurance.reporting.chinese import render_report
    report=render_report(state,e.root).read_text()
    unresolved=report.split('## 当前未决事项')[1]
    assert '已选检查／复核暂无待办' in unresolved
    assert ('尚无精确引用该执行的后续受理交接' in unresolved)==(delivery!='accepted')
    if delivery=='accepted':assert '精确引用不表示已解决或已正式化' in report
    # This checks the actual loaded resource, not an unattached instruction file or LLM behavior.
    method=(e.root/'audit-method.md').read_text()
    assert 'tasks/audit.md' in state.method_paths
    assert all(concept in method for concept in ('feedback-only','CheckRun','execution_package'))
