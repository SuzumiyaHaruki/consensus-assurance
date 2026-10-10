"""The single source of review categories, requirements and object-specific questions."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .sources import citation_status, ranges

POLICY={
 'candidate': {'applicability':'Does the newly sourced knowledge challenge this exact question or its earlier explanation? Preserve contrary evidence and distinguish requirements, scope and implementation understanding.'},
 'direct_check': {'checker_correspondence':"Does this evidence establish a conditional observation, an independently applicable local contract violation, or a reachable protocol violation? Before no_issue_found, identify the necessary premises and how fixed execution/producers or a sourced admitting contract establish them. A narrower endpoint alone cannot turn a missing necessary producer/history into independent scope. Answer exact open issues; unchanged sources or a correct oracle need no artificial edit. See evidence-review."}}


OPTIONAL={'direct_check':{
    'applicability':'Why does the sourced contract admit this input and initial state?',
    'decomposition':'Do the selected checks express the responsibility and preserve its dependencies?'}}


def category(obj):
    if hasattr(obj,'question'):return 'candidate'
    if hasattr(obj,'plan_path'):return 'direct_check'
    raise ValueError('Review requires a Candidate or direct-check artifact')


def required_aspects(obj):return set(POLICY[category(obj)])


def target_contract(state,obj):
    from .reviews import material_closure, review_objects
    materials,ids=material_closure(state,[obj.id])
    objects=review_objects(state)
    kind=category(obj)
    source_ranges=[{'file':file,'content_digest':version,'ranges':spans} for (file,version),spans in sorted(ranges([m for m in state.materials if m.id in materials]).items())]
    return {'source_ranges':source_ranges,'target_id':obj.id,'object_type':kind,'version':obj.version,'required_aspects':list(POLICY[kind]),
        'questions':POLICY[kind],'optional_questions':OPTIONAL.get(kind,{}),
        'required_material_ids':sorted(materials),'dependency_versions':{id:objects[id].version for id in sorted(ids) if hasattr(objects[id],'version')}}


def validate_contract(state,target_id,items):
    from .reviews import review_objects
    objects=review_objects(state)
    supplied={m.id for m in state.materials}
    errors=[]
    def issue(code,target,message,index=None):
        contract=target_contract(state,objects[target]) if target == target_id and target in objects else {'target_id':target}
        errors.append(Diagnostic(code=code,category='format',object_ids=[target],paths=['/review_items/'+str(index)] if index is not None else ['/review_items'],material_ids=contract.get('required_material_ids',[]),
            message=message,allowed=['representation','read'],details={'review_contract':contract,
            'allowed_targets':[target_contract(state,objects[target_id])] if target_id in objects else [],
            'item_index':index,'preservation':'Retain previous analysis, negative judgments, limitations and sources; add substantive required items rather than automatic approval'}))
    seen=set()
    for i,item in enumerate(items):
        if item.target_id != target_id or item.target_id not in objects:issue('review_unknown_target',item.target_id,'Review references an unknown or unrequested target',i);continue
        key=(item.target_id,item.aspect)
        if key in seen:issue('review_duplicate_item',item.target_id,'Duplicate semantic review aspect for an object',i)
        seen.add(key);kind=category(objects[item.target_id])
        if item.aspect not in set(POLICY[kind])|set(OPTIONAL.get(kind,{})):issue('review_wrong_aspect',item.target_id,'Aspect is not applicable to this object type under the supplied review contract',i)
        if item.status=='no_issue_found' and item.counterevidence:
            issue('review_contradictory_judgment',item.target_id,'no_issue_found cannot include current counterevidence; use a negative status or explain alternatives in rationale',i)
        if item.status in {'disputed','revision_needed'} and not item.counterevidence:
            issue('review_missing_challenge',item.target_id,'A negative judgment needs counterevidence; put scope boundaries in limitations',i)
        for source,status in citation_status(state,item.source_ids,supplied).items():
            if status!='provided':issue('review_unknown_source' if status=='unknown' else 'review_unavailable_source',item.target_id,'Citation '+source+': '+status+'; correct the reference or attach the actual range',i)
    if errors:raise DiagnosticError(errors)
