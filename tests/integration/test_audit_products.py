"""Audit products with scripted transport and actual isolated local execution."""
import json
from pathlib import Path
import pytest
from audit_support import products, first, check_step, review_step, stop, engine_for, partial_map, feedback


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


def test_raw_parse_failure_is_retained_and_whole_draft_can_continue(tmp_path):
    e,repo=engine_for(tmp_path,[lambda state:('{"action":',{}),first,stop])
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    rejected=list((e.root/'submissions').glob('*/diagnostics.json'))
    assert len(rejected)==1
    assert (rejected[0].parent/'raw.json').read_bytes()==b'{"action":'


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
    from test_audit_research import instance_products
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


def test_partial_map_then_references_and_persistent_resume(tmp_path):
    def research(state):
        spec=partial_map()
        return dict(action='research',map_path='map.json',sources=products()[0]['sources'],rationale='Save only the relevant fact'),{'map.json':json.dumps(spec)}
    def with_refs(state):
        value=products()[0]
        value['question'].update(activity_classes=['A1'],behavior_ids=['call'],fact_ids=['result'],obligation_relation_kind='establishment')
        return value,{}
    def missing_fact(state):
        value,files=with_refs(state);value['question']['fact_ids']=['missing']
        return value,files
    def refine(state):
        value,files=research(state)
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces']=[dict(entry_point='Unexamined consumer',disposition='deferred',reason='Consumer has not been examined',source_ids=['code'])]
        files['map.json']=json.dumps(spec)
        return value,files
    e,repo=engine_for(tmp_path,[research,missing_fact,with_refs,check_step(),refine,stop])
    state=e.start(repo)
    assert state.audit_spec_version==2 and len(state.units)==1,state.current_submission
    assert Path(state.audit_spec_path).is_file()
    assert state.units[0].audit_question.fact_ids==['result']
    assert len(state.direct_checks)==1
    assert json.loads((e.root/'audit-spec'/'v1.json').read_text())['behaviors'][0]['execution_owner']=='caller'
    assert e.resume().audit_spec_version==2
    assert len(list((e.root/'submissions').glob('*/diagnostics.json')))==1


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


def test_unreached_prerequisite_repairs_without_checker_issue(tmp_path):
    def unreached(state):
        sub,files=check_step()(state)
        files['helper.py']='def legal(value, limit):\n    return False\n'
        return sub,files
    e,repo=engine_for(tmp_path,[first,unreached,check_step(revise=True),review_step(),stop])
    state=e.start(repo)
    assert len(state.direct_checks)==2 and not state.review_issues
    assert state.monitor_results[0]['prerequisites']['status']=='not_reached'
    assert state.monitor_results[-1]['prerequisites']['status']=='matched'
    assert state.units[0].status=='checked'


@pytest.mark.parametrize('violated',[False,True])
def test_driver_repair_executes_reviews_and_continues_without_old_text_blockers(tmp_path,violated):
    from consensus_assurance.workflow.audit import validate_submission
    from consensus_assurance.reporting.chinese import render_report
    from test_audit_research import next_question, local_stop
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
        assert new['previous_id']==state['direct_checks'][1]['id']
        record=next(r for r in index['assessments'] if r['direct_check_id']==new['id'])
        assert index['assessments'][0]['reviewed_complete']
        assert record['bounded_complete'] and not record['reviewed_complete'] and record['correspondence'] is None
        assert record['open_issue_ids'] and any('unreviewed' in b for b in record['blockers'])
        old=json.loads((e.root/new['previous_record']['path']).read_text())
        retained['old']=next(a for a in old['direct_checks'] if a['id']==new['previous_id'])
        retained['bytes']=Path(retained['old']['plan_path']).read_bytes()
        assert conflict in retained['bytes'].decode()
        report=render_report(e.state,e.root).read_text()
        assert '对应性意见：尚未记录' in report and '对应性意见：no_issue_found' in report and conflict in report
        assert json.loads((e.root/'research.json').read_text())['assessments']==index['assessments']
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
    steps=[first,check_step(),review_step(),original,challenge,repair,pending,resolve,local_stop(),next_investigation,stop]
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
        if event=='audit_execution_completed' and len(e.state.direct_checks)==3 and e.agent.cursor==6:
            raise KeyboardInterrupt('New driver executed, correspondence still pending')
    e.checkpoint=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.checkpoint=checkpoint
    state=e.resume()
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.current_submission
    assert len(state.direct_checks)==3 and state.usage['experiments']==3 and len(state.question_candidates)==2
    independent,old,new=state.monitor_results
    assert independent['reviewed_complete']
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
    e,repo=engine_for(tmp_path,[explore,retain,next_turn,check_step(),review_step(),stop])
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
    assert len([s for s in state.selections if s['action']=='research'])==1
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


def test_whole_artifact_review_inherits_only_omitted_identity(tmp_path):
    from consensus_assurance.workflow.audit import validate_submission
    from consensus_assurance.core.submissions import AuditSubmission
    from consensus_assurance.core.types import SemanticCheck
    def review(state):
        raw,files=review_step()(state)
        raw['review_items'][0].pop('target_id')
        draft=e.root/'draft'/'review.json'
        draft.write_text(json.dumps(raw))
        assert validate_submission(e.state,e.root,draft.name,e.implementation)['valid']
        with pytest.raises(ValueError):AuditSubmission.model_validate({**raw,'review_items':raw['review_items']*31})
        for fields,expected in (({'target_id':'bounded'},'review_unknown_target'),
                ({'counterevidence':['This oracle remains disputed']},'review_contradictory_judgment'),
                ({'status':'revision_needed','counterevidence':['Wrong oracle'],'challenged_components':[]},'review_missing_component'),
                ({'source_ids':['unacquired']},'review_unknown_source')):
            broken=json.loads(json.dumps(raw));broken['review_items'][0].update(fields)
            draft.write_text(json.dumps(broken))
            diagnostics=validate_submission(e.state,e.root,draft.name,e.implementation)['diagnostics']
            assert expected in {d['code'] for d in diagnostics}
            if expected=='review_unknown_target':
                item=next(d for d in diagnostics if d['code']==expected)
                assert item['details']['allowed_targets'][0]['target_id']==raw['artifact_id']
                assert item['paths']==['/review_items/0']
        return raw,files
    e,repo=engine_for(tmp_path,[first,check_step(),review,stop]);state=e.start(repo)
    assert state.semantic_reviews[0].items[0].target_id==state.direct_checks[0].id
    assert 'target_id' not in AuditSubmission.model_json_schema()['$defs']['ArtifactReviewItem']['required']
    with pytest.raises(ValueError):SemanticCheck.model_validate({'aspect':'applicability','status':'no_issue_found',
        'source_ids':['code'],'rationale':'A normal persisted semantic item requires its target'})


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
