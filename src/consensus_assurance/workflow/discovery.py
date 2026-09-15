"""Repository reading, candidate discovery and incremental dependency expansion."""
import json
from pathlib import Path
from consensus_assurance.core.proposals import Discovery, GraphPatch
from consensus_assurance.adapters.storage.files import write_json
from .materials import catalogue, initial_materials, ReadingPlan, uid, material_allowance
from .graph import apply_discovery, apply_patch, validate_patch
from .errors import Blocked
from . import inquiry


def context(engine, unit=None):
    result = {"materials": [m.model_dump(mode="json") for m in engine.state.materials],
        "capabilities": [c.model_dump(mode="json") for c in engine.state.capabilities],
        "parameters": engine.config.parameters, "remaining_seconds": engine.budget.remaining(),
        "directed_question": engine.config.directed_question,
        "snapshot_id": engine.state.snapshot.id,
        "responsibilities":[r.model_dump(mode="json") for r in engine.state.responsibilities],
        "semantic_reviews":[r.model_dump(mode="json") for r in engine.state.semantic_reviews], "harness_kind": engine.implementation.harness_kind,
        "harness_instructions": engine.implementation.harness_instructions}
    if unit:
        from .reviews import material_closure
        wanted,closure=material_closure(engine.state,[unit.id])
        wanted.update(engine.state.task_attachments.get('unit:'+unit.id,[]))
        result["materials"]=[m.model_dump(mode="json") for m in engine.state.materials if m.id in wanted]
        result["omitted_material_ids"]=[m.id for m in engine.state.materials if m.id not in wanted]
        result["semantic_reviews"]=[r.model_dump(mode="json") for r in engine.state.semantic_reviews if set(r.target_versions)&closure]
        result.update({"obligation_progress":{"checked_scopes":unit.obligation_checks,"remaining":unit.remaining_obligation_ids or unit.obligation_ids},
            "unit":unit.model_dump(mode="json"),
            "claims":[c.model_dump(mode="json") if c.id in closure else {"id":c.id,"kind":c.kind,"description":c.description,"version":c.version} for c in engine.state.claims],
            "bindings":[b.model_dump(mode="json") for b in engine.state.bindings if b.id in closure],
            "relations":[e.model_dump(mode="json") for e in engine.state.relations if e.id in closure or e.source in closure]})
    return result

def discover(engine):
    source = engine.root / "source"
    if "materials" not in engine.state.completed_steps:
        if not engine.state.materials and 'automatic-survey' not in engine.state.read_plans:
            sample=initial_materials(source, engine.state.snapshot, engine.config.budget, engine.knowledge)
            engine.read([{'file':m.file,'start_line':m.start_line,'end_line':m.end_line,'reason':'Automatic bounded survey'} for m in sample if m.kind!='protocol_candidate'],purpose='breadth',partial=True,plan_id='automatic-survey',charge=False)
            for m in sample:
                if m.kind=='protocol_candidate':engine.state.materials.append(m)
            engine.checkpoint('initial_sample_recorded')
        if not engine.state.materials and material_allowance(engine.state,engine.config.budget,"breadth")["available_chars"]==0:raise Blocked("No material capacity for a grounded initial plan; no agent request sent")
        inventory = catalogue(source, engine.state.snapshot,engine.implementation)
        write_json(engine.root / "catalogue.json", inventory)
        plan, _ = engine.ask("read", ReadingPlan, {"catalogue": inventory, "initial_materials": [m.model_dump(mode="json") for m in engine.state.materials]})
        engine.read(plan.requests,purpose="breadth",partial=True,plan_id="initial-reading",related_ids=plan.related_ids,reason=plan.rationale,charge=False)
        write_json(engine.root / "materials.json", [m.model_dump(mode="json") for m in engine.state.materials])
        engine.state.completed_steps.append("materials"); engine.advance("discover")
    if "discovery" not in engine.state.completed_steps:
        def validate(proposal):
            trial=engine.state.model_copy(deep=True)
            apply_discovery(trial,proposal)
            inquiry.register_responsibilities(trial,proposal.responsibilities)
            inquiry.register_requests(trial,proposal.exploration_requests,'validation')
        proposal, check = engine.ask("discover", Discovery, engine.context(), validate)
        from .transactions import commit_graph
        def initial(proxy):
            apply_discovery(proxy.state,proposal)
            inquiry.initial_agenda(proxy,proposal)
            from consensus_assurance.core.types import ReadRequest
            for id,plan in proxy.state.read_plans.items():
                if plan['purpose']=='breadth' and plan['status']!='complete':
                    pending=[ReadRequest.model_validate(i['request']) for i in plan['items'] if i['status']=='deferred']
                    task=inquiry.enqueue(proxy.state,'explore','Deferred initial material remains unexplored','deferred:'+id,requests=pending)
                    task.stop_reason='Reserved local dependency capacity; original ranges preserved'
        commit_graph(engine,"discovery-"+check.id,proposal.model_dump(mode="json"),initial)
        path = engine.root / f"discovery-v{engine.state.graph_version}.json"
        write_json(path, proposal); engine.state.discovery_path = str(path)
        engine.state.completed_steps.append("discovery"); engine.advance("select")

def targeted_read(engine, unit, gap, relation_ids=None, requests=None, update_required=True):
    source = engine.root/"source"
    if engine.state.targeted_gap is None:
        engine.state.targeted_gap={"plan_id":uid(),"requests":[q.model_dump(mode="json") if hasattr(q,"model_dump") else q for q in (requests or [])],"gap":gap,"related_ids":unit.obligation_ids if unit else [],
            "update_required":update_required,"relation_ids":relation_ids or [],"stage":"read","new_material_ids":[]}
        engine.checkpoint("targeted_gap_recorded")
    task=engine.state.targeted_gap
    if task["stage"] == "read":
        if task["requests"]:
            reading=ReadingPlan.model_validate({"requests":task["requests"],"rationale":gap,"related_ids":task["related_ids"],"gap":gap})
        else:
            reading,_=engine.ask("targeted_read",ReadingPlan,{"gap":task,"catalogue":catalogue(source,engine.state.snapshot,engine.implementation),
                "already_read":[{"id":m.id,"file":m.file,"start":m.start_line,"end":m.end_line} for m in engine.state.materials],
                "relevant_bindings":[b.model_dump() for b in engine.state.bindings if unit and b.id in unit.binding_ids]})
        reading.related_ids=task["related_ids"]; reading.gap=gap
        task['requests']=[q.model_dump(mode='json') for q in reading.requests]
        engine.checkpoint('targeted_read_plan_saved')
        receipt=engine.read(reading.requests,plan_id=task['plan_id'],related_ids=task['related_ids'],reason=gap)
        task=engine.state.targeted_gap
        receipt['scope_requested']=task.get('update_required',True)
        task['receipt_id']=receipt['id'];task['unfulfilled']=[item for item in receipt['items'] if item['status']=='deferred']
        task['new_material_ids']=list(dict.fromkeys(task.get('new_material_ids',[])+[id for item in receipt['items'] if item['status']=='acquired' for id in item['material_ids']]))
        task['reattached_material_ids']=[id for item in receipt['items'] if item['status']=='cached' for id in item['material_ids']]
        if task['unfulfilled']:
            engine.checkpoint('targeted_read_deferred');raise Blocked('Required material remains deferred; resume the same reading plan before graph patch')
        task['stage']='patch';inquiry.release_action(engine)
        engine.checkpoint('targeted_materials_read')
    if not task["new_material_ids"]:
        if task.get('reattached_material_ids'):
            engine.state.targeted_gap=None;engine.checkpoint('existing_material_reattached');return None
        raise Blocked("Targeted reading found no usable range; dependency remains unexplained: "+gap)
    if not task.get("update_required",update_required):
        engine.state.targeted_gap=None;engine.checkpoint('material_context_returned');return None
    from .scope_updates import from_patch,validate_scope_update,ScopeUpdate,ScopeAssessment,accept
    def validate_proposal(p):
        from .mutations import write_set
        if unit and write_set(engine.state,p):validate_scope_update(engine.state,from_patch(engine.state,unit,p))
        else:validate_patch(engine.state,p)
    if task.get('scope_update'):
        update=ScopeUpdate.model_validate(task['scope_update'])
        patch=update.patch
    else:
        try:
            patch,check=engine.ask("graph_patch",GraphPatch,{"gap":task,
            "new_materials":[m.model_dump(mode="json") for m in engine.state.materials if m.id in task["new_material_ids"]],
            "claims":[c.model_dump(mode="json") for c in engine.state.claims],"bindings":[b.model_dump(mode="json") for b in engine.state.bindings],
            "relations":[e.model_dump(mode="json") for e in engine.state.relations if e.source in {c.id for c in engine.state.claims}],
            "units":[u.model_dump(mode="json") for u in engine.state.units]},validate_proposal)
        except Blocked:
            session=engine.state.pending_output_repair
            if session and any(d['code'].startswith('scope_') for d in session.get('diagnostics',[])):
                raw=GraphPatch.model_validate_json(Path(session['current_path']).read_text())
                pending=from_patch(engine.state,unit,raw)
                pending.read_plan_id=task['plan_id']
                task['scope_update']=pending.model_dump(mode='json')
                engine.state.scope_updates[pending.id]={'status':'needs_F2_or_investigation','proposal':pending.model_dump(mode='json'),'repair_session_id':session['id']}
                inquiry.enqueue(engine.state,'review','Resolve the proposed semantic/scope difference before applying any part', 'scope_dispute:'+pending.id,target_ids=sorted({c.target_id for c in pending.changes}),unit_id=unit.id)
                engine.checkpoint('scope_dispute_queued')
            raise
        from .mutations import write_set
        if unit and write_set(engine.state,patch):
            update=from_patch(engine.state,unit,patch)
            update.read_plan_id=task['plan_id']
            task['scope_update']=update.model_dump(mode='json')
            engine.state.scope_updates[update.id]={'status':'proposed','proposal':update.model_dump(mode='json'),'check_id':check.id}
            engine.checkpoint('scope_proposal_saved')
        else:update=None
    if update:
        needed=validate_scope_update(engine.state,update)
        if needed:
            assessment,_=engine.ask('scope_review',ScopeAssessment,{'scope_update':update.model_dump(mode='json'),'required_fields':needed,**engine.context(unit)})
            update.assessment=assessment
            task['scope_update']=update.model_dump(mode='json')
            engine.state.scope_updates[update.id]={'status':'reviewed' if assessment.decision=='refinement' else 'needs_F2_or_investigation','proposal':update.model_dump(mode='json')}
            engine.checkpoint('scope_interpretation_saved')
        if update.assessment and update.assessment.decision!='refinement':
            inquiry.enqueue(engine.state,'review','Investigate whether the proposed scope changes the original obligation','scope_dispute:'+update.id,target_ids=[unit.id],unit_id=unit.id)
            engine.checkpoint('scope_dispute_queued')
            raise Blocked('Scope interpretation remains unresolved; a scoped review/F2 task is pending')
        validate_scope_update(engine.state,update)
        return accept(engine,update)
    from .transactions import commit_graph
    def commit(proxy):
        apply_patch(proxy.state,patch)
        target=next((u for u in proxy.state.units if unit and u.id==unit.id),None)
        inquiry.material_reviews(proxy,target,proxy.state.targeted_gap["new_material_ids"])
        proxy.state.targeted_gap=None
        inquiry.release_action(proxy)
    commit_graph(engine,"targeted-"+engine.state.pending_action.id,patch.model_dump(mode="json"),commit)
    write_json(engine.root/"materials.json",[m.model_dump(mode="json") for m in engine.state.materials])
    engine.checkpoint("targeted_graph_patch_applied")
    return patch
