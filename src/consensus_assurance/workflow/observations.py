"""Finite, non-evaluating event correlation and fully observed safety monitors."""
from consensus_assurance.core.proposals import EventRequirement
from consensus_assurance.core.types import ExecutionStatus, Origin, Investigation
from .graph import validate_grounding

MISSING = object()


def field(event, path):
    value = event
    for key in path.split('.'):
        if not isinstance(value,dict) or key not in value:
            return MISSING
        value = value[key]
    return value


def compare(event, condition, aliases=None):
    left = field(event,condition.field)
    right = condition.value
    if condition.reference:
        alias, sep, path = condition.reference.partition('.')
        if not sep or alias not in (aliases or {}): return None
        right = field(aliases[alias],path)
    if left is MISSING or right is MISSING: return None
    equal = type(left) is type(right) and left == right
    return equal if condition.op == 'eq' else not equal


def match_prerequisites(events, requirements):
    if not requirements:
        return {'status':'unknown','reason':'No correlated prerequisite specification','matched_indices':[]}
    requirements = [EventRequirement.model_validate(r) for r in requirements]
    if len({r.alias for r in requirements}) != len(requirements):
        return {'status':'unknown','reason':'Duplicate prerequisite aliases','matched_indices':[]}
    missing = False
    def search(position, step, aliases, indices):
        nonlocal missing
        if step == len(requirements): return indices
        req = requirements[step]
        for index in range(position,len(events)):
            event = events[index]
            if event.get('event') != req.event: continue
            checks = [compare(event,c,aliases) for c in req.conditions]
            if any(c is None for c in checks): missing = True; continue
            if not all(checks): continue
            result = search(index+1,step+1,{**aliases,req.alias:event},indices+[index])
            if result is not None: return result
        return None
    indices = search(0,0,{},[])
    return {'status':'matched' if indices is not None else 'unknown' if missing else 'not_reached',
        'reason':'Correlated event conditions established' if indices is not None else 'Missing fields' if missing else 'No correlated event sequence reached',
        'matched_indices':indices or []}


def monitor_events(events, monitor):
    results, missing = [], []
    for index,event in enumerate(events):
        if event.get('event') != monitor.event: continue
        selectors = [compare(event,c) for c in monitor.conditions]
        if any(x is None for x in selectors): missing.append(index); continue
        if not all(selectors): continue
        if any(field(event,p) is MISSING for p in monitor.identity_fields): missing.append(index); continue
        value = compare(event,monitor.assertion)
        if value is None: missing.append(index)
        else: results.append((index,value))
    violations = [index for index,value in results if value is False]
    return {'monitor_id':monitor.id,'checker_id':monitor.checker_id,
        'outcome':'violated' if violations else 'unknown' if missing or not results else 'holds',
        'witness_indices':violations,'missing_indices':missing,
        'reason':'Only explicitly observed scalar assertions are evaluated; hidden model states are not evidence'}


def assess_execution(state, model, bundle, experiment, calibration, finding, events):
    prerequisite = match_prerequisites(events,bundle.harness.prerequisites)
    specs = {c.invariant:c for c in model.checkers}
    results = [monitor_events(events,m) for m in bundle.monitors if m.checker_id == finding.checker_id]
    limitations = []
    if experiment.status != ExecutionStatus.COMPLETED or experiment.exit_code != 0: limitations.append('Experiment did not complete successfully')
    if experiment.snapshot_id != model.snapshot_id or experiment.model_id != model.id: limitations.append('Experiment input association mismatch')
    if experiment.input_versions != model.artifact_digests: limitations.append('Experiment artifact versions do not match')
    if state.mode == 'mock' or model.origin in {Origin.MOCK, Origin.SYNTHETIC, Origin.MUTATION} or experiment.origin != Origin.EXECUTED: limitations.append('Mock, synthetic, imported or mutation execution cannot confirm the original implementation')
    if not calibration or calibration.status != 'compatible' or calibration.model_id != model.id or calibration.experiment_check_id != experiment.id:
        limitations.append('Exact experiment has not completed code calibration')
    if prerequisite['status'] != 'matched': limitations.append('Candidate prerequisites are not established')
    spec = specs.get(finding.checker_id)
    claim = next((c for c in state.claims if spec and c.id == spec.claim_id),None)
    bases = [bundle.harness.legality] + ([claim.grounding] if claim else [])
    if not claim: limitations.append('Checker claim is unavailable')
    elif claim.pending: limitations.extend(claim.pending)
    if bundle.harness.semantic_changes: limitations.append('Instrumentation/adaptation changes require independent legality resolution')
    if bundle.uncertainties: limitations.extend(bundle.uncertainties)
    materials={m.id:m for m in state.materials}; bindings={b.id for b in state.bindings}
    for basis in bases:
        try: validate_grounding(basis,materials,bindings)
        except ValueError as exc: limitations.append(str(exc))
        limitations.extend(basis.unresolved+basis.conflicts)
    if not bundle.harness.legal_conditions: limitations.append('No observable legality conditions supplied')
    for condition in bundle.harness.legal_conditions:
        if not events or not all(compare(event,condition) is True for event in events): limitations.append('Legal execution condition is missing or violated in the observed execution: '+condition.field)
    confirmed = None
    for monitor,result in zip([m for m in bundle.monitors if m.checker_id==finding.checker_id],results):
        local=[]
        try: validate_grounding(monitor.grounding,materials,bindings)
        except ValueError as exc: local.append(str(exc))
        local.extend(monitor.grounding.unresolved+monitor.grounding.conflicts)
        if not monitor.binding_ids or not set(monitor.binding_ids)<=set(model.binding_ids): local.append('Observation monitor lacks selected code bindings')
        if not monitor.identity_fields: local.append('Observation lacks participant/operation/context identity requirements')
        if not monitor.applicability_conditions: local.append('No observable applicability conditions')
        for index in result['witness_indices']:
            if not all(compare(events[index],c) is True for c in monitor.applicability_conditions): local.append('Property applicability is not established at the observed violation')
        # A fully observed witness must belong to the actual correlated prerequisite operation.
        if result['witness_indices'] and not set(result['witness_indices']) & set(prerequisite['matched_indices']):
            local.append('Violation witness is not part of the correlated counterexample execution')
        result['limitations']=local
        if result['outcome']=='violated' and not local and not limitations: confirmed=result
    if not results: limitations.append('No supported monitor for this checker; trace compatibility is not property violation')
    if confirmed:
        finding.stage=Investigation.REPRODUCED
        finding.applicability='current'
        finding.level='implementation_goal' if claim.kind=='goal' else 'implementation_obligation'
        finding.claim_id=claim.id; finding.claim_version=claim.version
    else:
        finding.stage=Investigation.INCONCLUSIVE
    finding.replay_check_id=experiment.id
    record={'finding_id':finding.id,'experiment_check_id':experiment.id,'snapshot_id':model.snapshot_id,'model_id':model.id,
        'calibration_id':calibration.id if calibration else None,'prerequisites':prerequisite,'properties':results,
        'limitations':limitations,'level':finding.level,'confirmed':confirmed is not None,
        'claim_version':claim.version if claim else None,
        'checker_scope':spec.scope.model_dump(mode='json') if spec else None,
        'monitor_algorithm':'observed_scalar_assertion/1'}
    state.monitor_results.append(record)
    return record
