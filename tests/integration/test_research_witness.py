"""Scoped knowledge progress and unconditional resource exits through audit products."""
import json
from pathlib import Path
import pytest
from audit_support import first, products, engine_for, check_step, review_step, stop, feedback
from test_audit_research import question_step, diagnostics


@pytest.mark.parametrize('owned_ref',['material','result','review','disposition','unknown','unexplained'])
def test_same_source_answer_can_reduce_current_unknowns(owned_ref,tmp_path):
    def answer(state):
        sub,files=question_step(state)
        sub['candidate_id']=state['question_candidates'][-1]['id']
        sub['question'].update(unknowns=[],disposition='ready_for_check')
        ref={'material':'code','result':next(c['id'] for c in state['checks'] if c.get('direct_check_id')),'review':state['semantic_reviews'][-1]['id'],
            'disposition':state['selections'][0]['operation_id'],'unknown':'invented','unexplained':'code'}[owned_ref]
        if owned_ref!='unexplained':sub['feedback']=dict(feedback(state),ref_ids=[ref],answered='The acquired source and local result answer the boundary; consumer semantics remain outside this scope')
        return sub,files
    # The second Candidate can cite actual results/reviews of the first discriminator.
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),question_step,answer,stop])
    state=e.start(repo)
    candidate=state.question_candidates[-1]
    if owned_ref in {'unknown','unexplained'}:
        assert candidate.question.unknowns and diagnostics(e)
    else:
        assert not candidate.question.unknowns and candidate.history[-1].unknowns
        assert not diagnostics(e)


@pytest.mark.parametrize('reason',['user_stop','resource_limit','tool_gap'])
def test_model_stop_labels_do_not_establish_controller_events(tmp_path,reason):
    from consensus_assurance.workflow.audit import validate_submission
    messages=[]
    def proposed(state):
        raw=dict(action='stop',reason=reason,scope='run',rationale='The model asks to terminate',
            ref_ids=[next(c['id'] for c in state['checks'] if c['action']=='exploration')],feedback=feedback(state))
        draft=e.root/'draft'/'stop.json';draft.write_text(json.dumps(raw))
        before=e.state.model_dump(mode='json')
        result=validate_submission(e.state,e.root,draft.name,e.implementation)
        assert not result['valid'] and e.state.model_dump(mode='json')==before
        diagnostic=result['diagnostics'][0];messages.append(diagnostic['message'])
        assert diagnostic['code']=='stop_decision' and diagnostic['details']['reconsider']=='research_decision'
        assert diagnostic['details']['capacity']['source_investigation']
        raw['origin']='controller';draft.write_text(json.dumps(raw))
        assert not validate_submission(e.state,e.root,draft.name,e.implementation)['valid']
        raw.pop('origin')
        return raw,{}
    def proceed(state):
        assert not state['run_stop'] and all(not c['stagnation'] for c in state['question_candidates'])
        assert diagnostics(e)[0]['errors']==messages
        assert state['units'][0]['status']!='checked' and not state['review_issues'][0]['resolved_by']
        return dict(action='research',feedback=feedback(state),rationale='The isolated exploration failure leaves source investigation available'),{}
    def fail_locally(state):
        return dict(action='explore',question='Observe a controlled local tool failure',harness_path='probe.py',
            rationale='Test that a failed local check does not end research'),{'probe.py':'raise RuntimeError("controlled local failure")\n'}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step('disputed'),fail_locally,proposed,proceed,stop])
    e.config.budget.agent_calls=20
    state=e.start(repo)
    assert state.run_stop['origin']=='controller' and state.run_stop['reason']=='user_stop'
    assert state.usage['agent_calls']==7 and not state.review_issues[0].resolved_by


@pytest.mark.parametrize('event',['deadline','cancel'])
def test_controller_interrupt_does_not_require_a_valid_draft(tmp_path,event):
    from consensus_assurance.workflow.audit import validate_submission
    def interrupted(state):
        raw=dict(action='stop',scope='run',reason='insufficient_basis',ref_ids=['code','doc'],
            rationale='A source boundary is unresolved',frontier_comparison=[dict(ref_ids=[state['units'][0]['id']],
                next_step='Acquire an external caller contract',actionable=False,rationale='That contract is outside the supplied snapshot')])
        draft=e.root/'draft'/'stop.json';draft.write_text(json.dumps(raw))
        assert validate_submission(e.state,e.root,draft.name,e.implementation)['valid']
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


def test_independent_consumer_enrichment_keeps_old_artifact_current(tmp_path):
    def enrich(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['behaviors'].append(dict(id='consumer',primary_activity='A1',execution_owner='caller',protocol_context='later operation',
            trigger='use',consumes_fact_ids=['result'],source_ids=['consumer-source']))
        spec['facts'][0]['unknowns']=['Which external caller orders production and consumption?']
        return dict(action='research',map_path='map.json',rationale='Record an independent later consumer',
            sources=[dict(id='consumer-source',file='consumer.py',start_line=1,end_line=2,kind='code_observation')],
            map_changes={'result':dict(impact='clarification',source_ids=['consumer-source','code'],
                rationale='The consumer forwards the value; its external invocation order remains unknown. The original local return scope and observation are unchanged.'),
                'consumer':dict(impact='dependency',source_ids=['consumer-source','code'],
                rationale='The later reader returns its input without mutation',
                preserves='The earlier obligation ends at step return; this later consumer does not alter that value or its recorded history')}),{'map.json':json.dumps(spec)}
    def investigate(state):
        sub,_=question_step(state);sub.pop('map_path');sub['sources']=[]
        sub['question'].update(audit_spec_version=None,question='Does the later consumer transform the delivered value?',
            behavior_ids=['consumer'],source_ids=['consumer-source','code'],obligation_relation_kind='consumption',
            counterevidence=['consume directly returns the argument'],unknowns=['External invocation ordering is not supplied'])
        sub['feedback']=dict(feedback(state),answered='The new source relation supports a separate consumer question; the first local result stays within its recorded scope')
        return sub,{}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),enrich,investigate,stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert not diagnostics(e) and state.audit_spec_version==2 and state.units[0].status=='checked'
    assert state.units[0].audit_question.audit_spec_version==1 and all(e.applicability=='current' for e in state.evidence)
    assert len(state.question_candidates)==2 and state.question_candidates[1].question.fact_ids==['result']
    old=json.loads((e.root/'audit-spec'/'v1.json').read_text());new=json.loads(Path(state.audit_spec_path).read_text())
    assert old['facts'][0]['unknowns']==['Consumer outside boundary']
    assert new['facts'][0]['unknowns']==['Which external caller orders production and consumption?']
    assert 'distributed consequences' in state.claims[0].scope.excluded and 'distributed consequences' not in json.dumps(new)
    assert sum(c.action=='direct_check' for c in state.checks)==1 and not state.revisions


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
