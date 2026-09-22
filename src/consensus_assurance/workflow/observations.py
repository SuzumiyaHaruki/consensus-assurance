"""Finite, non-evaluating event correlation and fully observed safety monitors."""
from consensus_assurance.core.types import ExecutionStatus, Origin, Investigation
from .graph_diagnostics import validate_grounding

from consensus_assurance.core.events import MISSING, field, compare, match_prerequisites


def monitor_events(events, monitor, prop, requirements=None):
    if prop is None:
        return {'monitor_id':monitor.id,'checker_id':monitor.checker_id,'outcome':'unknown',
            'witness_indices':[],'missing_indices':[],'reason':'No shared observable property'}
    results, missing, correlations, outside = [], [], {}, []
    for index,event in enumerate(events):
        if event.get('event') != monitor.event: continue
        active = compare(event,prop.trigger)
        if active is False: continue
        if active is None or any(field(event,k) is MISSING for k in prop.identity_fields):
            missing.append(index); continue
        aliases = {}
        if requirements is not None:
            linked = match_prerequisites(events,requirements,index,prop.identity_fields)
            correlations[str(index)] = linked
            if linked['status']!='matched': missing.append(index); continue
            aliases = {alias:events[i] for alias,i in linked['alias_indices'].items()}
        applicability=[compare(event,c,aliases) for c in monitor.applicability_conditions]
        if any(value is None for value in applicability):
            missing.append(index); continue
        if any(value is False for value in applicability):
            outside.append(index); continue
        value = compare(event,prop.assertion,aliases) if prop.kind=='event_assertion' else True
        if value is None: missing.append(index)
        else: results.append((index,value))
    violations = [index for index,value in results if value is False]
    if prop.kind=='stable_support':
        support = monitor_support(events,monitor,prop,{index for index,_ in results})
        violations = support['witness_indices']; missing.extend(support['missing_indices'])
    return {'monitor_id':monitor.id,'checker_id':monitor.checker_id,
        'outcome':'violated' if violations else 'unknown' if missing or not results else 'holds',
        'witness_indices':violations,'missing_indices':sorted(set(missing)),
        'evaluated_indices':[index for index,value in results],'outside_applicability_indices':outside,'correlations':correlations,
        'reason':'Actual result fields are compared after independent prerequisite association'}


def assess_execution(state, model, bundle, experiment, calibration, finding, events):
    prerequisite = match_prerequisites(events,bundle.harness.prerequisites)
    specs = {c.invariant:c for c in model.checkers}
    properties={p.checker_id:p for p in bundle.observable_properties}
    results = [monitor_events(events,m,properties.get(m.checker_id),bundle.harness.prerequisites) for m in bundle.monitors if m.checker_id == finding.checker_id]
    from .inquiry import semantic_limitations
    blockers = semantic_limitations(state,model)
    boundaries=list(bundle.uncertainties)
    from pathlib import Path
    from consensus_assurance.core.proposals import Bundle
    try:
        stored = Bundle.model_validate_json(Path(model.bundle_path).read_text())
        if stored.model_dump(mode="json") != bundle.model_dump(mode="json"):
            blockers.append('Assessment bundle differs from the saved model input')
    except (ValueError, OSError):
        blockers.append('Saved model input is unavailable for correspondence checking')
    if experiment.status != ExecutionStatus.COMPLETED or experiment.exit_code != 0: blockers.append('Experiment did not complete successfully')
    if experiment.snapshot_id != model.snapshot_id or experiment.model_id != model.id: blockers.append('Experiment input association mismatch')
    if experiment.input_versions != model.artifact_digests: blockers.append('Experiment artifact versions do not match')
    if state.mode == 'mock' or model.origin in {Origin.MOCK, Origin.SYNTHETIC, Origin.MUTATION} or experiment.origin != Origin.EXECUTED: blockers.append('Mock, synthetic, imported or mutation execution cannot confirm the original implementation')
    if not calibration or calibration.status != 'compatible' or calibration.model_id != model.id or calibration.experiment_check_id != experiment.id:
        blockers.append('Exact experiment has not completed code calibration')
    if prerequisite['status'] != 'matched': blockers.append('Candidate prerequisites are not established')
    spec = specs.get(finding.checker_id)
    if spec:boundaries.extend(spec.scope.excluded)
    claim = next((c for c in state.claims if spec and c.id == spec.claim_id),None)
    bases = [bundle.harness.legality] + ([claim.grounding] if claim else [])
    if not claim: blockers.append('Checker claim is unavailable')
    elif claim.pending: boundaries.extend(claim.pending)
    if claim and (finding.claim_id != claim.id or model.graph_versions.get(claim.id) != claim.version):
        blockers.append('Finding or claim version differs from the checked model')
    materials={m.id:m for m in state.materials}; bindings={b.id for b in state.bindings}
    for basis in bases:
        try: validate_grounding(basis,materials,bindings)
        except ValueError as exc: blockers.append(str(exc))
        blockers.extend(basis.unresolved+basis.conflicts)
    if any(event.get('event')=='invalid_observation' for event in events):blockers.append('Event output contains an incomplete or invalid CA_EVENT record')
    confirmed = None
    for monitor,result in zip([m for m in bundle.monitors if m.checker_id==finding.checker_id],results):
        local=[];local_boundaries=[]
        from consensus_assurance.adapters.verifiers.observable import correspondence
        mismatch = correspondence(bundle, monitor)
        if mismatch: local.append(mismatch)
        p=properties.get(monitor.checker_id)
        if p and p.kind == 'stable_support':
            history = []
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
        if not p or not p.identity_fields: local.append('Observation lacks participant/operation/context identity requirements')
        if result['missing_indices']:
            local.append('Result fields or unambiguous prerequisite association are missing')
        if claim and any(g.claim_id==claim.id for g in bundle.consequence_observations):
            mapping=next((g for g in bundle.consequence_observations if g.claim_id==claim.id),None)
            local_boundaries.extend(consequence_witness_limitations(mapping,events,result['witness_indices']))
            if mapping:
                try:validate_grounding(mapping.grounding,materials,bindings)
                except ValueError as exc:local.append(str(exc))
                local_boundaries.extend(mapping.grounding.unresolved+mapping.grounding.conflicts)
                if not mapping.binding_ids or not set(mapping.binding_ids)<=set(model.binding_ids):local_boundaries.append('Consequence observation mapping lacks selected source bindings')
        result['blockers']=list(dict.fromkeys(local));result['boundaries']=list(dict.fromkeys(local_boundaries))
        result['limitations']=list(dict.fromkeys(local+local_boundaries))
        if result['outcome']=='violated' and not local and not blockers: confirmed=result
    if not results: blockers.append('No supported monitor for this checker; trace compatibility is not property violation')
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
        'adaptations':bundle.harness.semantic_changes,
        'blockers':list(dict.fromkeys(blockers)),'boundaries':list(dict.fromkeys(boundaries)),
        'limitations':list(dict.fromkeys(blockers+boundaries)),'level':finding.level,'confirmed':confirmed is not None,
        'claim_version':claim.version if claim else None,
        'checker_scope':spec.scope.model_dump(mode='json') if spec else None,
        'monitor_algorithm':'shared_observable_property/2'}
    current=next((r for r in state.monitor_results if r.get('finding_id')==finding.id and r.get('experiment_check_id')==experiment.id),None)
    if current is None:state.monitor_results.append(record)
    else:current.clear();current.update(record)
    return record


def monitor_support(events, monitor, p, eligible=None):
    seen, violations, missing = [], [], []
    for index, event in enumerate(events):
        if event.get('event') != monitor.event:
            continue
        if eligible is not None and index not in eligible:
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
