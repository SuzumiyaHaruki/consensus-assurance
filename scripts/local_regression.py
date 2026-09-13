#!/usr/bin/env python3
"""Run a clearly labeled, local-only regression against an isolated target copy."""
import argparse
import shutil
import time
from pathlib import Path
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Bundle, ObservationMap, Harness
from consensus_assurance.core.types import *
from consensus_assurance.adapters.storage.files import Store, write_json, digest
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import run_experiment
from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
from consensus_assurance.plugins.implementations.hashicorp_raft.adapter import HashicorpRaft
from consensus_assurance.reporting.chinese import render_report


def run(repo, jar, out):
    started = time.monotonic()
    project = Path(__file__).resolve().parents[1]
    root = out.resolve() / ("local-regression-" + uid())
    root.mkdir(parents=True)
    snapshot = capture(repo, root / "source")
    config = Config(repo_path=str(repo), tlc_jar=str(jar))
    state = Analysis(mode="real", analysis_mode="regression", snapshot=snapshot, config=config.model_dump(mode="json"))
    state.gaps = ["Fixed developer-supplied regression; autonomous discovery was not executed",
        "User declined repository transmission to the agent backend",
        "In-memory reconstruction is not a real crash or production persistence test"]
    scope = Scope(description="One voter, two candidate identities, one term, at most one crash in the model; fixed local regression",
        assumptions=["Successful individual store writes survive recovery; failed writes have no effect"],
        excluded=["Autonomous goal discovery", "Cluster election", "Production storage and power failure", "Liveness, fairness, membership changes"],
        parameters={"NodeCount":2,"MaxTerm":1,"MaxCrashes":1,"MessageBound":1,"Broken":False})
    state.claims = [Claim(id="vote_obligation",kind="obligation",description="No conflicting granted votes in one term",scope=scope,source="Preset development regression, not an agent-discovered target")]
    state.unexplored = list(snapshot.files)
    runner = ProcessRunner(root)
    verifier = TLCVerifier(str(jar))
    probe = verifier.probe(runner); state.tools["verifier"] = probe["version"]; state.checks.extend(probe["checks"])
    impl = HashicorpRaft()
    version = runner.run(impl.version_command(), root, "implementation_tool_probe", snapshot.id, 10)
    from consensus_assurance.adapters.runners.process import output
    state.tools["implementation"] = output(version).strip(); state.checks.append(version)
    workspace = root / "experiments" / "workspace"
    shutil.copytree(root / "source", workspace)
    harness = (project / "tests/fixtures/hashicorp_focused.go").read_text()
    harness_path = workspace / impl.harness_filename
    harness_path.write_text(harness)
    experiment = run_experiment(runner, impl.experiment_command(), workspace, snapshot.id, 120, "bwrap", adapter=impl)
    experiment.tool_version = state.tools["implementation"]
    folder = root / "models" / "v1"; folder.mkdir(parents=True)
    source = (project / "tests/fixtures/tlc/Vote.tla").read_text().replace("MODULE Vote", "MODULE Behavior")
    source = source.replace("VoteSafe ==", "Obs == [current |-> current, voteTerm |-> voteTerm, voteCand |-> voteCand, grantA |-> <<1,1>> \in grants, grantB |-> <<1,2>> \in grants]\nVoteSafe ==")
    # Keep the original behavior, move only the independent checker to its own module.
    behavior, tail = source.split("VoteSafe ==",1)
    checker = "VoteSafe ==" + tail.split("Spec ==",1)[0]
    behavior += "=====================================================================\n"
    (folder / "Behavior.tla").write_text(behavior)
    properties = "---------------- MODULE Properties ----------------\nEXTENDS Behavior\n" + checker + "\n==================================================\n"
    path = folder / "Properties.tla"; path.write_text(properties)
    constants = "NodeCount = 2\nMaxTerm = 1\nMaxCrashes = 1\nMessageBound = 1\nBroken = FALSE"
    cfg = folder / "Properties.cfg"
    cfg.write_text("INIT Init\nNEXT Next\nINVARIANT VoteSafe\nCHECK_DEADLOCK FALSE\nCONSTANTS\n" + constants)
    observation = ObservationMap(fields=[{"model_field":k,"raw_field":k} for k in ["current","voteTerm","voteCand","grantA","grantB"]],
        required_events=["initial","write_completed","vote_response","reconstructed"], max_internal_steps=6, allow_observed_stutter=True,
        description="Successful store callbacks and actual RPC return values; identical observations may stutter")
    mapping_path = folder / "mapping.json"; write_json(mapping_path, observation)
    saved_harness = folder / impl.harness_filename; saved_harness.write_text(harness)
    model = ModelArtifact(version=1,kind="implementation_abstraction",origin=Origin.PRESET,claim_id="vote_obligation",snapshot_id=snapshot.id,
        path=str(path),config_path=str(cfg),content_digest=digest(path.read_bytes()),config_digest=digest(cfg.read_bytes()),scope=scope,
        initial_state="Empty stable state, no grant history",variables=["current","voteTerm","voteCand","phase","grants"],
        actions=["Begin","CheckTerm","CheckVote","WriteTerm","WriteCandidate","Reply","Abort","Crash","Recover"],properties=["VoteSafe"],
        constraints=[],binding_ids=[],extension_schema={"description":"Explicit fixed regression parameters"},extension_version="1",mapping_path=str(mapping_path),harness_path=str(saved_harness),
        artifact_digests={str(p):digest(p.read_bytes()) for p in [folder / "Behavior.tla",path,cfg,mapping_path,saved_harness]})
    state.models.append(model); experiment.model_id=model.id; experiment.input_versions=model.artifact_digests; state.checks.append(experiment)
    bundle = Bundle(description="Preset regression",behavior=behavior,properties=properties,constants=constants,invariants=["VoteSafe"],checked_claim_ids=["vote_obligation"],
        initial_state=model.initial_state,variables=model.variables,actions=model.actions,constraints=[],scope=scope,observation=observation,
        harness=Harness(kind="go_test",source=harness,description="Actual vote calls and store-write observations",prerequisite_events=["initial","vote_response","reconstructed","vote_response"],semantic_changes=["Store observation callbacks; skip asynchronous node startup"]),uncertainties=state.gaps)
    write_json(folder / "bundle.json",bundle)
    calibration, checks = verifier.calibrate(runner,model,bundle,experiment,60)
    state.calibrations.append(calibration); state.checks.extend(checks)
    checked = verifier.check(runner,model,60); state.checks.append(checked)
    if checked.status == ExecutionStatus.COMPLETED:
        state.add_evidence(Evidence(check_id=checked.id,model_id=model.id,snapshot_id=snapshot.id,claim_id=model.claim_id,origin=Origin.EXECUTED,
            level="model",scope=scope,description="Preset local model; calibration="+calibration.status,assessment=Assessment.SUPPORTED if checked.outcome=="holds" else Assessment.CHALLENGED,calibration_id=calibration.id))
    unchanged = snapshot.files == capture(repo).files
    state.stop_reason = "Local preset regression completed" if unchanged else "Original snapshot changed during regression; investigate external changes"
    state.elapsed_seconds = time.monotonic()-started
    write_json(root / "snapshot.json",snapshot); write_json(root / "config.json",config)
    write_json(root / "source-protection.json",{"unchanged":unchanged})
    Store(root).save(state,"local_regression_completed")
    print(render_report(state,root))
    print("experiment="+experiment.outcome+" calibration="+calibration.status+" search="+checked.outcome+" original_unchanged="+str(unchanged))
    return 0 if unchanged and experiment.outcome=="tests_passed" and calibration.status=="compatible" and checked.outcome=="holds" else 2


if __name__ == "__main__":
    p=argparse.ArgumentParser(description="Local fixed regression; never sends repository material to an agent")
    p.add_argument("--repo",required=True,type=Path);p.add_argument("--tlc-jar",required=True,type=Path);p.add_argument("--out",type=Path,default=Path("runs"))
    args=p.parse_args()
    raise SystemExit(run(args.repo.resolve(),args.tlc_jar.resolve(),args.out))
