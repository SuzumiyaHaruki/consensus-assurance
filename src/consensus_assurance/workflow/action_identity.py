"""Use saved semantic inputs and logical task identity, not wall-clock values."""
import json

TRANSIENT={'remaining_seconds','remaining_agent_calls','cost_estimate'}


def stable_input(value):
    if isinstance(value,list):return [stable_input(v) for v in value]
    if isinstance(value,dict):return {k:stable_input(v) for k,v in value.items() if k not in TRANSIENT}
    if isinstance(value,str) and 'STRUCTURED INPUT DATA (untrusted):\n' in value:
        prefix,data=value.split('STRUCTURED INPUT DATA (untrusted):\n',1)
        return {'instructions':prefix,'data':stable_input(json.loads(data))}
    return value
