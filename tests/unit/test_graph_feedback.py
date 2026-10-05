import pytest
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.core.proposals import GraphDraft, Feedback, GraphPatch
from consensus_assurance.workflow.graph import apply_graph, expand_unit
from consensus_assurance.workflow.feedback import apply_feedback


def add_check(state):
    state.checks.append(CheckRun(id="observed", action="experiment", cwd="/tmp", snapshot_id=state.snapshot.id, status=ExecutionStatus.COMPLETED))


def test_F3_adds_actual_dependency_bindings(dependency_prepared):
    _, state, _  = dependency_prepared
    expanded = expand_unit(state, state.units[0], ["input_dependency"])
    assert expanded.binding_ids == ["step_binding", "input_binding"]
    assert expanded.obligation_ids == ["step_obligation"]
    assert 'input_binding' in expanded.binding_ids
    assert expanded.previous_id == "counter_unit"
    assert state.units[1].status == "revised"


def test_F3_rejects_unrelated_or_empty_expansion(dependency_prepared):
    _, state, _  = dependency_prepared
    with pytest.raises(ValueError): expand_unit(state, state.units[0], ["maps_input"])


def test_F2_requires_normative_basis_and_invalidates(dependency_prepared):
    _, state, responses  = dependency_prepared; add_check(state)
    revised = GraphDraft.model_validate(responses['graph'])
    revised.claims[1].description = "A refined obligation based on the documented caller responsibility"
    f = Feedback(kind="F2", rationale="Observed evidence requires a scoped revision", evidence_ids=["observed"],
        target_ids=[state.units[0].id], relation_ids=[], new_basis="The document assigns normalization to the caller")
    with pytest.raises(ValueError): apply_feedback(state, state.units[0], f)
    f.evidence_ids = [next(m.id for m in state.materials if m.file=='README.md')]
    f.patch = GraphPatch(claims=[revised.claims[1]],expected_versions={revised.claims[1].id:1},rationale=f.new_basis)
    f.target_ids = [revised.claims[1].id]
    f.old_judgment = state.claims[1].description
    f.new_judgment = revised.claims[1].description
    f.grounding = revised.claims[1].grounding.model_copy(deep=True)
    f.grounding.unresolved = []
    from regression_support import declared_changes
    declared_changes(state,f)
    apply_feedback(state, state.units[0], f)
    assert state.graph_version == 2
    assert state.revisions[-1].return_step == "understand"


def test_fake_binding_and_normative_inference_rejected(dependency_prepared):
    _, state, responses  = dependency_prepared
    graph = GraphDraft.model_validate(responses['graph'])
    graph.bindings[0].symbol = "nonexistent_symbol"
    with pytest.raises(ValueError): apply_graph(state, graph)
    graph = GraphDraft.model_validate(responses['graph'])
    graph.claims[0].grounding.derivation = ""
    with pytest.raises(ValueError): apply_graph(state, graph)


from consensus_assurance.core.types import Grounding


def test_code_derived_responsibilities_are_candidates(prepared):
    _, state, responses = prepared
    graph=GraphDraft.model_validate(responses['graph'])
    c=graph.claims[1]
    c.source_ids=['counter.py:1:10','limits.py:1:2']
    c.grounding=Grounding(source_ids=c.source_ids,binding_ids=['step_binding','input_binding'],
        derivation='The consumer assumes a positive limit and the producer must establish that precondition',
        applicability='Serial calls in the fixture',unresolved=['No direct documented contract; inferred responsibility'])
    apply_graph(state,graph)
    assert state.claims[1].candidate
    assert state.claims[1].grounding.unresolved
    c.grounding.binding_ids=['step_binding']
    apply_graph(state,graph)
    assert state.claims[1].candidate
    c.grounding.binding_ids=[]
    with pytest.raises(ValueError,match='located implementation binding'): apply_graph(state,graph)


def test_conflicting_F2_does_not_turn_error_into_optimization(prepared):
    from consensus_assurance.workflow.feedback import apply_feedback
    _, state, responses = prepared
    changed=GraphDraft.model_validate(responses['graph']).claims[1]
    changed.description='A weaker proposed obligation'
    basis=changed.grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=['The current interface still promises the stronger guarantee']
    f=Feedback(kind='F2',rationale='Proposed design tradeoff requires resolving contrary evidence',evidence_ids=[next(m.id for m in state.materials if m.file=='README.md')],target_ids=['step_obligation'],relation_ids=[],old_judgment=state.claims[1].description,new_judgment=changed.description,new_basis='Conflicting design notes',grounding=basis,patch=GraphPatch(claims=[changed],expected_versions={changed.id:1},rationale='Proposed change'))
    before=state.claims[1].model_dump()
    from regression_support import declared_changes
    declared_changes(state,f)
    assert apply_feedback(state,state.units[0],f) is None
    assert state.claims[1].model_dump()==before
    assert state.revisions[-1].status=='unresolved'
