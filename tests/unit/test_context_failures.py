"""Reproduce the audited controller branches using actual project records."""
import pytest
from consensus_assurance.core.proposals import Feedback,GraphPatch,BindingDraft,RelationDraft,UnitDraft,ReviewReply
from consensus_assurance.core.types import ReviewIssue,SemanticCheck
from consensus_assurance.workflow.graph import apply_patch,expand_unit
from consensus_assurance.workflow.feedback import apply_feedback
from regression_support import ReadingPlan
from regression_support import add_reads
from consensus_assurance.workflow.errors import Blocked
from consensus_assurance.adapters.storage.snapshot import capture
from test_graph_mutations import controller


def dependency(dependency_prepared):
    repo,state,_,_=dependency_prepared
    (repo/'new_helper.py').write_text('def boundary(value):\n    return max(1, value)\n')
    state.snapshot=capture(repo)
    added=add_reads(state,repo,ReadingPlan(requests=[{'file':'new_helper.py','start_line':1,'end_line':2,'reason':'Read a previously absent provider'}],rationale='Actual new dependency'),__import__('consensus_assurance.core.config',fromlist=['Budget']).Budget())
    u=state.units[0];basis=state.relations[0].grounding.model_copy(deep=True)
    b=BindingDraft(id='fresh_provider',associations=[dict(claim_id=u.obligation_ids[0],source_ids=[added[0]],rationale='Selected fixture operation')],material_id=added[0],symbol='boundary',start_line=1,end_line=2,description='New supporting producer',pending=['Guarantee not checked'])
    edge=RelationDraft(id='fresh_dependency',source=u.obligation_ids[0],target=b.id,kind='boundary',group=None,rationale='The selected computation consumes the actual provider',pending=['Provider guarantee unverified'],grounding=basis)
    draft=UnitDraft(**{k:v for k,v in u.model_dump().items() if k in UnitDraft.model_fields})
    draft.binding_ids.append(b.id);draft.relation_ids.append(edge.id)
    return state,GraphPatch(bindings=[b],relations=[edge],units=[draft],expected_versions={u.id:u.version},rationale='Reconnect newly read producer'),added


def test_new_dependency_requires_executable_scope_continuation(dependency_prepared):
    state,patch,_=dependency(dependency_prepared);before=state.model_dump()
    with pytest.raises(ValueError):apply_patch(state,patch)
    assert state.model_dump()==before
    from consensus_assurance.workflow.scope_updates import from_patch,apply_scope_update
    update=from_patch(state,state.units[0],patch)
    new=apply_scope_update(state,update)
    assert 'fresh_provider' in new.binding_ids and new.obligation_ids==state.units[-1].obligation_ids


def test_F3_is_possible_before_first_model(dependency_prepared):
    _,state,_,_=dependency_prepared;u=state.units[0]
    f=Feedback(kind='F3',rationale='Inspect an actual dependency before building',evidence_ids=[state.materials[0].id],target_ids=[u.id],relation_ids=['input_dependency'],new_basis='',graph=None,bundle=None)
    result=apply_feedback(state,u,None,f)
    assert result.previous_id==u.id


def test_dependency_traversal_does_not_depend_on_list_order(dependency_prepared):
    _,state,_,_=dependency_prepared;first=next(e for e in state.relations if e.id=='input_dependency')
    second=first.model_copy(deep=True);second.id='second_edge';second.source=first.target;second.target='input_binding'
    state.relations.insert(0,second)
    a=state.model_copy(deep=True);b=state.model_copy(deep=True);b.relations.reverse()
    x=expand_unit(a,a.units[0],[first.id,second.id]);y=expand_unit(b,b.units[0],[first.id,second.id])
    assert x.binding_ids==y.binding_ids and x.obligation_ids==y.obligation_ids
