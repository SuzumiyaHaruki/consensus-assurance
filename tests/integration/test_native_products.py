"""Native products with scripted transport and actual isolated local execution."""
import json
from pathlib import Path
import pytest
from native_support import ScriptedAgent, products, first, check_step, review_step, stop, engine_for


def test_existing_unit_actual_compile_repair_review_progress(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(True),check_step(revise=True),review_step(),stop])
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    assert len(state.direct_checks)==2, state.native_current
    old,new=state.direct_checks
    assert new.previous_id==old.id and new.version==2
    executions=[c for c in state.checks if c.direct_check_id]
    assert len(executions)==2
    assert executions[0].exit_code!=0 and 'SyntaxError' in Path(executions[0].stderr).read_text()
    assert executions[1].exit_code==0
    assert state.units[0].status=='checked', state.units[0]
    assert not state.units[0].remaining_obligation_ids
    assert not state.review_issues
    assert (repo/'target.py').read_text().endswith('else 0\n')
    assert not (repo/'helper.py').exists()
    index=json.loads((e.root/'research.json').read_text())
    assert index['units'] and index['claims'] and index['bindings']
    assert index['implementation']['harness_kind']=='python'


def test_raw_parse_failure_is_retained_and_whole_draft_can_continue(tmp_path):
    e,repo=engine_for(tmp_path,[lambda state:('{"action":',{}),first,stop])
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    rejected=list((e.root/'native-submissions').glob('*/diagnostics.json'))
    assert len(rejected)==1
    assert (rejected[0].parent/'raw.json').read_bytes()==b'{"action":'


@pytest.mark.parametrize('interrupt',[False,True])
def test_rejected_receipt_recovery_preserves_the_finite_repair_limit(tmp_path,interrupt):
    malformed=lambda state:('{"action":',{})
    e,repo=engine_for(tmp_path,[malformed,malformed,first])
    e.config.budget.repair_attempts=2
    original=e.checkpoint
    def checkpoint(event):
        original(event)
        if interrupt and event=='native_receipt_saved' and e.state.usage['agent_calls']==2:
            raise KeyboardInterrupt('Durable second malformed receipt')
    e.checkpoint=checkpoint
    if interrupt:
        with pytest.raises(KeyboardInterrupt):e.start(repo)
    else:e.start(repo)
    e.checkpoint=original
    state=e.resume()
    assert state.usage['agent_calls']==2 and not state.units
    assert state.native_current['failures']==2 and 'bounded whole-draft' in state.stop_reason


def test_draft_symlinks_and_fixed_helper_bytes(tmp_path):
    from consensus_assurance.workflow.native import Inputs,draft_file
    draft=tmp_path/'draft';draft.mkdir();archive=tmp_path/'archive'
    (draft/'real').mkdir();(draft/'real'/'helper.py').write_text('fixed')
    (draft/'alias').symlink_to(draft/'real',target_is_directory=True)
    (draft/'link').symlink_to(draft/'real'/'helper.py')
    for name in ('alias/helper.py','link','../outside'):
        with pytest.raises(ValueError):draft_file(draft,name)
    inputs=Inputs(draft,archive)
    assert inputs.read('real/helper.py')=='fixed'
    (draft/'real'/'helper.py').write_text('modified')
    assert inputs.read('real/helper.py')=='fixed'


def test_accepted_check_recovers_without_remaining_model_call(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step()])
    original=e.checkpoint
    def checkpoint(event):
        original(event)
        if event=='semantic_operation_committed' and e.state.native_current.get('direct_check_id'):
            raise KeyboardInterrupt('accepted before execution')
    e.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    assert e.state.usage['agent_calls']==2
    e.checkpoint=original
    state=e.resume()
    assert len([c for c in state.checks if c.direct_check_id])==1, state.stop_reason
    assert len(state.native_turns)==2
    assert state.native_current['phase']=='executed'


def test_same_version_reading_and_independent_issues(tmp_path):
    def issues(state):
        artifact=state['direct_checks'][-1]['id']
        return dict(action='review',artifact_id=artifact,rationale='Two distinct uncertainty sources',
            review_items=[dict(target_id=artifact,aspect='checker_correspondence',status='needs_reading',source_ids=['code'],rationale='Need the actual bound contract'),
                dict(target_id=artifact,aspect='applicability',status='disputed',source_ids=['doc'],rationale='External callers may supply illegal input',counterevidence=['The caller boundary remains outside this local test'])]),{}
    def resolve(state):
        artifact=state['direct_checks'][-1]['id']
        issue=next(i for i in state['review_issues'] if i['aspect']=='checker_correspondence')
        other=next(i for i in state['review_issues'] if i['aspect']=='applicability')
        item=dict(target_id=artifact,aspect='checker_correspondence',status='no_issue_found',source_ids=['code','doc'],rationale='The actual README bounds the observed return for the explicitly admitted input')
        return dict(action='review',artifact_id=artifact,review_items=[item],rationale='Answer the named reading issue',
            resolutions=[dict(issue_id=issue['id'],target_version=issue['target_version'],original_question=issue['explanation'],source_ids=['code','doc'],rationale=item['rationale'],residual_issue_ids=[other['id']],scope_limitations=['Unrelated callers remain outside the observed invocation'])]),{}
    e,repo=engine_for(tmp_path,[first,check_step(),issues,resolve,stop])
    state=e.start(repo)
    assert len(state.direct_checks)==1
    assert len(state.review_issues)==2
    assert next(i for i in state.review_issues if i.aspect=='checker_correspondence').resolved_by
    assert not next(i for i in state.review_issues if i.aspect=='applicability').resolved_by
    assert state.units[0].remaining_obligation_ids==['bounded']


@pytest.mark.parametrize('phase',['action_result_saved','native_receipt_saved','runner_complete','native_runner_complete'])
def test_recovery_does_not_repeat_model_or_target_execution(tmp_path,phase):
    e,repo=engine_for(tmp_path,[first,check_step()])
    original=e.checkpoint
    interrupted=False
    def checkpoint(event):
        nonlocal interrupted
        if (phase=='native_runner_complete' and event=='action_result_saved'
                and e.state.pending_action.kind=='native_agent' and e.state.usage['agent_calls']==2 and not interrupted):
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
            write_json(log/'check.json',raw[0]);write_json(action/'native-response.json',raw[2])
            (action/'result.json').unlink()
            e.state.pending_action.status='running'
            e.agent.decode=CodexAgent().decode
            original('interruption_after_native_raw_receipt')
            raise KeyboardInterrupt('native receipt before action result')
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
    state=e.resume()
    assert len(state.native_turns)==2
    assert state.usage['agent_calls']==2
    assert state.usage['experiments']==1
    assert len(state.direct_checks)==1
    assert len([c for c in state.checks if c.direct_check_id])==1
    receipts=[json.loads(p.read_text()) for p in (e.root/'logs').glob('*/check.json')]
    assert sum(r['action']=='direct_check' for r in receipts)==1


@pytest.mark.parametrize('fault',['malformed_final','missing_submission','session_lost','login','quota'])
def test_native_receipt_failure_routes_preserve_or_stop_the_session(tmp_path,fault):
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.core.types import ExecutionStatus
    e,repo=engine_for(tmp_path,[first,stop,check_step(),stop])
    original=e.agent.investigate
    sessions=[]
    def investigate(runner,prompt,directory,snapshot_id,timeout,session_id=None):
        sessions.append(session_id)
        check,_,receipt=original(runner,prompt,directory,snapshot_id,timeout,session_id)
        action=e.root/'actions'/runner.active_action_id
        response=action/'native-response.json';response.write_text(json.dumps(receipt))
        events=action/'fixture-events.jsonl'
        events.write_text(json.dumps({'type':'thread.started','thread_id':session_id or 'fixture-session'})+'\n'+json.dumps({'type':'turn.completed'}))
        check.stdout=str(events)
        if len(sessions)==2:
            if fault=='malformed_final':response.write_text('{')
            elif fault=='missing_submission':response.write_text(json.dumps({'submission':'absent.json','summary':'Missing product'}))
            else:
                check.exit_code=1
                events.write_text({'session_lost':'thread not found','login':'please log in; 401','quota':'insufficient_quota'}[fault])
        return CodexAgent().decode(check,response,session_id)
    e.agent.investigate=investigate
    state=e.start(repo)
    assert len(state.units)==1
    if fault in {'login','quota'}:
        assert len(sessions)==2 and not state.direct_checks
        check=next(c for c in reversed(state.checks) if c.action=='native_agent')
        assert check.status==({'login':ExecutionStatus.LOGIN_REQUIRED,'quota':ExecutionStatus.QUOTA_EXHAUSTED}[fault])
    else:
        assert len(state.direct_checks)==1,state.native_current
        assert sessions[2]==(None if fault=='session_lost' else 'fixture-session')
        if fault=='session_lost':assert any('session unavailable' in gap for gap in state.gaps)
        else:assert list((e.root/'native-submissions').glob('*/diagnostics.json'))


def test_candidate_parent_conflict_and_paused_return_keep_one_active_question(tmp_path):
    def initial(state):
        sub=products()[0]
        sub.update(action='continue',obligation=None,bindings=[])
        sub['question'].update(disposition='needs_specific_evidence',unknowns=['Unexamined consumer'])
        return sub,{}
    def pause(index):
        def step(state):
            current=state['question_candidates'][index]
            return dict(action='pause',candidate_id=current['id'],question=current['question'],
                resume_conditions=['Inspect the remaining consumer'],rationale='Retain this boundary'),{}
        return step
    def independent(state):
        sub,_=initial(state);sub['question']['question']='Is a different local caller bounded?'
        return sub,{}
    def resume_parent(state):
        sub,_=initial(state);sub['candidate_id']=state['question_candidates'][0]['id']
        return sub,{}
    def conflicting_child(state):
        sub=products()[0];sub['candidate_id']=sub['parent_candidate_id']=state['question_candidates'][0]['id']
        return sub,{}
    def child(state):
        assert len(state['question_candidates'])==2 and not state['units']
        sub=products()[0];sub['parent_candidate_id']=state['question_candidates'][0]['id']
        return sub,{}
    e,repo=engine_for(tmp_path,[initial,pause(0),independent,resume_parent,pause(1),resume_parent,conflicting_child,child,check_step(),stop])
    state=e.start(repo)
    assert len(state.question_candidates)==3 and len(state.units)==1,state.native_current
    assert state.usage['audit_units']==1 and len(state.direct_checks)==1
    assert state.question_candidates[0].question.unknowns==['Unexamined consumer']
    assert state.question_candidates[2].parent_candidate_id==state.question_candidates[0].id
    assert not any(c.status=='active' for c in state.question_candidates)
    assert len(list((e.root/'native-submissions').glob('*/diagnostics.json')))==2


def test_accepted_execution_gap_is_not_reclassified_as_submission_rejection(tmp_path,monkeypatch):
    import consensus_assurance.workflow.native as native
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    monkeypatch.setattr(native,'execute_direct_check',lambda *a: (_ for _ in ()).throw(OSError('workspace unavailable')))
    state=e.start(repo)
    assert len(state.direct_checks)==1
    assert not list((e.root/'native-submissions').glob('*/diagnostics.json'))
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
        spec=dict(target_profile=dict(system_boundary='One local operation',source_ids=['code']),
            activities=[],behaviors=[dict(id='call',primary_activity='A1',execution_owner='caller',protocol_context='one request',trigger='invoke',produces_fact_ids=['result'],consumes_fact_ids=[],source_ids=['code'])],
            facts=[dict(id='result',meaning='Bounded return from the actual call',identity={'operation':'one'},validity_context='one completion',established_by=['call'],consumed_by=[],representation=['return'],durability='volatile',recovery='none',unknowns=['Consumer outside boundary'],source_ids=['code'])])
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
        spec['behaviors'][0]['execution_owner']='synchronous local caller'
        files['map.json']=json.dumps(spec)
        return value,files
    e,repo=engine_for(tmp_path,[research,missing_fact,with_refs,check_step(),refine,stop])
    state=e.start(repo)
    assert state.audit_spec_version==2 and len(state.units)==1,state.native_current
    assert Path(state.audit_spec_path).is_file()
    assert state.units[0].audit_question.fact_ids==['result']
    assert len(state.direct_checks)==1
    assert json.loads((e.root/'audit-spec'/'v1.json').read_text())['behaviors'][0]['execution_owner']=='caller'
    assert e.resume().audit_spec_version==2
    assert len(list((e.root/'native-submissions').glob('*/diagnostics.json')))==1


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
        sub['resolutions']=[dict(issue_id=issue['id'],target_version=issue['target_version'],original_question=issue['explanation'],source_ids=['code','doc'],rationale='The revised necessary predicate completed a new actual execution without demanding success',residual_issue_ids=[],scope_limitations=['No distributed consequence'])]
        return sub,{}
    e,repo=engine_for(tmp_path,[first,flawed,dispute,ordinary,corrected,resolve,stop])
    state=e.start(repo)
    assert len(state.direct_checks)==3,(state.stop_reason,state.native_current)
    assert [a.version for a in state.direct_checks]==[1,2,3]
    assert state.review_issues[0].resolved_by
    assert len([c for c in state.checks if c.direct_check_id])==3
    assert state.monitor_results[0]['outcome']=='violated'
    assert state.monitor_results[-1]['outcome']=='holds'
    assert state.units[0].status=='checked'


def test_isolated_runner_sees_fixed_submitted_helpers(tmp_path):
    from consensus_assurance.workflow.native import execute_accepted
    e,repo=engine_for(tmp_path,[first,check_step(),stop])
    e.config.execution_isolation='bwrap'
    original=e.checkpoint
    def mutate_after_acceptance(event):
        original(event)
        if event=='semantic_operation_committed' and e.state.native_current.get('direct_check_id'):
            (e.root/'native-draft'/'check.py').write_text("raise RuntimeError('changed draft')")
            (e.root/'native-draft'/'helper.py').write_text("raise RuntimeError('changed helper')")
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
