"""Repository reading, candidate discovery and incremental dependency expansion."""
import json
from pathlib import Path
from consensus_assurance.core.proposals import Discovery, GraphPatch
from consensus_assurance.adapters.storage.files import write_json
from .materials import catalogue, initial_materials, add_reads, ReadingPlan
from .graph import apply_discovery, apply_patch
from .errors import Blocked


def context(engine, unit=None):
    result = {"materials": [m.model_dump(mode="json") for m in engine.state.materials],
        "capabilities": [c.model_dump(mode="json") for c in engine.state.capabilities],
        "parameters": engine.config.parameters, "remaining_seconds": engine.budget.remaining(),
        "directed_question": engine.config.directed_question,
        "snapshot_id": engine.state.snapshot.id, "harness_kind": engine.implementation.harness_kind,
        "harness_instructions": engine.implementation.harness_instructions}
    if unit:
        ids = {b.file for b in engine.state.bindings if b.id in unit.binding_ids}
        ids |= {m.file for m in engine.state.materials if any(m.id in c.source_ids for c in engine.state.claims if c.id in unit.goal_ids+unit.obligation_ids)}
        recent = set(engine.state.reading_history[-1]["added_material_ids"]) if engine.state.reading_history else set()
        result["materials"] = [m.model_dump(mode="json") for m in engine.state.materials if m.file in ids or m.id in recent]
        result.update({"obligation_progress": {"checked_scopes":unit.obligation_checks,"remaining":unit.remaining_obligation_ids or unit.obligation_ids}, "unit": unit.model_dump(mode="json"), "claims": [c.model_dump(mode="json") for c in engine.state.claims],
            "bindings": [b.model_dump(mode="json") for b in engine.state.bindings if b.id in unit.binding_ids],
            "relations": [e.model_dump(mode="json") for e in engine.state.relations]})
    return result

def discover(engine):
    source = engine.root / "source"
    if "materials" not in engine.state.completed_steps:
        engine.state.materials = initial_materials(source, engine.state.snapshot, engine.config.budget, engine.knowledge)
        inventory = catalogue(source, engine.state.snapshot,engine.implementation)
        write_json(engine.root / "catalogue.json", inventory)
        plan, _ = engine.ask("read", ReadingPlan, {"catalogue": inventory, "initial_materials": [m.model_dump(mode="json") for m in engine.state.materials]})
        add_reads(engine.state, source, plan, engine.config.budget)
        write_json(engine.root / "materials.json", [m.model_dump(mode="json") for m in engine.state.materials])
        engine.state.completed_steps.append("materials"); engine.advance("discover")
    if "discovery" not in engine.state.completed_steps:
        proposal, check = engine.ask("discover", Discovery, engine.context(), lambda p: apply_discovery(engine.state, p))
        path = engine.root / f"discovery-v{engine.state.graph_version}.json"
        write_json(path, proposal); engine.state.discovery_path = str(path)
        if not engine.state.units and proposal.reading_requests:
            engine.targeted_read(None, "Insufficient material for grounded discovery", requests=proposal.reading_requests)
        engine.state.completed_steps.append("discovery"); engine.advance("select")

def targeted_read(engine, unit, gap, relation_ids=None, requests=None):
    source = engine.root/"source"
    if engine.state.targeted_gap is None:
        engine.budget.take("targeted_reads")
        engine.state.targeted_gap={"gap":gap,"related_ids":unit.obligation_ids if unit else [],
            "relation_ids":relation_ids or [],"stage":"read","new_material_ids":[]}
        engine.checkpoint("targeted_gap_recorded")
    task=engine.state.targeted_gap
    if task["stage"] == "read":
        if requests:
            reading=ReadingPlan.model_validate({"requests":requests,"rationale":gap,"related_ids":task["related_ids"],"gap":gap})
        else:
            reading,_=engine.ask("targeted_read",ReadingPlan,{"gap":task,"catalogue":catalogue(source,engine.state.snapshot,engine.implementation),
                "already_read":[{"id":m.id,"file":m.file,"start":m.start_line,"end":m.end_line} for m in engine.state.materials],
                "relevant_bindings":[b.model_dump() for b in engine.state.bindings if unit and b.id in unit.binding_ids]})
        reading.related_ids=task["related_ids"]; reading.gap=gap
        task["new_material_ids"]=add_reads(engine.state,source,reading,engine.config.budget)
        task["stage"]="patch"
        if engine.state.pending_action: engine.state.action_history.append(engine.state.pending_action); engine.state.pending_action=None
        engine.checkpoint("targeted_materials_read")
    if not task["new_material_ids"]:
        engine.state.targeted_gap=None
        raise Blocked("Targeted reading found no new usable range; dependency remains unexplained: " + gap)
    patch,_=engine.ask("graph_patch",GraphPatch,{"gap":task,
        "new_materials":[m.model_dump(mode="json") for m in engine.state.materials if m.id in task["new_material_ids"]],
        "claims":[c.model_dump(mode="json") for c in engine.state.claims],"bindings":[b.model_dump(mode="json") for b in engine.state.bindings],
        "relations":[e.model_dump(mode="json") for e in engine.state.relations if e.source in {c.id for c in engine.state.claims}],
        "units":[u.model_dump(mode="json") for u in engine.state.units]},lambda p:apply_patch(engine.state,p))
    write_json(engine.root/"materials.json",[m.model_dump(mode="json") for m in engine.state.materials])
    engine.state.targeted_gap=None
    if engine.state.pending_action: engine.state.action_history.append(engine.state.pending_action); engine.state.pending_action=None
    engine.checkpoint("targeted_graph_patch_applied")
    return patch
