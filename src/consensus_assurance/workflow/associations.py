"""One authoritative per-location association list; unit use is separate from checking."""

DIRECT_ROLES=('direct','input','environment')
DEPENDENCY_KINDS=('boundary','depends_all','conditional_on')


def graph_contract():
    return {'material_references':'Grounding.behavior_ids/expectation_ids and source_ids reference acquired material IDs only; binding_ids reference code bindings.',
        'code_use':{'direct_roles':list(DIRECT_ROLES),'direct_condition':'Use claim_ids are associated with the binding and selected as unit obligations.',
            'dependency_kinds':list(DEPENDENCY_KINDS),'dependency_direction':'checked obligation -> producer obligation or binding',
            'support_condition':'Every selected dependency edge must be reachable in that direction, reach the used binding or associated claim, and retain unverified guarantees. Unselected mappings alone do not provide a dependency path.'},
        'repair':'Source-reference correction must preserve derivation and applicability. A new relation needs sourced rationale and full graph validation; existing meaning cannot be silently reversed.'}



def claim_ids(binding):
    return {a.claim_id for a in binding.associations}


def support_path(unit,use,binding,relations):
    if not set(use.relation_ids)<=set(unit.relation_ids):return False
    selected={r.id:r for r in relations if r.id in use.relation_ids}
    if len(selected)!=len(set(use.relation_ids)) or not selected:return False
    reached=set(unit.obligation_ids);used=set()
    for _ in range(len(selected)):
        for id,r in selected.items():
            if r.source in reached and r.kind in DEPENDENCY_KINDS:
                reached.add(r.target);used.add(id)
    return used==set(selected) and bool(claim_ids(binding)&set(use.claim_ids)) and (binding.id in reached or bool(claim_ids(binding)&set(use.claim_ids)&reached))


def use_errors(unit,binding,relations,materials):
    use=next((u for u in unit.code_uses if u.binding_id==binding.id),None)
    direct=claim_ids(binding)&set(unit.obligation_ids)
    if use is None:return [] if direct else ['Binding is unrelated to selected claims: no selected association or explicit dependency use']
    errors=[]
    if not set(use.claim_ids)<=claim_ids(binding):errors.append('Use claim_ids are not all associated with this binding')
    if not set(use.source_ids)<=set(materials):errors.append('Use source_ids include unacquired material')
    if not use.rationale.strip():errors.append('Use rationale is empty')
    if errors:return errors
    if use.role in DIRECT_ROLES and set(use.claim_ids)<=set(unit.obligation_ids):
        return [] if direct else ['No association to selected obligations']
    if not use.unverified:errors.append('Dependency use must retain unverified producer guarantees')
    if not support_path(unit,use,binding,relations):
        errors.append('No complete selected directed dependency path from checked obligations to this binding or its used claims; unselected supports/alternative edges do not count')
    return errors


def relevant_use(unit,binding,relations,materials):
    return not use_errors(unit,binding,relations,materials)
