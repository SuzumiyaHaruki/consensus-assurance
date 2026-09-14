import json
import os
from pathlib import Path
import pytest
from consensus_assurance.cli import main
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Assessment
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.consensus.inquiry import INQUIRY
from consensus_assurance.adapters.storage.snapshot import capture


@pytest.mark.real
def test_default_no_goal_F3_new_artifacts_and_recalibration(tmp_path, tlc, prepared):
    repo, _, _, _ = prepared
    root = tmp_path / "full-run"
    fixture = Path(__file__).resolve().parents[1] / "fixtures/toy_responses.json"
    config = Config(protocol="toy", implementation="toy", agent_backend="mock", fixture=str(fixture), tlc_jar=os.environ["TLC_JAR"])
    config.budget.audit_units = 3
    impl, agent, verifier, knowledge = assemble(config)
    before = capture(repo)
    state = Engine(config, root, impl, agent, verifier, knowledge, INQUIRY).start(repo)
    assert state.stop_reason.startswith("No pending"), state.stop_reason
    assert len(state.models) == 2 and [r.kind for r in state.revisions] == ["F3"]
    assert state.models[0].binding_ids != state.models[1].binding_ids
    assert state.models[0].mapping_path != state.models[1].mapping_path
    assert state.calibrations[0].status == "compatible" and state.calibrations[0].applicability == "historical_scope" and state.calibrations[1].status == "compatible"
    assert all(e.level == "framework_test" and e.assessment != Assessment.SUPPORTED for e in state.evidence)
    assert before.files == capture(repo).files
    assert main(["report", "--run", str(root)]) == 0
    resumed = Engine(config, root, *assemble(config), INQUIRY).resume()
    assert len(resumed.models) == 2
    assert len([c for c in resumed.checks if c.action == "model_check"]) == 2
    (repo / "counter.py").write_text("def step(value, limit): return 999\n")
    changed = Engine(config, root, *assemble(config), INQUIRY).resume()
    assert "Inputs changed" in changed.stop_reason
    assert all(e.assessment == Assessment.STALE for e in changed.evidence)


def test_unavailable_agent_produces_blocked_report_without_preset_goals(tmp_path, prepared):
    repo, _, _, _ = prepared
    config = Config(protocol="toy", implementation="toy", agent_backend="mock", fixture=None)
    config.budget.action_timeout = 5
    root = tmp_path / "blocked"
    state = Engine(config, root, *assemble(config), INQUIRY).start(repo)
    assert not state.claims and not state.models
    assert "Agent blocked" in state.stop_reason
    assert (root / "state.json").exists()


def test_missing_target_cli_has_no_download(tmp_path, capsys):
    assert main(["run", "--repo", str(tmp_path / "absent"), "--runs-dir", str(tmp_path / "runs")]) == 2
    assert "does not exist" in capsys.readouterr().err
