from consensus_assurance.core.types import Claim, Binding, Relation, AuditUnit, uid


def apply_discovery(state, proposal):
    materials = {m.id: m for m in state.materials}
    ids = [c.id for c in proposal.claims] + [b.id for b in proposal.bindings]
    relation_ids = [r.id for r in proposal.relations]
    if len(ids + relation_ids) != len(set(ids + relation_ids)):
        raise ValueError("Duplicate graph identifiers")
    claims, bindings = [], []
    for c in proposal.claims:
        if not set(c.source_ids) <= materials.keys():
            raise ValueError("Claim references unread material")
        if c.kind in {"goal", "obligation"} and all(materials[i].kind == "code_observation" for i in c.source_ids):
            raise ValueError("Required behavior needs a source beyond code observations")
        claims.append(Claim(**c.model_dump(), source="Agent candidate from attributed materials"))
    for b in proposal.bindings:
        if b.claim_id not in {c.id for c in claims} or b.material_id not in materials:
            raise ValueError("Binding references an unknown claim or material")
        m = materials[b.material_id]
        if m.file not in state.snapshot.files or not m.start_line <= b.start_line <= b.end_line <= m.end_line:
            raise ValueError("Binding range is outside the read code snapshot")
        excerpt = "\n".join(m.text.splitlines()[b.start_line-m.start_line:b.end_line-m.start_line+1])
        if b.symbol not in excerpt:
            raise ValueError("Bound symbol is absent from the referenced code")
        bindings.append(Binding(id=b.id, claim_id=b.claim_id, file=m.file, symbol=b.symbol,
            start_line=b.start_line, end_line=b.end_line, snapshot_id=state.snapshot.id,
            content_digest=m.content_digest, basis="agent_inference", description=b.description,
            pending=b.pending, excerpt=excerpt))
    relations = []
    for edge in proposal.relations:
        if edge.source not in ids or edge.target not in ids:
            raise ValueError("Relation endpoint does not exist")
        relations.append(Relation(**edge.model_dump()))
    units = []
    for u in proposal.units:
        if not set(u.goal_ids) <= {c.id for c in claims if c.kind == "goal"}:
            raise ValueError("Audit unit references missing goals")
        if not set(u.obligation_ids) <= {c.id for c in claims if c.kind == "obligation"}:
            raise ValueError("Audit unit references missing obligations")
        if not set(u.binding_ids) <= {b.id for b in bindings} or not set(u.relation_ids) <= set(relation_ids):
            raise ValueError("Audit unit references missing bindings or relations")
        relevant = [e for e in relations if e.id in u.relation_ids]
        if not any(e.source in u.goal_ids and e.target in u.obligation_ids for e in relevant):
            raise ValueError("Audit unit must reference a goal-to-obligation relationship")
        units.append(AuditUnit(**u.model_dump()))
    state.claims, state.bindings, state.relations, state.units = claims, bindings, relations, units
    state.graph_version += 1
    state.gaps.extend(proposal.conflicts + proposal.unexplored)


def select_unit(state):
    pending = [u for u in state.units if u.status == "pending"]
    if not pending:
        return None
    # Prefer a pending producer of a required boundary over its consumer.
    selected = pending[0]
    used, visited = [], {selected.id}
    while True:
        obligations = set(selected.obligation_ids)
        dependency = next(((edge, unit) for edge in state.relations
            if edge.source in obligations and edge.kind in {"depends_all", "boundary"}
            for unit in pending if edge.target in unit.obligation_ids and unit.id not in visited), None)
        if not dependency:
            break
        edge, selected = dependency
        used.append(edge.id); visited.add(selected.id)
    selected.status = "selected"
    state.selections.append({"unit_id": selected.id, "relation_ids": list(dict.fromkeys(selected.relation_ids + used)),
        "binding_ids": selected.binding_ids, "rationale": "Follow pending boundary producers before consumers; otherwise use the agent's justified ordering",
        "graph_version": state.graph_version})
    return selected


def expand_unit(state, unit, relation_ids):
    edges = [e for e in state.relations if e.id in relation_ids and e.kind in {"boundary", "depends_all", "conditional_on"}]
    if len(edges) != len(set(relation_ids)) or not edges:
        raise ValueError("F3 requires specific dependency relations")
    reachable = set(unit.obligation_ids + unit.binding_ids)
    for edge in edges:
        if edge.source not in reachable:
            raise ValueError("F3 dependency must originate in the current scope")
        reachable.add(edge.target)
    added = [b.id for b in state.bindings if b.id in reachable or b.claim_id in reachable]
    binding_ids = list(dict.fromkeys(unit.binding_ids + added))
    obligation_ids = list(dict.fromkeys(unit.obligation_ids + [c.id for c in state.claims if c.kind == "obligation" and c.id in reachable]))
    if binding_ids == unit.binding_ids and obligation_ids == unit.obligation_ids:
        raise ValueError("F3 must add a concrete binding or related obligation; obtain missing material first")
    expanded = unit.model_copy(deep=True)
    expanded.id = uid(); expanded.previous_id = unit.id; expanded.status = "pending"
    expanded.binding_ids = binding_ids; expanded.obligation_ids = obligation_ids
    expanded.relation_ids = list(dict.fromkeys(unit.relation_ids + relation_ids))
    expanded.scope.description += "; expanded to explain dependency producers: " + ", ".join(relation_ids)
    expanded.rationale = "Dependency-driven expansion; regenerate state semantics, actions and observation mapping"
    unit.status = "revised"; state.units.insert(0, expanded)
    return expanded
