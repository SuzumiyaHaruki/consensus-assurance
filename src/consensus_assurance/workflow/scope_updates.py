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
    sources={b.material_id for b in patch.bindings}
    for r in patch.relations:sources.update(r.grounding.behavior_ids+r.grounding.expectation_ids)
    for u in patch.units:
        for use in u.code_uses:sources.update(use.source_ids)
    return ScopeUpdate(unit_id=unit.id,unit_version=unit.version,original_question=question(unit),obligation_ids=unit.obligation_ids,
        patch=patch,changes=changes,source_ids=sorted(sources),remaining_unknowns=list(dict.fromkeys([x for use in unit.code_uses for x in use.unverified]+unit.coverage_limitations)))


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
    old_uses={u.binding_id:u for u in unit.code_uses};new_uses={u.binding_id:u for u in draft.code_uses}
    if any(id not in new_uses or old.role!=new_uses[id].role or old.claim_ids!=new_uses[id].claim_ids for id,old in old_uses.items()):reject(update,'scope_use_reinterpreted','Existing code roles and responsibility associations cannot be replaced by scope refinement',writes)
    from .audit_spec import IDENTITY
    if unit.audit_question and (not draft.audit_question or any(getattr(draft.audit_question,k)!=getattr(unit.audit_question,k) for k in IDENTITY)):reject(update,'scope_question_changed','Replacing the audit question requires explicit semantic review',writes)
    refined={f for id,f in writes if f in {'audit_question'}}
    if any(old!=new_uses[id] for id,old in old_uses.items()):refined.add('code_uses')
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


def accept(engine,update):
    from .transactions import commit_graph
    from . import inquiry
    def commit(proxy):
        proxy.budget.take('revisions')
        new=apply_scope_update(proxy.state,update)
        proxy.state.deferred_units.pop(update.unit_id,None)
        proxy.state.active_unit_id=new.id;proxy.state.active_model_id=None;proxy.state.active_finding_id=None;proxy.state.next_action='build'
        proxy.state.scope_updates[update.id]={'status':'accepted','proposal':update.model_dump(mode='json'),'new_unit_id':new.id}
        inherited=proxy.state.task_attachments.get('unit:'+update.unit_id,[])
        proxy.state.task_attachments['unit:'+new.id]=list(dict.fromkeys(inherited+update.source_ids))
        proxy.state.targeted_gap=None
        inquiry.release_action(proxy)
        inquiry.review_unit(proxy,new,'before_model')
    commit_graph(engine,'scope-'+update.id,update.model_dump(mode='json'),commit)
    return next(u for u in engine.state.units if u.id==engine.state.active_unit_id)
