"""Dependency-ordered, non-mutating candidate diagnostics."""
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .locations import locate, location_context
from .sources import covered
from .associations import claim_ids,use_errors,goal_links,graph_contract


def grounding_errors(basis,materials,binding_ids):
    errors=[]
    if not basis.derivation.strip() or not basis.applicability.strip():
        errors.append((['derivation','applicability'],'A derivation and implementation applicability are required, not a source file kind'))
    if not basis.behavior_ids and not basis.expectation_ids:
        errors.append((['behavior_ids','expectation_ids'],'Grounding must reference actually read materials'))
    for field in ('behavior_ids','expectation_ids'):
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


def diagnose_graph(state,proposal):
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
        emit('duplicate_identity','association',all_ids,[],[],'Duplicate graph identifiers',['stop']);return issues
    claims={c.id:c for c in proposal.claims};bindings={b.id:b for b in proposal.bindings}
    for i,c in enumerate(proposal.claims):
        if not set(c.source_ids)<=set(materials):emit('missing_material','material',[c.id],[f'/claims/{i}/source_ids'],c.source_ids,'Claim references unread material',['read'])
    for collection in ('claims','relations'):
        for i,obj in enumerate(getattr(proposal,collection)):
            problems=grounding_errors(obj.grounding,materials,bindings)
            if problems:
                fields=list(dict.fromkeys(f for names,_ in problems for f in names))
                supplied=[id for id in obj.grounding.behavior_ids+obj.grounding.expectation_ids if id in materials]
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
            emit('relation_endpoint','association',[r.id,r.source,r.target],[f'/relations/{i}'],r.grounding.behavior_ids+r.grounding.expectation_ids,'Relation endpoint does not exist; keep a reading gap instead of inventing an endpoint',['association','read'])
    for i,u in enumerate(proposal.units):
        if not set(u.goal_ids+u.obligation_ids)<=set(claims) or not set(u.binding_ids)<=set(bindings):
            emit('unit_reference','association',[u.id],[f'/units/{i}'],[],'Audit unit references missing claims or bindings',['association']);continue
        for b in [bindings[id] for id in u.binding_ids]:
            if not claim_ids(b)<=set(claims):continue
            problems=use_errors(u,b,proposal.relations,materials)
            if problems:
                related=[r for r in proposal.relations if r.id in u.relation_ids and (r.source in u.obligation_ids or r.target in claim_ids(b))]
                sources=[b.material_id]+[x for r in related for x in r.grounding.behavior_ids+r.grounding.expectation_ids]
                emit('unit_code_use','association',[u.id,b.id]+sorted(claim_ids(b))+[r.id for r in related],[f'/units/{i}/code_uses'],[id for id in sources if id in materials],'; '.join(problems),['association','read','semantic_revision'])
                issues[-1].details={'failed_checks':problems,'contract':graph_contract()['code_use'],
                    'selected_obligation_ids':u.obligation_ids,'binding_association_ids':sorted(claim_ids(b)),
                    'selected_relations':[r.model_dump(mode='json') for r in related]}
        if not goal_links(u,proposal.relations):
            emit('goal_obligation_link','association',[u.id]+u.goal_ids+u.obligation_ids,
                 ['/relations/-',f'/units/{i}/relation_ids'],
                 [id for c in proposal.claims if c.id in u.goal_ids+u.obligation_ids for id in c.source_ids if id in materials],
                 'Unit needs a selected goal-to-obligation relationship (goal -> checked obligation) of an allowed kind; reversed maps do not satisfy it',
                 ['association','read','semantic_revision'])
            issues[-1].details={'contract':graph_contract()['goal_links'],
                'preservation':'Add a sourced relation only if justified; do not reverse existing meaning, weaken claims or change checked obligations.'}
    return issues


def require_graph(state,proposal):
    issues=diagnose_graph(state,proposal)
    if issues:raise DiagnosticError(issues)
