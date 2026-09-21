"""Investigation input assembly and side-effect-free feedback acceptance."""
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


def consequence_needed(unit, finding):
    return finding.level=='implementation_obligation'


def validate_consequence(state, unit, reply):
    from .graph import validate_patch
    if not set(reply.source_ids)<={m.id for m in state.materials} or not reply.rationale.strip():
        raise ValueError('Consequence plan must cite actual material and broader obligations')
    if reply.disposition=='investigate' and not reply.requests and not reply.patch:
        raise ValueError('Consequence investigation needs a bounded reading or joint-unit plan')
    if reply.patch:
        if not reply.patch.units:raise ValueError('Joint consequence scope needs an explicit unit')
        for new in reply.patch.units:
            if not new.audit_question or set(new.obligation_ids)&set(unit.obligation_ids):
                raise ValueError('Joint unit must explain the broader obligation and actual audit question')
        validate_patch(state,reply.patch)


def record_consequence(engine, unit, finding, reply=None, reason=''):
    from .inquiry import enqueue
    from .graph import apply_patch
    if any(c['finding_id']==finding.id for c in engine.state.consequences):return
    if reply and reply.patch:apply_patch(engine.state,reply.patch)
    tasks=[]
    if reply and reply.requests:
        task=enqueue(engine.state,'spec_refine','Investigate local-to-broader obligation consequences and compensation: '+reply.rationale,'consequence:'+finding.id,target_ids=unit.obligation_ids,unit_id=unit.id,model_id=finding.model_id,requests=reply.requests)
        tasks.append(task.id)
    engine.state.consequences.append({'finding_id':finding.id,
        'disposition':reply.disposition if reply else 'defer','reason':reply.rationale if reply else reason,'source_ids':reply.source_ids if reply else [],'task_ids':tasks,
        'limitations':reply.limitations if reply else ['Only the evidenced obligation-level result is reported; broader consequence is unestablished']})
