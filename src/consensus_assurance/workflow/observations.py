"""Finite, non-evaluating event correlation and fully observed safety monitors."""
from consensus_assurance.core.events import MISSING, field, compare, match_prerequisites, event_requirements


def monitor_events(events, monitor, prop, requirements=None):
    """Keep existential witnesses separate from completeness of the observed scope."""
    results, missing, correlations, outside, diagnostics = [], [], {}, [], []
    def gap(index, reason):
        missing.append(index)
        diagnostics.append({'event_index':index, 'identity':{k:field(events[index],k)
            for k in prop.identity_fields if field(events[index],k) is not MISSING}, 'reason':reason})
    for index, event in enumerate(events):
        if prop is None or event.get('event') != monitor.event:
            continue
        independent = [prop.trigger, *(c for c in monitor.applicability_conditions if not c.reference)]
        if any(compare(event,c) is False for c in independent):
            outside.append(index)
            continue
        absent = [k for k in prop.identity_fields if field(event,k) is MISSING]
        absent += [c.field for c in independent if compare(event,c) is None]
        if absent:
            gap(index, 'Missing identity or applicability fields: '+', '.join(dict.fromkeys(absent)))
            continue
        aliases = {}
        if requirements is not None:
            linked = match_prerequisites(events, requirements, index, prop.identity_fields)
            correlations[str(index)] = linked
            if linked['status'] != 'matched':
                gap(index, linked['reason'])
                continue
            aliases = {alias:events[i] for alias,i in linked['alias_indices'].items()}
        applicability = [compare(event,c,aliases) for c in monitor.applicability_conditions if c.reference]
        if any(value is False for value in applicability):
            outside.append(index)
            continue
        if any(value is None for value in applicability):
            gap(index, 'Missing alias-dependent applicability fields')
            continue
        value = compare(event,prop.assertion,aliases)
        if prop.kind == 'event_implication':
            antecedent = compare(event,prop.antecedent,aliases) if prop.antecedent else None
            value = None if antecedent is None or value is None else not antecedent or value
        if value is None and prop.kind != 'stable_support':
            gap(index, 'Missing required result fields: '+prop.assertion.field+
                (' or '+prop.antecedent.field if prop.antecedent else ''))
        else:
            results.append((index,value))
    violations = [index for index,value in results if value is False]
    if prop and prop.kind == 'stable_support':
        support = monitor_support(events,monitor,prop,{index for index,_ in results})
        violations = support['witness_indices']
        for index in support['missing_indices']:
            gap(index, 'Missing support identity or object')
    # A missing result in the same operation can affect its witness. Unknown
    # identity is not evidence of independence; distinct runner streams are.
    def independent_operation(left, right):
        a, b = events[left], events[right]
        if a.get('_ca_stream') is not None and b.get('_ca_stream') is not None and a['_ca_stream'] != b['_ca_stream']:
            return True
        return any(field(a,k) is not MISSING and field(b,k) is not MISSING
            and compare(a, type(prop.trigger)(field=k,reference='other.'+k), {'other':b}) is False
            for k in prop.identity_fields)
    if prop and requirements:
        try: initial = event_requirements(requirements)[0]
        except ValueError: initial = None
        for index,event in enumerate(events):
            if initial is None or event.get('event') != initial.event:continue
            conditions = initial.conditions+[c for c in monitor.applicability_conditions if not c.reference]
            if any(compare(event,c) is False for c in conditions):continue
            if not any(event.get('_ca_stream')==events[r].get('_ca_stream') and
                    all(field(event,k) is not MISSING and compare(event,type(prop.trigger)(field=k,reference='result.'+k),{'result':events[r]}) is True for k in prop.identity_fields)
                    for r in [i for i,_ in results]+outside):
                gap(index, 'Admitted operation has no complete applicable result observation')
    valid = [index for index in violations if all(independent_operation(index,m) for m in missing)]
    complete = bool(results) and not missing
    limitations = [f"Event {d['event_index']} {d['identity']}: {d['reason']}" for d in diagnostics]
    if not results and not missing:
        limitations.append('No applicable completed result event was reached')
    return {'monitor_id':monitor.id, 'checker_id':monitor.checker_id,
        'outcome':'violated' if valid else 'unknown' if missing or not results else 'holds',
        'witness_indices':violations, 'valid_witness_indices':valid, 'witness_complete':bool(valid),
        'comparison_complete':complete, 'missing_indices':sorted(set(missing)),
        'evaluated_indices':[index for index,_ in results], 'outside_applicability_indices':outside,
        'correlations':correlations, 'diagnostics':diagnostics, 'limitations':limitations,
        'reason':'Independent applicability, correlated prerequisites and fully observed result comparison'}


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
