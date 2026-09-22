"""Bounded event lookup and correlation, independent of workflow and tools."""
from .proposals import EventRequirement, Comparison

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


def event_requirements(requirements, reference=None):
    requirements = [EventRequirement.model_validate(r) for r in requirements]
    aliases = {r.alias for r in requirements}
    if len(aliases) != len(requirements) or any(not a or '.' in a for a in aliases):
        raise ValueError('Prerequisite aliases must be unique nonempty names')
    references = [c.reference for r in requirements for c in r.conditions if c.reference]
    if reference: references.append(reference)
    if any(ref.partition('.')[0] not in aliases or not ref.partition('.')[2] for ref in references):
        raise ValueError('Comparison references an unavailable prerequisite alias or field')
    ordered, pending = [], list(requirements)
    while pending:
        ready = next((r for r in pending if all(not c.reference or c.reference.partition('.')[0] in {a.alias for a in ordered} for c in r.conditions)),None)
        if ready is None: raise ValueError('Prerequisite references contain a causal cycle')
        ordered.append(ready); pending.remove(ready)
    return ordered


def match_prerequisites(events, requirements, witness_index=None, identity_fields=()):
    if not requirements:
        return {'status':'unknown','reason':'No correlated prerequisite specification','matched_indices':[], 'alias_indices':{}}
    try: ordered = event_requirements(requirements)
    except ValueError as exc:
        return {'status':'unknown','reason':str(exc),'matched_indices':[], 'alias_indices':{}}
    missing, matches = False, []
    witness = events[witness_index] if witness_index is not None else None
    def search(step, indices):
        nonlocal missing
        if step == len(ordered):
            matches.append(indices); return
        req = ordered[step]
        aliases = {alias:events[index] for alias,index in indices.items()}
        predecessors = [indices[c.reference.partition('.')[0]] for c in req.conditions if c.reference]
        for index,event in enumerate(events[:witness_index] if witness_index is not None else events):
            if event.get('event') != req.event or index in indices.values(): continue
            if any(index <= prior for prior in predecessors): continue
            identity = [compare(event,Comparison(field=k,reference='witness.'+k),{'witness':witness}) for k in identity_fields] if witness is not None else []
            if any(v is False for v in identity): continue
            checks = identity + [compare(event,c,aliases) for c in req.conditions]
            if any(v is False for v in checks): continue
            if any(v is None for v in checks): missing = True; continue
            search(step+1,{**indices,req.alias:index})
            if len(matches) >= (2 if witness is not None else 1): return
    search(0,{})
    ambiguous = witness is not None and (len(matches)>1 or missing)
    status = 'unknown' if ambiguous else 'matched' if matches else 'unknown' if missing else 'not_reached'
    indices = matches[0] if status=='matched' else {}
    return {'status':status,'reason':'Ambiguous prerequisite association or missing fields' if ambiguous else 'Declared prerequisites established' if indices else 'Missing fields' if missing else 'No corresponding prerequisite events reached',
        'matched_indices':list(indices.values()),'alias_indices':indices}
