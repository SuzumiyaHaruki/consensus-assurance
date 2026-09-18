"""The single source of review categories, requirements and object-specific questions."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .sources import citation_status, ranges

POLICY={
 'obligation': {'applicability':'Why does the implementation owe this responsibility in the selected scope?', 'decomposition':'Explain necessity, sufficiency, alternatives, producer/consumer dependencies and remaining guarantees.'},
 'assumption': {'applicability':'What actual source or explicit environment contract justifies the assumption, and what remains unverified?'},
 'binding': {'decomposition':'Check the source anchor and behavior range, the semantic association to responsibilities, and the selected unit use. Location alone does not establish an obligation.'},
 'relation': {'decomposition':'Check the direction, kind, conditions and actual endpoint responsibilities; explain the implementing handoff and alternatives.'},
 'unit': {'decomposition':'Check that the audit question, selected obligations, direct/support code uses and boundary assumptions form a coherent executable scope.'},
 'direct_check': {'checker_correspondence':'Compare the saved shared property, actual harness calls, independent oracle computation, correlated observations and legality with the selected obligation. No model or calibration is required; an assertion or matching ID alone is not correspondence.'},
 'model': {'checker_correspondence':'Compare actual behavior and checker/oracle encoding with the attributed claim, trigger, observations, scope and contrary evidence; tool completion alone is not correspondence.'}}
OPTIONAL={'binding':{'applicability':'Evaluate whether the code mapping applies to the current implementation configuration.'},'unit':{'applicability':'Evaluate whether the unit scope is applicable under the supplied execution conditions.'}}


def category(obj):
    if getattr(obj,'kind',None) in {'obligation','assumption'}:return obj.kind
    if hasattr(obj,'plan_path'):return 'direct_check'
    if hasattr(obj,'bundle_path'):return 'model'
    if hasattr(obj,'associations'):return 'binding'
    if hasattr(obj,'obligation_ids'):return 'unit'
    if hasattr(obj,'source') and hasattr(obj,'target'):return 'relation'
    raise ValueError('Unsupported semantic review object type')


def required_aspects(obj):return set(POLICY[category(obj)])


def target_contract(state,obj):
    from .reviews import material_closure, review_objects
    materials,ids=material_closure(state,[obj.id])
    objects=review_objects(state)
    kind=category(obj)
    source_ranges=[{'file':file,'content_digest':version,'ranges':spans} for (file,version),spans in sorted(ranges([m for m in state.materials if m.id in materials]).items())]
    return {'source_ranges':source_ranges,'target_id':obj.id,'object_type':kind,'version':obj.version,'required_aspects':list(POLICY[kind]),
        'questions':POLICY[kind],'optional_questions':OPTIONAL.get(kind,{}),
        'required_material_ids':sorted(materials),'dependency_versions':{id:objects[id].version for id in sorted(ids) if id in objects}}


def validate_contract(state,task,reply):
    from .reviews import review_objects
    objects=review_objects(state)
    supplied=set(task.material_ids) if task.context_receipt_id else set(task.material_ids) or {m.id for m in state.materials}
    errors=[]
    def issue(code,target,message,index=None):
        contract=target_contract(state,objects[target]) if target in objects else {'target_id':target}
        errors.append(Diagnostic(code=code,category='format',object_ids=[target],paths=['/items/'+str(index)] if index is not None else ['/items'],material_ids=contract.get('required_material_ids',[]),
            message=message,allowed=['representation','read'],details={'review_contract':contract,'item_index':index,'preservation':'Retain previous analysis, negative judgments, limitations and sources; add substantive required items rather than automatic approval'}))
    seen=set()
    for i,item in enumerate(reply.items):
        if item.target_id not in task.target_ids or item.target_id not in objects:issue('review_unknown_target',item.target_id,'Review references an unknown or unrequested target',i);continue
        key=(item.target_id,item.aspect)
        if key in seen:issue('review_duplicate_item',item.target_id,'Duplicate semantic review aspect for an object',i)
        seen.add(key);kind=category(objects[item.target_id])
        if item.aspect not in set(POLICY[kind])|set(OPTIONAL.get(kind,{})):issue('review_wrong_aspect',item.target_id,'Aspect is not applicable to this object type under the supplied review contract',i)
        for source,status in citation_status(state,item.source_ids,supplied).items():
            if status!='provided':issue('review_unknown_source' if status=='unknown' else 'review_unavailable_source',item.target_id,'Citation '+source+': '+status+'; correct the reference or attach the actual range',i)
    if errors:raise DiagnosticError(errors)


def same_basis(a,b):
    return a.get('version')==b.get('version') and a.get('dependency_versions')==b.get('dependency_versions') and a.get('source_ranges')==b.get('source_ranges')


def missing_pairs(state,task,items):
    from .reviews import review_objects
    objects=review_objects(state)
    return {id:sorted(missing) for id in task.target_ids if id in objects
        if (missing:=set(task.requested_aspects.get(id,required_aspects(objects[id])))-{i.aspect for i in items if i.target_id==id})}
