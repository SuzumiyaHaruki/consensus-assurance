"""Continue saved model components without inventing implementation observations."""
from consensus_assurance.core.proposals import Bundle, HarnessReply, BuildReply
from consensus_assurance.core.types import CheckRun, ExecutionStatus, now
from .artifacts import validate_bundle
from .errors import Blocked


def assemble(state, unit, draft, reply, implementation):
    if reply.harness is None or reply.observation is None:
        if reply.harness is not None or reply.observation is not None:
            raise ValueError('Return both executable harness and observation map, or a specific assembly gap')
        if not reply.gap.strip():
            raise ValueError('Missing implementation components require a concrete gap')
        return None
    if reply.requests:
        raise ValueError('Return completed assembly or material requests, not both')
    data=draft.model_dump(mode='json', exclude={'pending_work'})
    data.update(harness=reply.harness, observation=reply.observation,
                monitors=reply.monitors, consequence_observations=reply.consequence_observations)
    bundle=Bundle.model_validate(data)
    validate_bundle(state, unit, bundle, implementation)
    return bundle


def proceed(engine, unit, model, draft, phase):
    if phase == 'model_syntax':
        core=[work for work in draft.pending_work if work.component in {'behavior','properties'}]
        if core:
            requests=[r for work in core for r in work.requests]
            if not requests:
                raise Blocked('Saved draft has unresolved core behavior/property dependencies: '+ '; '.join(w.reason for w in core))
            engine.targeted_read(unit, '; '.join(w.reason for w in core), requests=requests)
            engine.advance('build')
            return
        if not hasattr(engine.verifier, 'syntax'):
            raise Blocked('Saved model requires a verifier with a syntax-check capability')
        check=CheckRun.model_validate(engine.action('model_syntax', 'model_checks',
            lambda:engine.verifier.syntax(engine.runner, model, engine.budget.timeout()), {'model_id':model.id}))
        engine.record(check)
        if check.status != ExecutionStatus.COMPLETED:
            if check.reason!='Model syntax error':
                raise Blocked('Saved model syntax check incomplete: '+check.status.value+'; '+check.reason)
            # The failed bytes and raw output remain the current model, never a completed search.
            engine.state.pending_feedback={'technical_phase':'search','check_id':check.id}
            engine.advance('model_repair')
            return
        engine.state.milestones.setdefault('model_parsed', now())
        engine.advance('model_explore')
    elif phase == 'model_repair':
        if not engine.state.pending_action or not engine.state.pending_action.kind.startswith('agent:technical'):
            engine.budget.take('technical_repairs')
        from .modeling import validate_build_reply
        failure=next(c for c in engine.state.checks if c.id==engine.state.pending_feedback['check_id'])
        reply,_=engine.ask('technical', BuildReply, {**engine.context(unit), 'draft':draft.model_dump(mode='json'),
            'failure':engine.error_context(failure), 'model_id':model.id},
            lambda p:validate_build_reply(engine.state,unit,p,engine.implementation,draft,'search'))
        if reply.draft is None and reply.bundle is None:
            engine.targeted_read(unit,reply.gap,requests=reply.requests,update_required=reply.reading_purpose=='dependency')
            engine.advance('model_repair')
            return
        repaired=reply.draft or reply.bundle
        reason='Encoding correction: '+reply.encoding_revision.rationale if reply.encoding_revision else 'Bounded syntax repair; property text preserved'
        revised=engine.save_model(unit,repaired,model,reason)
        engine.state.active_model_id=revised.id
        engine.advance('model_syntax' if reply.draft else 'experiment' if engine.config.allow_experiments else 'search')
    elif phase == 'model_explore':
        check=engine.search(unit, model, draft, None)
        if check.status != ExecutionStatus.COMPLETED:
            if check.reason=='Model syntax error':
                engine.state.pending_feedback={'technical_phase':'search','check_id':check.id}
                engine.advance('model_repair');return
            raise Blocked('Uncalibrated model search remains incomplete: '+check.reason)
        if check.outcome not in {'holds','counterexample'}:
            raise Blocked('Saved model search is diagnostic only: '+check.outcome)
        engine.state.gaps.append('Model-only result '+model.id+' has no implementation calibration; pending harness and observation assembly')
        engine.advance('harness')
    elif phase == 'harness':
        if engine.implementation is None:raise Blocked('Implementation calibration unavailable: no execution backend configured; local search retained')
        if engine.state.targeted_gap:
            gap=engine.state.targeted_gap
            engine.targeted_read(unit,gap['gap'],requests=gap.get('requests'),update_required=False)
        requests=[r for work in draft.pending_work if work.component in {'harness','observation'} for r in work.requests]
        from .sources import ranges
        supplied=[m for m in engine.state.materials if m.id in engine.state.task_attachments.get('unit:'+unit.id,[])]
        spans=ranges(supplied)
        needed=[r for r in requests if not any(file==r.file and any(a<=r.start_line<=r.end_line<=z for a,z in parts) for (file,version),parts in spans.items())]
        if needed:
            engine.targeted_read(unit,'Complete the saved model implementation experiment',requests=needed,update_required=False)
        reply,_=engine.ask('harness',HarnessReply,{**engine.context(unit),
            'model_id':model.id,'model_stage':model.stage,'model_components':draft.model_dump(mode='json'),
            'allowed_delta':'Complete harness and observation only; behavior, properties and scope remain unchanged'},
            lambda r:assemble(engine.state,unit,draft,r,engine.implementation))
        bundle=assemble(engine.state,unit,draft,reply,engine.implementation)
        if bundle is None:
            engine.targeted_read(unit,reply.gap,requests=reply.requests,update_required=False)
            engine.advance('harness')
            return
        completed=engine.save_model(unit,bundle,model,'Complete implementation components; preserve model search inputs')
        engine.state.active_model_id=completed.id
        engine.state.milestones.setdefault('harness_ready',now())
        engine.advance('experiment' if engine.config.allow_experiments else 'search')
