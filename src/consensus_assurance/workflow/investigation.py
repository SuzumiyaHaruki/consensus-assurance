"""Investigation input assembly and bounded result disposition."""
from .feedback import apply_feedback
from .artifacts import validate_bundle


def feedback_context(engine, unit, model, bundle, experiment, calibration, finding):
    search = next((c for c in engine.state.checks if finding and c.id == finding.check_id), None)
    calibration_checks = [c for c in engine.state.checks if calibration and c.id in calibration.check_ids]
    from consensus_assurance.adapters.runners.experiment import extract_events
    return {**engine.context(unit), 'bundle':bundle.model_dump(mode='json'), 'model_id':model.id,
        'calibration':calibration.model_dump(mode='json') if calibration else None,
        'calibration_outputs':[engine.error_context(c) for c in calibration_checks],
        'candidate_trace':engine.error_context(search) if search else {'missing':True,'reason':'No model counterexample execution is linked'},
        'experiment':engine.error_context(experiment) if experiment else None,
        'events':extract_events(experiment) if experiment else [],
        'finding':finding.model_dump(mode='json') if finding else None,
        'last_assessment':next((r for r in reversed(engine.state.monitor_results) if finding and r['finding_id']==finding.id),None)}


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


def record_consequence(engine, unit, finding):
    if any(c['finding_id']==finding.id for c in engine.state.consequences):return
    child=next((c for c in engine.state.question_candidates if c.obligation_id in unit.obligation_ids),None)
    parent=next((c for c in engine.state.question_candidates if child and c.id==child.parent_candidate_id),None)
    reason=('The existing parent candidate retains this broader discriminator; the child result is projected there without creating a duplicate inquiry task' if parent else
        'The bounded obligation result is retained for ordinary candidate reselection; broader consequence needs a distinct sourced question')
    engine.state.consequences.append({'finding_id':finding.id,
        'disposition':'defer','reason':reason,'source_ids':unit.audit_question.source_ids if unit.audit_question else [],'task_ids':[], 'parent_candidate_id':parent.id if parent else None,
        'limitations':['Only the evidenced obligation-level result is reported; broader consequence is unestablished']})
