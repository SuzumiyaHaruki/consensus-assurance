from consensus_assurance.core.types import Claim, Binding, Relation, AuditUnit, uid
from .mutations import adopt, write_set
from .associations import claim_ids, relevant_use
from .graph_diagnostics import require_graph
from .locations import locate


def validate_grounding(basis, materials, binding_ids):
    if not basis.derivation.strip() or not basis.applicability.strip():
        raise ValueError("A derivation and implementation applicability are required, not a source file kind")
    references = set(basis.behavior_ids + basis.expectation_ids)
    if not references or not references <= set(materials):
        raise ValueError("Grounding must reference actually read materials")
    if not set(basis.binding_ids) <= set(binding_ids):
        raise ValueError("Grounding references unavailable code bindings")
    if not basis.expectation_ids and not basis.binding_ids:
        raise ValueError("Derived responsibilities need a located implementation binding; adequacy requires semantic review")


def apply_discovery(state, proposal):
    require_graph(state,proposal)
    count = sum(len(getattr(proposal,name)) for name in ("claims","bindings","relations","units"))
    if count > state.config.get("budget",{}).get("graph_objects",1000):
        raise ValueError("Configured aggregate graph resource budget exceeded")
    materials = {m.id: m for m in state.materials}
    ids = [c.id for c in proposal.claims] + [b.id for b in proposal.bindings]
    relation_ids = [r.id for r in proposal.relations]
    if len(ids + relation_ids + [u.id for u in proposal.units]) != len(set(ids + relation_ids + [u.id for u in proposal.units])):
        raise ValueError("Duplicate graph identifiers")
    claims, bindings = [], []
    all_binding_ids = {b.id for b in proposal.bindings}
    for c in proposal.claims:
        if not set(c.source_ids) <= materials.keys():
            raise ValueError("Claim references unread material")
        validate_grounding(c.grounding, materials, all_binding_ids)
        claims.append(Claim(**c.model_dump(), source="Candidate derived from attributed implementation responsibilities"))
    for b in proposal.bindings:
        if not claim_ids(b)<={c.id for c in claims} or b.material_id not in materials:
            raise ValueError("Binding references an unknown claim or material")
        m = materials[b.material_id]
        if m.file not in state.snapshot.files or not m.start_line <= b.start_line <= b.end_line <= m.end_line:
            raise ValueError("Binding range is outside the read code snapshot")
        excerpt = "\n".join(m.text.splitlines()[b.start_line-m.start_line:b.end_line-m.start_line+1])
        anchor,_=locate(b,materials)
        associations=[a.model_copy(update={'source_ids':a.source_ids or [b.material_id]}) for a in b.associations]
        for association in associations:
            if not set(association.source_ids)<=set(materials) or not association.rationale.strip():raise ValueError("Code association lacks actual material and rationale")
        bindings.append(Binding(id=b.id, material_id=b.material_id, associations=associations, anchor=anchor,file=m.file, symbol=b.symbol,
            start_line=b.start_line, end_line=b.end_line, snapshot_id=state.snapshot.id,
            content_digest=m.content_digest, basis="agent_inference", description=b.description,
            pending=b.pending, excerpt=excerpt))
    relations = []
    for edge in proposal.relations:
        if edge.source not in ids or edge.target not in ids:
            raise ValueError("Relation endpoint does not exist")
        validate_grounding(edge.grounding, materials, all_binding_ids)
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
        if any(not relevant_use(u,b,relations,materials) for b in bindings if b.id in u.binding_ids):
            raise ValueError("Audit unit contains a binding unrelated to its claims")
        if not any(e.source in u.goal_ids and e.target in u.obligation_ids and e.kind in {"depends_all", "supports", "alternative", "conditional_on"} for e in relevant):
            raise ValueError("Audit unit must reference a goal-to-obligation relationship")
        if state.mode=='real' and state.analysis_mode!='regression' and not u.audit_question:
            raise ValueError("A generated audit unit needs a sourced audit_question, not a suspected bug")
        points=u.coverage_intent+(u.audit_question.points if u.audit_question else [])
        if u.audit_question and (not u.audit_question.question.strip() or not u.audit_question.importance.strip() or not set(u.audit_question.source_ids)<=set(materials)):
            raise ValueError("Audit question lacks actual materials or significance")
        for point in points:
            if not set(point.source_ids)<=set(materials) or not set(point.binding_ids)<=set(u.binding_ids) or not set(point.claim_ids)<=set(u.goal_ids+u.obligation_ids):
                raise ValueError("Coverage intent references unselected evidence or bindings")
        units.append(AuditUnit(**u.model_dump()))
    state.claims, state.bindings, state.relations, state.units = claims, bindings, relations, units
    state.graph_version += 1
    state.gaps.extend(proposal.conflicts + proposal.unexplored + proposal.gaps)


def select_unit(state):
    pending = [u for u in state.units if u.status in {"pending", "partial"}]
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
    reachable.update(c for b in state.bindings if b.id in reachable for c in claim_ids(b))
    added = [b.id for b in state.bindings if b.id in reachable or bool(claim_ids(b)&reachable)]
    binding_ids = list(dict.fromkeys(unit.binding_ids + added))
    obligation_ids = list(dict.fromkeys(unit.obligation_ids + [c.id for c in state.claims if c.kind == "obligation" and c.id in reachable]))
    if binding_ids == unit.binding_ids and obligation_ids == unit.obligation_ids:
        raise ValueError("F3 must add a concrete binding or related obligation; obtain missing material first")
    expanded = unit.model_copy(deep=True)
    expanded.id = uid(); expanded.previous_id = unit.id; expanded.status = "pending"
    expanded.binding_ids = binding_ids; expanded.obligation_ids = obligation_ids
    expanded.goal_observable=False
    expanded.semantic_readiness={};expanded.obligation_checks={};expanded.remaining_obligation_ids=list(obligation_ids)
    expanded.coverage_limitations=['New scope requires regenerated observation, trigger and semantic review records']
    expanded.relation_ids = list(dict.fromkeys(unit.relation_ids + relation_ids))
    expanded.scope.description += "; expanded to explain dependency producers: " + ", ".join(relation_ids)
    expanded.boundary_changes = ["Included producer bindings: " + ", ".join(b for b in binding_ids if b not in unit.binding_ids),
        "Prior external boundary assumptions must be reconsidered; inclusion does not establish the guarantee"]
    expanded.rationale = "Dependency-driven expansion; regenerate state semantics, actions and observation mapping"
    unit.status = "revised"; state.units.insert(0, expanded)
    return expanded


def _apply_patch(state, patch, semantic=False):
    """Validate an incremental update on a copy, then preserve superseded object versions."""
    from consensus_assurance.core.proposals import GraphDraft, ClaimDraft, BindingDraft, RelationDraft, UnitDraft
    writes=write_set(state,patch)
    current = {x.id: x for x in [*state.claims, *state.bindings, *state.relations, *state.units]}
    for key, version in patch.expected_versions.items():
        if key not in current or current[key].version != version:
            raise ValueError("Graph patch version does not match the current object")
    replacements = [*patch.claims, *patch.bindings, *patch.relations, *patch.units]
    if len({obj.id for obj in replacements}) != len(replacements):
        raise ValueError("Duplicate patch object identifiers")
    for obj in patch.relations:
        if obj.id in current and not semantic:
            old = current[obj.id]
            if any(getattr(obj,key) != getattr(old,key) for key in ("source","target","kind","group","rationale","grounding")) or not set(old.pending)<=set(obj.pending):
                raise ValueError("Changing relationship semantics requires F2")
    for obj in patch.units:
        if obj.id in current and not semantic:
            old=current[obj.id]
            if obj.scope!=old.scope or not set(old.goal_ids)<=set(obj.goal_ids) or not set(old.obligation_ids)<=set(obj.obligation_ids):
                raise ValueError("Ordinary patches cannot remove unit obligations or change scope; use attributed semantic revision or F3 expansion")
    for obj in replacements:
        if obj.id in current and obj.id not in patch.expected_versions:
            raise ValueError("Replacing an object requires its expected version")
        if obj.id in current and hasattr(obj, "kind") and obj.kind in {"goal", "obligation", "assumption"} and not semantic:
            old = current[obj.id]
            if obj.kind != old.kind or obj.description != old.description or obj.scope != old.scope or obj.grounding != old.grounding or not set(old.pending)<=set(obj.pending):
                raise ValueError("Changing claim semantics requires F2; dependency additions do not")
    if not semantic and writes:
        raise ValueError("Changing existing graph semantics requires scoped F2; add candidates or use F3 for new scope")
    def merge(old, changes, convert):
        values = {x.id: convert(x) for x in old}
        values.update({x.id:x for x in changes})
        return list(values.values())
    def binding(x):
        material = next((m for m in state.materials if (x.material_id is None or m.id==x.material_id) and m.file == x.file and m.start_line <= x.start_line <= x.end_line <= m.end_line), None)
        if not material:
            raise ValueError("Old binding no longer has its source material")
        return BindingDraft(id=x.id,associations=x.associations,anchor=x.anchor,material_id=material.id,symbol=x.symbol,start_line=x.start_line,end_line=x.end_line,description=x.description,pending=x.pending)
    claims = merge(state.claims,patch.claims,lambda x: ClaimDraft(**{k:v for k,v in x.model_dump().items() if k in ClaimDraft.model_fields}))
    bindings = merge(state.bindings,patch.bindings,binding)
    # Evidence edges are retained separately; they are not agent graph declarations.
    internal = [e for e in state.relations if e.source in current and e.target in current]
    external = [e for e in state.relations if e not in internal]
    relations = merge(internal,patch.relations,lambda x: RelationDraft(**{k:v for k,v in x.model_dump().items() if k in RelationDraft.model_fields}))
    units = merge(state.units,patch.units,lambda x: UnitDraft(**{k:v for k,v in x.model_dump().items() if k in UnitDraft.model_fields}))
    trial = state.model_copy(deep=True)
    apply_discovery(trial,GraphDraft(claims=claims,bindings=bindings,relations=relations,units=units,gaps=patch.gaps))
    changed = {id for id,field in writes}|{x.id for x in replacements if x.id not in current}
    for kind in ("claims","bindings","relations","units"):
        values = getattr(trial,kind)
        for index,item in enumerate(values):
            if item.id in current:
                old = current[item.id]
                if item.id not in changed:
                    values[index] = old
                else:
                    item.version = old.version + 1
                    state.graph_history.append({"kind":kind,"id":old.id,"version":old.version,"record":old.model_dump(mode="json"),"reason":patch.rationale})
        setattr(state,kind,values)
    state.relations.extend(external)
    if changed: state.graph_version += 1
    state.gaps.extend(patch.gaps)
    return changed


def validate_patch(state,patch,semantic=False):
    trial=state.model_copy(deep=True)
    _apply_patch(trial,patch,semantic)
    return trial


def apply_patch(state,patch,semantic=False):
    existing={x.id for name in ('claims','bindings','relations','units') for x in getattr(state,name)}
    changed={id for id,field in write_set(state,patch)}|{x.id for name in ('claims','bindings','relations','units') for x in getattr(patch,name) if x.id not in existing}
    trial=validate_patch(state,patch,semantic)
    adopt(state,trial)
    return changed
