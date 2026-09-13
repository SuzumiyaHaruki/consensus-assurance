from consensus_assurance.core.types import Revision
from .graph import apply_discovery, expand_unit


def apply_feedback(state, unit, current, feedback):
    known = {c.id for c in state.checks} | {c.id for c in state.calibrations} | {m.id for m in state.materials}
    if not set(feedback.evidence_ids) <= known or not feedback.evidence_ids:
        raise ValueError("Semantic feedback requires recorded evidence or material sources")
    targets = {c.id for c in state.claims} | {b.id for b in state.bindings} | {m.id for m in state.models} | {u.id for u in state.units}
    if not feedback.target_ids or not set(feedback.target_ids) <= targets:
        raise ValueError("Feedback target does not exist")
    before = {"unit": unit.model_dump(mode="json"), "checked_claim_ids": current.checked_claim_ids,
              "properties": current.properties, "scope": current.scope.model_dump(mode="json")}
    if feedback.kind == "F1":
        if feedback.bundle is None or feedback.graph is not None:
            raise ValueError("F1 revises behavior, mapping or environment only")
        if feedback.bundle.properties != current.properties or feedback.bundle.invariants != current.invariants or feedback.bundle.checked_claim_ids != current.checked_claim_ids:
            raise ValueError("F1 cannot change the checked property")
        result, step = feedback.bundle, "build"
    elif feedback.kind == "F2":
        if feedback.graph is None or feedback.bundle is not None or not feedback.new_basis.strip():
            raise ValueError("F2 requires a semantic graph revision with a new attributed basis")
        if not set(feedback.evidence_ids) & {m.id for m in state.materials if m.kind != "code_observation"}:
            raise ValueError("F2 requires normative material, not just a failed check")
        apply_discovery(state, feedback.graph)
        result, step = None, "understand"
    elif feedback.kind == "F3":
        if feedback.bundle is not None or feedback.graph is not None:
            raise ValueError("F3 expands the scope before regenerating model semantics")
        result = expand_unit(state, unit, feedback.relation_ids)
        step = "select"
    elif feedback.kind == "F4":
        if feedback.bundle is None or feedback.graph is not None:
            raise ValueError("F4 requires an experiment-only revision")
        left, right = current.model_dump(), feedback.bundle.model_dump()
        left.pop("harness"); right.pop("harness")
        if left != right:
            raise ValueError("F4 may only revise the experiment")
        result, step = feedback.bundle, "experiment"
    else:
        state.gaps.append("Unresolved attribution: " + feedback.rationale)
        return None
    state.invalidate("Revalidation required after " + feedback.kind + ": " + feedback.rationale)
    after = {"scope": result.scope.model_dump(mode="json") if hasattr(result, "scope") else {},
             "unit_id": result.id if hasattr(result, "id") else unit.id,
             "graph_version": state.graph_version}
    revision = Revision(kind=feedback.kind, rationale=feedback.rationale, evidence_ids=feedback.evidence_ids,
        target_ids=feedback.target_ids, relation_ids=feedback.relation_ids, before=before, after=after, return_step=step)
    state.revisions.append(revision)
    return result
