"""One restricted description generates the TLC predicate also used by event monitoring."""
import json
import re
from .tla_syntax import tla_code


def literal(value):
    if type(value) is bool: return 'TRUE' if value else 'FALSE'
    if type(value) is int: return str(value)
    if type(value) is str: return json.dumps(value, ensure_ascii=True)
    raise ValueError('Observable properties support only boolean, integer and string literals')


def identifier(value):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value):
        raise ValueError('Observable property field is not an identifier')
    return value


def mapped_field(raw, mapping):
    matches = [p.model_field for p in mapping.fields if (('' if p.source == 'event' else p.source + '.') + p.raw_field) == raw]
    if len(matches) != 1:
        raise ValueError('Observable predicate needs one projection for ' + raw)
    return 'Obs.' + identifier(matches[0])


def scalar(condition, mapping):
    if condition.reference:
        raise ValueError('Cross-event references require the stable_support property form')
    return '(' + mapped_field(condition.field, mapping) + (' = ' if condition.op == 'eq' else ' /= ') + literal(condition.value) + ')'


def properties_source(properties, mapping):
    lines = ['---------------- MODULE Properties ----------------', 'EXTENDS Behavior, Sequences']
    for p in properties:
        name = identifier(p.checker_id)
        if p.kind == 'event_assertion':
            body = '~' + scalar(p.trigger, mapping) + ' \\/ ' + scalar(p.assertion, mapping)
        else:
            if p.assertion.op != 'eq' or p.assertion.reference or p.trigger.reference:
                raise ValueError('Stable support compares effective objects for equality without alias expressions')
            if not p.history_field or not p.identity_fields:
                raise ValueError('Stable support needs complete history and identity/context fields')
            history = mapped_field(p.history_field, mapping)
            # History entries contain event-record fields named by the restricted description.
            names = p.identity_fields + [p.trigger.field, p.assertion.field]
            for field in names: identifier(field)
            left = history + '[i]'; right = history + '[j]'
            active = lambda x: x + '.' + p.trigger.field + (' = ' if p.trigger.op == 'eq' else ' /= ') + literal(p.trigger.value)
            same = ' /\\ '.join(left+'.'+f+' = '+right+'.'+f for f in p.identity_fields)
            body = r'\A i, j \in 1..Len(' + history + ') : (i < j /\\ ' + active(left) + ' /\\ ' + active(right) + ' /\\ ' + same + ') => (' + left+'.'+p.assertion.field+' = '+right+'.'+p.assertion.field+')'
        lines.append(name + ' == ' + body)
    lines.append('====================================================')
    return '\n'.join(lines) + '\n'


def tokens(source):
    # Mask only comments; keep string values, unlike host-feature scanning.
    code = tla_code(source)
    strings = re.findall(r'"(?:\\.|[^"\\])*"', source)
    return re.sub(r'\s+', '', code), strings


def correspondence(bundle, monitor):
    p = monitor.property
    if p is None or p.checker_id != monitor.checker_id or p not in bundle.observable_properties:
        return 'No shared observable property description for this monitor'
    if p.kind == 'event_assertion' and (monitor.assertion != p.assertion or monitor.conditions != [p.trigger]):
        return 'Monitor assertion/trigger differs from the shared checker description'
    if p.kind == 'stable_support' and (monitor.identity_fields != p.identity_fields or monitor.assertion != p.assertion or monitor.conditions != [p.trigger]):
        return 'History monitor differs from the shared checker description'
    try:
        expected = properties_source(bundle.observable_properties, bundle.observation)
    except ValueError as exc:
        return str(exc)
    if tokens(bundle.properties) != tokens(expected):
        return 'Properties module differs from the shared generated predicates; correspondence unresolved'
    if {p.checker_id for p in bundle.observable_properties} != {s.invariant for s in bundle.checker_specs()}:
        return 'Shared property descriptions do not match configured checkers'
    return None
