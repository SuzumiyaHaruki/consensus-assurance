from consensus_assurance.core.types import Revision
from .graph import _apply_patch, expand_unit
from .graph_diagnostics import validate_grounding
from .mutations import adopt, validate_changes


def _apply_feedback(state, unit, feedback, audit_spec=None):
    known = {c.id for c in state.checks} | {c.id for c in state.calibrations} | {m.id for m in state.materials}
    if not set(feedback.evidence_ids) <= known or not feedback.evidence_ids:
        raise ValueError("Semantic feedback requires recorded evidence or material sources")
    targets = {c.id for c in state.claims} | {b.id for b in state.bindings} | {m.id for m in state.models} | {u.id for u in state.units} | {r.id for r in state.relations}
    if not feedback.target_ids or not set(feedback.target_ids) <= targets:
        raise ValueError("Feedback target does not exist")
    before = {"unit": unit.model_dump(mode="json") if unit else None}
    if feedback.kind == "F3":
        if feedback.patch is not None or unit is None:
            raise ValueError("F3 requires an accepted unit and expands scope without a semantic patch")
        result = expand_unit(state, unit, feedback.relation_ids)
        state.revisions[-1].evidence_ids=list(dict.fromkeys(state.revisions[-1].evidence_ids+feedback.evidence_ids))
        return result
    if feedback.kind == "F2":
        if feedback.patch is None or not feedback.new_basis.strip() or not feedback.old_judgment.strip() or not feedback.new_judgment.strip():
            raise ValueError("F2 requires old/new judgments, attributed reasoning, and an incremental semantic patch")
        validate_changes(state,feedback)
        validate_grounding(feedback.grounding, {m.id:m for m in state.materials}, {b.id for b in state.bindings})
        conditions=feedback.grounding.conflicts+feedback.grounding.unresolved
        remaining=bool(conditions)
        if feedback.condition_dispositions:
            from .repair_policy import classify_conditions
            classified=classify_conditions(state,conditions,feedback.condition_dispositions,feedback.evidence_ids)
            remaining=any(c.applies_to=='current_judgment' for c in classified)
        if remaining:
            state.gaps.append("F2 remains unresolved: conflicting or insufficient applicability evidence")
            state.revisions.append(Revision(kind="F2", rationale=feedback.rationale,
                evidence_ids=feedback.evidence_ids, target_ids=feedback.target_ids, before=before,
                after={"old_judgment":feedback.old_judgment,"new_judgment":feedback.new_judgment,
                       "grounding":feedback.grounding.model_dump()}, return_step="understand", status="unresolved"))
            return None
        if not set(feedback.evidence_ids) & set(feedback.grounding.source_ids + feedback.grounding.expectation_ids):
            raise ValueError("A failed trace alone cannot authorize a semantic weakening")
        originals={obj.id:obj for obj in [*state.claims,*state.bindings,*state.relations,*state.units]}
        replaced={obj.id for name in ('claims','bindings','relations','units') for obj in getattr(feedback.patch,name)}
        before["semantic_objects"]={key:originals[key].model_dump(mode="json") for key in replaced if key in originals}
        changed = _apply_patch(state, feedback.patch, semantic=True, audit_spec=audit_spec)
        affected = [m.id for m in state.models if changed & (set(m.binding_ids) | {c.claim_id for c in m.checkers} | set(m.graph_versions))]
        before["old_judgment"] = feedback.old_judgment
    else:
        state.gaps.append("Unresolved attribution: " + feedback.rationale)
        return None
    state.affect(affected, feedback.rationale)
    after = {"scope": {}, "unit_id": unit.id if unit else None,
             "graph_version": state.graph_version, "new_judgment": feedback.new_judgment,
             "grounding": feedback.grounding.model_dump(), "affected_model_ids": affected,
             "condition_dispositions":[d.model_dump(mode="json") for d in feedback.condition_dispositions],
             "property_changes": feedback.new_basis, "changes":[c.model_dump(mode="json") for c in feedback.changes]}
    revision = Revision(kind=feedback.kind, rationale=feedback.rationale, evidence_ids=feedback.evidence_ids,
        target_ids=feedback.target_ids, relation_ids=feedback.relation_ids, before=before, after=after, return_step="understand")
    state.revisions.append(revision)


def apply_feedback(state, unit, feedback, audit_spec=None):
    trial=state.model_copy(deep=True)
    copied=next((u for u in trial.units if unit and u.id==unit.id),None)
    result=_apply_feedback(trial,copied,feedback,audit_spec)
    adopt(state,trial)
    return result
