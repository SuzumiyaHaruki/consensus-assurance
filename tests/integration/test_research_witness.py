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
    e,repo=engine_for(tmp_path,[first,interrupted]);e.config.budget.agent_calls=20
    state=e.start(repo)
    assert state.run_stop['origin']=='controller' and state.run_stop['reason']==('user_stop' if event=='cancel' else 'resource_limit')
    assert state.usage['agent_calls']==2 and state.run_stop['pending_work']
    assert not state.evidence and not state.run_stop.get('frontier_comparison')
    assert not any(s['action']=='rejected' for s in state.selections)
    assert bool(diagnostics(e))==(event=='deadline')
    if event=='deadline':assert Path(diagnostics(e)[0]['raw_path']).read_text()=='{'


def test_nonadjacent_history_support_retains_actual_core_relationship(tmp_path):
    def submit(state):
        sub,files=first(state);spec=json.loads(files['map.json'])
        spec['behaviors'].append(dict(id='prefix',primary_activity='A1',execution_owner='caller',protocol_context='initialization',trigger='start',source_ids=['code']))
        sub['question']['supporting_behavior_ids']={'prefix':'Legal initial invocation prefix; not a direct producer of the return'}
        files['map.json']=json.dumps(spec)
        return sub,files
    e,repo=engine_for(tmp_path,[submit,stop]);state=e.start(repo)
    assert not diagnostics(e) and state.units[0].audit_question.supporting_behavior_ids
    assert not e.config.activity_focus


def test_controller_version_normalization_cannot_declare_semantic_changes(tmp_path):
    def undeclared(state):
        from consensus_assurance.core.proposals import UnitDraft
        unit=state['units'][0]
        draft=UnitDraft(**{k:v for k,v in unit.items() if k in UnitDraft.model_fields})
        draft.audit_question.contexts=['A different invocation contract']
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces'].append(dict(entry_point='background',disposition='deferred',reason='Not inspected',source_ids=['code']))
        fb=dict(kind='F2',rationale='Proposed scoped contract change',evidence_ids=['code','doc'],target_ids=[unit['id']],relation_ids=[],
            new_basis='Acquired source interpretation',old_judgment='Original context',new_judgment='Different context',
            grounding=products()[0]['obligation']['grounding'],changes=[],
            patch=dict(units=[draft.model_dump(mode='json')],expected_versions={unit['id']:unit['version']},rationale='Undeclared context change'))
        return dict(action='semantic_revision',unit_id=unit['id'],map_path='map.json',feedback_path='feedback.json',
            rationale='Metadata normalization cannot grant semantic write authority'),{'map.json':json.dumps(spec),'feedback.json':json.dumps(fb)}
    e,repo=engine_for(tmp_path,[first,undeclared,stop]);state=e.start(repo)
    assert len(diagnostics(e))==1 and 'own declaration' in str(diagnostics(e))
    assert state.audit_spec_version==1 and state.units[0].audit_question.contexts==products()[0]['question']['contexts']
