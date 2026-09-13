import re
from pathlib import Path
from consensus_assurance.core.types import ModelArtifact, Origin
from consensus_assurance.adapters.storage.files import digest, write_json

SAFE_MODULES = {"Naturals", "Integers", "Sequences", "FiniteSets", "Bags", "Reals", "Behavior"}


def validate_tla(source, module):
    if not re.search(r"-+ MODULE " + module + r" -+", source):
        raise ValueError("Unexpected TLA module name")
    # Generated specifications cannot load host-language overrides or unsafe IO modules.
    if re.search(r"\b(?:INSTANCE|LOCAL|ASSUME)\b|!|Java|IOUtils|Json|CSV|EXTENDS[^\n]*TLC", source):
        raise ValueError("Unsupported module feature; external overrides and assumptions are not accepted")
    for match in re.finditer(r"EXTENDS\s+([^\n]+)", source):
        modules = {m.strip() for m in match[1].split(",")}
        if not modules <= SAFE_MODULES:
            raise ValueError("Unapproved TLA module dependency")


def save_bundle(root, state, unit, bundle, implementation, previous=None, reason="Initial generation"):
    if not set(bundle.checked_claim_ids) <= set(unit.obligation_ids + (unit.goal_ids if unit.goal_observable else [])):
        raise ValueError("Checker claims must belong to the selected observable audit unit")
    if not set(unit.obligation_ids) & set(bundle.checked_claim_ids):
        raise ValueError("Model must check a selected obligation")
    if bundle.harness.kind != implementation.harness_kind:
        raise ValueError("Harness kind is incompatible with the selected implementation adapter")
    validate_tla(bundle.behavior, "Behavior"); validate_tla(bundle.properties, "Properties")
    for name in ("Init", "Next", "vars", "Obs"):
        if not re.search(r"\b" + name + r"\s*==", bundle.behavior):
            raise ValueError("Behavior module is missing " + name)
    for invariant in bundle.invariants:
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
    version = 1 + max([m.version for m in state.models] or [0])
    folder = root / "models" / f"v{version}"
    folder.mkdir(parents=True, exist_ok=False)
    behavior, checker, cfg = folder / "Behavior.tla", folder / "Properties.tla", folder / "Properties.cfg"
    behavior.write_text(bundle.behavior); checker.write_text(bundle.properties)
    cfg.write_text("INIT Init\nNEXT Next\nCHECK_DEADLOCK FALSE\n" + ("CONSTANTS\n" + bundle.constants + "\n" if bundle.constants.strip() else "") + "INVARIANTS\n" + "\n".join(bundle.invariants) + "\n")
    mapping, harness, proposal = folder / "mapping.json", folder / implementation.harness_filename, folder / "bundle.json"
    write_json(mapping, bundle.observation); harness.write_text(bundle.harness.source); write_json(proposal, bundle)
    artifacts = {str(p): digest(p.read_bytes()) for p in [behavior, checker, cfg, mapping, harness, proposal]}
    model = ModelArtifact(version=version, kind="implementation_abstraction", origin=Origin.MOCK if state.mode == "mock" else Origin.AGENT,
        claim_id=bundle.checked_claim_ids[0], snapshot_id=state.snapshot.id, path=str(checker), config_path=str(cfg),
        content_digest=digest(checker.read_bytes()), config_digest=digest(cfg.read_bytes()), scope=bundle.scope,
        initial_state=bundle.initial_state, variables=bundle.variables, actions=bundle.actions,
        properties=bundle.invariants, constraints=bundle.constraints, binding_ids=unit.binding_ids,
        extension_schema={"type": "object", "description": "Tool-specific TLA metadata; constants are saved verbatim"}, extension_version="2",
        unit_id=unit.id, checker_path=str(checker), mapping_path=str(mapping), harness_path=str(harness), bundle_path=str(proposal),
        artifact_digests=artifacts, previous_id=previous.id if previous else None, revision_reason=reason)
    state.models.append(model)
    return model
