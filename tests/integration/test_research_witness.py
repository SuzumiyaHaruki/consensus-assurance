"""Scoped knowledge progress and unconditional resource exits through audit products."""
import json
from pathlib import Path
import pytest
from audit_support import first, products, engine_for, check_step, review_step, stop, feedback
from audit_support import question_step, diagnostics


def test_same_source_answer_can_reduce_current_unknowns(tmp_path):
    import shutil
    from types import SimpleNamespace
    from consensus_assurance.workflow.audit import prepare_submission, Inputs
    from consensus_assurance.core.submissions import AuditSubmission
    from consensus_assurance.workflow.budget import BudgetTracker
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),question_step,stop]);e.start(repo)
    baseline=e.state.model_dump(mode='json')
    refs={'material':'code','result':next(c.id for c in e.state.checks if c.direct_check_id),
        'review':e.state.semantic_reviews[-1].id,'disposition':e.state.selections[0]['operation_id'],
        'unknown':'invented','unexplained':'code'}
    for kind,ref in refs.items():
        # Private framework fixtures share only retained read-only evidence, not acceptance state or output.
        root=tmp_path/kind;shutil.copytree(e.root,root)
        state=e.state.model_copy(deep=True);config=e.config.model_copy(deep=True)
        context=SimpleNamespace(root=root,state=state,config=config,implementation=e.implementation,budget=BudgetTracker(config.budget,state))
        sub,files=question_step(baseline);sub['candidate_id']=state.question_candidates[-1].id
        sub['question'].update(unknowns=[],disposition='ready_for_check')
        if kind!='unexplained':sub['feedback']=dict(feedback(baseline),ref_ids=[ref],answered='The acquired source and local result answer this boundary; consumer semantics stay outside scope')
        for name,text in files.items():(root/'draft'/name).write_text(text)
        product=AuditSubmission.model_validate(sub)
        if kind in {'unknown','unexplained'}:
            with pytest.raises(ValueError):prepare_submission(context,product,Inputs(root/'draft'),'answer')
        else:
            prepare_submission(context,product,Inputs(root/'draft'),'answer')()
            candidate=state.question_candidates[-1]
            assert not candidate.question.unknowns and candidate.history[-1].unknowns
        assert e.state.model_dump(mode='json')==baseline and e.state.question_candidates[-1].question.unknowns


def test_model_stop_labels_do_not_establish_controller_events(tmp_path):
    from consensus_assurance.workflow.audit import validate_submission
    def proposed(state):
        raw=dict(action='stop',reason='user_stop',scope='run',rationale='The model asks to terminate',
            ref_ids=[next(c['id'] for c in state['checks'] if c['action']=='exploration')],feedback=feedback(state))
        before=e.state.model_dump(mode='json')
        for reason in ('user_stop','resource_limit','tool_gap'):
            root=tmp_path/reason;(root/'draft').mkdir(parents=True)
            sample=dict(raw,reason=reason)
            path=root/'draft/stop.json';path.write_text(json.dumps(sample))
            result=validate_submission(e.state.model_copy(deep=True),root,path.name,e.implementation)
            diagnostic=result['diagnostics'][0]
            assert not result['valid'] and diagnostic['code']=='stop_decision'
            assert diagnostic['details']['reconsider']=='research_decision' and diagnostic['details']['capacity']['source_investigation']
            path.write_text(json.dumps(dict(sample,origin='controller')))
            assert not validate_submission(e.state.model_copy(deep=True),root,path.name,e.implementation)['valid']
        sample=dict(raw,reason='bounded_completed',scope='focus',ref_ids=[state['question_candidates'][0]['id']])
        path.write_text(json.dumps(sample))
        assert 'focus exhaustion' in str(validate_submission(e.state.model_copy(deep=True),root,path.name,e.implementation))
        assert e.state.model_dump(mode='json')==before
        return raw,{}
    def proceed(state):
        assert not state['run_stop'] and len(diagnostics(e))==1
        assert state['units'][0]['status']!='checked' and not state['review_issues'][0]['resolved_by']
        return dict(action='research',feedback=feedback(state),rationale='The local exploration failure leaves source investigation available'),{}
    def fail_locally(state):
        return dict(action='explore',question='Observe a controlled local tool failure',harness_path='probe.py',
            rationale='A local failure must not end research'),{'probe.py':'raise RuntimeError("controlled local failure")\n'}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step('disputed'),fail_locally,proposed,proceed,stop])
    e.config.budget.agent_calls=20
    state=e.start(repo)
    assert state.run_stop['origin']=='controller' and state.run_stop['reason']=='user_stop'
    assert state.usage['agent_calls']==7 and not state.review_issues[0].resolved_by


@pytest.mark.parametrize('event',['deadline','cancel'])
def test_controller_interrupt_does_not_require_a_valid_draft(tmp_path,event):
    from consensus_assurance.workflow.audit import validate_submission
    def interrupted(state):
        raw=dict(action='stop',scope='run',reason='insufficient_basis',ref_ids=['code','doc'],rationale='A source boundary is unresolved')
        draft=e.root/'draft'/'stop.json';draft.write_text(json.dumps(raw))
        assert not validate_submission(e.state,e.root,draft.name,e.implementation)['valid']
        if event=='cancel':
            draft.write_text('{')
            return stop(state)
        e.budget.previous=e.config.budget.total_seconds
        return '{',{}
    steps=[interrupted] if event=='cancel' else [first,interrupted]
    e,repo=engine_for(tmp_path,steps);e.config.budget.agent_calls=20
    state=e.start(repo)
    assert state.run_stop['origin']=='controller' and state.run_stop['reason']==('user_stop' if event=='cancel' else 'resource_limit')
    assert state.usage['agent_calls']==len(steps)
    assert not state.evidence and not state.run_stop.get('frontier_comparison')
    assert not any(s['action']=='rejected' for s in state.selections)
    assert bool(diagnostics(e))==(event=='deadline')
    if event=='deadline':assert Path(diagnostics(e)[0]['raw_path']).read_text()=='{'
    else:assert not state.audit_spec_path


def test_claim_revision_keeps_old_evidence_and_executes_new_basis(tmp_path):
    from consensus_assurance.core.proposals import ClaimDraft
    saved={}
    def revise(state):
        old=state['direct_checks'][0]
        saved['artifact']=old
        saved['output']=Path(next(c['stdout'] for c in state['checks'] if c.get('direct_check_id')==old['id'])).read_bytes()
        claim=ClaimDraft(**{k:v for k,v in state['claims'][0].items() if k in ClaimDraft.model_fields})
        claim.description='The legal return must equal zero'
        sub,files=check_step(revise=True)(state)
        sub['revision']=dict(claims=[claim.model_dump(mode='json')],expected_versions={claim.id:1})
        sub['rationale']='Replace range comparison with the stronger zero-return proposition; this needs a new execution'
        plan=json.loads(files['plan.json'])
        plan['observable_properties'][0]['assertion']={'field':'state.value','value':0}
        files['plan.json']=json.dumps(plan)
        files['check.py']=files['check.py'].replace("'in_range':0 <= value <= 3", "'in_range':0 <= value <= 3,'value':value")
        return sub,files
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),revise,review_step(),stop])
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    old,new=state.direct_checks
    assert old.model_dump(mode='json')==saved['artifact'] and new.previous_id==old.id
    assert new.graph_versions['bounded']==2 and old.graph_versions['bounded']==1
    checks=[c for c in state.checks if c.action=='direct_check']
    assert len(checks)==2 and checks[0].id!=checks[1].id
    assert Path(checks[0].stdout).read_bytes()==saved['output']
    assert state.revisions[0].after['graph_changes']==[{'object_id':'bounded','field':'description'}]
    assert any(h['id']=='bounded' and h['version']==1 for h in state.graph_history)
    assert state.semantic_reviews[0].target_versions=={old.id:1}
    assert state.usage['experiments']==2
