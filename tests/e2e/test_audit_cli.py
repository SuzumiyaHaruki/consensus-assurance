import json
from pathlib import Path
import pytest
from consensus_assurance.cli import main
from consensus_assurance.core.config import Config, Budget


def test_cli_fixed_execution_and_fresh_run_are_independent(tmp_path, capsys):
    from support.audit import combined
    repo = tmp_path / 'source'
    repo.mkdir()
    (repo / 'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo / 'README.md').write_text('Fixture boundary contract.\n')
    submission, files = combined({})
    fixture = tmp_path / 'responses.json'
    fixture.write_text(json.dumps([dict(submission=submission, files=files)]))
    config = Config(agent_backend='mock', execution_backend='python', fixture=str(fixture),
                    investigation_focus=['Trace persistence across recovery'],
                    execution_isolation='workspace', runs_dir=str(tmp_path / 'runs'),
                    budget=Budget(agent_calls=1, experiments=1, total_seconds=30))
    path = tmp_path / 'config.json'
    path.write_text(config.model_dump_json())
    original = {p.name: p.read_bytes() for p in repo.iterdir()}
    for _ in range(2):
        assert main(['run', '--config', str(path), '--repo', str(repo)]) == 2
    roots = sorted((tmp_path / 'runs').iterdir())
    states = [json.loads((root / 'state.json').read_text()) for root in roots]
    assert len(roots) == 2 and states[0]['id'] != states[1]['id']
    assert states[0]['experiments'][0]['id'] != states[1]['experiments'][0]['id']
    for root, state in zip(roots, states):
        assert state['usage'] == {'agent_calls': 1, 'experiments': 1}
        assert len(state['experiments']) == 1 and state['interpretations'] == []
        assert main(['report', '--run', str(root), '--export-views']) == 0
        assert (root / 'knowledge.json').is_file()
        view = json.loads((root / 'research.json').read_text())
        assert view['investigation_focus'] == config.investigation_focus
        assert len(view['reselection']['investigation_axes']) == 2
    assert {p.name: p.read_bytes() for p in repo.iterdir()} == original
    capsys.readouterr()


def test_historical_method_rejected_before_writes_but_saved_report_readable(tmp_path, capsys, monkeypatch):
    import consensus_assurance.cli as cli
    root = tmp_path / 'archive'
    root.mkdir()
    (root / 'state.json').write_text(json.dumps({'framework_revision': 'audit-products-v69',
        'interpretations': [{'report_title': '原有标题', 'report_answer': '旧中文摘要'}]}))
    (root / 'report.md').write_text('Original saved report\n')
    before = {p.name: p.read_bytes() for p in root.iterdir()}

    def forbidden(*args, **kwargs):
        raise AssertionError('Historical commands must not assemble providers or migrate state')

    monkeypatch.setattr(cli, 'assemble', forbidden)
    assert main(['resume', '--run', str(root)]) == 2
    assert main(['validate', '--run', str(root), '--submission', 'submission.json']) == 2
    assert main(['report', '--run', str(root)]) == 0
    assert 'Original saved report' in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before

@pytest.fixture
def codex_workspace():
    import shutil,tempfile,time
    from consensus_assurance.adapters.runners.process import ProcessRunner
    if not shutil.which('codex') or not shutil.which('bwrap'):pytest.skip('Local Codex and bubblewrap are required')
    # The permission profile deliberately denies /tmp; retain probe receipts outside it.
    cache=Path.home()/'.cache/consensus-assurance';cache.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='provider-acceptance-',dir=cache))
    source=root/'agent-source';source.mkdir();(source/'value.txt').write_text('7\n')
    draft=root/'draft';draft.mkdir()
    runner=ProcessRunner(root);runner.deadline=time.monotonic()+300
    print('Retained capability receipts:',root)
    return runner,draft


@pytest.mark.real
@pytest.mark.parametrize('custom',[False,True])
def test_real_codex_local_permissions(codex_workspace,monkeypatch,custom):
    from consensus_assurance.cli import load_config
    from consensus_assurance.adapters.runners.process import output
    from consensus_assurance.adapters.agents.backend import CodexAgent
    runner,draft=codex_workspace
    cfg=load_config('configs/ca/deepseek.yaml')
    provider=cfg.codex_provider.model_copy(update={'env_key':'CA_PROVIDER_CANARY'}) if custom else None
    monkeypatch.setenv('CA_PROVIDER_CANARY','unlabelled-local-canary-987654321')
    agent=CodexAgent('low','deepseek-flash' if custom else None,provider)
    agent.bind_inputs(runner.root,runner.root/'agent-source')
    assert agent.probe(runner)['available']
    ok,checks=agent.prepare(runner,draft,'synthetic')
    assert ok,output(checks[-1])
    if custom:
        assert 'CREDENTIAL_ABSENT' in output(checks[-1])
        assert 'READ:5' in output(checks[-1]) and 'DENIED:write:5' in output(checks[-1])
    assert (runner.root/'agent-source/value.txt').read_text()=='7\n'
    for path in runner.root.rglob('*'):
        if path.is_file():
            assert b'unlabelled-local-canary-987654321' not in path.read_bytes()
            assert b'ca-provider-permission-canary' not in path.read_bytes()
