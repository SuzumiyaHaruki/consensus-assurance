"""Finite, non-evaluating event correlation and fully observed safety monitors."""
from consensus_assurance.core.types import ExecutionStatus, Origin, Investigation
from .graph_diagnostics import validate_grounding

from consensus_assurance.core.events import MISSING, field, compare, match_prerequisites


def monitor_events(events, monitor, aliases=None):
    if monitor.property and monitor.property.kind == 'stable_support':
        return monitor_support(events, monitor)

    results, missing = [], []
    for index,event in enumerate(events):
        if event.get('event') != monitor.event: continue
        selectors = [compare(event,c) for c in monitor.conditions]
        if any(x is None for x in selectors): missing.append(index); continue
        if not all(selectors): continue
        if any(field(event,p) is MISSING for p in monitor.identity_fields): missing.append(index); continue
        value = compare(event,monitor.assertion,aliases)
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
    from .inquiry import semantic_limitations
    limitations = semantic_limitations(state,model)
    from pathlib import Path
    from consensus_assurance.core.proposals import Bundle
    try:
        stored = Bundle.model_validate_json(Path(model.bundle_path).read_text())
        if stored.model_dump(mode="json") != bundle.model_dump(mode="json"):
            limitations.append('Assessment bundle differs from the saved model input')
    except (ValueError, OSError):
        limitations.append('Saved model input is unavailable for correspondence checking')
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
    if claim and (finding.claim_id != claim.id or model.graph_versions.get(claim.id) != claim.version):
        limitations.append('Finding or claim version differs from the checked model')
    from .instrumentation import observation_change_limitations
    limitations.extend(observation_change_limitations(bundle.harness, model.binding_ids))
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
        from consensus_assurance.adapters.verifiers.observable import correspondence
        mismatch = correspondence(bundle, monitor)
        if mismatch: local.append(mismatch)
        if monitor.property and monitor.property.kind == 'stable_support':
            history = []
            p = monitor.property
            for event in events:
                if event.get('event') == monitor.event:
                    history.append({key:field(event,key) for key in p.identity_fields + [p.trigger.field,p.assertion.field]})
                observed = field(event,p.history_field)
                if observed is MISSING or observed != history or any(v is MISSING for item in history for v in item.values()):
                    local.append('Complete observed support history does not match actual events')
                    break
        try: validate_grounding(monitor.grounding,materials,bindings)
        except ValueError as exc: local.append(str(exc))
        local.extend(monitor.grounding.unresolved+monitor.grounding.conflicts)
        if not monitor.binding_ids or not set(monitor.binding_ids)<=set(model.binding_ids): local.append('Observation monitor lacks selected code bindings')
        if not monitor.identity_fields: local.append('Observation lacks participant/operation/context identity requirements')
        if not monitor.applicability_conditions: local.append('No observable applicability conditions')
        for index in result['witness_indices']:
            if not all(compare(events[index],c) is True for c in monitor.applicability_conditions): local.append('Property applicability is not established at the observed violation')
        # A fully observed witness must belong to the actual correlated prerequisite operation.
        if result['witness_indices'] and not set(result['witness_indices']) <= set(prerequisite['matched_indices']):
            local.append('Violation witness is not part of the correlated counterexample execution')
        if claim and any(g.claim_id==claim.id for g in bundle.consequence_observations):
            mapping=next((g for g in bundle.consequence_observations if g.claim_id==claim.id),None)
            local.extend(consequence_witness_limitations(mapping,events,result['witness_indices']))
            if mapping:
                try:validate_grounding(mapping.grounding,materials,bindings)
                except ValueError as exc:local.append(str(exc))
                local.extend(mapping.grounding.unresolved+mapping.grounding.conflicts)
                if not mapping.binding_ids or not set(mapping.binding_ids)<=set(model.binding_ids):local.append('Consequence observation mapping lacks selected source bindings')
        result['limitations']=local
        if result['outcome']=='violated' and not local and not limitations: confirmed=result
    if not results: limitations.append('No supported monitor for this checker; trace compatibility is not property violation')
    if confirmed:
        finding.stage=Investigation.REPRODUCED
        finding.applicability='current'
        finding.level='implementation_obligation'
        finding.claim_id=claim.id; finding.claim_version=claim.version
    else:
        finding.stage=Investigation.INCONCLUSIVE
        finding.level="model_candidate"
    finding.replay_check_id=experiment.id
    record={'finding_id':finding.id,'experiment_check_id':experiment.id,'snapshot_id':model.snapshot_id,'model_id':model.id,
        'calibration_id':calibration.id if calibration else None,'prerequisites':prerequisite,'properties':results,
        'limitations':limitations,'level':finding.level,'confirmed':confirmed is not None,
        'claim_version':claim.version if claim else None,
        'checker_scope':spec.scope.model_dump(mode='json') if spec else None,
        'monitor_algorithm':'shared_observable_property/2'}
    state.monitor_results.append(record)
    return record


def monitor_support(events, monitor):
    p = monitor.property
    seen, violations, missing = [], [], []
    for index, event in enumerate(events):
        if event.get('event') != monitor.event:
            continue
        active = compare(event,p.trigger)
        keys = [field(event,k) for k in p.identity_fields]
        obj = field(event,p.assertion.field)
        if active is None or any(v is MISSING for v in keys) or obj is MISSING:
            missing.append(index); continue
        if not active: continue
        for old_keys, old_obj, old_index in seen:
            if all(type(a) is type(b) and a==b for a,b in zip(keys,old_keys)) and not (type(obj) is type(old_obj) and obj==old_obj):
                violations.extend([old_index,index])
        seen.append((keys,obj,index))
    return {'monitor_id':monitor.id,'checker_id':monitor.checker_id,
        'outcome':'violated' if violations else 'unknown' if missing or not seen else 'holds',
        'witness_indices':sorted(set(violations)), 'missing_indices':missing,
        'reason':'Compare effective support objects for the same observed identity/context across ordered events'}


def consequence_witness_limitations(mapping,events,indices):
    if mapping is None or not mapping.identity_fields or not mapping.witness_events:
        return ['Consequence witness lacks explicit correlated participants, events and identity fields']
    limitations=[]
    for index in indices:
        witness=events[index];ids=[field(witness,key) for key in mapping.identity_fields]
        matched=[e for e in events[:index+1] if all(field(e,k)==v and v is not MISSING for k,v in zip(mapping.identity_fields,ids))]
        if any(not any(e.get('participant')==r.participant and e.get('event')==r.event for e in matched) for r in mapping.witness_events):limitations.append('Consequence events do not belong to the actual violating operation/context history')
        if not set(mapping.required_participants)<={r.participant for r in mapping.witness_events} or not set(mapping.required_events)<={r.event for r in mapping.witness_events}:limitations.append('Consequence witness plan does not account for its declared observation requirements')
    return limitations
