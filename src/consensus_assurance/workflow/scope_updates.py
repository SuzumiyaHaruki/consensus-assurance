"""Reconnect grounded dependencies through F3 without authorizing normative changes."""
from consensus_assurance.core.types import Record,uid,Revision
from consensus_assurance.core.proposals import GraphPatch, JudgmentChange
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from .mutations import write_set,adopt,canonical,classify_writes
from pydantic import Field
from typing import Literal
import json


class ScopeAssessment(Record):
    decision: Literal['refinement','semantic_change','unresolved']
    source_ids: list[str] = Field(min_length=1)
    addressed_fields: list[str]
    preserved_question: str
    rationale: str
    remaining_unknowns: list[str]


class ScopeUpdate(Record):
    id: str = Field(default_factory=uid)
    read_plan_id: str | None = None
    unit_id: str
    unit_version: int
    original_question: str
    obligation_ids: list[str]
    patch: GraphPatch
    changes: list[JudgmentChange]
    source_ids: list[str]
    remaining_unknowns: list[str]
    continue_at: Literal['build'] = 'build'
    assessment: ScopeAssessment | None = None


def question(unit):return unit.audit_question.question if unit.audit_question else unit.rationale


def from_patch(state,unit,patch):
    changes=[JudgmentChange(target_id=id,field=f,old_value_json=json.dumps(a,ensure_ascii=False),new_value_json=json.dumps(b,ensure_ascii=False)) for (id,f),(a,b) in write_set(state,patch).items()]
    from .sources import dependency_closure
    objects={x.id:x for name in ('claims','bindings','relations','units') for x in getattr(state,name)}
    objects.update({x.id:x for name in ('claims','bindings','relations','units') for x in getattr(patch,name)})
    sources,_=dependency_closure(objects,[u.id for u in patch.units])
    return ScopeUpdate(unit_id=unit.id,unit_version=unit.version,original_question=question(unit),obligation_ids=unit.obligation_ids,
        patch=patch,changes=changes,source_ids=sorted(sources),remaining_unknowns=list(dict.fromkeys(unit.coverage_limitations+[x for b in state.bindings if b.id in unit.binding_ids for x in b.pending]+[x for r in state.relations if r.id in unit.relation_ids for x in r.pending+r.grounding.unresolved])))


def reject(update,code,message,writes):
    raise DiagnosticError([Diagnostic(code=code,category='semantic',object_ids=[update.unit_id],paths=[],material_ids=update.source_ids,
        message=message,allowed=['semantic_revision','stop'],details={'actual_fields':[{'object_id':id,'field':f,'old':a,'new':b} for (id,f),(a,b) in writes.items()],'next_action':'Record a scoped F2 or unresolved investigation; never silently apply a mixed patch'})])


def validate_scope_update(state,update):
    unit=next((u for u in state.units if u.id==update.unit_id),None)
    if unit is None or unit.version!=update.unit_version:raise ValueError('Scope source unit/version no longer matches')
    writes=write_set(state,update.patch)
    if update.original_question!=question(unit) or update.obligation_ids!=unit.obligation_ids:reject(update,'scope_question_changed','Scope update must preserve the original question and checked claims',writes)
    declared={(c.target_id,c.field):(json.loads(c.old_value_json),json.loads(c.new_value_json)) for c in update.changes}
    if len(declared)!=len(update.changes) or canonical(declared_to_list(declared))!=canonical(declared_to_list(writes)):reject(update,'scope_diff_mismatch','Scope changes must describe the entire actual diff',writes)
    if classify_writes(writes,unit.id)=='semantic_revision':reject(update,'scope_requires_F2','Changed existing semantic objects or fault/configuration scope require scoped F2',writes)
    if set(update.patch.expected_versions)!={unit.id} or update.patch.expected_versions[unit.id]!=unit.version:raise ValueError('Scope update requires exactly its source unit version')
    if len(update.patch.units)!=1 or update.patch.units[0].id!=unit.id:raise ValueError('Scope update must address one existing unit')
    draft=update.patch.units[0]
    if not set(unit.binding_ids)<=set(draft.binding_ids) or not set(unit.relation_ids)<=set(draft.relation_ids):reject(update,'scope_removed_path','Removing existing code or dependency paths requires semantic investigation',writes)
    if not update.source_ids or not set(update.source_ids)<={m.id for m in state.materials}:raise ValueError('Scope update requires actually acquired sources')
    from .audit_spec import IDENTITY
    if unit.audit_question and (not draft.audit_question or any(getattr(draft.audit_question,k)!=getattr(unit.audit_question,k) for k in IDENTITY)):reject(update,'scope_question_changed','Replacing the audit question requires explicit semantic review',writes)
    refined={f for id,f in writes if f in {'audit_question'}}
    from .graph import apply_patch
    candidate=new_candidate_patch(state,update)
    try:apply_patch(state.model_copy(deep=True),candidate)
    except DiagnosticError as exc:
        # Explicit provenance, not ID-prefix guessing or merged-array coordinates.
        identities={candidate.units[0].id:update.unit_id}
        for d in exc.diagnostics:
            d.object_ids=[identities.get(id,id) for id in d.object_ids]
            d.details['proposal_identity_map']=identities
        raise
    if refined:
        a=update.assessment
        if a is None:return sorted(refined)
        if a.decision!='refinement' or a.preserved_question!=update.original_question or not refined<=set(a.addressed_fields) or not a.rationale.strip() or not set(a.source_ids)<=set(update.source_ids):reject(update,'scope_interpretation_unresolved','The changed paths require an attributed refinement judgment; semantic changes remain F2 work',writes)
    return []


def declared_to_list(values):return sorted((id,f,a,b) for (id,f),(a,b) in values.items())


def new_candidate_patch(state,update):
    patch=update.patch.model_copy(deep=True);patch.expected_versions={};patch.units[0].id=update.unit_id+'.scope.'+update.id
    current={o.id for o in state.claims+state.bindings+state.relations}
    for kind in ('claims','bindings','relations'):setattr(patch,kind,[o for o in getattr(patch,kind) if o.id not in current])
    return patch


def apply_scope_update(state,update):
    needed=validate_scope_update(state,update)
    if needed:reject(update,'scope_review_needed','Review the changed event/coverage interpretation before adoption',write_set(state,update.patch))
    trial=state.model_copy(deep=True);old=next(u for u in trial.units if u.id==update.unit_id)
    new_id=old.id+'.scope.'+update.id
    existing=next((u for u in trial.units if u.id==new_id),None)
    if existing:return existing
    patch=new_candidate_patch(trial,update)
    from .graph import apply_patch
    apply_patch(trial,patch)
    old=next(u for u in trial.units if u.id==update.unit_id);new=next(u for u in trial.units if u.id==new_id)
    new.previous_id=old.id;new.version=old.version+1
    new.semantic_readiness={};new.remaining_obligation_ids=list(new.obligation_ids)
    new.boundary_changes=['Grounded dependency scope update: '+update.patch.rationale]+update.remaining_unknowns
    if update.assessment:new.boundary_changes+=update.assessment.remaining_unknowns
    new.coverage_limitations=['Newly included support code is not a verified guarantee; current scope needs new model and observation checks']
    trial.graph_history.append({'kind':'units','id':old.id,'version':old.version,'record':old.model_dump(mode='json'),'reason':update.patch.rationale})
    old.status='revised';trial.units.remove(new);trial.units.insert(0,new)
    affected=[m.id for m in trial.models if m.unit_id==old.id];trial.affect(affected,update.patch.rationale,historical=True)
    trial.revisions.append(Revision(kind='F3',rationale=update.patch.rationale,evidence_ids=update.source_ids,target_ids=[old.id],relation_ids=patch.units[0].relation_ids,
        before={'unit':old.model_dump(mode='json'),'question':update.original_question},after={'unit_id':new.id,'scope_update':update.model_dump(mode='json'),'affected_model_ids':affected},return_step='build'))
    adopt(state,trial)
    return next(u for u in state.units if u.id==new_id)
