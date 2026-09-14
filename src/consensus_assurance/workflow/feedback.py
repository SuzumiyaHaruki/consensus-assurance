from consensus_assurance.core.types import Revision
from .graph import apply_patch, expand_unit, validate_grounding


def apply_feedback(state, unit, current, feedback):
    known = {c.id for c in state.checks} | {c.id for c in state.calibrations} | {m.id for m in state.materials}
    if not set(feedback.evidence_ids) <= known or not feedback.evidence_ids:
        raise ValueError("Semantic feedback requires recorded evidence or material sources")
    targets = {c.id for c in state.claims} | {b.id for b in state.bindings} | {m.id for m in state.models} | {u.id for u in state.units}
    if not feedback.target_ids or not set(feedback.target_ids) <= targets:
        raise ValueError("Feedback target does not exist")
    before = {"unit": unit.model_dump(mode="json"), "checked_claim_ids": current.checked_claim_ids,
              "properties": current.properties, "scope": current.scope.model_dump(mode="json"),
              "behavior": current.behavior, "observation": current.observation.model_dump(), "harness": current.harness.model_dump()}
    affected = [m.id for m in state.models if m.unit_id == unit.id]
    if feedback.kind == "F1":
        if feedback.bundle is None or feedback.graph is not None:
            raise ValueError("F1 revises behavior, mapping or environment only")
        if feedback.bundle.properties != current.properties or feedback.bundle.checker_specs() != current.checker_specs():
            raise ValueError("F1 cannot change the checked property")
        result, step = feedback.bundle, "build"
    elif feedback.kind == "F2":
        if feedback.patch is None or feedback.bundle is not None or not feedback.new_basis.strip() or not feedback.old_judgment.strip() or not feedback.new_judgment.strip():
            raise ValueError("F2 requires old/new judgments, attributed reasoning, and an incremental semantic patch")
        validate_grounding(feedback.grounding, {m.id:m for m in state.materials}, {b.id for b in state.bindings})
        if feedback.grounding.conflicts or feedback.grounding.unresolved:
            state.gaps.append("F2 remains unresolved: conflicting or insufficient applicability evidence")
            state.revisions.append(Revision(kind="F2", rationale=feedback.rationale,
                evidence_ids=feedback.evidence_ids, target_ids=feedback.target_ids, before=before,
                after={"old_judgment":feedback.old_judgment,"new_judgment":feedback.new_judgment,
                       "grounding":feedback.grounding.model_dump()}, return_step="understand", status="unresolved"))
            return None
        if not set(feedback.evidence_ids) & set(feedback.grounding.behavior_ids + feedback.grounding.expectation_ids):
            raise ValueError("A failed trace alone cannot authorize a semantic weakening")
        current_claims = {c.id:c for c in state.claims}
        if not any(c.id in current_claims and current_claims[c.id].description == feedback.old_judgment and c.description == feedback.new_judgment for c in feedback.patch.claims):
            raise ValueError("F2 old/new judgments must identify an actual claim revision")
        changed = apply_patch(state, feedback.patch, semantic=True)
        affected = [m.id for m in state.models if changed & (set(m.binding_ids) | {c.claim_id for c in m.checkers} | set(m.graph_versions))]
        before["old_judgment"] = feedback.old_judgment
        result, step = None, "understand"
    elif feedback.kind == "F3":
        if feedback.bundle is not None or feedback.graph is not None or feedback.patch is not None:
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
        affected = []
    else:
        state.gaps.append("Unresolved attribution: " + feedback.rationale)
        return None
    if feedback.kind != "F4":
        state.affect(affected, feedback.rationale, historical=feedback.kind == "F3")
    after = {"scope": result.scope.model_dump(mode="json") if hasattr(result, "scope") else {},
             "unit_id": result.id if hasattr(result, "id") else unit.id,
             "graph_version": state.graph_version, "new_judgment": feedback.new_judgment,
             "grounding": feedback.grounding.model_dump(), "affected_model_ids": affected,
             "property_changes": feedback.new_basis,
             "behavior": feedback.bundle.behavior if feedback.bundle else None,
             "observation": feedback.bundle.observation.model_dump() if feedback.bundle else None,
             "harness": feedback.bundle.harness.model_dump() if feedback.bundle else None}
    revision = Revision(kind=feedback.kind, rationale=feedback.rationale, evidence_ids=feedback.evidence_ids,
        target_ids=feedback.target_ids, relation_ids=feedback.relation_ids, before=before, after=after, return_step=step)
    state.revisions.append(revision)
    return result
