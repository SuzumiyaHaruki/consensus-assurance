"""Explicit checker-encoding correction preserves the claim and behavior contract."""
import re
from .artifacts import materialize_bundle


def validate_encoding(state,previous,current,repaired,revision):
    if revision.old_direct_check_id or revision.issue_id or revision.input_changes:raise ValueError('Model encoding correction cannot claim a direct-check issue or input adaptation')
    if revision.old_model_id!=previous.id or not revision.rationale.strip() or not set(revision.source_ids)<={m.id for m in state.materials}:
        raise ValueError('Encoding correction needs the actual previous model and material rationale')
    if not revision.source_ids:raise ValueError('Encoding correction cannot cite only a failing result')
    current_versions={c.id:c.version for c in state.claims}
    if any(current_versions.get(id)!=version for id,version in previous.graph_versions.items() if id in current_versions):raise ValueError('Claim meaning changed; this is F2, not encoding correction')
    for field in ['behavior','constants','scope','constraints','observable_properties']:
        if getattr(current,field)!=getattr(repaired,field):raise ValueError('Encoding correction cannot change behavior, scope or intended observable property; use F1/F2/F3')
    if current.checker_specs()!=repaired.checker_specs():raise ValueError('Encoding correction changed claim/checker attribution')
    text=materialize_bundle(repaired).properties
    for spec in repaired.checker_specs():
        if re.search(r'(?m)^\s*'+spec.invariant+r'\s*==\s*(?:TRUE|FALSE)\s*$',text):raise ValueError('A constant checker cannot discharge a semantic encoding repair')


def validate_direct_encoding(state,artifact,previous,repaired,revision):
    from .reviews import lineage
    ancestors = lineage(state, artifact) if artifact else set()
    issue=next((i for i in state.review_issues if i.id==revision.issue_id and not i.resolved_by),None)
    if artifact is None or revision.old_model_id or revision.old_direct_check_id!=artifact.id or not issue or issue.target_id not in ancestors or issue.aspect!='checker_correspondence':
        raise ValueError('Direct encoding correction must name the current artifact and its open checker issue')
    if not revision.rationale.strip() or not set(revision.source_ids)<={m.id for m in state.materials} or not set(issue.source_ids)&set(revision.source_ids):
        raise ValueError('Direct encoding correction needs actual source and the disputed issue basis')
    if not any(c.direct_check_id==artifact.id and c.status.value=='completed' for c in state.checks):raise ValueError('An accepted direct encoding correction requires the original completed execution')
    versions={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units}
    if any(versions.get(id)!=v for id,v in artifact.graph_versions.items()):raise ValueError('Semantic inputs changed; encoding correction cannot repair a changed obligation')
    if previous.claim_id!=repaired.claim_id or previous.binding_ids!=repaired.binding_ids or previous.uncertainties!=repaired.uncertainties or previous.description!=repaired.description:
        raise ValueError('Direct encoding correction cannot change claim, source, scenario or execution inputs')
    before=previous.harness.model_dump();after=repaired.harness.model_dump()
    for field in ('source','files','semantic_changes'):before.pop(field);after.pop(field)
    if before!=after or ((previous.harness.source,previous.harness.files)!=(repaired.harness.source,repaired.harness.files))!=bool(revision.input_changes) or (previous.harness.semantic_changes!=repaired.harness.semantic_changes)!=bool(revision.input_changes):
        raise ValueError('Observation input changes must be declared and preserve harness prerequisites, legality and scope')
    old={p.checker_id:p for p in previous.observable_properties}
    new={p.checker_id:p for p in repaired.observable_properties}
    if old.keys()!=new.keys() or {m.id:m.checker_id for m in previous.monitors}!={m.id:m.checker_id for m in repaired.monitors}:
        raise ValueError('Direct encoding correction cannot change checker attribution')
    for left,right in zip(previous.monitors,repaired.monitors):
        if left.model_copy(update={'applicability_conditions':right.applicability_conditions})!=right:
            raise ValueError('Direct encoding correction cannot change the observation endpoint or grounding')
    for id in old:
        if old[id].model_copy(update={'assertion':new[id].assertion,'description':new[id].description,
                'kind':new[id].kind,'antecedent':new[id].antecedent})!=new[id]:
            raise ValueError('Direct encoding correction cannot change trigger or identity')
        if new[id].kind not in {'event_assertion','event_implication'}:
            raise ValueError('Direct encoding correction needs a supported result predicate')
    if not any((old[id].assertion,old[id].kind,old[id].antecedent)!=(new[id].assertion,new[id].kind,new[id].antecedent) for id in old) and not any(a.applicability_conditions!=b.applicability_conditions for a,b in zip(previous.monitors,repaired.monitors)):
        raise ValueError('Direct encoding correction needs an actual oracle change')
