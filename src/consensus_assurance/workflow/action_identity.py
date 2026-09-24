"""Use saved semantic inputs and logical task identity, not wall-clock values."""

TRANSIENT={'remaining_seconds','remaining_agent_calls','cost_estimate'}


def stable_input(value):
    if isinstance(value,list):return [stable_input(v) for v in value]
    if isinstance(value,dict):return {k:stable_input(v) for k,v in value.items() if k not in TRANSIENT}
    return value
