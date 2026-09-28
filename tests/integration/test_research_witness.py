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


@pytest.mark.parametrize('prefix',[[],[question_step],[first],[first,check_step(),review_step('disputed')]])
def test_forced_stop_ignores_malformed_semantics_and_retains_pending(tmp_path,prefix):
    def forced(state):
        refs=[c['id'] for c in state['question_candidates']]+[u['id'] for u in state['units']]
        return dict(action='stop',reason='resource_limit',scope='invalid-scope',rationale='Total time exhausted',
            ref_ids=refs+refs+['stale'],sources='not a source list',map_path='absent-map',feedback={'answered':'erase dispute'}),{}
    e,repo=engine_for(tmp_path,prefix+[forced])
    state=e.start(repo)
    assert state.run_stop['reason']=='resource_limit' and state.run_stop['notes']['diagnostics']
    assert not diagnostics(e) and state.usage['agent_calls']==len(prefix)+1
    assert state.run_stop['pending_work']==__import__('consensus_assurance.workflow.research',fromlist=['pending_work']).pending_work(state)
    assert all(not i.resolved_by for i in state.review_issues)
    assert all(u.status!='checked' for u in state.units) if len(prefix)!=0 else not state.units
    raw=list((e.root/'submissions').glob('*/raw.json'))
    assert any(json.loads(p.read_text()).get('sources')=='not a source list' for p in raw)


def test_independent_consumer_enrichment_keeps_old_artifact_current(tmp_path):
    def enrich(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['behaviors'].append(dict(id='consumer',primary_activity='A1',execution_owner='caller',protocol_context='later operation',
            trigger='use',consumes_fact_ids=['result'],source_ids=['consumer-source']))
        return dict(action='research',map_path='map.json',rationale='Record an independent later consumer',
            sources=[dict(id='consumer-source',file='consumer.py',start_line=1,end_line=2,kind='code_observation')],
            map_changes={'consumer':dict(impact='dependency',source_ids=['consumer-source','code'],
                rationale='The later reader returns its input without mutation',
                preserves='The earlier obligation ends at step return; this later consumer does not alter that value or its recorded history')}),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),enrich,stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert not diagnostics(e) and state.audit_spec_version==2 and state.units[0].status=='checked'
    assert state.units[0].audit_question.audit_spec_version==1 and all(e.applicability=='current' for e in state.evidence)


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
