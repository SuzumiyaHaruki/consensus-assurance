"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


def required_aspects(obj):
    kind=getattr(obj,'kind',None)
    if hasattr(obj,'bundle_path'):return {'checker_correspondence'}
    return {'applicability','decomposition'} if kind=='obligation' else {'applicability'} if kind in {'goal','assumption'} else {'decomposition'}


def material_closure(state, ids):
    objects={x.id:x for x in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}
    wanted=set();visited=set();todo=list(ids)
    while todo:
        id=todo.pop()
        if id in visited:continue
        visited.add(id);obj=objects.get(id)
        if obj is None:continue
        wanted.update(getattr(obj,'source_ids',[]))
        if hasattr(obj,'source') and hasattr(obj,'target'):todo.extend([obj.source,obj.target])
        for association in getattr(obj,'associations',[]):
            todo.append(association.claim_id);wanted.update(association.source_ids)
        for use in getattr(obj,'code_uses',[]):
            todo.extend(use.claim_ids+use.relation_ids);wanted.update(use.source_ids)
        anchor=getattr(obj,'anchor',None)
        if anchor:wanted.add(anchor.material_id)
        question=getattr(obj,'audit_question',None)
        if question:wanted.update(question.source_ids)
        for point in getattr(obj,'coverage_intent',[])+(question.points if question else []):wanted.update(point.source_ids)
        basis=getattr(obj,'grounding',None)
        if basis:
            wanted.update(basis.behavior_ids+basis.expectation_ids);todo.extend(basis.binding_ids)
        todo.extend(getattr(obj,'binding_ids',[]));todo.extend(getattr(obj,'goal_ids',[]));todo.extend(getattr(obj,'obligation_ids',[]));todo.extend(getattr(obj,'relation_ids',[]))
        if hasattr(obj,'file'):
            wanted.update(m.id for m in state.materials if m.file==obj.file and m.start_line<=obj.end_line and m.end_line>=obj.start_line)
    return wanted,visited


def valid_supersession(state,review,task):
    objects={x.id:x for x in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}
    if task.id not in review.supersedes_task_ids:return False
    if task.unit_id and task.unit_id!=review.unit_id:return False
    if task.unit_version is not None and task.unit_version!=review.unit_version:return False
    if task.model_id and task.model_id!=review.model_id:return False
    if not set(task.material_ids)<=set(review.material_ids):return False
    for id,version in task.target_versions.items():
        if id not in objects or review.target_versions.get(id)!=version:return False
        items=[i for i in review.items if i.target_id==id and i.status=='no_issue_found' and not i.limitations]
        if not required_aspects(objects[id])<={i.aspect for i in items}:return False
    return bool(task.target_versions)


def validate_resolutions(state, task, reply):
    from consensus_assurance.core.types import SemanticReview
    if reply.resolves_issue_ids or reply.supersedes_task_ids:
        if not reply.resolution_rationale.strip():raise ValueError('Explicit resolution requires attributed rationale')
    current={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}
    review=SemanticReview(task_id=task.id,check_id='validation',unit_id=task.unit_id,unit_version=task.unit_version,model_id=task.model_id,target_versions={i:current[i] for i in task.target_ids},material_ids=task.material_ids or [m.id for m in state.materials],items=reply.items,origin='agent',supersedes_task_ids=reply.supersedes_task_ids)
    for id in reply.supersedes_task_ids:
        old=next((t for t in state.inquiry_tasks if t.id==id),None)
        if old is None or not valid_supersession(state,review,old):raise ValueError('Superseding review does not cover the old task scope, versions and aspects')
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
        matching=[i for i in reply.items if i.target_id==resolution_target and i.aspect==issue.aspect and i.status=='no_issue_found' and not i.limitations]
        if not matching or not any(set(issue.source_ids)<=set(i.source_ids) for i in matching):
            raise ValueError('Resolution must address the specific prior issue and its material evidence')
        if issue.model_id and task.model_id!=issue.model_id:
            model=next((m for m in state.models if m.id==task.model_id),None)
            if model is None:raise ValueError('Checker issue resolution requires an explicit current model')


def record_dispositions(state,review,reply,followup_ids):
    for old in state.inquiry_tasks:
        if valid_supersession(state,review,old):old.superseded_by=review.id
    for issue in state.review_issues:
        if issue.id in reply.resolves_issue_ids:
            issue.resolved_by=review.id;issue.resolution_model_id=review.model_id
            issue.resolution_checks=[c.id for c in state.checks if c.model_id==review.model_id and c.action=='model_check']
    for item in reply.items:
        if item.status=='no_issue_found' and not item.limitations:continue
        disposition='reading' if reply.requests else 'revision' if reply.revision else 'investigation' if followup_ids else 'blocked'
        state.review_issues.append(ReviewIssue(review_id=review.id,target_id=item.target_id,target_version=review.target_versions[item.target_id],aspect=item.aspect,model_id=review.model_id,source_ids=item.source_ids,explanation=item.explanation,disposition=disposition,task_ids=followup_ids,
            reason='Follow-up evidence or semantic review is required' if disposition!='blocked' else 'No actionable follow-up was supplied; the issue remains unresolved and requires planning'))


def readiness(state,unit):
    objects={x.id:x for x in [*state.claims,*state.bindings,*state.relations,*state.units]}
    ids=set(unit.goal_ids+unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id])
    materials,_=material_closure(state,ids)
    reviews=[];missing=[];disputed=[]
    for id in ids:
        obj=objects[id]
        for aspect in required_aspects(obj):
            candidates=[r for r in state.semantic_reviews if r.target_versions.get(id)==obj.version and materials<=set(r.material_ids) and any(i.target_id==id and i.aspect==aspect for i in r.items)]
            if not candidates:missing.append(id+':'+aspect);continue
            review=candidates[-1];reviews.append(review.id)
            if any(i.target_id==id and i.aspect==aspect and (i.status!='no_issue_found' or i.limitations) for i in review.items):disputed.append(id+':'+aspect)
    disputed.extend(i.id for i in state.review_issues if i.target_id in ids and not i.resolved_by)
    return {'unit_version':unit.version,'target_versions':{id:objects[id].version for id in ids},'material_ids':sorted(materials),
        'review_ids':sorted(set(reviews)),'status':'unreviewed' if missing else 'disputed' if disputed else 'reviewed',
        'unresolved':missing+disputed,'purpose':unit.rationale,
        'limitation':'Exploratory checking is allowed; unreviewed or disputed semantics cannot confirm implementation defects' if missing or disputed else 'Review is provisional and scoped, not proof'}
