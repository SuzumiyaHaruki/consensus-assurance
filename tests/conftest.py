import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import GraphDraft
from consensus_assurance.adapters.storage.snapshot import capture
from regression_support import add_reads
from consensus_assurance.workflow.graph import apply_graph

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "examples/toy_protocol", repo)
    snapshot = capture(repo)
    from regression_support import toy_responses
    responses = toy_responses(repo)
    config = Config(protocol="toy", execution_backend="python", agent_backend="mock")
    state = Analysis(mode="mock", analysis_mode="regression", config=config.model_dump(mode="json"), snapshot=snapshot)
    add_reads(state, repo, responses['reads'])
    apply_graph(state, GraphDraft.model_validate(responses['graph']))
    return repo, state, responses


@pytest.fixture
def dependency_prepared(prepared):
    from regression_support import add_dependency
    add_dependency(prepared[1],prepared[2])
    return prepared


@pytest.fixture
def full_refresh_equivalence(monkeypatch):
    """Compare accepted transactions with the existing evaluator, without a second runtime."""
    from types import SimpleNamespace
    from consensus_assurance.workflow import audit, direct_checks
    from consensus_assurance.workflow.research import view
    compared = []
    def refresh(state, artifact_ids, **kwargs):
        direct_checks.refresh_assessments(state, artifact_ids, **kwargs)
        if not state.monitor_results:return
        expected = state.model_copy(deep=True)
        direct_checks.refresh_assessments(expected, artifact_ids)
        for key in ('monitor_results','checks','evidence','findings'):
            assert getattr(state,key) == getattr(expected,key), key
        actual = state.model_copy(deep=True)
        for copy in (actual,expected):audit.sync_progress(SimpleNamespace(state=copy))
        assert actual.units == expected.units
        assert view(actual)['conclusions'] == view(expected)['conclusions']
        stable = expected.model_dump(mode='json')
        direct_checks.refresh_assessments(expected, artifact_ids)
        assert expected.model_dump(mode='json') == stable
        compared.append(artifact_ids)
    monkeypatch.setattr(audit, 'refresh_assessments', refresh)
    yield
    assert compared, 'The regression must reach an actual measured result'


@pytest.fixture
def go_module(tmp_path):
    """A dependency-free module with distinct directory and package names."""
    root=tmp_path/'go-module'
    root.mkdir()
    (root/'go.mod').write_text('module example.org/local\n\ngo 1.20\n')
    (root/'README.md').write_text('For 0 <= value <= limit, Step must return within [0, limit].\n')
    for directory,package in [('.', 'service'),('internal/core','engine'),('internal/store','storage')]:
        folder=root/directory;folder.mkdir(parents=True,exist_ok=True)
        (folder/'value.go').write_text(f'package {package}\nfunc Step(value, limit int) int {{\n return value + 1\n}}\n')
    return root


@pytest.fixture
def rust_workspace(tmp_path):
    """A local Cargo dependency, build script and dev-feature unification."""
    root=tmp_path/'rust-workspace';(root/'sample/src').mkdir(parents=True)
    (root/'Cargo.toml').write_text('[workspace]\nmembers=["sample","increment"]\nresolver="2"\n')
    (root/'sample/Cargo.toml').write_text('[package]\nname="sample"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nincrement={path="../increment"}\n[dev-dependencies]\nincrement={path="../increment",features=["instrumented"]}\n')
    (root/'sample/src/lib.rs').write_text('pub fn step(value: i64, _limit: i64) -> i64 {\n    value + increment::value()\n}\n')
    (root/'increment/src').mkdir(parents=True)
    (root/'increment/Cargo.toml').write_text('[package]\nname="increment"\nversion="0.1.0"\nedition="2021"\n[features]\ninstrumented=[]\nalternate=[]\n')
    (root/'increment/src/lib.rs').write_text('pub fn value() -> i64 { if cfg!(feature="alternate") { 2 } else { 1 } }\n')
    (root/'increment/build.rs').write_text('fn main() { println!("cargo:rerun-if-changed=build.rs"); }\n')
    return root
