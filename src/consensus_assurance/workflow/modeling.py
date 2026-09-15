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
    if reply.bundle is None:
        if not reply.gap.strip():
            raise ValueError('A missing model needs a concrete material or modeling gap')
        return
    if reply.requests:
        raise ValueError('Return a model or focused reading requests, not both')
    validate_bundle(state, unit, reply.bundle, implementation)
    if current is not None:
        if reply.encoding_revision and phase=='search':
            previous=next((m for m in state.models if m.id==reply.encoding_revision.old_model_id),None)
            if previous is None:raise ValueError('Encoding repair references an unavailable original model')
            from .encoding import validate_encoding
            validate_encoding(state,previous,current,reply.bundle,reply.encoding_revision)
        else:validate_technical_repair(current, reply.bundle, phase)


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
            if any(not any(x.requirement_id==r.id and x.status=='reachable' for x in reach) for r in requirements):complete=False
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
        for req in model.reachability_requirements:
            result=next((r for r in reversed(state.reachability_results) if r.model_id==model.id and r.requirement_id==req.id),None)
            if result is None or result.status!='reachable':limits.append('Trigger '+req.id+' is '+(result.status if result else 'unchecked'))
        cals=[c for c in state.calibrations if c.model_id==model.id]
        if not cals or cals[-1].status!='compatible':limits.append('Model '+model.id+' has no completed compatible implementation calibration')
    return limits
