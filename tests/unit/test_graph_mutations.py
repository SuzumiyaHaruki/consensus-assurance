"""Repository-type reproductions of the four audited boundary failures."""
import json
import pytest
from consensus_assurance.core.proposals import ClaimDraft, GraphPatch, Feedback, JudgmentChange


def revision_for(state, ids):
    drafts=[];changes=[]
    for id in ids:
        old=next(c for c in state.claims if c.id==id)
        new=ClaimDraft(**{k:v for k,v in old.model_dump().items() if k in ClaimDraft.model_fields})
        new.description=old.description+' with a weaker requirement'
        drafts.append(new)
        changes.append(JudgmentChange(target_id=id,field='description',old_value_json=json.dumps(old.description),new_value_json=json.dumps(new.description)))
    basis=drafts[0].grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=[]
    return Feedback(kind='F2',rationale='Candidate correction',evidence_ids=basis.expectation_ids or basis.source_ids,target_ids=[ids[0]],relation_ids=[],new_basis='Actual materials support the requested correction',patch=GraphPatch(claims=drafts,expected_versions={i:1 for i in ids},rationale='Correction'),changes=changes,old_judgment=state.claims[1].description,new_judgment=drafts[0].description,grounding=basis)


from consensus_assurance.core.proposals import RelationDraft, BindingDraft, UnitDraft
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.graph import apply_patch


@pytest.mark.parametrize('extra',['claim','relation','unit','binding'])
def test_actual_write_set_rejects_every_unreviewed_object(dependency_prepared,extra):
    _, state, _ = dependency_prepared;a,b=state.claims[1:3]
    f=revision_for(state,[a.id])
    if extra=='claim':f.patch.claims.append(ClaimDraft(**{k:v for k,v in b.model_dump().items() if k in ClaimDraft.model_fields}).model_copy(update={'description':'Weakened unrelated B'}))
    if extra=='relation':
        old=state.relations[0];f.patch.relations=[RelationDraft(**{k:v for k,v in old.model_dump().items() if k in RelationDraft.model_fields}).model_copy(update={'kind':'conditional_on'})]
    if extra=='unit':
        old=state.units[0]
        f.patch.units=[UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields}).model_copy(update={'obligation_ids':[b.id]})]
    if extra=='binding':
        old=state.bindings[0];m=next(m for m in state.materials if m.file==old.file and m.start_line<=old.start_line<=old.end_line<=m.end_line)
        f.patch.bindings=[BindingDraft(id=old.id,associations=[dict(claim_id=b.id,source_ids=[m.id],rationale='Selected fixture operation')],material_id=m.id,symbol=old.symbol,start_line=old.start_line,end_line=old.end_line,description=old.description,pending=old.pending)]
    for name in ('claims','relations','bindings','units'):
        for obj in getattr(f.patch,name):f.patch.expected_versions[obj.id]=1
    from regression_support import declared_changes
    declared_changes(state,f)
    before=state.model_dump()
    with pytest.raises(ValueError,match='write set'):apply_feedback(state,state.units[0],f)
    assert state.model_dump()==before


def test_cross_type_collision_and_incomplete_changes_are_atomic(prepared):
    _, state, _ = prepared
    candidate=ClaimDraft(**{k:v for k,v in state.claims[0].model_dump().items() if k in ClaimDraft.model_fields})
    candidate.id=state.bindings[0].id
    before=state.model_dump()
    with pytest.raises(ValueError,match='types'):apply_patch(state,GraphPatch(claims=[candidate],expected_versions={candidate.id:1},rationale='Collision'),semantic=True)
    f=revision_for(state,[state.claims[1].id]);f.changes=[]
    with pytest.raises(ValueError,match='changes must'):apply_feedback(state,state.units[0],f)
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
    with pytest.raises(ValueError,match='F2'): apply_patch(state,patch)
    apply_patch(state,patch,semantic=True)
    assert state.claims[1].version==2 and state.claims[0].version==1
    assert state.graph_history[-1]['record']['description']==current.description
    with pytest.raises(ValueError,match='version'): apply_patch(state,patch,semantic=True)
