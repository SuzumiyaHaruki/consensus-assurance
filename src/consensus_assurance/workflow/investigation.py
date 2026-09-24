"""Investigation input assembly and bounded result disposition."""
from .feedback import apply_feedback
from .artifacts import validate_bundle


def validate_feedback(state, unit, bundle, feedback, implementation, requested_kind):
    if feedback.kind == "unresolved":
        if not feedback.rationale.strip(): raise ValueError("Unresolved feedback needs a concrete limitation")
        return
    if feedback.requests:
        if not feedback.rationale.strip():
            raise ValueError('Reading requests require a concrete investigation gap')
        return
    if requested_kind in {'F1','F4'} and feedback.kind != requested_kind:
        raise ValueError('Feedback attempts to change a different semantic object')
    if feedback.bundle:
        feedback.bundle=validate_bundle(state,unit,feedback.bundle,implementation)
    copied = state.model_copy(deep=True)
    copied_unit = next(u for u in copied.units if u.id == unit.id)
    apply_feedback(copied,copied_unit,bundle,feedback)


def validate_replay(state, unit, bundle, finding, plan, implementation):
    if plan.checker_id != finding.checker_id:
        raise ValueError('Replay plan targets another checker')
    revised = bundle.model_copy(deep=True)
    revised.harness = plan.harness
    if plan.monitors is not None:
        revised.monitors = plan.monitors
    if plan.observation is not None:
        revised.observation = plan.observation
    validate_bundle(state,unit,revised,implementation)
    return revised
