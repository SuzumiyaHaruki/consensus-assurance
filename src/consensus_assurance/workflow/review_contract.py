"""The single source of review categories, requirements and object-specific questions."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError

POLICY={
 'goal': {'applicability':'Why is this goal required by the current implementation contract, configuration and fault scope? Preserve contrary evidence and unresolved applicability.'},
 'obligation': {'applicability':'Why does the implementation owe this responsibility in the selected scope?', 'decomposition':'Explain necessity, sufficiency, alternatives, producer/consumer dependencies and remaining guarantees.'},
 'assumption': {'applicability':'What actual source or explicit environment contract justifies the assumption, and what remains unverified?'},
 'binding': {'decomposition':'Check the source anchor and behavior range, the semantic association to responsibilities, and the selected unit use. Location alone does not establish an obligation.'},
 'relation': {'decomposition':'Check the direction, kind, conditions and actual endpoint responsibilities; explain the implementing handoff and alternatives.'},
 'unit': {'decomposition':'Check that the audit question, selected obligations, direct/support code uses and boundary assumptions form a coherent executable scope.'},
 'model': {'checker_correspondence':'Compare actual behavior and checker encoding with the attributed claim, trigger, observations, scope and contrary evidence; tool completion alone is not correspondence.'}}
OPTIONAL={'binding':{'applicability':'Evaluate whether the code mapping applies to the current implementation configuration.'},'unit':{'applicability':'Evaluate whether the unit scope is applicable under the supplied execution conditions.'}}


def category(obj):
    if getattr(obj,'kind',None) in {'goal','obligation','assumption'}:return obj.kind
    if hasattr(obj,'bundle_path'):return 'model'
    if hasattr(obj,'associations'):return 'binding'
    if hasattr(obj,'obligation_ids'):return 'unit'
    if hasattr(obj,'source') and hasattr(obj,'target'):return 'relation'
    raise ValueError('Unsupported semantic review object type')


def required_aspects(obj):return set(POLICY[category(obj)])


def target_contract(state,obj):
    from .reviews import material_closure
    materials,ids=material_closure(state,[obj.id])
    objects={o.id:o for o in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}
    kind=category(obj)
    ranges={}
    for m in state.materials:
        if m.id in materials:ranges.setdefault((m.file,m.content_digest),set()).update(range(m.start_line,m.end_line+1))
    source_ranges=[]
    for (file,version),lines in sorted(ranges.items()):
        chunks=[]
        for line in sorted(lines):
            if not chunks or line>chunks[-1][1]+1:chunks.append([line,line])
            else:chunks[-1][1]=line
        source_ranges.append({'file':file,'content_digest':version,'ranges':chunks})
    return {'source_ranges':source_ranges,'target_id':obj.id,'object_type':kind,'version':obj.version,'required_aspects':list(POLICY[kind]),
        'questions':POLICY[kind],'optional_questions':OPTIONAL.get(kind,{}),
        'required_material_ids':sorted(materials),'dependency_versions':{id:objects[id].version for id in sorted(ids) if id in objects}}


def validate_contract(state,task,reply):
    objects={o.id:o for o in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}
    supplied=set(task.material_ids) if task.context_receipt_id else set(task.material_ids) or {m.id for m in state.materials}
    errors=[]
    def issue(code,target,message,index=None):
        contract=target_contract(state,objects[target]) if target in objects else {'target_id':target}
        errors.append(Diagnostic(code=code,category='format',object_ids=[target],paths=['/items/-'] if code in {'review_missing_aspect','review_missing_target'} else ['/items/'+str(index)] if index is not None else ['/items'],material_ids=contract.get('required_material_ids',[]),
            message=message,allowed=['representation','read'],details={'review_contract':contract,'item_index':index,'preservation':'Retain previous analysis, negative judgments, limitations and sources; add substantive required items rather than automatic approval'}))
    seen=set()
    for i,item in enumerate(reply.items):
        if item.target_id not in task.target_ids or item.target_id not in objects:issue('review_unknown_target',item.target_id,'Review references an unknown or unrequested target',i);continue
        key=(item.target_id,item.aspect)
        if key in seen:issue('review_duplicate_item',item.target_id,'Duplicate semantic review aspect for an object',i)
        seen.add(key);kind=category(objects[item.target_id])
        if item.aspect not in set(POLICY[kind])|set(OPTIONAL.get(kind,{})):issue('review_wrong_aspect',item.target_id,'Aspect is not applicable to this object type under the supplied review contract',i)
        if not set(item.source_ids)<=supplied:issue('review_unavailable_source',item.target_id,'Semantic review cites material not supplied in this task',i)
    for id in task.target_ids:
        if id not in objects:issue('review_unknown_target',id,'Requested target is no longer available');continue
        if not any(i.target_id==id for i in reply.items):issue('review_missing_target',id,'Review must account for each requested object');continue
        required=set(task.requested_aspects.get(id,required_aspects(objects[id])))
        missing=required-{i.aspect for i in reply.items if i.target_id==id}
        if missing:issue('review_missing_aspect',id,'Review omitted a required semantic aspect for '+id+': '+', '.join(sorted(missing)))
    if errors:raise DiagnosticError(errors)


def same_basis(a,b):
    return a.get('version')==b.get('version') and a.get('dependency_versions')==b.get('dependency_versions') and a.get('source_ranges')==b.get('source_ranges')
