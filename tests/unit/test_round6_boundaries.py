"""Project-level reproductions of the reviewed interface boundaries."""
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Material,Responsibility,ResponsibilityHandoff
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.reviews import material_closure
from consensus_assurance.workflow.inquiry import queue_handoffs


def controller(tmp_path,state):
    cfg=Config(implementation='toy',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'');engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    return engine


def test_same_action_kind_cannot_consume_other_input(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state)
    assert e.action('agent:review','agent_calls',lambda:'first',{'task':'A','value':1})=='first'
    assert e.action('agent:review','agent_calls',lambda:'second',{'task':'B','value':2})=='second'
    assert state.usage['agent_calls']==2


def test_selected_relation_closure_contains_endpoint_contract(prepared):
    _,state,_,_=prepared
    m=Material(id='upstream-contract',file='notes.md',start_line=1,end_line=1,kind='document_statement',text='The provider accepts only bounded inputs',content_digest='fixture')
    state.materials.append(m);state.claims[2].source_ids.append(m.id)
    relation=next(r for r in state.relations if r.target==state.claims[2].id)
    materials,_=material_closure(state,[relation.id])
    assert m.id in materials


def test_unrelated_unit_assignment_does_not_hide_handoff(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);source=state.materials[0].id
    state.responsibilities=[Responsibility(id='producer',description='Create output',source_ids=[source],claim_ids=[],applicability='Fixture',handoffs=[ResponsibilityHandoff(target_id='consumer',description='Transfer ownership of output',source_ids=[source],covered_by_unit_ids=[state.units[0].id])]),Responsibility(id='consumer',description='Use output',source_ids=[source],claim_ids=[],applicability='Fixture')]
    queue_handoffs(e)
    assert any(t.trigger.startswith('handoff:') for t in state.inquiry_tasks)


def test_graph_failures_carry_machine_diagnostics(prepared):
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.workflow.graph import apply_discovery
    _,state,_,responses=prepared
    p=Discovery.model_validate(responses[1]);p.bindings[0].symbol='DoesNotExist'
    p.units[0].binding_ids.append(p.bindings[-1].id)
    before=state.model_dump()
    with pytest.raises(ValueError) as caught:apply_discovery(state,p)
    assert hasattr(caught.value,'diagnostics')
    assert len(caught.value.diagnostics)>=2
    assert state.model_dump()==before
