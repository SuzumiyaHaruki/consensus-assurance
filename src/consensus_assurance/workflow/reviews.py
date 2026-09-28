"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


from .review_contract import required_aspects, target_contract
from .sources import includes


def review_objects(state):
    return {o.id:o for o in state.claims+state.bindings+state.relations+state.units+state.models+state.direct_checks+state.question_candidates}


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


def repair_changes(old, artifact):
    """Compare the challenged component, never infer it from the review column."""
    if hasattr(artifact, 'plan_path'):
        from .direct_checks import load_plan
        from .encoding import direct_changes
        before, after = load_plan(old.plan_path), load_plan(artifact.plan_path)
        changes=direct_changes(before,after)
        inputs,predicate,observation=changes['inputs'],changes['oracle'],changes['observation']
    else:
        from .artifacts import load_model
        before, after = load_model(old), load_model(artifact)
        inputs = (before.behavior, before.constants) != (after.behavior, after.constants)
        predicate = before.properties != after.properties
        observation = getattr(before,'observation',None) != getattr(after,'observation',None)
    semantic = old.graph_versions != artifact.graph_versions
    return {'configuration':inputs, 'initialization':inputs, 'driver':inputs,
        'observation':inputs or predicate or observation, 'oracle':predicate,
        'expectation':semantic, 'scope':semantic or old.scope != artifact.scope}


def accept_review(state, submission, operation_id):
    from types import SimpleNamespace
    from consensus_assurance.core.proposals import ReviewReply
    from consensus_assurance.core.types import SemanticReview
    from .review_contract import validate_contract
    objects = review_objects(state)
    artifact = objects.get(submission.artifact_id)
    candidate=artifact if hasattr(artifact,'question') else None
    if artifact is None or not (candidate or hasattr(artifact, 'plan_path') or hasattr(artifact, 'bundle_path')):
        raise ValueError('Review requires an accepted artifact or Candidate ID')
    checks = [c for c in state.checks if (c.direct_check_id == artifact.id or c.model_id == artifact.id)
              and c.status.value == 'completed']
    if not checks and not candidate:
        raise ValueError('Review requires an actual completed execution of the selected artifact')
    sources = [m.id for m in state.materials]
    task = SimpleNamespace(target_ids=[artifact.id], material_ids=sources, context_receipt_id=None)
    reply = ReviewReply(items=submission.review_items, limitations=[])
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    errors = []
    try:validate_contract(state, task, reply)
    except DiagnosticError as exc:errors.extend(exc.diagnostics)
    if not required_aspects(artifact) <= {i.aspect for i in reply.items}:
        raise ValueError('Review must address the supplied whole-artifact contract')
    if any(not i.source_ids or not i.rationale.strip() for i in reply.items):
        raise ValueError('Review needs actual source citations and substantive reasoning')
    ancestors = lineage(state, artifact)
    owner=next((u.candidate_id for u in state.units if u.id==getattr(artifact,'unit_id',None)),None)
    if owner:ancestors.add(owner)
    if len({r.issue_id for r in submission.resolutions}) != len(submission.resolutions):
        raise ValueError('Duplicate issue resolution')
    def error(index, issue, message, **details):
        errors.append(Diagnostic(code='issue_resolution', category='format',
            object_ids=[issue.id] if issue else [], paths=[f'/resolutions/{index}'],
            message=message, details=details, allowed=['read','representation','semantic_revision']))
    evidence = {x.id for name in ('checks','direct_checks','models','evidence','findings','semantic_reviews')
        for x in getattr(state,name)}
    for index, resolution in enumerate(submission.resolutions):
        issue = next((i for i in state.review_issues if i.id == resolution.issue_id and not i.resolved_by), None)
        if not issue or issue.target_id not in ancestors:
            error(index, issue, 'Resolution must address an open issue on this artifact or its lineage',
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
        item = next((i for i in reply.items if i.aspect == issue.aspect and i.status == 'no_issue_found'), None)
        if not item or item.counterevidence or not includes(state,resolution.source_ids,item.source_ids):
            error(index, issue, 'Resolution needs matching substantive review with its answer sources and no current counterevidence', aspect=issue.aspect, answer_source_ids=resolution.source_ids)
        others = {i.id for i in state.review_issues if not i.resolved_by and i.id != issue.id and i.parent_issue_id != issue.id}
        if not set(resolution.residual_issue_ids) <= others or issue.explanation in resolution.scope_limitations:
            raise ValueError('The original dispute cannot be renamed as a residual scope boundary')
        components = issue.challenged_components
        if components:
            old = objects[issue.target_id]
            if hasattr(artifact, 'plan_path'):
                executed = any(c.action == 'direct_check' and c.exit_code == 0 for c in checks)
            else:
                executed = any(c.action == 'model_check' and c.outcome in {'holds', 'counterexample'}
                    and c.search_fingerprint == artifact.search_fingerprint and not c.reused for c in checks)
            changes = repair_changes(old,artifact)
            unchanged = [c for c in components if not changes[c]]
            if artifact.id == old.id or unchanged or not executed:
                error(index, issue, 'Repair needs a new artifact, the challenged component change and matching fresh execution',
                    challenged_components=components, unchanged_components=unchanged, fresh_execution=executed,
                    original_artifact=old.id, answering_artifact=artifact.id)
    if errors:raise DiagnosticError(errors)
    review = SemanticReview(task_id='native:' + operation_id, check_id=operation_id,
        target_versions={artifact.id:artifact.question.audit_spec_version if candidate else artifact.version}, material_ids=sources, items=reply.items,
        origin='mock' if state.mode == 'mock' else 'agent', unit_id=getattr(artifact,'unit_id',None) or None,
        unit_version=next((u.version for u in state.units if u.id == getattr(artifact,'unit_id',None)), None),
        model_id=artifact.id if hasattr(artifact, 'bundle_path') else None,
        resolves_issue_ids=[r.issue_id for r in submission.resolutions])
    state.semantic_reviews.append(review)
    for resolution in submission.resolutions:
        issue = next(i for i in state.review_issues if i.id == resolution.issue_id)
        issue.resolved_by = review.id
        issue.resolution_basis = resolution.model_dump(mode='json')
        issue.resolution_checks = [c.id for c in checks]
    for item in reply.items:
        if item.status == 'no_issue_found':
            continue
        if any(i.target_id == artifact.id and i.aspect == item.aspect and i.explanation == item.rationale
               and not i.resolved_by for i in state.review_issues):
            continue
        state.review_issues.append(ReviewIssue(review_id=review.id, target_id=artifact.id,
            target_version=artifact.question.audit_spec_version if candidate else artifact.version, aspect=item.aspect, model_id=review.model_id,
            source_ids=item.source_ids, explanation=item.rationale, reason=item.rationale,
            disposition='reading' if item.status == 'needs_reading' else 'investigation',
            challenged_components=item.challenged_components if item.status=='revision_needed' else []))
    return review


def semantic_limitations(state, model):
    relevant = lineage(state, model) | set(model.graph_versions)
    relevant.update(u.candidate_id for u in state.units if u.id==model.unit_id)
    blockers = ['Open review issue: ' + i.id + ': ' + i.explanation
        for i in state.review_issues if not i.resolved_by and i.target_id in relevant]
    versions = {o.id:o.version for o in state.claims + state.bindings + state.relations + state.units}
    if any(versions.get(key) != version for key, version in model.graph_versions.items()):
        blockers.append('Model semantic inputs changed; recheck required')
    if model.snapshot_id != state.snapshot.id:
        blockers.append('Model belongs to a different source snapshot')
    reviews = [i for r in state.semantic_reviews if r.target_versions.get(model.id) == model.version
        for i in r.items if i.target_id == model.id and i.aspect == 'checker_correspondence']
    if not reviews or reviews[-1].status != 'no_issue_found' or reviews[-1].counterevidence:
        blockers.append('Current model correspondence remains unreviewed or disputed')
    return blockers
