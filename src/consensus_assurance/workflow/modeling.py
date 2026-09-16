"""Pure model acceptance and execution coverage policies."""
from .artifacts import validate_bundle


def validate_technical_repair(current, repaired, phase):
    if repaired.checker_specs() != current.checker_specs() or repaired.scope != current.scope:
        raise ValueError('Technical repair changed property scope or attribution; semantic revision required')
    if repaired.properties != current.properties or repaired.observable_properties != current.observable_properties:
        raise ValueError('Technical repair cannot change property text, even with identical checker IDs; use explicit semantic investigation')
    if phase != 'search':
        left, right = current.model_dump(), repaired.model_dump()
        left.pop('harness'); right.pop('harness')
        if left != right:
            raise ValueError('Compilation repair may change only the harness')


def validate_build_reply(state, unit, reply, implementation, current=None, phase=None):
    if reply.bundle is not None and reply.draft is not None:
        raise ValueError('Return one complete bundle or one staged model, not competing artifacts')
    model=reply.draft or reply.bundle
    if model is None:
        if not reply.gap.strip():
            raise ValueError('A missing model needs a concrete material or modeling gap')
        return
    if reply.requests:
        raise ValueError('Return a model or focused reading requests; stage missing-component requests under pending_work')
    validate_bundle(state,unit,model,implementation)
    if reply.draft is not None:
        if not {'harness','observation'} <= {p.component for p in reply.draft.pending_work}:
            raise ValueError('Model-only output must acknowledge missing harness and observation components')
        from consensus_assurance.core.proposals import ModelDraft
        if current is not None and not isinstance(current,ModelDraft):
            raise ValueError('Technical repair cannot discard an existing harness or observation map')
    if current is not None:
        if reply.encoding_revision and phase=='search':
            previous=next((m for m in state.models if m.id==reply.encoding_revision.old_model_id),None)
            if previous is None:raise ValueError('Encoding repair references an unavailable original model')
            from .encoding import validate_encoding
            validate_encoding(state,previous,current,model,reply.encoding_revision)
        else:validate_technical_repair(current,model,phase)


def obligation_progress(state, unit):
    import json
    expected={claim:{} for claim in unit.obligation_ids}
    versions={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units]}
    for model in state.models:
        if model.unit_id!=unit.id:continue
        if any(versions.get(k)!=v for k,v in model.graph_versions.items()):continue
        if any(e.model_id==model.id and e.applicability=='recheck_required' for e in state.evidence):continue
        for spec in model.checkers:
            if spec.claim_id in expected:
                expected[spec.claim_id][(spec.invariant,json.dumps(spec.scope.model_dump(mode='json'),sort_keys=True))]=(model,spec)
    covered={}
    for claim,slots in expected.items():
        ids=[]; complete=bool(slots)
        for model,spec in slots.values():
            checks=[c for c in state.checks if c.model_id==model.id and c.action=='model_check']
            check=checks[-1] if checks else None
            valid=bool(check and model.search_fingerprint and check.search_fingerprint==model.search_fingerprint and check.status.value=='completed')
            if valid and check.reused_from:
                source=next((c for c in state.checks if c.id==check.reused_from),None)
                valid=bool(source and source.search_fingerprint==check.search_fingerprint and source.status.value=='completed')
            result=next((r for r in check.checker_results if r.invariant==spec.invariant and r.claim_id==claim and r.scope==spec.scope),None) if valid else None
            requirements=[r for r in model.reachability_requirements if claim in r.claim_ids]
            points=unit.coverage_intent+(unit.audit_question.points if unit.audit_question else [])
            if any(claim in p.claim_ids and not any(p.id in r.point_ids and (not p.sequence_required or bool(r.sequence)) for r in requirements) for p in points):complete=False
            reach=[r for r in state.reachability_results if r.model_id==model.id and r.search_fingerprint==model.search_fingerprint]
            latest={x.requirement_id:x for x in reach}
            if any(r.id not in latest or latest[r.id].status!='reachable' for r in requirements):complete=False
            if not result or result.outcome not in {'holds','violated'}:complete=False
            else:ids.append(check.id)
        if complete:covered[claim]=list(dict.fromkeys(ids))
    return covered,[c for c in unit.obligation_ids if c not in covered]


def coverage_limitations(state,unit):
    limits=[]
    models=[m for m in state.models if m.unit_id==unit.id]
    if not unit.audit_question:limits.append('Audit question is not structured; effective interaction coverage is unestablished')
    for point in unit.coverage_intent+(unit.audit_question.points if unit.audit_question else []):
        if not any(point.id in r.point_ids and (not point.sequence_required or bool(r.sequence)) for m in models for r in m.reachability_requirements):
            limits.append('No executable trigger requirement covers point '+point.id)
    for model in models:
        import json
        from pathlib import Path
        data=json.loads(Path(model.bundle_path).read_text()) if Path(model.bundle_path).is_file() else {}
        if not data.get('context_analysis'):limits.append('Context/history correspondence was not supplied; no cross-context coverage claim')
        for req in model.reachability_requirements:
            result=next((r for r in reversed(state.reachability_results) if r.model_id==model.id and r.requirement_id==req.id),None)
            if result is None or result.status!='reachable':limits.append('Trigger '+req.id+' is '+(result.status if result else 'unchecked'))
        cals=[c for c in state.calibrations if c.model_id==model.id]
        if not cals or cals[-1].status!='compatible':limits.append('Model '+model.id+' has no completed compatible implementation calibration')
    return limits


def check_triggers(engine,model,bundle):
    from consensus_assurance.core.types import ReachabilityResult, CheckRun
    for req in bundle.reachability:
        while True:
            prior=[r for r in engine.state.reachability_results if r.model_id==model.id and r.requirement_id==req.id and r.search_fingerprint==model.search_fingerprint]
            if prior and prior[-1].status in {'reachable','unreachable'}:break
            last=next((c for c in engine.state.checks if prior and c.id==prior[-1].check_id),None)
            retryable=not prior or (last is not None and last.status.value in {'timeout','error'})
            allowed=retryable and len(prior)<=engine.config.budget.trigger_retries
            task=next((t for t in engine.state.trigger_retry_tasks if t['model_id']==model.id and t['requirement_id']==req.id and t['search_fingerprint']==model.search_fingerprint),None)
            if task is None:
                task={'model_id':model.id,'requirement_id':req.id,'search_fingerprint':model.search_fingerprint,'attempts':[]}
                engine.state.trigger_retry_tasks.append(task)
            task['status']='pending' if allowed else 'blocked'
            task['reason']='Bounded retry of incomplete tool execution' if allowed else 'Retry limit reached or failure needs a tool/input change'
            if not allowed:break
            engine.checkpoint('trigger_attempt_pending')
            result=engine.action("reachability:"+req.id,"reachability_checks",lambda:engine.verifier.reachability(engine.runner,model,bundle,req,engine.budget.timeout()),{"model_id":model.id,"requirement":req.model_dump(mode='json'),"search_fingerprint":model.search_fingerprint,"attempt":len(prior)+1})
            record=ReachabilityResult.model_validate(result[0]);check=CheckRun.model_validate(result[1])
            if not any(r.check_id==record.check_id for r in engine.state.reachability_results):engine.state.reachability_results.append(record)
            if check.id not in task['attempts']:task['attempts'].append(check.id)
            task['status']=record.status
            engine.record(check)
            engine.advance("triggers")
