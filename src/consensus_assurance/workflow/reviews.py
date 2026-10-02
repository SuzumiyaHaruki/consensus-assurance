"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


from .review_contract import required_aspects
from .sources import includes


def review_objects(state):
    return {o.id:o for o in state.claims+state.bindings+state.relations+state.units+state.direct_checks+state.question_candidates}


def issue_challenges(state,issue):
    review=next((r for r in state.semantic_reviews if r.id==issue.review_id),None)
    item=next((x for x in review.items if x.target_id==issue.target_id and x.aspect==issue.aspect),None) if review else None
    return item.counterevidence if item and item.counterevidence else [c['text'] for c in issue.conditions] or [issue.explanation]


def material_closure(state, ids):
    objects=review_objects(state)
    from .sources import dependency_closure
    wanted,visited=dependency_closure(objects,ids)
    for id in ids:
        artifact=objects.get(id)
        if artifact is None or not hasattr(artifact,'plan_path'):continue
        from .direct_checks import load_plan
        plan=load_plan(artifact.plan_path)
        dependencies=[plan.claim_id,*plan.binding_ids,*(binding for monitor in plan.monitors for binding in monitor.binding_ids)]
        for basis in [plan.harness.legality,*(monitor.grounding for monitor in plan.monitors)]:
            wanted.update(basis.source_ids+basis.expectation_ids)
            dependencies.extend(basis.binding_ids)
        source_ids,_=dependency_closure(objects,dependencies)
        wanted.update(source_ids)
    for id in visited:
        obj=objects[id]
        if hasattr(obj,'question'):wanted.update(obj.question.source_ids)
        if hasattr(obj,'file'):
            wanted.update(m.id for m in state.materials if m.file==obj.file and m.content_digest==obj.content_digest and m.start_line<=obj.end_line and m.end_line>=obj.start_line)
    return wanted,visited


def lineage(state, artifact):
    objects = review_objects(state)
    result = {artifact.id}
    parent = getattr(artifact, 'previous_id', None)
    while parent and parent not in result:
        result.add(parent)
        parent = getattr(objects.get(parent), 'previous_id', None)
    return result


def open_issues(state, artifact=None):
    """A resolution applies to its answering version and descendants, never older inputs."""
    if artifact is None:
        superseded={a.previous_id for a in state.direct_checks}
        current=[a for a in state.direct_checks if a.id not in superseded]
        current+=state.question_candidates
        ids={i.id for a in current for i in open_issues(state,a)}
        return [i for i in state.review_issues if i.id in ids]
    ancestors=lineage(state,artifact)
    relevant=ancestors | set(getattr(artifact,'graph_versions',{}))
    relevant.update(u.candidate_id for u in state.units if u.id==getattr(artifact,'unit_id',None))
    resolved={id for r in state.semantic_reviews if set(r.target_versions)&relevant for id in r.resolves_issue_ids}
    return [i for i in state.review_issues if i.target_id in relevant and i.id not in resolved]


def retain_conflicts(state, artifact, plan):
    """Retain exact input conflicts in the existing issue/resolution chain."""
    from .repair_policy import condition_records
    claim=next(c for c in state.claims if c.id==plan.claim_id)
    ancestors=lineage(state,artifact)
    pending={i.id for i in open_issues(state,artifact)}
    bases=[(claim,'grounding',claim.grounding),(artifact,'harness',plan.harness.legality)]
    bases.extend((artifact,'monitor/'+m.id,m.grounding) for m in plan.monitors)
    for owner,field,basis in bases:
        sources=list(dict.fromkeys(basis.source_ids+basis.expectation_ids))
        for record in condition_records(basis.conflicts,owner.id+'/'+field,sources,owner.id,owner.version):
            inherited=any((owner is not artifact or i.id in pending) and i.target_id in (ancestors if owner is artifact else {owner.id}) and
                (owner is artifact or i.target_version==owner.version) and any(c['text']==record['text'] and
                c['id'].startswith(i.target_id+'/'+field+'/condition/') for c in i.conditions) for i in state.review_issues)
            if inherited:continue
            state.review_issues.append(ReviewIssue(review_id='input:'+artifact.id,target_id=owner.id,
                target_version=owner.version,aspect='applicability',source_ids=sources,
                explanation=record['text'],reason='Fixed input counterevidence needs an attributed resolution',
                conditions=[record],disposition='investigation'))


def validate_driver_repair(state, prior, old, plan, issue_ids, changed_inputs):
    """Authorize an attributed draft answer; only subsequent review can discharge it."""
    issues={i.id:i for i in open_issues(state,prior) if i.target_id in lineage(state,prior) and
        (i.aspect=='applicability' or set(i.challenged_components)&{'driver','configuration','initialization'})}
    basis=plan.harness.legality
    if not issue_ids or len(set(issue_ids))!=len(issue_ids) or not set(issue_ids)<=issues.keys():
        raise ValueError('Driver premise repair must name exact open applicability or input issues on its lineage')
    if not changed_inputs or not basis.derivation.strip() or not basis.source_ids or basis.binding_ids!=old.harness.legality.binding_ids:
        raise ValueError('Driver premise repair needs changed inputs and sourced legality with preserved bindings')
    removed=set(old.harness.legality.conflicts)-set(basis.conflicts)
    answered={c['text'] for id in issue_ids for c in issues[id].conditions
        if c['id'].startswith(issues[id].target_id+'/harness/condition/')}
    if not removed<=answered:
        raise ValueError('Removed counterevidence needs its exact harness condition issue; no anonymous conflict removal')


def repair_changes(old, artifact, version=None):
    """Compare the challenged component, never infer it from the review column."""
    if not hasattr(old,'plan_path'):
        changed=artifact.graph_versions.get(old.id)!=version
        return {c:changed if c in {'expectation','scope'} else False for c in
            ('configuration','initialization','driver','observation','oracle','expectation','scope')}
    from .direct_checks import load_plan
    from .encoding import direct_changes
    before, after = load_plan(old.plan_path), load_plan(artifact.plan_path)
    changes=direct_changes(before,after)
    inputs,predicate,observation=changes['inputs'],changes['oracle'],changes['observation']
    semantic = old.graph_versions != artifact.graph_versions
    return {'configuration':inputs, 'initialization':inputs, 'driver':inputs,
        'observation':inputs or predicate or observation, 'oracle':predicate,
        'expectation':semantic, 'scope':semantic or old.scope != artifact.scope}


def accept_review(state, submission, operation_id):
    from consensus_assurance.core.types import SemanticReview
    from .review_contract import validate_contract
    objects = review_objects(state)
    artifact = objects.get(submission.artifact_id)
    candidate=artifact if hasattr(artifact,'question') else None
    if artifact is None or not (candidate or hasattr(artifact, 'plan_path')):
        raise ValueError('Review requires an accepted artifact or Candidate ID')
    checks = [c for c in state.checks if (c.direct_check_id == artifact.id)
              and c.status.value == 'completed']
    if not checks and not candidate:
        raise ValueError('Review requires an actual completed execution of the selected artifact')
    sources = [m.id for m in state.materials]
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    errors = []
    try:validate_contract(state, artifact.id, submission.review_items)
    except DiagnosticError as exc:errors.extend(exc.diagnostics)
    if not required_aspects(artifact) <= {i.aspect for i in submission.review_items}:
        raise ValueError('Review must address the supplied whole-artifact contract')
    if any(not i.source_ids or not i.rationale.strip() for i in submission.review_items):
        raise ValueError('Review needs actual source citations and substantive reasoning')
    pending = {i.id:i for i in open_issues(state,artifact)}
    if len({r.issue_id for r in submission.resolutions}) != len(submission.resolutions):
        raise ValueError('Duplicate issue resolution')
    def error(index, issue, message, **details):
        errors.append(Diagnostic(code='issue_resolution', category='format',
            object_ids=[issue.id] if issue else [], paths=[f'/resolutions/{index}'],
            message=message, details=details, allowed=['read','representation','semantic_revision']))
    evidence = {x.id for name in ('checks','direct_checks','evidence','findings','semantic_reviews')
        for x in getattr(state,name)}
    for index, resolution in enumerate(submission.resolutions):
        issue = pending.get(resolution.issue_id)
        if not issue:
            error(index, issue, 'Resolution must address an open issue on this artifact, lineage or semantic dependencies',
                issue_id=resolution.issue_id, artifact_id=artifact.id)
            continue
        unknown = set(resolution.source_ids)-set(sources)
        if unknown:error(index, issue, 'source_ids accepts acquired Material IDs', unknown_material_ids=sorted(unknown))
        unknown_evidence = set(resolution.evidence_ids)-evidence
        if unknown_evidence:error(index, issue, 'evidence_ids accepts retained execution, artifact, evidence or review IDs', unknown_evidence_ids=sorted(unknown_evidence))
        if not resolution.rationale.strip():error(index, issue, 'Explain how the answer addresses this issue', original_question=issue.explanation)
        if issue.conditions:
            from .repair_policy import classify_conditions
            dispositions = classify_conditions(state, [c['text'] for c in issue.conditions],
                resolution.condition_dispositions, resolution.source_ids, records=issue.conditions)
            if any(d.applies_to == 'current_judgment' for d in dispositions):
                raise ValueError('Current unresolved conditions cannot discharge their issue')
        item = next((i for i in submission.review_items if i.aspect == issue.aspect and i.status == 'no_issue_found'), None)
        if not item or item.counterevidence or not includes(state,resolution.source_ids,item.source_ids):
            error(index, issue, 'Resolution needs matching substantive review with its answer sources and no current counterevidence', aspect=issue.aspect, answer_source_ids=resolution.source_ids)
        others = {i.id for i in open_issues(state) if i.id != issue.id and i.parent_issue_id != issue.id}
        if not set(resolution.residual_issue_ids) <= others or issue.explanation in resolution.scope_limitations:
            raise ValueError('The original dispute cannot be renamed as a residual scope boundary')
        components = issue.challenged_components
        if components:
            old = objects[issue.target_id]
            executed = any(c.action == 'direct_check' and c.exit_code == 0 for c in checks)
            changes = repair_changes(old,artifact,issue.target_version)
            unchanged = [c for c in components if not changes[c]]
            sourced_answer = (artifact.id==old.id and
                not includes(state,resolution.source_ids,issue.source_ids))
            if not sourced_answer and (artifact.id == old.id or unchanged or not executed):
                error(index, issue, 'Repair needs a new artifact, the challenged component change and matching fresh execution',
                    challenged_components=components, unchanged_components=unchanged, fresh_execution=executed,
                    original_artifact=old.id, answering_artifact=artifact.id)
    if errors:raise DiagnosticError(errors)
    review = SemanticReview(task_id='review:' + operation_id, check_id=operation_id,
        target_versions={artifact.id:artifact.question.audit_spec_version if candidate else artifact.version}, material_ids=sources, items=submission.review_items,
        origin='mock' if state.mode == 'mock' else 'agent', unit_id=getattr(artifact,'unit_id',None) or None,
        unit_version=next((u.version for u in state.units if u.id == getattr(artifact,'unit_id',None)), None),
        resolves_issue_ids=[r.issue_id for r in submission.resolutions])
    state.semantic_reviews.append(review)
    for resolution in submission.resolutions:
        issue = next(i for i in state.review_issues if i.id == resolution.issue_id)
        issue.resolved_by = review.id
        issue.resolution_basis = resolution.model_dump(mode='json')
        issue.resolution_checks = [c.id for c in checks]
    for item in submission.review_items:
        if item.status == 'no_issue_found':
            continue
        if any(i.target_id == artifact.id and i.aspect == item.aspect and i.explanation == item.rationale
               and not i.resolved_by for i in state.review_issues):
            continue
        existing=next((i for i in pending.values() if i.target_id==artifact.id and i.aspect==item.aspect and
            i.conditions and item.counterevidence==[c['text'] for c in i.conditions]),None)
        if existing:
            existing.prior_review_ids.append(existing.review_id)
            existing.review_id=review.id
            existing.challenged_components=item.challenged_components if item.status=='revision_needed' else []
            continue
        state.review_issues.append(ReviewIssue(review_id=review.id, target_id=artifact.id,
            target_version=artifact.question.audit_spec_version if candidate else artifact.version, aspect=item.aspect,
            source_ids=item.source_ids, explanation=item.rationale, reason=item.rationale,
            disposition='reading' if item.status == 'needs_reading' else 'investigation',
            challenged_components=item.challenged_components if item.status=='revision_needed' else []))
    return review
