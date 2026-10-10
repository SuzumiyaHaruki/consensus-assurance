"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


from .review_contract import required_aspects
from .sources import includes


def review_objects(state):
    return {o.id:o for o in state.claims+state.bindings+state.relations+state.units+state.direct_checks+state.question_candidates}


def issue_review_item(state,issue):
    review=next((r for r in state.semantic_reviews if r.id==issue.review_id),None)
    return next((x for x in review.items if x.target_id==issue.target_id and x.aspect==issue.aspect),None) if review else None


def issue_challenges(state,issue):
    item=issue_review_item(state,issue)
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
    claim=next(c for c in state.claims if c.id==plan.claim_id)
    ancestors=lineage(state,artifact)
    pending={i.id for i in open_issues(state,artifact)}
    bases=[(claim,'grounding',claim.grounding),(artifact,'harness',plan.harness.legality)]
    bases.extend((artifact,'monitor/'+m.id,m.grounding) for m in plan.monitors)
    for owner,field,basis in bases:
        sources=list(dict.fromkeys(basis.source_ids+basis.expectation_ids))
        for n,text in enumerate(dict.fromkeys(basis.conflicts + basis.unresolved),1):
            record={'id':owner.id+'/'+field+'/condition/'+str(n),'text':text,
                'target_id':owner.id,'version':owner.version,'source_ids':sources}
            inherited=any((owner is not artifact or i.id in pending) and i.target_id in (ancestors if owner is artifact else {owner.id}) and
                (owner is artifact or i.target_version==owner.version) and any(c['text']==record['text'] and
                c['id'].startswith(i.target_id+'/'+field+'/condition/') for c in i.conditions) for i in state.review_issues)
            if inherited:continue
            state.review_issues.append(ReviewIssue(review_id='input:'+artifact.id,target_id=owner.id,
                target_version=owner.version,aspect='applicability',source_ids=sources,
                explanation=record['text'],reason='Fixed input counterevidence needs an attributed resolution',
                conditions=[record],disposition='investigation'))


def resolution_executions(state, artifact, resolution, items):
    """Check retained associations and observations; causal sufficiency remains a review judgment."""
    from consensus_assurance.adapters.runners.experiment import extract_events
    from .direct_checks import load_plan, compute_assessment, validate_execution_attribution
    objects = review_objects(state)
    versions = {id:o.version for id,o in objects.items()}
    related = {artifact.id, getattr(artifact, 'unit_id', None), getattr(artifact, 'claim_id', None)}
    related.update(u.candidate_id for u in state.units if u.id in related)
    related.update(u.id for u in state.units if u.candidate_id == artifact.id)
    for id, indices in resolution.executions.items():
        check = next((c for c in state.checks if c.id == id), None)
        if check is None or check.action not in {'direct_check','exploration'}:
            raise ValueError('Resolution executions require actual target CheckRun IDs: ' + id)
        if check.snapshot_id != state.snapshot.id or check.status.value != 'completed':
            raise ValueError('Resolution execution has a different snapshot or is incomplete: ' + id)
        owner = next((a for a in state.direct_checks if a.id == check.direct_check_id), None)
        linked = any('accepted_versions' in s and {id} <= set(s.get('feedback',{}).get('ref_ids',[])) and
            related & set(s['feedback']['ref_ids']) for s in state.selections)
        dependency = owner and owner.claim_id != getattr(artifact, 'claim_id', None) and owner.claim_id in getattr(artifact, 'graph_versions', {}) and (
            owner.graph_versions.get(owner.claim_id) == artifact.graph_versions[owner.claim_id])
        if owner != artifact and not (linked or dependency or hasattr(artifact, 'question') and owner and owner.unit_id in related):
            raise ValueError('Resolution execution needs the answering artifact or an explicit dependency/handoff association: ' + id)
        events = extract_events(check)
        if (not indices or len(set(indices)) != len(indices) or
                any(type(i) is not int or not 0 <= i < len(events) for i in indices) or
                any(e.get('event') == 'invalid_observation' for e in events)):
            raise ValueError('Resolution needs valid decisive parsed observation indices: ' + id)
        if check.parameters.get('changed_target_files') or check.parameters.get('lock_unchanged') is False:
            raise ValueError('Resolution execution changed protected inputs: ' + id)
        if check.action == 'direct_check':
            if (owner is None or owner.snapshot_id != check.snapshot_id or
                    any(versions.get(k) != v for k,v in owner.graph_versions.items())):
                raise ValueError('Resolution execution has missing or stale fixed artifact inputs: ' + id)
            plan = load_plan(owner.plan_path)
            unit = next(u for u in state.units if u.id == owner.unit_id)
            observed = compute_assessment(state, unit, owner, plan, check, events)
            if observed['prerequisites']['status'] != 'matched':
                raise ValueError('Resolution execution has unmatched prerequisites: ' + id)
        else:
            actions = [*state.action_history, *([state.pending_action] if state.pending_action else [])]
            operation = next((a.logical_input.get('operation_id') for a in actions if a.id == check.pending_action_id), None)
            if not any(s['operation_id'] == operation and s['action'] == 'explore' and 'accepted_versions' in s for s in state.selections):
                raise ValueError('Resolution exploration lacks accepted fixed inputs: ' + id)
        if check.exit_code != 0 or check.outcome == 'not_applicable':
            opinions = items if owner == artifact else [i for r in state.semantic_reviews
                if owner and r.target_versions.get(owner.id) == owner.version for i in r.items]
            item = next((i for i in reversed(opinions) if i.execution_attribution and i.execution_attribution.check_id == id), None)
            if not owner or not item:
                raise ValueError('Resolution execution requires successful completion or valid narrow failure attribution: ' + id)
            validate_execution_attribution(state, owner, plan, check, observed['properties'], item)


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
    for item in submission.review_items:
        if item.execution_attribution is None:continue
        if candidate:raise ValueError('Execution attribution requires a direct-check artifact')
        from .direct_checks import load_plan, compute_assessment, validate_execution_attribution
        from consensus_assurance.adapters.runners.experiment import extract_events
        check=next((c for c in checks if c.id==item.execution_attribution.check_id),None)
        if check is None:raise ValueError('Execution attribution must identify a completed execution of this artifact')
        plan=load_plan(artifact.plan_path)
        unit=next(u for u in state.units if u.id==artifact.unit_id)
        observed=compute_assessment(state,unit,artifact,plan,check,extract_events(check))
        validate_execution_attribution(state,artifact,plan,check,observed['properties'],item)
        if observed['parsing_errors'] or observed['prerequisites']['status']!='matched':
            raise ValueError('Execution attribution requires complete parsing and matched prerequisites')
    pending = {i.id:i for i in open_issues(state,artifact)}
    if submission.resolutions and hasattr(artifact, 'graph_versions') and (
            artifact.snapshot_id != state.snapshot.id or any(a.previous_id == artifact.id for a in state.direct_checks) or
            any(objects.get(id) is None or objects[id].version != v for id,v in artifact.graph_versions.items())):
        raise ValueError('Resolve issues against the current artifact and semantic inputs')
    if len({r.issue_id for r in submission.resolutions}) != len(submission.resolutions):
        raise ValueError('Duplicate issue resolution')
    def error(index, issue, message, **details):
        errors.append(Diagnostic(code='issue_resolution', category='format',
            object_ids=[issue.id] if issue else [], paths=[f'/resolutions/{index}'],
            message=message, details=details, allowed=['read','research','revise_check']))
    for index, resolution in enumerate(submission.resolutions):
        issue = pending.get(resolution.issue_id)
        if not issue:
            error(index, issue, 'Resolution must address an open issue on this artifact, lineage or semantic dependencies',
                issue_id=resolution.issue_id, artifact_id=artifact.id)
            continue
        unknown = set(resolution.source_ids)-set(sources)
        if unknown:error(index, issue, 'source_ids accepts acquired Material IDs', unknown_material_ids=sorted(unknown))
        try:resolution_executions(state, artifact, resolution, submission.review_items)
        except ValueError as exc:error(index, issue, str(exc))
        if not resolution.rationale.strip():error(index, issue, 'Explain how the answer addresses this issue', original_question=issue.explanation)
        item = next((i for i in submission.review_items if i.aspect == issue.aspect and i.status == 'no_issue_found'), None)
        if not item or item.counterevidence or not includes(state,resolution.source_ids,item.source_ids):
            error(index, issue, 'Resolution needs matching substantive review with its answer sources and no current counterevidence', aspect=issue.aspect, answer_source_ids=resolution.source_ids)
    if errors:raise DiagnosticError(errors)
    review = SemanticReview(task_id='review:' + operation_id, check_id=operation_id,
        target_versions={artifact.id:artifact.version}, material_ids=sources, items=submission.review_items,
        origin='mock' if state.mode == 'mock' else 'agent', unit_id=getattr(artifact,'unit_id',None) or None,
        unit_version=next((u.version for u in state.units if u.id == getattr(artifact,'unit_id',None)), None),
        resolves_issue_ids=[r.issue_id for r in submission.resolutions])
    state.semantic_reviews.append(review)
    for resolution in submission.resolutions:
        issue = next(i for i in state.review_issues if i.id == resolution.issue_id)
        issue.resolved_by = review.id
        issue.resolution_basis = resolution.model_dump(mode='json')
        issue.resolution_checks = list(resolution.executions)
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
            continue
        state.review_issues.append(ReviewIssue(review_id=review.id, target_id=artifact.id,
            target_version=artifact.version, aspect=item.aspect,
            source_ids=item.source_ids, explanation=item.rationale, reason=item.rationale,
            disposition='reading' if item.status == 'needs_reading' else 'investigation'))
    return review
