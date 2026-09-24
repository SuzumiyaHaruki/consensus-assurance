from consensus_assurance.core.types import Claim, Binding, Relation, AuditUnit
from .mutations import adopt, write_set
from .associations import claim_ids
from .graph_diagnostics import require_graph
from .locations import location_evidence


def apply_graph(state, proposal, audit_spec=None):
    require_graph(state,proposal,audit_spec)
    materials={m.id:m for m in state.materials}
    claims=[Claim(**c.model_dump(),source="Candidate derived from attributed implementation responsibilities") for c in proposal.claims]
    bindings=[]
    for b in proposal.bindings:
        m=materials[b.material_id];evidence,_=location_evidence(b,materials)
        view=evidence['view'];anchor=evidence['anchor']
        excerpt="\n".join(view.text.splitlines()[b.start_line-view.start_line:b.end_line-view.start_line+1])
        associations=[a.model_copy(update={'source_ids':a.source_ids or [b.material_id]}) for a in b.associations]
        bindings.append(Binding(id=b.id,material_id=b.material_id,associations=associations,anchor=anchor,file=m.file,symbol=b.symbol,
            start_line=b.start_line,end_line=b.end_line,snapshot_id=state.snapshot.id,content_digest=m.content_digest,
            basis='agent_inference',description=b.description,pending=b.pending,excerpt=excerpt))
    state.claims=claims;state.bindings=bindings
    state.relations=[Relation(**r.model_dump()) for r in proposal.relations]
    state.units=[AuditUnit(**u.model_dump()) for u in proposal.units]
    state.graph_version+=1
    state.gaps.extend(proposal.conflicts+proposal.unexplored+proposal.gaps)


def expand_unit(state, unit, relation_ids):
    from .scope_updates import from_patch,apply_scope_update
    from consensus_assurance.core.proposals import GraphPatch,UnitDraft
    edges = sorted([e for e in state.relations if e.id in relation_ids and e.kind in {'boundary','depends_all','conditional_on'}],key=lambda e:e.id)
    if len(edges)!=len(set(relation_ids)) or not edges:raise ValueError('F3 requires specific dependency relations')
    reachable=set(unit.obligation_ids+unit.binding_ids);used=set()
    while True:
        fresh=[e for e in edges if e.source in reachable and e.id not in used]
        if not fresh:break
        for edge in fresh:reachable.add(edge.target);used.add(edge.id)
    if used!={e.id for e in edges}:raise ValueError('F3 dependency must originate in the current scope; reversed or unrelated edges remain excluded')
    added=sorted(b.id for b in state.bindings if b.id in reachable or claim_ids(b)&reachable)
    draft=UnitDraft(**{k:v for k,v in unit.model_dump().items() if k in UnitDraft.model_fields})
    draft.binding_ids=list(dict.fromkeys(unit.binding_ids+added));draft.relation_ids=list(dict.fromkeys(unit.relation_ids+sorted(used)))
    if draft.binding_ids==unit.binding_ids:raise ValueError('F3 must add a concrete binding; use an explicit scope proposal to refine existing event granularity')
    draft.rationale=unit.rationale+'; inspect the selected producer dependencies'
    patch=GraphPatch(units=[draft],expected_versions={unit.id:unit.version},rationale='Included producer bindings through selected directed dependencies')
    update=from_patch(state,unit,patch)
    return apply_scope_update(state,update)


def _apply_patch(state, patch, semantic=False, audit_spec=None):
    """Validate an incremental update on a copy, then preserve superseded object versions."""
    from consensus_assurance.core.proposals import GraphDraft, ClaimDraft, BindingDraft, RelationDraft, UnitDraft
    from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
    def reject(message,ids):
        selected=[(name,i,o) for name in ('claims','bindings','relations','units') for i,o in enumerate(getattr(patch,name)) if o.id in ids]
        paths=[f'/{name}/{i}' for name,i,o in selected] or ['/expected_versions']
        sources=list(dict.fromkeys(x for _,_,o in selected for x in getattr(o,'source_ids',[])))
        raise DiagnosticError([Diagnostic(code='patch_authority',category='semantic',object_ids=list(ids),paths=paths,material_ids=sources,message=message,allowed=['semantic_revision'])])
    writes=write_set(state,patch)
    current = {x.id: x for x in [*state.claims, *state.bindings, *state.relations, *state.units]}
    for key, version in patch.expected_versions.items():
        if key not in current or current[key].version != version:
            reject("Graph patch version does not match the current object",[key])
    replacements = [*patch.claims, *patch.bindings, *patch.relations, *patch.units]
    if len({obj.id for obj in replacements}) != len(replacements):
        reject("Duplicate patch object identifiers",[o.id for o in replacements])
    for obj in patch.relations:
        if obj.id in current and not semantic:
            old = current[obj.id]
            if any(getattr(obj,key) != getattr(old,key) for key in ("source","target","kind","group","rationale","grounding")) or not set(old.pending)<=set(obj.pending):
                reject("Changing relationship semantics requires F2",[obj.id])
    for obj in patch.units:
        if obj.id in current and not semantic:
            old=current[obj.id]
            if obj.scope!=old.scope or not set(old.obligation_ids)<=set(obj.obligation_ids):
                reject("Ordinary patches cannot remove unit obligations or change scope; use attributed semantic revision or F3 expansion",[obj.id])
    for obj in replacements:
        if obj.id in current and obj.id not in patch.expected_versions:
            reject("Replacing an object requires its expected version",[obj.id])
        if obj.id in current and hasattr(obj, "kind") and obj.kind in {"obligation", "assumption"} and not semantic:
            old = current[obj.id]
            if obj.kind != old.kind or obj.description != old.description or obj.scope != old.scope or obj.grounding != old.grounding or not set(old.pending)<=set(obj.pending):
                reject("Changing claim semantics requires F2; dependency additions do not",[obj.id])
    if not semantic and writes:
        reject("Changing existing graph semantics requires scoped F2; add candidates or use F3 for new scope",[id for id,field in writes])
    def merge(old, changes, convert):
        values = {x.id: convert(x) for x in old}
        values.update({x.id:x for x in changes})
        return list(values.values())
    def binding(x):
        # The cited fragment may be narrower than behavior; location_evidence below
        # verifies declaration and behavior against contiguous same-version sources.
        material = next((m for m in state.materials if (x.material_id is None or m.id==x.material_id) and m.file==x.file and m.content_digest==x.content_digest),None)
        if not material:
            reject("Old binding no longer has its source material",[x.id])
        return BindingDraft(id=x.id,associations=x.associations,anchor=x.anchor,material_id=material.id,symbol=x.symbol,start_line=x.start_line,end_line=x.end_line,description=x.description,pending=x.pending)
    claims = merge(state.claims,patch.claims,lambda x: ClaimDraft(**{k:v for k,v in x.model_dump().items() if k in ClaimDraft.model_fields}))
    bindings = merge(state.bindings,patch.bindings,binding)
    # Evidence edges are retained separately; they are not agent graph declarations.
    internal = [e for e in state.relations if e.source in current and e.target in current]
    external = [e for e in state.relations if e not in internal]
    relations = merge(internal,patch.relations,lambda x: RelationDraft(**{k:v for k,v in x.model_dump().items() if k in RelationDraft.model_fields}))
    units = merge(state.units,patch.units,lambda x: UnitDraft(**{k:v for k,v in x.model_dump().items() if k in UnitDraft.model_fields}))
    trial = state.model_copy(deep=True)
    apply_graph(trial,GraphDraft(claims=claims,bindings=bindings,relations=relations,units=units,gaps=patch.gaps),audit_spec)
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


def validate_patch(state,patch,semantic=False,audit_spec=None):
    trial=state.model_copy(deep=True)
    _apply_patch(trial,patch,semantic,audit_spec)
    return trial


def apply_patch(state,patch,semantic=False,audit_spec=None):
    existing={x.id for name in ('claims','bindings','relations','units') for x in getattr(state,name)}
    changed={id for id,field in write_set(state,patch)}|{x.id for name in ('claims','bindings','relations','units') for x in getattr(patch,name) if x.id not in existing}
    trial=validate_patch(state,patch,semantic,audit_spec)
    adopt(state,trial)
    return changed
