"""Audit products with scripted transport and actual isolated local execution."""
import json
from pathlib import Path
import pytest
from audit_support import products, first, check_step, review_step, stop, engine_for, partial_map, feedback


def test_existing_unit_actual_compile_repair_review_progress(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(True),check_step(revise=True),review_step(),stop])
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    assert len(state.direct_checks)==2, state.current_submission
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
    assert index['units'] and index['claims'] and index['artifacts']
    assert index['implementation']['harness_kind']=='python'


def test_raw_parse_failure_is_retained_and_whole_draft_can_continue(tmp_path):
    e,repo=engine_for(tmp_path,[lambda state:('{"action":',{}),first,stop])
    state=e.start(repo)
    assert len(state.units)==1, state.stop_reason
    rejected=list((e.root/'submissions').glob('*/diagnostics.json'))
    assert len(rejected)==1
    assert (rejected[0].parent/'raw.json').read_bytes()==b'{"action":'


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
    inputs=Inputs(draft,archive)
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
            resolutions=[dict(issue_id=issue['id'],source_ids=['code','doc'],rationale=item['rationale'],residual_issue_ids=[other['id']],scope_limitations=['Unrelated callers remain outside the observed invocation'])]),{}
    e,repo=engine_for(tmp_path,[first,check_step(),issues,resolve,stop])
    state=e.start(repo)
    assert len(state.direct_checks)==1
    assert len(state.review_issues)==2
    assert next(i for i in state.review_issues if i.aspect=='checker_correspondence').resolved_by
    assert not next(i for i in state.review_issues if i.aspect=='applicability').resolved_by
    assert state.units[0].remaining_obligation_ids==['bounded']


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
    e,repo=engine_for(tmp_path,[first,stop,check_step(),stop])
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
                check.status=ExecutionStatus.TIMEOUT;check.exit_code=-9;check.reason='Total budget ended before reliable completion'
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
        check=next(c for c in reversed(state.checks) if c.action=='agent_turn')
        assert check.status==({'login':ExecutionStatus.LOGIN_REQUIRED,'quota':ExecutionStatus.QUOTA_EXHAUSTED,'service_refusal':ExecutionStatus.ERROR,'timeout':ExecutionStatus.TIMEOUT}[fault])
    else:
        assert len(state.direct_checks)==1,state.current_submission
        assert sessions[2]==(None if fault=='session_lost' else 'fixture-session')
        if fault=='session_lost':assert any('session unavailable' in gap for gap in state.gaps)
        else:assert list((e.root/'submissions').glob('*/diagnostics.json'))


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


def test_configuration_repair_closes_its_issue_without_changing_oracle(tmp_path):
    def original(state):
        sub,files=check_step()(state)
        files['check.py']='duration = 0\n'+files['check.py']
        return sub,files
    def challenge(state):
        sub,_=review_step('revision_needed')(state)
        sub['sources']=[dict(id='configuration-source',file='target.py',start_line=3,end_line=5,kind='code_observation')]
        sub['review_items'][0].update(challenged_components=['configuration'],source_ids=['configuration-source','doc'],
            rationale='The setup uses an invalid duration and bypasses the actual validator',
            counterevidence=['The real validation function rejects nonpositive duration'])
        return sub,{}
    def repair(state):
        sub,files=check_step(revise=True)(state)
        files['check.py']='from target import validate_config\nduration = validate_config(1)\n'+files['check.py']
        plan=json.loads(files['plan.json']);plan['description']='Same comparison with validated setup'
        plan['harness']['legality']['derivation']+='; the setup now invokes the actual validation function'
        files['plan.json']=json.dumps(plan)
        return sub,files
    def resolve(state):
        sub,_=review_step()(state)
        sub['review_items'][0]['source_ids']=['configuration-source','code','doc']
        sub['resolutions']=[dict(issue_id=state['review_issues'][0]['id'],source_ids=['configuration-source'],
            evidence_ids=[state['direct_checks'][-1]['id']],rationale='The new fixed input calls validation before any operation, and the fresh execution reaches the same independent result',
            residual_issue_ids=[],scope_limitations=['No distributed consequence'])]
        return sub,{}
    e,repo=engine_for(tmp_path,[first,original,challenge,repair,resolve,stop])
    with (repo/'target.py').open('a') as stream:stream.write('def validate_config(duration):\n    if duration <= 0: raise ValueError("invalid duration")\n    return duration\n')
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.current_submission
    assert state.review_issues[0].resolved_by
    old,new=[json.loads(Path(a.plan_path).read_text()) for a in state.direct_checks]
    assert old['observable_properties']==new['observable_properties'] and old['monitors']==new['monitors']
    assert len([c for c in state.checks if c.direct_check_id])==2 and state.units[0].status=='checked'
    assert old['harness']['source'].startswith('duration = 0')
    assert state.review_issues[0].source_ids==['configuration-source','doc']


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
    from consensus_assurance.workflow.research import view
    from consensus_assurance.workflow.audit import accept, Inputs, AuditSubmission
    from consensus_assurance.workflow.transactions import commit_graph
    def explore(state):
        return dict(action='explore',question='Observe the local return before selecting a claim',
            harness_path='explore.py',rationale='Use a real local call'),{
            'explore.py':"from target import step\nprint('observed', step(3,3))\n"}
    def retain(state):
        check=next(c for c in state['checks'] if c['action']=='exploration')
        return dict(action='research',rationale='Retain the construction observation',feedback=dict(
            ref_ids=[check['id']],answered='The executed local boundary call returned zero.',remaining=[],
            understanding='updated',rationale='No normative claim or map change is implied.')),{}
    def next_turn(state):
        current=view(e.state,compact=True)
        assert current['handoffs'][-1]['feedback']['answered'].endswith('zero.')
        assert not any(state[k] for k in ('question_candidates','units','evidence','findings'))
        assert state['audit_spec_version']==0
        from consensus_assurance.workflow.audit import validate_submission
        raw=retain(state)[0]
        raw['feedback']['ref_ids']=[current['handoffs'][-1]['operation_id']]
        (e.root/'draft'/'indirect.json').write_text(json.dumps(raw))
        assert validate_submission(e.state,e.root,'indirect.json',e.implementation)['valid']
        return dict(action='stop',scope='run',reason='user_stop',rationale='End the scripted exercise'),{}
    e,repo=engine_for(tmp_path,[explore,retain,next_turn])
    e.config.directed_question=None
    old=e.graph_commit_hook
    def interrupt(key):
        if e.state.usage.get('agent_calls')==2:raise KeyboardInterrupt('Retained transaction before adoption')
    e.graph_commit_hook=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.graph_commit_hook=old
    state=e.resume()
    assert state.usage['experiments']==1
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
                lambda proxy:accept(proxy,sub,Inputs(e.root/'draft',e.root/'submissions'/('bad-'+str(index))),'bad'))
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
            Inputs(draft,e.root/'submissions'/'bad-combined'),'bad-combined'))
    assert {d['code'] for d in rejected['diagnostics']}=={d.code for d in formal.value.diagnostics}
    assert validate(sub)['valid']
    assert not e.state.units and not e.state.direct_checks
    # Later byte and capacity changes must be checked again by the formal path.
    (draft/'check.py').write_text('changed harness bytes\n')
    e.state.usage['experiments']=e.config.budget.experiments
    assert not validate(sub)['valid']
    with pytest.raises(ValueError,match='experiments'):
        commit_graph(e,'capacity-change',sub,lambda proxy:accept(proxy,AuditSubmission.model_validate(sub),
            Inputs(draft,e.root/'submissions'/'capacity-change'),'capacity-change'))
    e.state.usage.pop('experiments')
    assert validate(sub)['valid']
    commit_graph(e,'fresh-bytes',sub,lambda proxy:accept(proxy,AuditSubmission.model_validate(sub),
        Inputs(draft,e.root/'submissions'/'fresh-bytes'),'fresh-bytes'))
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
        return raw,files
    e,repo=engine_for(tmp_path,[first,check_step(),review,stop]);state=e.start(repo)
    assert state.semantic_reviews[0].items[0].target_id==state.direct_checks[0].id
    assert 'target_id' not in AuditSubmission.model_json_schema()['$defs']['ArtifactReviewItem']['required']
    with pytest.raises(ValueError):SemanticCheck.model_validate({'aspect':'applicability','status':'no_issue_found',
        'source_ids':['code'],'rationale':'A normal persisted semantic item requires its target'})
