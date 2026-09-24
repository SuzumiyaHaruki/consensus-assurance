"""Review execution, open semantic issues, and scoped dispositions are separate records."""
from consensus_assurance.core.types import ReviewIssue


from .review_contract import required_aspects, target_contract
from .sources import citation_status, includes


def review_objects(state):
    return {o.id:o for o in state.claims+state.bindings+state.relations+state.units+state.models+state.direct_checks}


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


def accept_review(state, submission, operation_id):
    from types import SimpleNamespace
    from consensus_assurance.core.proposals import ReviewReply
    from consensus_assurance.core.types import SemanticReview
    from .review_contract import validate_contract
    objects = review_objects(state)
    artifact = objects.get(submission.artifact_id)
    if artifact is None or not (hasattr(artifact, 'plan_path') or hasattr(artifact, 'bundle_path')):
        raise ValueError('Review requires an accepted check or model artifact ID')
    checks = [c for c in state.checks if (c.direct_check_id == artifact.id or c.model_id == artifact.id)
              and c.status.value == 'completed']
    if not checks:
        raise ValueError('Review requires an actual completed execution of the selected artifact')
    sources = [m.id for m in state.materials]
    task = SimpleNamespace(target_ids=[artifact.id], material_ids=sources, context_receipt_id=None)
    reply = ReviewReply(items=submission.review_items, limitations=[])
    validate_contract(state, task, reply)
    if not required_aspects(artifact) <= {i.aspect for i in reply.items}:
        raise ValueError('Review must address the supplied whole-artifact contract')
    if any(not i.source_ids or not i.rationale.strip() for i in reply.items):
        raise ValueError('Review needs actual source citations and substantive reasoning')
    ancestors = lineage(state, artifact)
    if len({r.issue_id for r in submission.resolutions}) != len(submission.resolutions):
        raise ValueError('Duplicate issue resolution')
    for resolution in submission.resolutions:
        issue = next((i for i in state.review_issues if i.id == resolution.issue_id and not i.resolved_by), None)
        if not issue or issue.target_id not in ancestors:
            raise ValueError('Resolution must address an open issue on this artifact or its lineage')
        if (resolution.target_version != issue.target_version or resolution.original_question != issue.explanation
                or not resolution.rationale.strip() or not set(resolution.source_ids) <= set(sources)):
            raise ValueError('Resolution must retain the exact original issue and cite its actual answer')
        if not includes(state, issue.source_ids, resolution.source_ids):
            raise ValueError('Resolution must retain the original issue source basis')
        if issue.conditions:
            from .repair_policy import classify_conditions
            dispositions = classify_conditions(state, [c['text'] for c in issue.conditions],
                resolution.condition_dispositions, resolution.source_ids, records=issue.conditions)
            if any(d.applies_to == 'current_judgment' for d in dispositions):
                raise ValueError('Current unresolved conditions cannot discharge their issue')
        item = next((i for i in reply.items if i.aspect == issue.aspect and i.status == 'no_issue_found'), None)
        if not item or item.counterevidence or not set(resolution.source_ids) <= set(item.source_ids):
            raise ValueError('Resolution needs matching substantive review without current counterevidence')
        others = {i.id for i in state.review_issues if not i.resolved_by and i.id != issue.id and i.parent_issue_id != issue.id}
        if not set(resolution.residual_issue_ids) <= others or issue.explanation in resolution.scope_limitations:
            raise ValueError('The original dispute cannot be renamed as a residual scope boundary')
        if issue.needs_recheck:
            old = objects[issue.target_id]
            if hasattr(artifact, 'plan_path'):
                from .direct_checks import load_plan
                a, b = load_plan(old.plan_path), load_plan(artifact.plan_path)
                changed = (a.observable_properties, a.monitors) != (b.observable_properties, b.monitors)
                executed = any(c.action == 'direct_check' and c.exit_code == 0 for c in checks)
            else:
                from .artifacts import load_model
                changed = load_model(old).properties != load_model(artifact).properties
                executed = any(c.action == 'model_check' and c.outcome in {'holds', 'counterexample'}
                    and c.search_fingerprint == artifact.search_fingerprint and not c.reused for c in checks)
            if artifact.id == old.id or not changed or not executed:
                raise ValueError('Checker issue requires a changed oracle and actual matching reexecution')
    review = SemanticReview(task_id='native:' + operation_id, check_id=operation_id,
        target_versions={artifact.id:artifact.version}, material_ids=sources, items=reply.items,
        origin='mock' if state.mode == 'mock' else 'agent', unit_id=artifact.unit_id,
        unit_version=next(u.version for u in state.units if u.id == artifact.unit_id),
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
            target_version=artifact.version, aspect=item.aspect, model_id=review.model_id,
            source_ids=item.source_ids, explanation=item.rationale, reason=item.rationale,
            disposition='reading' if item.status == 'needs_reading' else 'investigation',
            needs_recheck=item.aspect == 'checker_correspondence' and item.status == 'revision_needed'))
    return review


def semantic_limitations(state, model):
    relevant = lineage(state, model) | set(model.graph_versions)
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
