"""Bounded event lookup and correlation, independent of workflow and tools."""
from .proposals import EventRequirement

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
