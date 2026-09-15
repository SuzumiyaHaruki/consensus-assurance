import json
import pytest
from pydantic import ValidationError
from consensus_assurance.core.proposals import Discovery, GraphPatch, ClaimDraft, UnitDraft, RelationDraft, Feedback, JudgmentChange
from consensus_assurance.workflow.graph import apply_patch
from consensus_assurance.workflow.feedback import apply_feedback


def test_bounded_patches_can_grow_aggregate_past_initial_reply_limits(prepared):
    _,state,_,responses=prepared
    template=Discovery.model_validate(responses[1])
    for batch in range(3):
        claims=[template.claims[0].model_copy(update={'id':f'goal_{batch}_{i}'}) for i in range(8)]
        units=[template.units[0].model_copy(update={'id':f'unit_{batch}_{i}'}) for i in range(4)]
        apply_patch(state,GraphPatch(claims=claims,units=units,rationale='Small sourced additions'))
    assert len(state.claims)>15 and len(state.units)>5
    with pytest.raises(ValidationError):
        Discovery(understanding='Oversized batch',selection_rationale='Test',claims=[template.claims[0]]*16)
    before=state.model_dump()
    state.config['budget']['graph_objects']=len(state.claims)
    with pytest.raises(ValueError,match='aggregate graph'):
        apply_patch(state,GraphPatch(claims=[template.claims[0].model_copy(update={'id':'extra'})],rationale='Too large'))
    assert len(state.claims)==len(before['claims'])


def test_relationship_only_F2_before_model_preserves_claims_and_history(prepared):
    _,state,_,responses=prepared
    edge=state.relations[0]
    changed=RelationDraft(**{k:v for k,v in edge.model_dump().items() if k in RelationDraft.model_fields})
    changed.kind='alternative'
    patch=GraphPatch(relations=[changed],expected_versions={edge.id:edge.version},rationale='An actual alternative mechanism exists')
    with pytest.raises(ValueError,match='relationship semantics'):
        apply_patch(state,patch)
    basis=edge.grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=[]
    f=Feedback(kind='F2',rationale='Correct the dependency kind',evidence_ids=basis.behavior_ids,target_ids=[edge.id],relation_ids=[edge.id],new_basis='Current source exposes an alternative mechanism',graph=None,bundle=None,patch=patch,old_judgment='Treated as mandatory',new_judgment='One alternative path',grounding=basis,
        changes=[JudgmentChange(target_id=edge.id,field='kind',old_value_json=json.dumps(edge.kind),new_value_json=json.dumps('alternative'))])
    before=[c.model_dump() for c in state.claims]
    apply_feedback(state,None,None,f)
    assert [c.model_dump() for c in state.claims]==before
    new=next(r for r in state.relations if r.id==edge.id)
    assert new.kind=='alternative' and new.version==edge.version+1
    assert state.graph_history[-1]['record']['kind']==edge.kind
    assert state.revisions[-1].before['properties'] is None
    assert state.revisions[-1].after['changes']


def test_local_budget_reserve_keeps_calls_and_time_for_inquiry(prepared):
    from consensus_assurance.workflow.budget import BudgetTracker,BudgetExhausted
    from consensus_assurance.core.config import Budget
    _,state,_,_=prepared
    state.usage['agent_calls']=2
    tracker=BudgetTracker(Budget(agent_calls=3,total_seconds=30),state)
    tracker.reserved_agent_calls=1;tracker.reserved_seconds=30
    with pytest.raises(BudgetExhausted,match='reserved'):tracker.take('agent_calls')
    with pytest.raises(BudgetExhausted,match='reserved'):tracker.timeout()
    assert state.usage['agent_calls']==2
    tracker.reserved_agent_calls=0;tracker.reserved_seconds=0
    tracker.take('agent_calls')
    assert tracker.timeout()>0


def test_unresolved_semantic_review_prevents_implementation_upgrade(prepared,tmp_path):
    from consensus_assurance.core.types import SemanticReview,SemanticCheck
    from consensus_assurance.workflow.inquiry import semantic_limitations
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    _,state,bundle,_=prepared
    model=save_bundle(tmp_path,state,state.units[0],bundle,ToyImplementation())
    claim=next(c for c in state.claims if c.id==model.claim_id)
    state.semantic_reviews.append(SemanticReview(task_id='task',check_id='agent-review',target_versions={claim.id:claim.version},material_ids=claim.source_ids,origin='mock',items=[SemanticCheck(target_id=claim.id,aspect='applicability',status='disputed',source_ids=claim.source_ids,explanation='The selected configuration may promise a different result',alternatives='A weaker configured guarantee exists',counterexample_reasoning='A passing local checker does not resolve the configuration')]))
    assert any('Unresolved semantic review' in s for s in semantic_limitations(state,model))
    assert claim.assessment.value=='unassessed'


def test_deferred_local_stage_keeps_repair_context_for_explicit_resume(prepared,tmp_path):
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.inquiry import pause_unit,resume_deferred
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.core.config import Config
    _,state,_,_=prepared
    engine=Engine(Config(),tmp_path,None,None,None,'','');engine.state=state;engine.budget=BudgetTracker(engine.config.budget,state)
    unit=state.units[0];unit.status='selected';state.active_unit_id=unit.id
    state.next_action='technical_repair';state.active_model_id='model'
    state.pending_feedback={'technical_phase':'search','check_id':'failed-search'}
    pause_unit(engine,'Runtime reserved for pending exploration or review')
    assert state.active_unit_id is None and unit.status=='blocked'
    resume_deferred(engine)
    assert state.active_unit_id==unit.id and state.next_action=='technical_repair'
    assert state.pending_feedback['check_id']=='failed-search'


def test_checker_dispute_survives_a_new_replay_model_version(prepared,tmp_path):
    from consensus_assurance.core.types import SemanticReview,SemanticCheck
    from consensus_assurance.workflow.inquiry import semantic_limitations
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    _,state,bundle,_=prepared
    first=save_bundle(tmp_path,state,state.units[0],bundle,ToyImplementation())
    second=save_bundle(tmp_path,state,state.units[0],bundle,ToyImplementation(),previous=first,reason='New experiment only')
    item=SemanticCheck(target_id=first.id,aspect='checker_correspondence',status='disputed',source_ids=['README.md:1:5'],explanation='The antecedent may never trigger',alternatives='Inspect actual triggering paths',counterexample_reasoning='An unreachable trigger can make the checker vacuous')
    state.semantic_reviews.append(SemanticReview(task_id='task',check_id='review',model_id=first.id,target_versions={first.id:first.version},material_ids=item.source_ids,origin='mock',items=[item]))
    assert any('antecedent' in s for s in semantic_limitations(state,second))


def test_ordinary_patch_cannot_hide_existing_unit_obligations(prepared):
    _,state,_,responses=prepared
    unit=state.units[0];unit.obligation_ids.append('input_obligation')
    changed=UnitDraft(**{k:v for k,v in unit.model_dump().items() if k in UnitDraft.model_fields})
    changed.obligation_ids=['step_obligation']
    with pytest.raises(ValueError,match='remove unit obligations'):
        apply_patch(state,GraphPatch(units=[changed],expected_versions={unit.id:unit.version},rationale='Drop the difficult obligation'))
    assert 'input_obligation' in state.units[0].obligation_ids
