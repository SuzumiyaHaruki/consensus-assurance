"""Explicit offline imports only; never normalize fresh backend declarations here."""
import json
from consensus_assurance.core.types import AuditQuestion


def import_question_changes(reply):
    """Return a copy with historical whole-question diffs normalized to this schema."""
    reply=reply.model_copy(deep=True)
    revision=getattr(reply,'revision',None)
    if revision:
        for change in revision.changes:
            if change.field=='audit_question':
                for name in ('old_value_json','new_value_json'):
                    value=json.loads(getattr(change,name))
                    if value is not None:setattr(change,name,AuditQuestion.model_validate(import_record(value)).model_dump_json())
    return reply


def import_record(value):
    """Read old archives into a view only. Original bytes and revision stay unchanged."""
    import copy
    value=copy.deepcopy(value)
    def visit(obj):
        if isinstance(obj,list):return [visit(x) for x in obj]
        if not isinstance(obj,dict):return obj
        obj={k:visit(v) for k,v in obj.items()}
        for k in ('responsibilities','responsibility_history','exploration_requests','coverage_intent'):
            obj.pop(k,None)
        if 'points' in obj and 'question' in obj:
            points=obj.pop('points')
            obj['unknowns']=list(dict.fromkeys(obj.get('unknowns',[])+[s for p in points for s in p.get('unknowns',[])]))
        if 'point_ids' in obj:obj.pop('point_ids')
        if 'responsibility_ids' in obj:obj.pop('responsibility_ids');obj['activity_classes']=[]
        if obj.get('kind')=='explore':obj['kind']='spec_refine'
        if {'target_id','aspect','status','source_ids'}<=obj.keys() and 'explanation' in obj:
            obj['rationale']='\n'.join(str(obj.pop(k,'')) for k in ('explanation','alternatives','counterexample_reasoning')).strip()
            obj['limitations']=list(dict.fromkeys(obj.get('limitations',[])+obj.pop('scope_limitations',[])))
            obj.setdefault('counterevidence',[])
        return obj
    return visit(value)


def load_analysis(path):
    from pathlib import Path
    from consensus_assurance.core.types import Analysis
    value=json.loads(Path(path).read_text())
    if value.get('framework_revision')!='seven-activity-v2':value=import_record(value)
    return Analysis.model_validate(value)
