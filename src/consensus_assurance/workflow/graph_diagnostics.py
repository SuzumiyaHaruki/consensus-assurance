"""Dependency-ordered, non-mutating candidate diagnostics."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .locations import locate, location_context
from .sources import covered
from .associations import claim_ids,relevant_use


def diagnose_graph(state,proposal):
    issues=[];materials={m.id:m for m in state.materials}
    def emit(code,category,ids,paths,sources,message,allowed):
        issues.append(Diagnostic(code=code,category=category,object_ids=ids,paths=paths,material_ids=list(dict.fromkeys(sources)),message=message,allowed=allowed))
    collections=['claims','bindings','relations','units'];all_ids=[o.id for name in collections for o in getattr(proposal,name)]
    if len(set(all_ids))!=len(all_ids):
        emit('duplicate_identity','association',all_ids,[],[],'Duplicate graph identifiers',['stop']);return issues
    claims={c.id:c for c in proposal.claims};bindings={b.id:b for b in proposal.bindings}
    for i,c in enumerate(proposal.claims):
        if not set(c.source_ids)<=set(materials):emit('missing_material','material',[c.id],[f'/claims/{i}/source_ids'],c.source_ids,'Claim references unread material',['read'])
    for i,b in enumerate(proposal.bindings):
        ids=claim_ids(b)
        if len(ids)!=len(b.associations):
            emit('duplicate_association','association',[b.id],[f'/bindings/{i}/associations'],[b.material_id],'Duplicate claim association for one physical binding',['association']);continue
        if not ids<=set(claims) or b.material_id not in materials:
            emit('binding_reference','association',[b.id]+sorted(ids),[f'/bindings/{i}/associations',f'/bindings/{i}/material_id'],[b.material_id],'Binding references an unknown claim or material',['read','association']);continue
        m=materials[b.material_id]
        if m.file not in state.snapshot.files or not covered(m.model_copy(update={'start_line':b.start_line,'end_line':b.end_line}),materials.values()):
            emit('behavior_range','location',[b.id],[f'/bindings/{i}/{f}' for f in ['symbol','material_id','anchor','start_line','end_line']],[m.id],'Binding range is outside the read code snapshot',['representation','read']);continue
        anchor,reason=locate(b,materials)
        if not anchor:
            evidence=location_context(b,materials)
            emit('declaration_identity','location',[b.id],[f'/bindings/{i}/{f}' for f in ['symbol','material_id','anchor','start_line','end_line']],evidence['material_ids'],f'Binding {b.id}: literal symbol {b.symbol!r} has no verified declaration: '+reason,['representation','read'])
            issues[-1].details=evidence
    for i,r in enumerate(proposal.relations):
        if r.source not in set(claims)|set(bindings) or r.target not in set(claims)|set(bindings):
            emit('relation_endpoint','association',[r.id,r.source,r.target],[f'/relations/{i}'],r.grounding.behavior_ids+r.grounding.expectation_ids,'Relation endpoint does not exist; keep a reading gap instead of inventing an endpoint',['association','read'])
    for i,u in enumerate(proposal.units):
        if not set(u.goal_ids+u.obligation_ids)<=set(claims) or not set(u.binding_ids)<=set(bindings):
            emit('unit_reference','association',[u.id],[f'/units/{i}'],[],'Audit unit references missing claims or bindings',['association']);continue
        for b in [bindings[id] for id in u.binding_ids]:
            if not claim_ids(b)<=set(claims):continue
            if not relevant_use(u,b,proposal.relations,materials):
                related=[r for r in proposal.relations if r.id in u.relation_ids and (r.source in u.obligation_ids or r.target in claim_ids(b))]
                sources=[b.material_id]+[x for r in related for x in r.grounding.behavior_ids+r.grounding.expectation_ids]
                emit('unit_code_use','association',[u.id,b.id]+sorted(claim_ids(b))+[r.id for r in related],[f'/units/{i}/code_uses'],sources,'Audit unit contains a binding unrelated to its claims without an explicit selected support use',['association','read','semantic_revision'])
    return issues


def require_graph(state,proposal):
    issues=diagnose_graph(state,proposal)
    if issues:raise DiagnosticError(issues)
