import re
from pathlib import Path
from consensus_assurance.core.types import ModelArtifact, Origin
from consensus_assurance.adapters.storage.files import digest, write_json

SAFE_MODULES = {"Naturals", "Integers", "Sequences", "FiniteSets", "Bags", "Reals", "Behavior"}


def tla_code(source):
    """Remove strings and nested comments while preserving line structure for validation."""
    out, i, depth, quoted = [], 0, 0, False
    while i < len(source):
        pair = source[i:i+2]
        c = source[i]
        if depth:
            if pair == "(*": depth += 1; out.extend("  "); i += 2; continue
            if pair == "*)": depth -= 1; out.extend("  "); i += 2; continue
            out.append("\n" if c == "\n" else " "); i += 1; continue
        if quoted:
            if ord(c) == 92 and i+1<len(source): out.extend("  "); i += 2; continue
            if c == '"': quoted=False
            out.append("\n" if c == "\n" else " "); i += 1; continue
        if pair == "(*": depth=1; out.extend("  "); i += 2; continue
        if pair == "\\*":
            end=source.find("\n",i)
            if end<0: end=len(source)
            out.extend(" "*(end-i)); i=end; continue
        if c == '"': quoted=True; out.append(" "); i += 1; continue
        out.append(c); i += 1
    if depth or quoted: raise ValueError("Unterminated TLA comment or string")
    return "".join(out)


def validate_tla(source, module):
    code = tla_code(source)
    if not re.search(r"-+ MODULE " + module + r" -+", code):
        raise ValueError("Unexpected TLA module name")
    if re.search(r"\b(?:INSTANCE|LOCAL|ASSUME|Java|IOUtils|Json|CSV)\b",code):
        raise ValueError("Unsupported module feature; external overrides and assumptions are not accepted")
    if re.search(r"\b[A-Za-z_]\w*\s*!\s*[A-Za-z_]\w*",code) or re.search(r"!(?!\s*[\[.])",code):
        raise ValueError("Module-qualified operators are not allowed; EXCEPT updates are supported")
    for match in re.finditer(r"\bEXTENDS\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",code):
        modules = {m.strip() for m in match[1].split(",")}
        if not modules <= SAFE_MODULES: raise ValueError("Unapproved TLA module dependency")


def save_bundle(root, state, unit, bundle, implementation, previous=None, reason="Initial generation"):
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
    version = 1 + max([m.version for m in state.models] or [0])
    folder = root / "models" / f"v{version}"
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
        artifact_digests=artifacts, checkers=specs, graph_versions={x.id:x.version for x in [*state.claims,*state.bindings,*state.relations] if x.id in set(checked_ids)|set(unit.binding_ids)|set(unit.relation_ids)}, previous_id=previous.id if previous else None, revision_reason=reason)
    state.models.append(model)
    return model
