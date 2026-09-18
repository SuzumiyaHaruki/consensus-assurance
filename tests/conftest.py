import json
import os
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import Bundle, Derivation
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.workflow.materials import initial_materials, add_reads, ReadingPlan
from consensus_assurance.workflow.graph import apply_graph
from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
from consensus_assurance.adapters.runners.process import ProcessRunner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "examples/toy_protocol", repo)
    snapshot = capture(repo)
    from regression_support import toy_responses
    responses = toy_responses(repo)
    fixture = tmp_path / "toy_responses.json"
    fixture.write_text(json.dumps(responses))
    config = Config(protocol="toy", implementation="toy", agent_backend="mock", fixture=str(fixture))
    state = Analysis(mode="mock", analysis_mode="regression", config=config.model_dump(mode="json"), snapshot=snapshot)
    state.materials = initial_materials(repo, snapshot, config.budget, "Toy fixture normative context")
    add_reads(state, repo, ReadingPlan.model_validate(responses[0]), config.budget)
    apply_graph(state, Derivation.model_validate(responses[1]))
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


@pytest.fixture(autouse=True)
def verification_fixture_inventory(monkeypatch):
    """Materialize the descriptive step in scripted downstream fixture playback."""
    from consensus_assurance.adapters.agents.backend import MockAgent
    from regression_support import descriptive_inventory
    original=MockAgent.__init__
    def initialize(self,fixture=None):
        original(self,fixture)
        if len(self.responses)>1 and 'requests' in self.responses[0] and self.responses[1].get('claims'):
            source=self.responses[1]['claims'][0]['source_ids'][0]
            self.responses.insert(1,descriptive_inventory(source).model_dump(mode='json'))
    monkeypatch.setattr(MockAgent,'__init__',initialize)
