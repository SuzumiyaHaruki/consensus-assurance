"""The single source of review categories, requirements and object-specific questions."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .sources import citation_status, ranges

POLICY={
 'candidate': {'applicability':'Does the newly sourced knowledge challenge this exact question or its earlier explanation? Preserve contrary evidence and distinguish requirements, scope and implementation understanding.'},
 'obligation': {'applicability':'Why does the implementation owe this responsibility in the selected scope?', 'decomposition':'Explain necessity, sufficiency, alternatives, producer/consumer dependencies and remaining guarantees.'},
 'assumption': {'applicability':'What actual source or explicit environment contract justifies the assumption, and what remains unverified?'},
 'binding': {'decomposition':'Check the source anchor and behavior range, the semantic association to responsibilities, and the selected unit use. Location alone does not establish an obligation.'},
 'relation': {'decomposition':'Check the direction, kind, conditions and actual endpoint responsibilities; explain the implementing handoff and alternatives.'},
 'unit': {'decomposition':'Check that the audit question, selected obligations, direct/support code uses and boundary assumptions form a coherent executable scope.'},
 'direct_check': {'checker_correspondence':'Review the entire selected obligation, question, source bindings, assumptions and scope together with the saved property, actual calls, oracle, correlated observations and legality. State concrete issues within this whole check instead of requesting separate object/aspect approvals. No model or calibration is required; an assertion or matching ID alone is not correspondence.'},
 'model': {'checker_correspondence':'Compare actual behavior and checker/oracle encoding with the attributed claim, trigger, observations, scope and contrary evidence; tool completion alone is not correspondence.'}}
OPTIONAL={'binding':{'applicability':'Evaluate whether the code mapping applies to the current implementation configuration.'},'unit':{'applicability':'Evaluate whether the unit scope is applicable under the supplied execution conditions.'}}
for kind in ('direct_check', 'model'):
    OPTIONAL[kind] = {key: value for key, value in POLICY['obligation'].items()}


def category(obj):
    if hasattr(obj,'question'):return 'candidate'
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
    return {'source_ranges':source_ranges,'target_id':obj.id,'object_type':kind,'version':obj.question.audit_spec_version if kind=='candidate' else obj.version,'required_aspects':list(POLICY[kind]),
        'questions':POLICY[kind],'optional_questions':OPTIONAL.get(kind,{}),
        'required_material_ids':sorted(materials),'dependency_versions':{id:objects[id].version for id in sorted(ids) if hasattr(objects[id],'version')}}


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
        if item.status=='no_issue_found' and item.counterevidence:
            issue('review_contradictory_judgment',item.target_id,'no_issue_found cannot include current counterevidence; use a negative status or explain alternatives in rationale',i)
        if item.status in {'disputed','revision_needed'} and not item.counterevidence:
            issue('review_missing_challenge',item.target_id,'A negative judgment needs counterevidence; put scope boundaries in limitations',i)
        if item.status == 'revision_needed' and not item.challenged_components:
            issue('review_missing_component',item.target_id,'Name the challenged configuration, initialization, driver, observation, oracle, expectation or scope; the review aspect does not determine the repair',i)
        if kind=='candidate' and item.challenged_components:
            issue('review_wrong_component',item.target_id,'Review an executed artifact for component repairs; Candidate applicability uses sourced disputes or reading questions',i)
        if item.status == 'no_issue_found' and item.challenged_components:
            issue('review_contradictory_component',item.target_id,'A current repair challenge requires a negative judgment',i)
        for source,status in citation_status(state,item.source_ids,supplied).items():
            if status!='provided':issue('review_unknown_source' if status=='unknown' else 'review_unavailable_source',item.target_id,'Citation '+source+': '+status+'; correct the reference or attach the actual range',i)
    if errors:raise DiagnosticError(errors)
