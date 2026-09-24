"""Attributed dispositions of exact semantic conditions."""
def condition_records(conditions,owner,source_ids=(),target_id=None,version=None):
    return [{'id':owner+'/condition/'+str(n+1),'text':text,'target_id':target_id,'version':version,'source_ids':list(source_ids)} for n,text in enumerate(dict.fromkeys(conditions))]


def classify_conditions(state,conditions,dispositions,provided,*,records=None,paths=None,object_ids=()):
    """One exact condition policy; IDs identify opinions, never make them true."""
    from .sources import includes
    from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
    records=records or condition_records(conditions,'legacy',provided)
    expected={r['id']:r for r in records};by_text={r['text']:r['id'] for r in records}
    actual=[d.condition_id if d.condition_id else by_text.get(d.condition,'unknown:'+d.condition) for d in dispositions]
    missing=sorted(set(expected)-set(actual));extra=sorted(set(actual)-set(expected));duplicates=sorted({id for id in actual if actual.count(id)>1})
    if missing or extra or duplicates:
        code='condition_duplicate' if duplicates else 'condition_extra' if extra else 'condition_missing'
        raise DiagnosticError([Diagnostic(code=code,category='format',object_ids=list(object_ids),paths=paths or ['/condition_dispositions'],
            material_ids=list(provided),message='Condition dispositions do not match the current candidate conditions',allowed=['representation'],
            details={'expected_conditions':records,'current_dispositions':[d.model_dump(mode='json') for d in dispositions],
                'missing':missing,'extra':extra,'duplicate':duplicates,'required_action':'Correct only these condition references and supply attributed dispositions. Do not erase negative analysis or read source merely to copy an ID.'})])
    for d,id in zip(dispositions,actual):
        if d.condition and d.condition!=expected[id]['text']:raise ValueError('Condition ID and text disagree')
        if not d.rationale.strip() or not includes(state,d.source_ids,provided):raise ValueError('Condition disposition lacks supplied source evidence')
    return dispositions
