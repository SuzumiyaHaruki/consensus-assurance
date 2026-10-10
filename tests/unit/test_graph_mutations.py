"""Repository-type reproductions of the four audited boundary failures."""
import pytest
from consensus_assurance.core.proposals import ClaimDraft, GraphPatch


from consensus_assurance.core.proposals import RelationDraft, BindingDraft, UnitDraft
from consensus_assurance.workflow.graph import apply_patch


def test_cross_type_collision_and_incomplete_changes_are_atomic(prepared):
    _, state, _ = prepared
    candidate=ClaimDraft(**{k:v for k,v in state.claims[0].model_dump().items() if k in ClaimDraft.model_fields})
    candidate.id=state.bindings[0].id
    before=state.model_dump()
    with pytest.raises(ValueError,match='types'):apply_patch(state,GraphPatch(claims=[candidate],expected_versions={candidate.id:1},rationale='Collision'),semantic=True)
    assert state.model_dump()==before


"""Project-level reproductions of the reviewed interface boundaries."""
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Material
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.reviews import material_closure


def controller(tmp_path,state):
    cfg=Config(execution_backend='python',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg));engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    return engine


def test_same_action_kind_cannot_consume_other_input(tmp_path,prepared):
    _, state, _ = prepared;e=controller(tmp_path,state)
    assert e.action('agent:review','agent_calls',lambda:'first',{'task':'A','value':1})=='first'
    assert e.action('agent:review','agent_calls',lambda:'second',{'task':'B','value':2})=='second'
    assert state.usage['agent_calls']==2


def test_selected_relation_closure_contains_endpoint_contract(dependency_prepared):
    _, state, _ = dependency_prepared
    m=Material(id='upstream-contract',file='notes.md',start_line=1,end_line=1,kind='document_statement',text='The provider accepts only bounded inputs',content_digest='fixture')
    state.materials.append(m);state.claims[2].source_ids.append(m.id)
    relation=next(r for r in state.relations if r.target==state.claims[2].id)
    materials,_=material_closure(state,[relation.id])
    assert m.id in materials


from consensus_assurance.core.proposals import GraphDraft


def test_patch_keeps_object_versions_and_unrelated_claims(prepared):
    _, state, responses = prepared
    current=state.claims[1]
    changed=GraphDraft.model_validate(responses['graph']).claims[1]
    changed.description='Refined responsibility under the same documented configuration'
    patch=GraphPatch(claims=[changed],expected_versions={changed.id:1},rationale='New interpretation')
    with pytest.raises(ValueError,match='revise_check'): apply_patch(state,patch)
    apply_patch(state,patch,semantic=True)
    assert state.claims[1].version==2 and state.claims[0].version==1
    assert state.graph_history[-1]['record']['description']==current.description
    with pytest.raises(ValueError,match='version'): apply_patch(state,patch,semantic=True)
