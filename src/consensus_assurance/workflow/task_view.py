"""Derived current worksets. Immutable audit records remain in state and raw artifacts."""
from .reviews import material_closure, review_objects, issue_challenges


def candidate_view(state,candidate):
    unit=next((u for u in state.units if candidate.obligation_id in u.obligation_ids),None)
    artifacts=[a for a in state.direct_checks if unit and a.unit_id==unit.id]
    result=next((r for r in reversed(state.monitor_results) if any(a.id==r.get('direct_check_id') for a in artifacts)),None)
    current={k:result.get(k) for k in ('outcome','bounded_complete','confirmed','blockers','boundaries','level')} if result else None
    if current:
        issues=[i for i in state.review_issues if not i.resolved_by and any(a.id==i.target_id for a in artifacts)]
        reviews=[i for r in state.semantic_reviews for i in r.items if any(a.id==i.target_id for a in artifacts) and i.aspect=='checker_correspondence']
        try:
            from .direct_checks import load_plan
            uncertainties=load_plan(next(a for a in artifacts if a.id==result['direct_check_id']).plan_path).uncertainties
        except (OSError,ValueError,StopIteration):uncertainties=[]
        if issues:current['blockers']=['Issue '+i.id+': '+'; '.join(issue_challenges(state,i)) for i in issues]
        if reviews:current['boundaries']=list(dict.fromkeys(unit.scope.excluded+uncertainties+reviews[-1].limitations))
    records=[e for e in state.evidence if e.claim_id==candidate.obligation_id and (not result or e.check_id==result['experiment_check_id'])]
    checks=list(dict.fromkeys(candidate.check_ids+[e.check_id for e in records]+([result['experiment_check_id']] if result else [])+
        [t.check_id for t in state.inquiry_tasks if t.check_id and (t.candidate_id==candidate.id or unit and t.unit_id==unit.id)]))
    evidence=[e.id for e in records]
    return {'id':candidate.id,'parent_candidate_id':candidate.parent_candidate_id,'fork_reason':candidate.fork_reason,
        'question':candidate.question.question,'fact_ids':candidate.question.fact_ids,'lifecycle':candidate.question.obligation_relation_kind,
        'status':candidate.status,'reason':candidate.stop_reason,'obligation_id':candidate.obligation_id,
        'unit_id':unit.id if unit else None,'unit_status':'blocked' if current and current['blockers'] else unit.status if unit else None,'archived_unit_status':unit.status if unit else None,'scope':result.get('scope') if result else unit.scope.model_dump(mode='json') if unit else {'contexts':candidate.question.contexts,'event_paths':candidate.question.event_paths},'check_ids':checks,'evidence_ids':evidence,
        'current_result':current,
        'remaining_discriminators':result.get('blockers',[])+result.get('boundaries',[]) if result else candidate.question.unknowns}


def semantic_view(state,ids):
    objects=review_objects(state)
    issues=[i for i in state.review_issues if i.target_id in ids]
    tasks={t.id:t for t in state.inquiry_tasks}
    positive={};sources=set()
    for review in state.semantic_reviews:
        for item in review.items:
            if item.target_id not in ids:continue
            linked=[i for i in issues if i.review_id==review.id and i.target_id==item.target_id and i.aspect==item.aspect]
            if linked and all(i.resolved_by for i in linked):continue
            task=tasks.get(review.task_id)
            if task and task.superseded_by and not any(not i.resolved_by for i in linked):continue
            current=objects.get(item.target_id)
            same_version=bool(current and review.target_versions.get(item.target_id)==current.version)
            if item.status!='no_issue_found' or not same_version:continue
            from .review_contract import target_contract,same_basis
            basis=review.context_dependencies.get(item.target_id,{})
            if basis and not same_basis(basis,target_contract(state,current)):continue
            positive[(item.target_id,item.aspect)]={'review_id':review.id,'target_id':item.target_id,'version':review.target_versions.get(item.target_id),
                'aspect':item.aspect,'status':item.status,'source_ids':item.source_ids,'explanation':item.rationale,
                'limitations':item.limitations,'basis_status':'current' if basis else 'historical_dependency_basis_unrecorded'}
    open_issues=[{'id':i.id,'target_id':i.target_id,'version':i.target_version,'aspect':i.aspect,'explanation':i.explanation,
        'source_ids':i.source_ids,'disposition':i.disposition,'reason':i.reason} for i in issues if not i.resolved_by]
    for r in list(positive.values())+open_issues:sources.update(r['source_ids'])
    return {'judgments':list(positive.values()),'open_issues':open_issues,
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
        'unit':unit.model_dump(mode='json',exclude={'semantic_readiness','obligation_checks','remaining_obligation_ids'}),
        'verification_continuation':state.question_continuations.get(unit.id,{}),
        'claims':[c.model_dump(mode='json') for c in state.claims if c.id in ids],
        'bindings':[b.model_dump(mode='json') for b in state.bindings if b.id in ids],
        'relations':[r.model_dump(mode='json') for r in state.relations if r.id in ids or r.id in unit.relation_ids],
        'obligation_progress':{'checked_scopes':unit.obligation_checks,'remaining':unit.remaining_obligation_ids or unit.obligation_ids}}


def local_basis(state,unit):
    materials,ids=material_closure(state,[unit.id])
    materials.update(state.task_attachments.get('unit:'+unit.id,[]))
    from .sources import ranges
    spans=[{'file':f,'content_digest':v,'ranges':r} for (f,v),r in sorted(ranges([m for m in state.materials if m.id in materials]).items())]
    return {'versions':{o.id:o.version for o in state.claims+state.bindings+state.relations+state.units if o.id in ids},
        'materials':spans,'model_ids':sorted(relevant_model_ids(state,unit))}
