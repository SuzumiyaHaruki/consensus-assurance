"""Recoverable semantic state commits, keyed by existing controller action identity."""
import copy
import json
import re
from consensus_assurance.core.types import Analysis
from consensus_assurance.adapters.storage.files import write_json
from .mutations import adopt
from .budget import BudgetTracker

EXCLUDED={'checks','tools','elapsed_seconds','created_at'}


def commit_graph(engine,key,payload,callback):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*',key) or '..' in key:raise ValueError('Invalid semantic operation ID')
    recorded=engine.state.applied_operations.get(key)
    if recorded:
        if recorded['input']!=payload:raise ValueError('Operation identity reused with different semantic input')
        return
    path=engine.root/'graph-commits'/(key+'.json')
    if path.exists():
        operation=json.loads(path.read_text())
        if operation['input']!=payload:raise ValueError('Prepared semantic input differs')
    else:
        proxy=copy.copy(engine);proxy.state=engine.state.model_copy(deep=True)
        proxy.budget=BudgetTracker(engine.config.budget,proxy.state)
        before=engine.state.model_dump(mode='json')
        callback(proxy)
        proxy.state.applied_operations[key]={'input':payload}
        after=proxy.state.model_dump(mode='json')
        fields=[k for k in after if k not in EXCLUDED and before[k]!=after[k]]
        operation={'input':payload,'before':{k:before[k] for k in fields},'after':{k:after[k] for k in fields}}
        write_json(path,operation)
        engine.graph_commit_hook(key)
    current=engine.state.model_dump(mode='json')
    if any(current[k]!=v for k,v in operation['before'].items()):raise ValueError('Semantic operation base changed; cannot replay a prepared mutation')
    trial=Analysis.model_validate({**current,**operation['after']})
    adopt(engine.state,trial)
    engine.checkpoint('semantic_operation_committed')
