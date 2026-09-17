import copy
import pytest
from consensus_assurance.core.types import AuditUnit, CheckRun, ExecutionStatus, Calibration, Origin
from consensus_assurance.core.proposals import Discovery, Feedback, GraphPatch
from consensus_assurance.workflow.graph import apply_discovery, select_unit, expand_unit
from consensus_assurance.workflow.feedback import apply_feedback


def feedback(state, kind, bundle=None, graph=None, evidence=None, **kwargs):
    return Feedback(kind=kind, rationale="Observed evidence requires a scoped revision", evidence_ids=evidence or ["observed"],
        target_ids=[state.units[0].id], relation_ids=kwargs.get("relation_ids", []), new_basis=kwargs.get("new_basis", ""), graph=graph, bundle=bundle)


def add_check(state):
    state.checks.append(CheckRun(id="observed", action="experiment", cwd="/tmp", snapshot_id=state.snapshot.id, status=ExecutionStatus.COMPLETED))


def test_relation_changes_selection(prepared):
    _, state, _, _ = prepared
    producer = state.units[0].model_copy(deep=True)
    producer.id = "producer_unit"; producer.obligation_ids = ["input_obligation"]; producer.binding_ids = ["input_binding"]
    producer.relation_ids = ["supports_input", "maps_input"]
    state.units.append(producer)
    without = state.model_copy(deep=True)
    without.relations = [e for e in without.relations if e.id != "input_dependency"]
    assert select_unit(without).id == "counter_unit"
    assert select_unit(state).id == "producer_unit"
    assert "input_dependency" in state.selections[-1]["relation_ids"]


def test_F3_adds_actual_dependency_bindings(prepared):
    _, state, _, _ = prepared
    expanded = expand_unit(state, state.units[0], ["input_dependency"])
    assert expanded.binding_ids == ["step_binding", "input_binding"]
    assert expanded.obligation_ids == ["step_obligation"]
    assert any(u.binding_id=="input_binding" and u.role=="support" for u in expanded.code_uses)
    assert expanded.previous_id == "counter_unit"
    assert state.units[1].status == "revised"


def test_F3_rejects_unrelated_or_empty_expansion(prepared):
    _, state, _, _ = prepared
    with pytest.raises(ValueError): expand_unit(state, state.units[0], ["maps_input"])


def test_F1_preserves_property(prepared):
    _, state, bundle, _ = prepared; add_check(state)
    changed = bundle.model_copy(deep=True)
    changed.observation.max_internal_steps = 4
    result = apply_feedback(state, state.units[0], bundle, feedback(state, "F1", changed))
    assert result.observation.max_internal_steps == 4
    assert state.revisions[-1].return_step == "build"
    changed.properties += "\nWeakened == TRUE"
    with pytest.raises(ValueError): apply_feedback(state, state.units[0], bundle, feedback(state, "F1", changed))


def test_F2_requires_normative_basis_and_invalidates(prepared):
    _, state, bundle, responses = prepared; add_check(state)
    revised = Discovery.model_validate(responses[1])
    revised.claims[1].description = "A refined obligation based on the documented caller responsibility"
    f = feedback(state, "F2", graph=revised, new_basis="The document assigns normalization to the caller")
    with pytest.raises(ValueError): apply_feedback(state, state.units[0], bundle, f)
    f.evidence_ids = [next(m.id for m in state.materials if m.file=='README.md')]
    f.graph = None
    f.patch = GraphPatch(claims=[revised.claims[1]],expected_versions={revised.claims[1].id:1},rationale=f.new_basis)
    f.target_ids = [revised.claims[1].id]
    f.old_judgment = state.claims[1].description
    f.new_judgment = revised.claims[1].description
    f.grounding = revised.claims[1].grounding.model_copy(deep=True)
    f.grounding.unresolved = []
    state.calibrations.append(Calibration(model_id="old", experiment_check_id="observed", mapping_path="mapping", trace_path="trace", status="compatible", reason="Previous match", origin=Origin.MOCK))
    from regression_support import declared_changes
    declared_changes(state,f)
    apply_feedback(state, state.units[0], bundle, f)
    assert state.graph_version == 2
    assert state.calibrations[0].status == "compatible"  # Unrelated historical calibration survives.
    assert state.revisions[-1].return_step == "understand"


def test_F4_changes_only_experiment(prepared):
    _, state, bundle, _ = prepared; add_check(state)
    changed = bundle.model_copy(deep=True)
    changed.harness.prerequisite_events = ["started", "context_changed", "completed"]
    apply_feedback(state, state.units[0], bundle, feedback(state, "F4", changed))
    assert state.revisions[-1].return_step == "experiment"
    changed.behavior += "\nExtra == TRUE"
    with pytest.raises(ValueError): apply_feedback(state, state.units[0], bundle, feedback(state, "F4", changed))


def test_fake_binding_and_normative_inference_rejected(prepared):
    _, state, _, responses = prepared
    graph = Discovery.model_validate(responses[1])
    graph.bindings[0].symbol = "nonexistent_symbol"
    with pytest.raises(ValueError): apply_discovery(state, graph)
    graph = Discovery.model_validate(responses[1])
    graph.claims[0].grounding.derivation = ""
    with pytest.raises(ValueError): apply_discovery(state, graph)
