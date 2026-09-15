"""One authoritative per-location association list; unit use is separate from checking."""

def claim_ids(binding):
    return {a.claim_id for a in binding.associations}


def support_path(unit,use,binding,relations):
    if not set(use.relation_ids)<=set(unit.relation_ids):return False
    selected={r.id:r for r in relations if r.id in use.relation_ids}
    if len(selected)!=len(set(use.relation_ids)) or not selected:return False
    reached=set(unit.obligation_ids);used=set()
    for _ in range(len(selected)):
        for id,r in selected.items():
            if r.source in reached and r.kind in {'boundary','depends_all','conditional_on'}:
                reached.add(r.target);used.add(id)
    return used==set(selected) and bool(claim_ids(binding)&set(use.claim_ids)&reached)


def relevant_use(unit,binding,relations,materials):
    use=next((u for u in unit.code_uses if u.binding_id==binding.id),None)
    direct=claim_ids(binding)&set(unit.goal_ids+unit.obligation_ids)
    if use is None:return bool(direct)
    if not set(use.claim_ids)<=claim_ids(binding) or not set(use.source_ids)<=set(materials) or not use.rationale.strip():return False
    if use.role=='direct':return bool(set(use.claim_ids)&set(unit.goal_ids+unit.obligation_ids))
    return bool(use.unverified) and support_path(unit,use,binding,relations)
