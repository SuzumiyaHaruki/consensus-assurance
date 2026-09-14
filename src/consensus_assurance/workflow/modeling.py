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
        validate_technical_repair(current, reply.bundle, phase)


def obligation_progress(state, unit):
    # Track every planned scoped checker, even if a later bundle omits one of them.
    import json
    expected = {claim:set() for claim in unit.obligation_ids}
    completed = {claim:{} for claim in unit.obligation_ids}
    versions = {c.id:c.version for c in state.claims}
    def key(spec):
        return spec.invariant, json.dumps(spec.scope.model_dump(mode="json"),sort_keys=True)
    for model in state.models:
        if model.unit_id != unit.id:
            continue
        stale = any(e.model_id == model.id and e.applicability == 'recheck_required' for e in state.evidence)
        if stale:
            continue
        for claim in unit.obligation_ids:
            specs = [s for s in model.checkers if s.claim_id == claim]
            if not specs or model.graph_versions.get(claim) != versions.get(claim):
                continue
            expected[claim].update(key(s) for s in specs)
            for check in state.checks:
                if check.model_id != model.id or check.action != 'model_check' or check.status.value != 'completed':
                    continue
                results = {r.invariant:r for r in check.checker_results}
                for spec in specs:
                    result = results.get(spec.invariant)
                    if result and result.claim_id == claim and result.scope == spec.scope and result.outcome in {'holds','violated'}:
                        completed[claim].setdefault(key(spec),[]).append(check.id)
    covered = {claim:list(dict.fromkeys(check for ids in completed[claim].values() for check in ids))
        for claim in unit.obligation_ids if expected[claim] and expected[claim] <= set(completed[claim])}
    return covered, [claim for claim in unit.obligation_ids if claim not in covered]
