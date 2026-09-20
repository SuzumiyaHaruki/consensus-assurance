import json
import os
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import Bundle, GraphDraft
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.workflow.materials import initial_materials,  ReadingPlan
from regression_support import add_reads
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
    config = Config(protocol="toy", execution_backend="python", agent_backend="mock", fixture=str(fixture))
    state = Analysis(mode="mock", analysis_mode="regression", config=config.model_dump(mode="json"), snapshot=snapshot)
    state.materials = initial_materials(repo, snapshot, config.budget, "Toy fixture normative context")
    add_reads(state, repo, ReadingPlan.model_validate(responses[0]), config.budget)
    apply_graph(state, GraphDraft.model_validate(responses[1]))
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
    from regression_support import descriptive_inventory,bounded_derivation,fixture_reachability
    original=MockAgent.__init__
    def initialize(self,fixture=None):
        original(self,fixture)
        responses=[];structured=False
        for reply in self.responses:
            if isinstance(reply,dict) and reply.get('units') and 'claims' in reply and 'expected_versions' not in reply and len(self.responses)>1 and 'requests' in self.responses[0]:
                if len(responses)==1 and 'requests' in responses[0]:
                    source=reply['claims'][0]['source_ids'][0]
                    responses.append(descriptive_inventory(source).model_dump(mode='json'))
                response=bounded_derivation(reply);structured=response['audit_question']['fact_ids']==['fixture_value']
                from regression_support import selection_derivation
                selection=selection_derivation(response)
                responses.extend([selection,response])
            elif structured and isinstance(reply,dict) and 'behavior' in reply:responses.append(fixture_reachability(reply))
            else:responses.append(reply)
        self.responses=responses
    monkeypatch.setattr(MockAgent,'__init__',initialize)


@pytest.fixture
def dependency_prepared(prepared):
    from regression_support import add_dependency
    add_dependency(prepared[1],prepared[3])
    return prepared
