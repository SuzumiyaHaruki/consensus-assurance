"""Assignment is a sourced plan, not completed interaction coverage."""

def handoff_status(state,role,handoff):
    other=next((r for r in state.responsibilities if r.id==handoff.target_id),None)
    relevant=[]
    if other:
        for unit in state.units:
            if unit.id not in handoff.covered_by_unit_ids or not unit.audit_question:continue
            points=unit.coverage_intent+unit.audit_question.points
            for point in points:
                if point.phase not in {'handoff','use','maintain','recover'}:continue
                if not set(point.source_ids)&set(handoff.source_ids):continue
                referenced=set(point.claim_ids)|{c for use in unit.code_uses for c in use.claim_ids}
                if not referenced&set(role.claim_ids) or not referenced&set(other.claim_ids):continue
                if not any(r.id in unit.relation_ids and r.kind in {'boundary','depends_all','conditional_on'} and ((r.source in role.claim_ids and r.target in other.claim_ids) or (r.target in role.claim_ids and r.source in other.claim_ids)) for r in state.relations):continue
                relevant.append({'unit_id':unit.id,'version':unit.version,'execution_status':unit.status,'coverage_limitations':unit.coverage_limitations})
    return {'assignments':relevant,'status':'assigned_not_proven' if relevant else 'unassigned','reason_needs_review':bool(handoff.no_separate_check_reason)}
