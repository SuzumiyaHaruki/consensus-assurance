"""Derived current worksets. Immutable audit records remain in state and raw artifacts."""
import json
from .reviews import material_closure, review_objects


def semantic_view(state,ids):
    objects=review_objects(state)
    issues=[i for i in state.review_issues if i.target_id in ids]
    tasks={t.id:t for t in state.inquiry_tasks}
    positive={};negative={};sources=set()
    for review in state.semantic_reviews:
        for item in review.items:
            if item.target_id not in ids:continue
            linked=[i for i in issues if i.review_id==review.id and i.target_id==item.target_id and i.aspect==item.aspect]
            if linked and all(i.resolved_by for i in linked):continue
            task=tasks.get(review.task_id)
            if task and task.superseded_by and not any(not i.resolved_by for i in linked):continue
            current=objects.get(item.target_id)
            same_version=bool(current and review.target_versions.get(item.target_id)==current.version)
            record={'review_id':review.id,'target_id':item.target_id,'version':review.target_versions.get(item.target_id),
                'aspect':item.aspect,'status':item.status,'source_ids':item.source_ids,'explanation':item.rationale,
                'counterevidence':item.counterevidence,
                'limitations':item.limitations,'current_version':same_version}
            if item.status!='no_issue_found' or item.limitations or item.counterevidence:
                # Keep unresolved counterevidence even after a later positive opinion.
                key=json.dumps({k:v for k,v in record.items() if k!='review_id'},sort_keys=True)
                negative[key]=record
            elif same_version:
                from .review_contract import target_contract,same_basis
                basis=review.context_dependencies.get(item.target_id,{})
                if basis and not same_basis(basis,target_contract(state,current)):continue
                record['basis_status']='current' if basis else 'historical_dependency_basis_unrecorded'
                positive[(item.target_id,item.aspect)]=record
    open_issues=[{'id':i.id,'target_id':i.target_id,'version':i.target_version,'aspect':i.aspect,'explanation':i.explanation,
        'source_ids':i.source_ids,'disposition':i.disposition,'reason':i.reason} for i in issues if not i.resolved_by]
    resolved={}
    for i in issues:
        if i.resolved_by:
            resolved[(i.target_id,i.aspect,i.explanation)]={'issue_id':i.id,'target_id':i.target_id,'aspect':i.aspect,'resolved_by':i.resolved_by,
                'conclusion':i.resolution_basis.get('rationale','Explicit scoped resolution; consult the recorded disposition'),
                'source_ids':i.resolution_basis.get('source_ids',i.source_ids),'remaining_scope':i.resolution_basis.get('scope_limitations',[])}
    records=list(positive.values())+list(negative.values())
    for r in records+open_issues+list(resolved.values()):sources.update(r['source_ids'])
    # The issue already carries the same attributed explanation and sources.
    # Reference those exact fields, retaining alternatives and counterarguments.
    for record in records:
        linked=[i for i in issues if not i.resolved_by and i.review_id==record['review_id'] and i.target_id==record['target_id'] and i.aspect==record['aspect']]
        if len(linked)==1:
            issue=linked[0]
            record['issue_ref']=issue.id
            if record['explanation']==issue.explanation:
                record.pop('explanation');record['explanation_ref']=issue.id
            if record['source_ids']==issue.source_ids:
                record.pop('source_ids');record['source_ids_ref']=issue.id
    return {'issue_reference_rule':'explanation_ref/source_ids_ref point to the exact unchanged fields of open_issues by issue ID; all alternatives and counterarguments remain on the judgment',
        'judgments':records,'open_issues':open_issues,'resolved':list(resolved.values()),
        'archive_access':'Request a focused review of a named issue/review to retrieve its archived reasoning; these are scoped opinions, not proof'},sources


def relevant_model_ids(state, unit):
    models={m.id:m for m in state.models}
    active=models.get(state.active_model_id)
    if active is None or active.unit_id not in {unit.id,unit.previous_id}:
        active=next((m for m in reversed(state.models) if m.unit_id in {unit.id,unit.previous_id}),None)
    ids=set()
    while active and active.id not in ids:
        ids.add(active.id);active=models.get(active.previous_id)
    return ids


def local_workset(engine,unit):
    state=engine.state
    needed,ids=material_closure(state,[unit.id]);ids.update(relevant_model_ids(state,unit));semantic,sources=semantic_view(state,ids)
    needed.update(sources)
    explicit=set(state.task_attachments.get('unit:'+unit.id,[]));needed.update(explicit)
    # Completed review reading belongs to the reviewed unit as well as its inquiry.
    for task in state.inquiry_tasks:
        if task.unit_id==unit.id and (task.unit_version is None or task.unit_version==unit.version):
            needed.update(task.added_material_ids)
            needed.update(state.task_attachments.get('inquiry:'+task.id,[]))
    return {'materials':[m.model_dump(mode='json') for m in state.materials if m.id in needed],
        'required_material_ids':sorted(needed),'explicit_material_ids':sorted(explicit),
        'omitted_material_ids':[m.id for m in state.materials if m.id not in needed],
        'omission_reason':'Outside this unit, its selected dependency closure and current semantic issues; full history remains archived',
        'semantic_view':semantic,
        'unit':unit.model_dump(mode='json'),
        'verification_continuation':state.question_continuations.get(unit.id,{}),
        'claims':[c.model_dump(mode='json') for c in state.claims if c.id in ids],
        'bindings':[b.model_dump(mode='json') for b in state.bindings if b.id in ids],
        'relations':[r.model_dump(mode='json') for r in state.relations if r.id in ids or r.id in unit.relation_ids],
        'obligation_progress':{'checked_scopes':unit.obligation_checks,'remaining':unit.remaining_obligation_ids or unit.obligation_ids},
        'modeling_brief':{'unit_id':unit.id,'version':unit.version,'question_ref':unit.id,'obligation_ids':unit.obligation_ids,
            'scope_ref':unit.id,'code_refs':unit.binding_ids,'relationship_refs':unit.relation_ids,
            'remaining_conditions':unit.coverage_limitations+[x for b in state.bindings if b.id in unit.binding_ids for x in b.pending]+[x for r in state.relations if r.id in unit.relation_ids for x in r.pending+r.grounding.unresolved],
            'basis':'Derived current obligation and code view; complete referenced objects and required source are included once'}}


def local_basis(state,unit):
    ids=set(unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id])
    materials,closure=material_closure(state,[unit.id]);closure.update(relevant_model_ids(state,unit));view,sources=semantic_view(state,closure)
    materials.update(sources);materials.update(state.task_attachments.get('unit:'+unit.id,[]))
    from .sources import ranges
    spans=[{'file':f,'content_digest':v,'ranges':r} for (f,v),r in sorted(ranges([m for m in state.materials if m.id in materials]).items())]
    return {'versions':{o.id:o.version for o in state.claims+state.bindings+state.relations+state.units if o.id in ids},
        'materials':spans,'issues':[[i['id'],i['version']] for i in view['open_issues']]}
