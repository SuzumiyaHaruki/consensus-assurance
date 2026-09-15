import re
import json
import os
from pathlib import Path
from consensus_assurance.core.types import ModelArtifact, Origin, uid
from consensus_assurance.adapters.storage.files import digest, write_json

from consensus_assurance.adapters.verifiers.tla_syntax import tla_code, validate_tla


def materialize_bundle(bundle):
    if bundle.properties == "GENERATE_FROM_OBSERVABLE_PROPERTIES":
        from consensus_assurance.adapters.verifiers.observable import properties_source
        if not bundle.observable_properties:
            raise ValueError("Shared property generation requires nonempty observable_properties")
        bundle = bundle.model_copy(deep=True)
        bundle.properties = properties_source(bundle.observable_properties, bundle.observation)
    return bundle


def validate_bundle(state, unit, bundle, implementation):
    bundle = materialize_bundle(bundle)
    specs = bundle.checker_specs()
    checked_ids = {c.claim_id for c in specs}
    invariants = [c.invariant for c in specs]
    if not set(checked_ids) <= set(unit.obligation_ids + (unit.goal_ids if unit.goal_observable else [])):
        raise ValueError("Checker claims must belong to the selected observable audit unit")
    if not set(unit.obligation_ids) & set(checked_ids):
        raise ValueError("Model must check a selected obligation")
    if bundle.harness.kind != implementation.harness_kind:
        raise ValueError("Harness kind is incompatible with the selected implementation adapter")
    validate_tla(bundle.behavior, "Behavior"); validate_tla(bundle.properties, "Properties")
    for name in ("Init", "Next", "vars", "Obs"):
        if not re.search(r"\b" + name + r"\s*==", bundle.behavior):
            raise ValueError("Behavior module is missing " + name)
    for invariant in invariants:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", invariant):
            raise ValueError("Invalid invariant identifier")
        if re.search(r"\b" + invariant + r"\b", bundle.behavior):
            raise ValueError("Checked property must be separate from behavior")
        if not re.search(r"\b" + invariant + r"\s*==", bundle.properties):
            raise ValueError("Checker declaration missing")
    if re.search(r"(?im)^\s*(?:CONSTRAINT|ACTION_CONSTRAINT|INIT|NEXT|SPECIFICATION|INVARIANT|PROPERTY|VIEW|SYMMETRY|CHECK_DEADLOCK)\b|<-", bundle.constants):
        raise ValueError("Only constant assignments are permitted; no search filters or overrides")
    known = {m.id for m in state.materials} | {b.id for b in state.bindings} | {c.id for c in state.claims}
    for constraint in bundle.constraints:
        if not set(constraint.source_ids) <= known:
            raise ValueError("Model constraint cites an unknown source")
        if constraint.source_kind == "code_observation" and not set(constraint.source_ids) & set(unit.binding_ids):
            raise ValueError("Code-derived transition constraint must cite a selected binding")
    if len({r.id for r in bundle.reachability})!=len(bundle.reachability):raise ValueError("Duplicate reachability requirement")
    points=unit.coverage_intent+(unit.audit_question.points if unit.audit_question else [])
    for requirement in bundle.reachability:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",requirement.operator) or not re.search(r"\b"+requirement.operator+r"\s*==",tla_code(bundle.behavior)):
            raise ValueError("Reachability requires an actual named Behavior operator")
        if not requirement.claim_ids or not set(requirement.point_ids)<={p.id for p in points}:raise ValueError("Reachability must link claims and known audit question points")
        if not set(requirement.claim_ids)<=checked_ids:
            raise ValueError("Reachability requirement references an unchecked claim")
    for spec in specs:
        if spec.claim_id in unit.goal_ids:
            mapping=next((g for g in bundle.goal_observations if g.claim_id==spec.claim_id),None)
            if mapping is None or not mapping.required_participants or not mapping.required_events or not mapping.binding_ids or not set(mapping.binding_ids)<=set(unit.binding_ids):
                raise ValueError("Goal checking needs explicit observed participants, events and code bindings")
            from .graph import validate_grounding
            validate_grounding(mapping.grounding,{m.id:m for m in state.materials},set(unit.binding_ids))
    return specs


def save_bundle(root, state, unit, bundle, implementation, previous=None, reason="Initial generation", transaction_key=None):
    bundle = materialize_bundle(bundle)
    specs = validate_bundle(state, unit, bundle, implementation)
    invariants = [c.invariant for c in specs]
    checked_ids = {c.claim_id for c in specs}
    root = Path(root)
    if transaction_key:
        for manifest in (root / "models").glob("v*/commit.json"):
            saved = json.loads(manifest.read_text())
            if saved["transaction_key"] != transaction_key:
                continue
            if saved["bundle"] != bundle.model_dump(mode="json") or saved["unit_id"] != unit.id or saved["previous_id"] != (previous.id if previous else None):
                raise ValueError("Model commit input differs from the pending action")
            model = ModelArtifact.model_validate(saved["model"])
            if any(not Path(path).is_file() or digest(Path(path).read_bytes()) != expected for path, expected in model.artifact_digests.items()):
                raise ValueError("Committed model files are incomplete or changed")
            if not any(m.id == model.id for m in state.models):
                state.models.append(model)
            return model
    version = 1 + max([m.version for m in state.models] or [0])
    folder = root / "models" / f"v{version}"
    destination = folder
    if transaction_key:
        folder = root / "models" / (".pending-" + transaction_key)
        if folder.exists():
            # Preserve partial bytes as an abandoned attempt, then rebuild the same commit.
            folder.rename(folder.with_name(folder.name + "-incomplete-" + uid()))
    folder.mkdir(parents=True, exist_ok=False)
    behavior, checker, cfg = folder / "Behavior.tla", folder / "Properties.tla", folder / "Properties.cfg"
    behavior.write_text(bundle.behavior); checker.write_text(bundle.properties)
    cfg.write_text("INIT Init\nNEXT Next\nCHECK_DEADLOCK FALSE\n" + ("CONSTANTS\n" + bundle.constants + "\n" if bundle.constants.strip() else "") + "INVARIANTS\n" + "\n".join(invariants) + "\n")
    mapping, harness, proposal = folder / "mapping.json", folder / implementation.harness_filename, folder / "bundle.json"
    write_json(mapping, bundle.observation); harness.write_text(bundle.harness.source); write_json(proposal, bundle)
    artifacts = {str(p): digest(p.read_bytes()) for p in [behavior, checker, cfg, mapping, harness, proposal]}
    model = ModelArtifact(version=version, kind="implementation_abstraction", origin=Origin.MOCK if state.mode == "mock" else Origin.PRESET if state.analysis_mode == "regression" else Origin.AGENT,
        claim_id=specs[0].claim_id, snapshot_id=state.snapshot.id, path=str(checker), config_path=str(cfg),
        content_digest=digest(checker.read_bytes()), config_digest=digest(cfg.read_bytes()), scope=bundle.scope,
        initial_state=bundle.initial_state, variables=bundle.variables, actions=bundle.actions,
        properties=invariants, constraints=bundle.constraints, binding_ids=unit.binding_ids,
        extension_schema={"type": "object", "description": "Tool-specific TLA metadata; constants are saved verbatim"}, extension_version="2",
        unit_id=unit.id, checker_path=str(checker), mapping_path=str(mapping), harness_path=str(harness), bundle_path=str(proposal),
        artifact_digests=artifacts, checkers=specs, graph_versions={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units] if x.id in set(unit.goal_ids+unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id])}, previous_id=previous.id if previous else None, revision_reason=reason)
    from .inputs import search_inputs, fingerprint
    model.reachability_requirements=bundle.reachability
    model.search_inputs=search_inputs(state,unit,bundle,cfg.read_text())
    model.search_fingerprint=fingerprint(model.search_inputs)
    if transaction_key:
        old_folder = str(folder)
        payload = model.model_dump(mode="json")
        for key in ("path", "config_path", "checker_path", "mapping_path", "harness_path", "bundle_path"):
            payload[key] = payload[key].replace(old_folder, str(destination), 1)
        payload["artifact_digests"] = {path.replace(old_folder, str(destination), 1): value for path, value in payload["artifact_digests"].items()}
        model = ModelArtifact.model_validate(payload)
        write_json(folder / "commit.json", {"transaction_key": transaction_key, "unit_id": unit.id,
            "previous_id": previous.id if previous else None, "bundle": bundle.model_dump(mode="json"), "model": model.model_dump(mode="json")})
        os.rename(folder, destination)
    state.models.append(model)
    return model
