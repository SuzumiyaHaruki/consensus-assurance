import json
import os
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import Bundle, Discovery
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.workflow.materials import initial_materials, add_reads, ReadingPlan
from consensus_assurance.workflow.graph import apply_discovery
from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
from consensus_assurance.adapters.runners.process import ProcessRunner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "examples/toy_protocol", repo)
    snapshot = capture(repo)
    config = Config(protocol="toy", implementation="toy", agent_backend="mock", fixture=str(ROOT / "tests/fixtures/toy_responses.json"))
    state = Analysis(mode="mock", config=config.model_dump(mode="json"), snapshot=snapshot)
    responses = json.loads((ROOT / "tests/fixtures/toy_responses.json").read_text())
    state.materials = initial_materials(repo, snapshot, config.budget, "Toy fixture normative context")
    add_reads(state, repo, ReadingPlan.model_validate(responses[0]), config.budget)
    apply_discovery(state, Discovery.model_validate(responses[1]))
    return repo, state, Bundle.model_validate(responses[2]), responses


@pytest.fixture
def tlc(tmp_path):
    jar = os.environ.get("TLC_JAR")
    if not jar or not Path(jar).is_file() or not shutil.which("java"):
        pytest.skip("Real TLC requires Java and an explicit TLC_JAR; this is not a passed check")
    runner = ProcessRunner(tmp_path / "run")
    verifier = TLCVerifier(jar)
    probe = verifier.probe(runner)
    if not probe["available"]:
        pytest.skip("TLC capability probe failed")
    return verifier, runner
