"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


from .review_contract import required_aspects, target_contract
from .sources import citation_status, includes


def review_objects(state):
    return {o.id:o for o in state.claims+state.bindings+state.relations+state.units+state.models+state.direct_checks}


def material_closure(state, ids):
    objects=review_objects(state)
    from .sources import dependency_closure
    wanted,visited=dependency_closure(objects,ids)
    for id in visited:
        obj=objects[id]
        if hasattr(obj,'file'):
            wanted.update(m.id for m in state.materials if m.file==obj.file and m.content_digest==obj.content_digest and m.start_line<=obj.end_line and m.end_line>=obj.start_line)
    return wanted,visited


def valid_supersession(state,review,task):
    objects=review_objects(state)
    if task.id not in review.supersedes_task_ids:return False
    if task.unit_id and task.unit_id!=review.unit_id:return False
    if task.unit_version is not None and task.unit_version!=review.unit_version:return False
    if task.model_id and task.model_id!=review.model_id:return False
    if not includes(state,task.material_ids,review.material_ids):return False
    for id,version in task.target_versions.items():
        if id not in objects or review.target_versions.get(id)!=version:return False
        if review.context_receipt_id:
            contract=target_contract(state,objects[id])
            if review.context_dependencies.get(id,{}).get('dependency_versions')!=contract['dependency_versions'] or not includes(state,contract['required_material_ids'],review.material_ids):return False
        items=[i for i in review.items if i.target_id==id and i.status=='no_issue_found' and not i.limitations and not i.counterevidence]
        if not set(task.requested_aspects.get(id,required_aspects(objects[id])))<={i.aspect for i in items}:return False
    return bool(task.target_versions)


def validate_resolutions(state, task, reply):
    from consensus_assurance.core.types import SemanticReview
    if reply.resolves_issue_ids or reply.supersedes_task_ids:
        if not reply.resolution_rationale.strip():raise ValueError('Explicit resolution requires attributed rationale')
    current={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models,*state.direct_checks]}
    review=SemanticReview(task_id=task.id,check_id='validation',unit_id=task.unit_id,unit_version=task.unit_version,model_id=task.model_id,target_versions={i:current[i] for i in task.target_ids},material_ids=task.material_ids if task.context_receipt_id else task.material_ids or [m.id for m in state.materials],context_receipt_id=task.context_receipt_id,context_dependencies=task.context_dependencies,items=reply.items,origin='agent',supersedes_task_ids=reply.supersedes_task_ids)
    for id in reply.supersedes_task_ids:
        old=next((t for t in state.inquiry_tasks if t.id==id),None)
        if old is None or not valid_supersession(state,review,old):raise ValueError('Superseding review does not cover the old task scope, versions and aspects')
    explicit={r.issue_id:r for r in reply.resolutions}
    if len(explicit)!=len(reply.resolutions) or not set(explicit)<=set(reply.resolves_issue_ids):raise ValueError('Issue resolutions must uniquely refer to requested issue dispositions')
    def fail(issue,message,code='issue_resolution_basis',sources=None):
        from consensus_assurance.core.diagnostics import DiagnosticError,Diagnostic
        paths=['/resolutions','/resolves_issue_ids']
        if code=='issue_citation_missing':paths=[f'/items/{n}/source_ids' for n,i in enumerate(reply.items) if i.target_id==issue.target_id and i.aspect==issue.aspect]
        raise DiagnosticError([Diagnostic(code=code,category='format',object_ids=[issue.target_id],paths=paths,material_ids=sources if sources is not None else issue.source_ids,
            message=message,allowed=['representation'] if code=='issue_citation_missing' else ['representation','read'],details={'issue':issue.model_dump(mode='json'),'required':'Supply an issue-specific resolution with source evidence and independent residual issues, or retain this issue unresolved'})])
    for id in reply.resolves_issue_ids:
        issue=next((i for i in state.review_issues if i.id==id and i.resolved_by is None),None)
        if issue is None:raise ValueError('Resolution references an unavailable open issue')
        if issue.needs_recheck and not any(c.model_id==task.model_id and c.action=='model_check' and c.status.value=='completed' and c.outcome in {'holds','counterexample'} and c.search_fingerprint==next((m.search_fingerprint for m in state.models if m.id==task.model_id),None) for c in state.checks):raise ValueError('Encoding issue resolution requires an actual matching model recheck')
        resolution_target=issue.target_id
        if issue.id in task.resolution_issue_ids and issue.model_id!=task.model_id:
            from .encoding import issue_models
            from pathlib import Path
            model=next((m for m in state.models if m.id==task.model_id),None)
            old=issue_models(state,issue,model) if model else None
            checks=[c for c in state.checks if model and c.model_id==model.id and c.action=='model_check' and c.status.value=='completed' and c.search_fingerprint==model.search_fingerprint and c.outcome in {'holds','counterexample'}]
            if not old or Path(old.path).read_text()==Path(model.path).read_text() or not checks:
                raise ValueError('Old checker issue needs a related changed encoding and actual current search; harness-only or unrelated models cannot resolve it')
            resolution_target=model.id
        resolution=explicit.get(id)
        matching=[i for i in reply.items if i.target_id==resolution_target and i.aspect==issue.aspect and i.status=='no_issue_found']
        if resolution:
            if resolution.target_version!=issue.target_version or resolution.original_question!=issue.explanation or not resolution.rationale.strip():fail(issue,'The disposition must address the exact issue/version with attributed reasoning')
            supplied=task.material_ids if task.context_receipt_id else task.material_ids or [m.id for m in state.materials]
            status=citation_status(state,resolution.source_ids,supplied)
            unknown=[id for id,v in status.items() if v=='unknown']
            absent=[id for id,v in status.items() if v=='cached_not_provided']
            if unknown:fail(issue,'Unknown citations need a source identity correction or actual acquisition', 'issue_unknown_source',unknown)
            if absent:fail(issue,'Cited ranges are cached but were not supplied; attach them before evaluating this explanation', 'issue_context_not_provided',absent)
            # Old gap citations remain in the issue. New evidence may answer it without
            # repeating every old citation; exact question, rationale and counterevidence
            # dispositions below still apply. Citation validity is not semantic proof.
            if not any(includes(state,resolution.source_ids,i.source_ids) for i in matching):
                fail(issue,'The matching analysis must cite the evidence used by its issue disposition', 'issue_citation_missing',resolution.source_ids)
            others={i.id:i for i in state.review_issues if not i.resolved_by}
            if any(x not in others or x==id or others[x].parent_issue_id==id for x in resolution.residual_issue_ids):fail(issue,'An unresolved root or child cannot be renamed as an independent residual')
            if any(issue.explanation.strip().casefold()==x.strip().casefold() for x in resolution.scope_limitations):fail(issue,'The unresolved original question cannot be relabeled as a scope boundary')
            from .repair_policy import classify_conditions,condition_records
            remaining=list(dict.fromkeys(x for i in matching for x in i.counterevidence+i.limitations if x not in resolution.scope_limitations or x in i.counterevidence))
            if remaining:
                records=condition_records(remaining,task.id+'/'+resolution_target+'/'+issue.aspect,resolution.source_ids,resolution_target,current[resolution_target])
                original={r['text']:r for r in issue.conditions}
                records=[original.get(r['text'],r) for r in records]
                index=reply.resolutions.index(resolution)
                from consensus_assurance.core.diagnostics import DiagnosticError
                try:
                    classified=classify_conditions(state,remaining,resolution.condition_dispositions,supplied,records=records,
                        paths=[f'/resolutions/{index}/condition_dispositions'],object_ids=[resolution_target])
                except DiagnosticError as exc:
                    for diagnostic in exc.diagnostics:
                        diagnostic.details.update(issue=issue.model_dump(mode='json'),
                            current_items=[{'path':f'/items/{n}','item':item.model_dump(mode='json')} for n,item in enumerate(reply.items) if item in matching],
                            resolution_path=f'/resolutions/{index}')
                    raise
                if any(c.applies_to!='independent_scope' for c in classified):fail(issue,'A condition still affects the current judgment; keep the issue open')
            if not matching:fail(issue,'An issue disposition needs matching substantive analysis')
        elif not matching or any(i.counterevidence or i.limitations for i in matching) or not any(set(issue.source_ids)<=set(i.source_ids) for i in matching):
            fail(issue,'Resolution must address the specific prior issue and its material evidence; independent boundaries need an explicit issue disposition')
        if issue.model_id and task.model_id!=issue.model_id:
            model=next((m for m in state.models if m.id==task.model_id),None)
            if model is None:raise ValueError('Checker issue resolution requires an explicit current model')


def record_dispositions(state,review,reply,followup_ids):
    for old in state.inquiry_tasks:
        if valid_supersession(state,review,old):old.superseded_by=review.id
    for issue in state.review_issues:
        if issue.id in reply.resolves_issue_ids:
            issue.resolved_by=review.id;issue.resolution_model_id=review.model_id
            issue.resolution_basis=next((r.model_dump(mode='json') for r in reply.resolutions if r.issue_id==issue.id),{'rationale':reply.resolution_rationale})
            issue.resolution_checks=[c.id for c in state.checks if c.model_id==review.model_id and c.action=='model_check']
    for item in reply.items:
        independent={x for r in reply.resolutions if r.issue_id in reply.resolves_issue_ids and any(i.id==r.issue_id and i.target_id==item.target_id and i.aspect==item.aspect for i in state.review_issues) for x in r.scope_limitations}
        unresolved=[x for x in item.counterevidence+item.limitations if x not in independent or x in item.counterevidence]
        if item.status=='no_issue_found' and not item.counterevidence:continue
        disposition='reading' if reply.requests else 'revision' if reply.revision else 'investigation' if followup_ids else 'blocked'
        prior=next((i for i in state.review_issues if not i.resolved_by and i.target_id==item.target_id and i.target_version==review.target_versions[item.target_id] and i.aspect==item.aspect and i.explanation==item.rationale),None)
        if prior:
            prior.source_ids=list(dict.fromkeys(prior.source_ids+item.source_ids))
            prior.prior_review_ids=list(dict.fromkeys(prior.prior_review_ids+[review.id]));prior.task_ids=list(dict.fromkeys(prior.task_ids+followup_ids));continue
        from .repair_policy import condition_records
        state.review_issues.append(ReviewIssue(conditions=condition_records(unresolved,review.task_id+'/'+item.target_id+'/'+item.aspect,item.source_ids,item.target_id,review.target_versions[item.target_id]),review_id=review.id,target_id=item.target_id,target_version=review.target_versions[item.target_id],aspect=item.aspect,model_id=review.model_id,source_ids=item.source_ids,explanation=item.rationale,disposition=disposition,task_ids=followup_ids,
            reason='Follow-up evidence or semantic review is required' if disposition!='blocked' else 'No actionable follow-up was supplied; the issue remains unresolved and requires planning'))


def readiness(state,unit):
    objects={x.id:x for x in [*state.claims,*state.bindings,*state.relations,*state.units]}
    ids=set(unit.obligation_ids+[unit.id])
    relevant=ids|set(unit.binding_ids+unit.relation_ids)
    ids.update(i.target_id for i in state.review_issues if not i.resolved_by and i.target_id in relevant)
    materials,_=material_closure(state,ids)
    reviews=[];missing=[];disputed=[]
    for id in ids:
        obj=objects[id]
        dependency=target_contract(state,obj)
        needed=set(dependency['required_material_ids'])
        for aspect in required_aspects(obj):
            candidates=[r for r in state.semantic_reviews if r.target_versions.get(id)==obj.version and includes(state,needed,r.material_ids) and all(r.context_dependencies.get(id,{}).get('dependency_versions',dependency['dependency_versions']).get(k)==v for k,v in dependency['dependency_versions'].items()) and any(i.target_id==id and i.aspect==aspect for i in r.items)]
            if not candidates:missing.append(id+':'+aspect);continue
            review=candidates[-1];reviews.append(review.id)
            if any(i.target_id==id and i.aspect==aspect and (i.status!='no_issue_found' or i.counterevidence) for i in review.items):disputed.append(id+':'+aspect)
    disputed.extend(i.id for i in state.review_issues if i.target_id in relevant and not i.resolved_by)
    return {'unit_version':unit.version,'target_versions':{id:objects[id].version for id in ids},'material_ids':sorted(materials),
        'review_ids':sorted(set(reviews)),'status':'unreviewed' if missing else 'disputed' if disputed else 'reviewed',
        'unresolved':missing+disputed,'purpose':unit.rationale,
        'limitation':'Exploratory checking is allowed; unreviewed or disputed semantics cannot confirm implementation defects' if missing or disputed else 'Review is provisional and scoped, not proof'}
