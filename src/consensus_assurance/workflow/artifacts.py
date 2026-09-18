import re
import json
import os
from pathlib import Path
from consensus_assurance.core.types import ModelArtifact, Origin, uid
from consensus_assurance.core.proposals import Bundle, ModelDraft
from consensus_assurance.adapters.storage.files import digest, write_json

from consensus_assurance.adapters.verifiers.tla_syntax import tla_code, validate_tla


def materialize_bundle(bundle):
    if bundle.properties == "GENERATE_FROM_OBSERVABLE_PROPERTIES":
        if isinstance(bundle, ModelDraft):
            raise ValueError("Observable property generation requires a complete observation map")
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
    if not set(checked_ids) <= set(unit.obligation_ids):
        raise ValueError("Checker claims must belong to the selected observable audit unit")
    if not set(unit.obligation_ids) & set(checked_ids):
        raise ValueError("Model must check a selected obligation")
    if isinstance(bundle, Bundle) and bundle.harness.kind != implementation.harness_kind:
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
    from .sources import covered
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    materials={m.id for m in state.materials}
    selected={b.id:b for b in state.bindings if b.id in unit.binding_ids}
    for index,constraint in enumerate(bundle.constraints):
        error=None
        if not set(constraint.source_ids)<=materials:
            error="Constraint source_ids must be actual material IDs"
        elif not set(constraint.binding_ids)<=set(selected):
            error="Constraint binding_ids must select existing unit bindings"
        elif constraint.source_kind == "code_observation":
            if not constraint.binding_ids:
                error="Code observation requires selected binding_ids, separate from material source_ids"
            elif not all(covered(selected[id],[m for m in state.materials if m.id in constraint.source_ids]) for id in constraint.binding_ids):
                error="Constraint material sources must cover each selected binding material"
        if error:
            prefix='/draft' if isinstance(bundle,ModelDraft) else '/bundle'
            raise DiagnosticError([Diagnostic(code='constraint_binding_citation',category='format',
                object_ids=[unit.id]+unit.binding_ids,paths=[prefix+'/constraints/'+str(index)+'/source_ids',prefix+'/constraints/'+str(index)+'/binding_ids'],
                material_ids=constraint.source_ids if set(constraint.source_ids)<=materials else [],
                message=error,allowed=['representation'],details={'unit_binding_ids':unit.binding_ids,
                    'selected_bindings':[b.model_dump(mode='json',exclude={'excerpt'}) for b in selected.values()],
                    'constraint_path':prefix+'/constraints/'+str(index),
                    'preservation':'Correct citation representation only; preserve behavior, property and scope'} )])
    if len({r.id for r in bundle.reachability})!=len(bundle.reachability):raise ValueError("Duplicate reachability requirement")
    from .audit_spec import reachability_refs
    selected_refs=reachability_refs(unit.audit_question)
    for requirement in bundle.reachability:
        names=requirement.sequence+([requirement.identity_operator] if requirement.identity_operator else []) if requirement.sequence else [requirement.operator]
        if requirement.sequence and (len(requirement.sequence)<2 or not requirement.identity_operator):raise ValueError("Sequential reachability requires at least two predicates and an explicit identity operator")
        for name in names:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",name) or not re.search(r"\b"+name+r"\s*==",tla_code(bundle.behavior)):
                raise ValueError("Reachability requires an actual named Behavior operator")
        if not requirement.claim_ids or not reachability_refs(requirement)<=selected_refs:raise ValueError("Reachability must link claims and selected behavior/fact references")
        if not set(requirement.claim_ids)<=checked_ids:raise ValueError("Reachability requirement references an unchecked claim")
    def context_error(message):
        from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
        raise DiagnosticError([Diagnostic(code='context_mapping',category='association',object_ids=[unit.id],paths=['/draft/context_analysis' if isinstance(bundle,ModelDraft) else '/bundle/context_analysis'],message=message,allowed=['representation','read'],
            details={'variables':bundle.variables,'actions':bundle.actions,'checkers':[c.model_dump(mode='json') for c in specs],'reachability':[r.model_dump(mode='json') for r in bundle.reachability],
                     'preservation':'Correct scenario correspondence only. Behavior, properties, selected obligations and fault scope cannot change in this repair.'})])
    # A scenario names real executable artifacts, not just prose about a round.
    for scenario in bundle.context_analysis:
        if not set(scenario.binding_ids)<=set(unit.binding_ids):context_error('Context analysis cites code outside this unit')
        if not scenario.actions or not set(scenario.actions)<=set(bundle.actions) or not set(scenario.variables)<=set(bundle.variables):context_error('Context analysis references unavailable behavior actions or variables')
        if not scenario.checker_ids or not set(scenario.checker_ids)<=set(invariants):context_error('Context scenario requires configured checker correspondence')
        requirements=[r for r in bundle.reachability if r.id in scenario.reachability_ids]
        if len(requirements)!=len(set(scenario.reachability_ids)):context_error('Context scenario refers to absent reachability configuration')
        if scenario.mode=='cross_context' and not any(r.sequence and r.identity_operator for r in requirements):context_error('Cross-context coverage needs a same-history identity-correlated trigger')
        if scenario.mode=='cross_context' and not {c.claim_id for c in specs if c.invariant in scenario.checker_ids}<={id for r in requirements for id in r.claim_ids}:context_error('Joint-history trigger does not cover the scenario checker claims')
        for name in scenario.actions:
            if not re.search(r'\b'+re.escape(name)+r'\s*(?:\([^\n]*\))?\s*==',tla_code(bundle.behavior)):context_error('Context action has no actual Behavior definition')
    # Model-level consequence expression does not require an implementation monitor.
    for mapping in bundle.consequence_observations:
        if mapping.claim_id not in unit.obligation_ids or not set(mapping.binding_ids)<=set(unit.binding_ids):raise ValueError("Consequence observation references an unselected obligation or binding")
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
    files = [behavior, checker, cfg, proposal]
    complete = isinstance(bundle, Bundle)
    if complete:
        write_json(mapping, bundle.observation)
        harness.write_text(bundle.harness.source)
        files.extend([mapping, harness])
    write_json(proposal, bundle)
    artifacts = {str(p): digest(p.read_bytes()) for p in files}
    from .inputs import semantic_ids
    semantic_references=semantic_ids(state,unit)
    model = ModelArtifact(stage="complete" if complete else "model_only", pending_components=[] if complete else [p.component for p in bundle.pending_work], version=version, kind="implementation_abstraction", origin=Origin.MOCK if state.mode == "mock" else Origin.PRESET if state.analysis_mode == "regression" else Origin.AGENT,
        claim_id=specs[0].claim_id, snapshot_id=state.snapshot.id, path=str(checker), config_path=str(cfg),
        content_digest=digest(checker.read_bytes()), config_digest=digest(cfg.read_bytes()), scope=bundle.scope,
        initial_state=bundle.initial_state, variables=bundle.variables, actions=bundle.actions,
        properties=invariants, constraints=bundle.constraints, binding_ids=unit.binding_ids,
        extension_schema={"type": "object", "description": "Tool-specific TLA metadata; constants are saved verbatim"}, extension_version="2",
        unit_id=unit.id, checker_path=str(checker), mapping_path=str(mapping) if complete else "", harness_path=str(harness) if complete else "", bundle_path=str(proposal),
        artifact_digests=artifacts, checkers=specs, graph_versions={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units] if x.id in semantic_references}, previous_id=previous.id if previous else None, revision_reason=reason)
    from .inputs import search_inputs
    from consensus_assurance.adapters.verifiers.input_identity import fingerprint
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


def load_model(model):
    proposal = ModelDraft if model.stage == "model_only" else Bundle
    return proposal.model_validate_json(Path(model.bundle_path).read_text())
