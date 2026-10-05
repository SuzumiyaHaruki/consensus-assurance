"""Reproduce the audited controller branches using actual project records."""
import pytest
from regression_support import dependency
from consensus_assurance.core.proposals import Feedback
from consensus_assurance.workflow.graph import apply_patch,expand_unit
from consensus_assurance.workflow.feedback import apply_feedback


def test_new_dependency_requires_executable_scope_continuation(dependency_prepared):
    state,patch,_=dependency(dependency_prepared);before=state.model_dump()
    with pytest.raises(ValueError):apply_patch(state,patch)
    assert state.model_dump()==before
    from consensus_assurance.workflow.scope_updates import from_patch,apply_scope_update
    update=from_patch(state,state.units[0],patch)
    new=apply_scope_update(state,update)
    assert 'fresh_provider' in new.binding_ids and new.obligation_ids==state.units[-1].obligation_ids


def test_F3_is_possible_before_first_check(dependency_prepared):
    _, state, _ = dependency_prepared;u=state.units[0]
    f=Feedback(kind='F3',rationale='Inspect an actual dependency before building',evidence_ids=[state.materials[0].id],target_ids=[u.id],relation_ids=['input_dependency'],new_basis='')
    result=apply_feedback(state,u,f)
    assert result.previous_id==u.id


def test_dependency_traversal_does_not_depend_on_list_order(dependency_prepared):
    _, state, _ = dependency_prepared;first=next(e for e in state.relations if e.id=='input_dependency')
    second=first.model_copy(deep=True);second.id='second_edge';second.source=first.target;second.target='input_binding'
    state.relations.insert(0,second)
    a=state.model_copy(deep=True);b=state.model_copy(deep=True);b.relations.reverse()
    x=expand_unit(a,a.units[0],[first.id,second.id]);y=expand_unit(b,b.units[0],[first.id,second.id])
    assert x.binding_ids==y.binding_ids and x.obligation_ids==y.obligation_ids
