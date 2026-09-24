"""Dependency-ordered, non-mutating candidate diagnostics."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .locations import locate, location_context
from .sources import covered
from .associations import claim_ids,relevant_use,dependency_reach,graph_contract


def grounding_errors(basis,materials,binding_ids):
    errors=[]
    if not basis.derivation.strip() or not basis.applicability.strip():
        errors.append((['derivation','applicability'],'A derivation and implementation applicability are required, not a source file kind'))
    if not basis.source_ids and not basis.expectation_ids:
        errors.append((['source_ids','expectation_ids'],'Grounding must reference actually read materials'))
    for field in ('source_ids','expectation_ids'):
        unknown=set(getattr(basis,field))-set(materials)
        if unknown:errors.append(([field],'Grounding must reference actually read materials; unknown '+field+': '+', '.join(sorted(unknown))))
    if not set(basis.binding_ids)<=set(binding_ids):
        errors.append((['binding_ids'],'Grounding references unavailable code bindings'))
    if not basis.expectation_ids and not basis.binding_ids:
        errors.append((['binding_ids'],'Derived responsibilities need a located implementation binding; adequacy requires semantic review'))
    return errors


def validate_grounding(basis,materials,binding_ids):
    errors=grounding_errors(basis,materials,binding_ids)
    if errors:raise ValueError('; '.join(message for _,message in errors))


def diagnose_graph(state,proposal,audit_spec=None):
    issues=[];materials={m.id:m for m in state.materials}
    def emit(code,category,ids,paths,sources,message,allowed):
        # One citation mistake often repeats across the same draft. Repair that
        # field family together within the existing 24-replacement interface.
        if code=='grounding_reference' and issues and issues[-1].code==code and len(issues[-1].paths)+len(paths)<=24:
            previous=issues[-1]
            previous.object_ids=list(dict.fromkeys(previous.object_ids+ids))
            previous.paths+=paths;previous.material_ids=list(dict.fromkeys(previous.material_ids+sources))
            previous.message+='; '+message
            return
        issues.append(Diagnostic(code=code,category=category,object_ids=ids,paths=paths,material_ids=list(dict.fromkeys(sources)),message=message,allowed=allowed))
    collections=['claims','bindings','relations','units'];all_ids=[o.id for name in collections for o in getattr(proposal,name)]
    if len(set(all_ids))!=len(all_ids):
        duplicate={id for id in all_ids if all_ids.count(id)>1}
        paths=[f'/{name}/{i}/id' for name in collections for i,o in enumerate(getattr(proposal,name)) if o.id in duplicate]
        emit('duplicate_identity','association',sorted(duplicate),paths,[],'Duplicate graph identifiers',['association']);return issues
    if len(all_ids)>state.config.get('budget',{}).get('graph_objects',1000):
        emit('graph_capacity','format',all_ids,['/'+name for name in collections],[],'Configured graph object budget exceeded',['representation'])
    claims={c.id:c for c in proposal.claims};bindings={b.id:b for b in proposal.bindings}
    for i,c in enumerate(proposal.claims):
        if not set(c.source_ids)<=set(materials):emit('missing_material','material',[c.id],[f'/claims/{i}/source_ids'],c.source_ids,'Claim references unread material',['read'])
    for collection in ('claims','relations'):
        for i,obj in enumerate(getattr(proposal,collection)):
            problems=grounding_errors(obj.grounding,materials,bindings)
            if problems:
                fields=list(dict.fromkeys(f for names,_ in problems for f in names))
                supplied=[id for id in obj.grounding.source_ids+obj.grounding.expectation_ids if id in materials]
                emit('grounding_reference','material',[obj.id],[f'/{collection}/{i}/grounding/{f}' for f in fields],supplied,
                     '; '.join(message for _,message in problems),['representation','read'])
                issues[-1].details={'reference_contract':graph_contract()['material_references'],
                    'available_material_ids':list(materials),'available_binding_ids':list(bindings),
                    'preservation':'Do not change derivation, applicability, unresolved conditions or expectation meaning to make a citation pass.'}
    for i,b in enumerate(proposal.bindings):
        ids=claim_ids(b)
        if len(ids)!=len(b.associations):
            emit('duplicate_association','association',[b.id],[f'/bindings/{i}/associations'],[b.material_id],'Duplicate claim association for one physical binding',['association']);continue
        if not ids<=set(claims) or b.material_id not in materials:
            emit('binding_reference','association',[b.id]+sorted(ids),[f'/bindings/{i}/associations',f'/bindings/{i}/material_id'],[b.material_id],'Binding references an unknown claim or material',['read','association']);continue
        for j,association in enumerate(b.associations):
            if not set(association.source_ids)<=set(materials) or not association.rationale.strip():
                emit('binding_association','association',[b.id,association.claim_id],[f'/bindings/{i}/associations/{j}'],[b.material_id],'Code association requires actual sources and rationale',['association','read'])
        m=materials[b.material_id]
        if m.file not in state.snapshot.files or not covered(m.model_copy(update={'start_line':b.start_line,'end_line':b.end_line}),materials.values()):
            emit('behavior_range','location',[b.id],[f'/bindings/{i}/{f}' for f in ['symbol','material_id','anchor','start_line','end_line']],[m.id],'Binding range is outside the read code snapshot',['representation','read']);continue
        anchor,reason=locate(b,materials)
        if not anchor:
            evidence=location_context(b,materials)
            evidence["file_metadata"]=state.file_index.get(m.file,{})
            emit('declaration_identity','location',[b.id],[f'/bindings/{i}/{f}' for f in ['symbol','material_id','anchor','start_line','end_line']],evidence['material_ids'],f'Binding {b.id}: literal symbol {b.symbol!r} has no verified declaration: '+reason,['representation','read'])
            issues[-1].details=evidence
    for i,r in enumerate(proposal.relations):
        if r.source not in set(claims)|set(bindings) or r.target not in set(claims)|set(bindings):
            emit('relation_endpoint','association',[r.id,r.source,r.target],[f'/relations/{i}'],r.grounding.source_ids+r.grounding.expectation_ids,'Relation endpoint does not exist; keep a reading gap instead of inventing an endpoint',['association','read'])
    from .audit_spec import load,validate_question
    spec=audit_spec or load(state)
    relations={r.id:r for r in proposal.relations}
    for i,u in enumerate(proposal.units):
        sources=list(dict.fromkeys([bindings[id].material_id for id in u.binding_ids if id in bindings]+(u.audit_question.source_ids if u.audit_question else [])))
        for field,known in [('obligation_ids',{id for id,c in claims.items() if c.kind=='obligation'}),('binding_ids',set(bindings)),('relation_ids',set(relations))]:
            missing=set(getattr(u,field))-known
            if missing:emit('unit_reference','association',[u.id,*sorted(missing)],[f'/units/{i}/{field}'],sources,'Audit unit references missing '+field+': '+', '.join(sorted(missing)),['association','read'])
        if len(u.obligation_ids)!=1:
            emit('unit_primary','semantic',[u.id],[f'/units/{i}/obligation_ids'],sources,'One primary obligation is required',['semantic_revision'])
        reached,used=dependency_reach(u,proposal.relations)
        if set(u.relation_ids)<=relations.keys() and used!=set(u.relation_ids):
            emit('unit_dependency','association',[u.id],[f'/units/{i}/relation_ids'],sources,'Selected dependencies must form directed paths from the checked obligation',['association','read'])
        for b in [bindings[id] for id in u.binding_ids if id in bindings]:
            if not relevant_use(u,b,proposal.relations):
                emit('unit_dependency','association',[u.id,b.id,*sorted(claim_ids(b))],[f'/units/{i}/relation_ids',f'/units/{i}/binding_ids'],sources,'Selected code has no direct association or selected directed dependency path',['association','read','semantic_revision'])
                issues[-1].details={'contract':graph_contract()['dependency']}
        q=u.audit_question
        if q and (not q.question.strip() or not q.importance.strip() or not q.source_ids or not set(q.source_ids)<=set(materials)):
            emit('audit_question','semantic',[u.id],[f'/units/{i}/audit_question'],sources,'Audit question requires actual materials and significance',['read','semantic_revision'])
        if q and (q.disposition is not None or state.analysis_mode!='regression'):
            from .direct_checks import validate_question as validate_route
            try:validate_route(q)
            except ValueError as exc:emit('audit_question','semantic',[u.id],[f'/units/{i}/audit_question'],sources,str(exc),['read','semantic_revision'])
        if q and (q.behavior_ids or q.fact_ids):
            try:
                if not spec:raise ValueError('A generated question requires accepted implementation understanding')
                validate_question(spec,q)
            except ValueError as exc:
                emit('audit_question','semantic',[u.id],[f'/units/{i}/audit_question'],sources,str(exc),['read','semantic_revision'])
    return issues


def require_graph(state,proposal,audit_spec=None):
    issues=diagnose_graph(state,proposal,audit_spec)
    if issues:raise DiagnosticError(issues)
