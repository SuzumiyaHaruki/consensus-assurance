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
        if 'code_uses' in obj:
            uses=obj.pop('code_uses')
            obj['coverage_limitations']=obj.get('coverage_limitations',[])+[text for use in uses for text in use.get('unverified',[])]
        if 'relations' in obj:
            old=[r for r in obj['relations'] if r.get('kind') in {'maps','alternative'}]
            obj['relations']=[r for r in obj['relations'] if r not in old]
            if old:obj['gaps']=obj.get('gaps',[])+['Historical non-dependency relation: '+json.dumps(r) for r in old]
        if 'discovery_path' in obj:obj['derivation_path']=obj.pop('discovery_path')
        if obj.get('kind')=='goal':obj['kind']='obligation'
        for name in ('goal_ids','goal_observable','handoff_ids'):obj.pop(name,None)
        if obj.get('obligation_relation_kind')=='cross_activity_handoff':obj['obligation_relation_kind']='consumption'
        if 'goal_observations' in obj:obj['consequence_observations']=obj.pop('goal_observations')
        if obj.get('level')=='implementation_goal':obj['level']='implementation_consequence'
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
    if value.get('framework_revision') not in {'obligation-audit-v2','selected-question-v3','selected-question-v4','selected-question-v5'}:value=import_record(value)
    return Analysis.model_validate(value)
