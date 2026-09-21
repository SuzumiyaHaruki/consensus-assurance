"""Selected locations and directed dependencies; no duplicate authored code-use map."""
DEPENDENCY_KINDS=('depends_all','conditional_on','boundary')


def graph_contract():
    return {'material_references':'Grounding.source_ids/expectation_ids and source_ids reference acquired material IDs; binding_ids reference located code.',
        'dependency':{'kinds':list(DEPENDENCY_KINDS),'direction':'checked obligation -> producer obligation or binding',
            'direct':'A selected binding associated with the checked obligation needs no relation.',
            'support':'Other selected bindings need a selected directed path from the checked obligation. Keep producer guarantees unresolved in relation grounding/pending or binding pending; selecting support does not check its obligation.'},
        'repair':'Preserve attribution, applicability and unresolved conditions; source-backed semantic changes require F2.'}


def claim_ids(binding):return {a.claim_id for a in binding.associations}


def dependency_reach(unit,relations):
    selected=[r for r in relations if r.id in unit.relation_ids and r.kind in DEPENDENCY_KINDS]
    reached=set(unit.obligation_ids);used=set()
    for _ in selected:
        for edge in selected:
            if edge.source in reached:reached.add(edge.target);used.add(edge.id)
    return reached,used


def relevant_use(unit,binding,relations,materials=None):
    if claim_ids(binding)&set(unit.obligation_ids):return True
    reached,used=dependency_reach(unit,relations)
    return (binding.id in reached or bool(claim_ids(binding)&reached)) and bool(used)
