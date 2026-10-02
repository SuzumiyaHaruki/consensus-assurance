"""Explicit checker-encoding correction preserves the claim and behavior contract."""


def direct_changes(before, after):
    """One component comparison for ordinary/encoding admission and review repair."""
    inputs=(before.harness.source,before.harness.files)!=(after.harness.source,after.harness.files)
    properties=lambda plan:[p.model_dump(exclude={'description'}) for p in plan.observable_properties]
    predicates=lambda plan:[(m.checker_id,m.applicability_conditions) for m in plan.monitors]
    observations=lambda plan:[(m.checker_id,m.event,m.admission_alias,m.binding_ids) for m in plan.monitors]
    oracle=properties(before)!=properties(after) or predicates(before)!=predicates(after)
    def contract(plan):
        harness=plan.harness.model_dump(exclude={'source','files','description','semantic_changes','legality'})
        harness['prerequisites']=sorted(harness['prerequisites'],key=lambda r:r['alias'])
        monitors=[m.model_dump(exclude={'event','admission_alias','applicability_conditions'}) for m in plan.monitors]
        return plan.claim_id,plan.binding_ids,plan.uncertainties,harness,monitors
    return {'inputs':inputs,'oracle':oracle,'observation':observations(before)!=observations(after),
        'contract':contract(before)!=contract(after),
        'legality':before.harness.legality.model_dump(exclude={'derivation'})!=after.harness.legality.model_dump(exclude={'derivation'})}


def validate_direct_encoding(state,artifact,previous,repaired,revision):
    from .reviews import lineage, open_issues
    ancestors = lineage(state, artifact) if artifact else set()
    issue=next((i for i in open_issues(state,artifact) if i.id==revision.issue_id),None)
    if artifact is None or revision.old_direct_check_id!=artifact.id or not issue or issue.target_id not in ancestors or issue.aspect!='checker_correspondence':
        raise ValueError('Direct encoding correction must name the current artifact and its open checker issue')
    components=set(issue.challenged_components)
    if not components&{'oracle','observation'}:
        raise ValueError('Encoding correction needs an oracle or observation challenge; configuration and driver repairs preserve the oracle')
    if not revision.rationale.strip() or not set(revision.source_ids)<={m.id for m in state.materials} or not set(issue.source_ids)&set(revision.source_ids):
        raise ValueError('Direct encoding correction needs actual source and the disputed issue basis')
    if not any(c.direct_check_id==artifact.id and c.status.value=='completed' for c in state.checks):raise ValueError('An accepted direct encoding correction requires the original completed execution')
    versions={o.id:o.version for o in state.claims+state.bindings+state.relations+state.units}
    if any(versions.get(id)!=v for id,v in artifact.graph_versions.items()):raise ValueError('Semantic inputs changed; encoding correction cannot repair a changed obligation')
    changed=direct_changes(previous,repaired)
    if changed['contract'] or changed['legality'] or changed['inputs']!=bool(revision.input_changes) or (previous.harness.semantic_changes!=repaired.harness.semantic_changes)!=bool(revision.input_changes):
        raise ValueError('Observation input changes must be declared and preserve harness prerequisites, legality and scope')
    old={p.checker_id:p for p in previous.observable_properties}
    new={p.checker_id:p for p in repaired.observable_properties}
    if old.keys()!=new.keys():
        raise ValueError('Direct encoding correction cannot change checker attribution')
    if 'observation' not in components and changed['observation']:
        raise ValueError('Oracle correction cannot change the observation endpoint')
    for id in old:
        allowed={'assertion','description','kind','antecedent'}|({'trigger','identity_fields'} if 'observation' in components else set())
        if old[id].model_copy(update={k:getattr(new[id],k) for k in allowed})!=new[id]:
            raise ValueError('Direct encoding correction cannot change trigger or identity')
        if new[id].kind not in {'event_assertion','event_implication'}:
            raise ValueError('Direct encoding correction needs a supported result predicate')
    if not (changed['oracle'] or changed['observation']):
        raise ValueError('Direct encoding correction needs an actual observation or oracle change')
