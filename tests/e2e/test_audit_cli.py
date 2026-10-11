import json
import re
from pathlib import Path
import pytest
from consensus_assurance.cli import main, create_run_directory, resolve_run
from consensus_assurance.core.config import Config, Budget
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine


def test_cli_fixed_execution_and_fresh_run_are_independent(tmp_path, capsys):
    from audit_support import combined
    repo = tmp_path / 'source'
    repo.mkdir()
    (repo / 'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo / 'README.md').write_text('Fixture boundary contract.\n')
    submission, files = combined({})
    fixture = tmp_path / 'responses.json'
    fixture.write_text(json.dumps([dict(submission=submission, files=files)]))
    config = Config(agent_backend='mock', execution_backend='python', fixture=str(fixture),
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
        schema = json.loads((root / 'submission.schema.json').read_text())
        assert not {'Unit', 'Claim', 'Binding', 'GraphPatch', 'Evidence', 'Finding'} & schema['$defs'].keys()
    assert {p.name: p.read_bytes() for p in repo.iterdir()} == original
    capsys.readouterr()


def test_historical_method_rejected_before_writes_but_saved_report_readable(tmp_path, capsys, monkeypatch):
    import consensus_assurance.cli as cli
    root = tmp_path / 'archive'
    root.mkdir()
    (root / 'state.json').write_text(json.dumps({'framework_revision': 'audit-products-v62', 'retired': 'layout'}))
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

def test_missing_target_cli_has_no_download(tmp_path, capsys):
    assert main(["run", "--repo", str(tmp_path / "absent"), "--runs-dir", str(tmp_path / "runs")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_readable_unique_run_directories(tmp_path):
    config = Config(runs_dir=str(tmp_path), execution_backend='go_module', agent_backend='mock')
    first = create_run_directory(config, 'plan')
    second = create_run_directory(config, 'plan')
    assert first != second
    assert re.match(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-go_module-mock-plan', first.name)
    assert resolve_run(first.name, tmp_path) == first
    old = tmp_path / ('a' * 32)
    old.mkdir()
    assert resolve_run(old.name, tmp_path) == old


def test_estimate_reports_explicit_long_limits_without_tools(tmp_path,capsys,monkeypatch):
    import consensus_assurance.cli as cli
    def forbidden(*args,**kwargs):raise AssertionError('Estimate must not assemble or create a run')
    monkeypatch.setattr(cli,'assemble',forbidden)
    monkeypatch.setattr(cli,'create_run_directory',forbidden)
    config=cli.load_config(Path(__file__).parents[2]/'configs/targets/etcd_raft.yaml')
    config.budget.total_seconds=4800
    example=tmp_path/'long.yaml';example.write_text(config.model_dump_json())
    assert main(['estimate','--config',str(example),'--repo',str(tmp_path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['预算']['total_seconds']==4800 and result['预算']['experiments']==16
    assert set(result['预算'])=={'total_seconds','agent_turn_timeout','action_timeout','agent_calls','experiments'}
    assert '模型检查' not in result['后端'] and result['后端']['目标执行']=='go_module'
    assert result['授权']=={'发送材料':False,'执行目标':False}
    assert '粗略计划下限' not in result and '计划可能受限' not in result
    assert '失败重试' in result['计数口径']['experiments']
    config=cli.load_config(example);config.budget.experiments=0
    path=tmp_path/'zero.yaml';path.write_text(config.model_dump_json())
    assert main(['estimate','--config',str(path),'--repo',str(tmp_path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['零额度']==['experiments'] and '源码调查' in result['限制说明']


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
    cfg=load_config('configs/targets/deepseek.example.yaml')
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


@pytest.mark.real
def test_deepseek_two_turn_acceptance(request):
    """Explicit opt-in: official service, synthetic data, two turns, five minutes total."""
    import os,secrets
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.core.types import ExecutionStatus
    if os.environ.get('CA_DEEPSEEK_ACCEPTANCE')!='1':
        pytest.skip('Paid DeepSeek acceptance requires explicit CA_DEEPSEEK_ACCEPTANCE=1 authorization')
    from consensus_assurance.cli import load_config
    from consensus_assurance.adapters.agents.backend import codex_events
    from consensus_assurance.adapters.storage.files import write_json
    runner,draft=request.getfixturevalue('codex_workspace')
    cfg=load_config('configs/targets/deepseek.example.yaml')
    assert cfg.codex_provider.base_url=='https://api.deepseek.com' and cfg.agent_model=='deepseek-flash'
    agent=CodexAgent(cfg.agent_reasoning_effort,cfg.agent_model,cfg.codex_provider)
    agent.client_environment()
    agent.bind_inputs(runner.root,runner.root/'agent-source')
    write_json(runner.root/'config.json',cfg)
    assert agent.probe(runner)['available']
    assert agent.prepare(runner,draft,'synthetic')[0]
    marker=secrets.token_hex(16)
    prompts=[
        f'Authorized synthetic capability check. Read {runner.root}/agent-source/value.txt through a shell tool. '
        'Use apply_patch to create one.json in the current draft with a value field equal to twice the observed integer. '
        'Run /usr/bin/python3 to load that JSON and print its value. '
        f'Remember this session marker only in conversation: {marker}. Do not echo it, put it in a command, '
        'write it to any file or repeat it in the answer. Return exactly {"submission":"one.json","summary":"first complete"}.',
        'Continue this exact session. Use the value obtained in the previous tool loop and the session marker '
        'provided only in that turn. Do not reread the source or search saved logs. Use apply_patch to create two.json '
        'with previous_value, marker and next_value (previous_value plus one). Run /usr/bin/python3 to load it and '
        'print next_value. Return exactly {"submission":"two.json","summary":"second complete"}.']
    session=None
    for index,prompt in enumerate(prompts,1):
        agent.validate_inputs(runner.root,cfg)
        runner.active_action_id=f'capability-{index}'
        check,observed,result=agent.investigate(runner,prompt,draft,'synthetic',120,session)
        write_json(runner.root/'logs'/check.id/'check.json',check)
        assert check.status==ExecutionStatus.COMPLETED and check.exit_code==0 and check.parameters['agent_turn_completed'],check.reason
        assert result==dict(submission='one.json' if index==1 else 'two.json',summary='first complete' if index==1 else 'second complete')
        assert observed and (session is None or observed==session)
        session=observed
        items=[e['item'] for e in codex_events(check) if e.get('type')=='item.completed']
        assert any(i.get('type')=='file_change' and i.get('status')=='completed' for i in items)
        expected=14 if index==1 else 15
        assert any(i.get('type')=='command_execution' and i.get('exit_code')==0
            and str(expected) in i.get('aggregated_output','').split() for i in items)
        value=json.loads((draft/result['submission']).read_text())
        assert value==({'value':14} if index==1 else {'previous_value':14,'marker':marker,'next_value':15})
        if index==1:
            assert all(marker.encode() not in p.read_bytes() for p in runner.root.rglob('*') if p.is_file())
    assert (runner.root/'agent-source/value.txt').read_text()=='7\n'
