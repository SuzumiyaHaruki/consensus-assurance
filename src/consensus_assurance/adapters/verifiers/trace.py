import json
import re
import shutil
from pathlib import Path
from consensus_assurance.core.types import Calibration, ExecutionStatus, uid
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.adapters.storage.files import write_json, digest


def tla_value(value):
    if isinstance(value, bool):
        return str(value).upper()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, dict) and value:
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", k) for k in value):
            raise ValueError("Observation fields must be TLA identifiers")
        return "[" + ", ".join(f"{k} |-> {tla_value(v)}" for k, v in sorted(value.items())) + "]"
    raise ValueError("Only scalar observations and nonempty records are supported")


def project(events, mapping):
    if not mapping.fields or any(e["event"] == "invalid_observation" for e in events):
        raise ValueError("Missing mapping or malformed observation")
    if not set(mapping.required_events) <= {e["event"] for e in events}:
        raise ValueError("Required events were not observed")
    projected = []
    for event in events:
        if "state" not in event:
            continue
        if not isinstance(event["state"], dict):
            raise ValueError("Invalid observed state")
        state = {}
        for field in mapping.fields:
            if field.raw_field not in event["state"]:
                raise ValueError("Key observation is missing: " + field.raw_field)
            state[field.model_field] = event["state"][field.raw_field]
        tla_value(state)
        projected.append(state)
    if len(projected) < 2:
        raise ValueError("At least initial and subsequent observations are required")
    return projected


def calibration_source(observations, mapping):
    trace = "<<" + ", ".join(tla_value(o) for o in observations) + ">>"
    stutter = r" \/ (UNCHANGED vars)" if mapping.allow_observed_stutter else ""
    return r"""---------------- MODULE Calibration ----------------
EXTENDS Behavior, Sequences
VARIABLE cursor, internalSteps
Trace == TRACE_VALUE
CInit == Init /\ cursor = 1 /\ internalSteps = 0 /\ Obs = Trace[1]
CNext == /\ cursor < Len(Trace)
         /\ \/ /\ (NextSTUTTER)
                  /\ Obs' = Trace[cursor + 1]
                  /\ cursor' = cursor + 1 /\ internalSteps' = 0
             \/ /\ Next /\ Obs' = Obs
                  /\ internalSteps < INTERNAL_BOUND
                  /\ internalSteps' = internalSteps + 1 /\ UNCHANGED cursor
TraceNotAccepted == cursor < Len(Trace)
=====================================================
""".replace("TRACE_VALUE", trace).replace("STUTTER", stutter).replace("INTERNAL_BOUND", str(mapping.max_internal_steps))


def calibrate(verifier, runner, model, bundle, experiment, timeout):
    folder = runner.root / "calibrations" / uid()
    folder.mkdir(parents=True, exist_ok=True)
    events = extract_events(experiment)
    trace_path = folder / "events.json"
    write_json(trace_path, events)
    record = Calibration(model_id=model.id, experiment_check_id=experiment.id, mapping_path=model.mapping_path,
        trace_path=str(trace_path), reason="Not executed", origin=experiment.origin)
    if experiment.status != ExecutionStatus.COMPLETED:
        record.status = "inconclusive"; record.reason = "Experiment execution did not complete"
        return record, []
    try:
        observations = project(events, bundle.observation)
    except ValueError as exc:
        record.status = "inconclusive"; record.reason = str(exc)
        return record, []
    write_json(folder / "projected.json", observations)
    source = folder / "Calibration.tla"
    source.write_text(calibration_source(observations, bundle.observation))
    shutil.copyfile(Path(model.path).parent / "Behavior.tla", folder / "Behavior.tla")
    cfg = folder / "Calibration.cfg"
    cfg.write_text("INIT CInit\nNEXT CNext\nINVARIANT TraceNotAccepted\nCHECK_DEADLOCK FALSE\n" + ("CONSTANTS\n" + bundle.constants + "\n" if bundle.constants.strip() else ""))
    adapted = model.model_copy(update={"path": str(source), "config_path": str(cfg)})
    check = verifier.check(runner, adapted, timeout)
    check.action = "trace_calibration"; check.origin = experiment.origin
    check.artifacts.extend([str(trace_path), str(folder / "projected.json"), model.mapping_path])
    check.input_versions = {**model.artifact_digests, **{str(p): digest(p.read_bytes()) for p in
        [source, cfg, trace_path, folder / "projected.json", folder / "Behavior.tla"]}}
    record.check_ids = [check.id]
    if check.status != ExecutionStatus.COMPLETED:
        record.status = "inconclusive"; record.reason = "Calibration search did not complete"
    elif check.outcome == "counterexample":
        # Violation of TraceNotAccepted is a witness that the complete observed sequence is reachable.
        record.status = "compatible"; record.reason = "TLC reached the full projected trace using only bounded invisible transitions and declared stuttering"
    elif check.outcome == "holds":
        record.status = "incompatible"; record.reason = "No path explains the full trace under the declared projection and internal-step bound"
    else:
        record.status = "inconclusive"; record.reason = "Unrecognized calibration result"
    return record, [check]
