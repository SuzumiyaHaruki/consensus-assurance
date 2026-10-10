"""The public CLI uses the same file products as the real Codex transport."""
import json
from pathlib import Path
import pytest
from audit_support import first, check_step
from consensus_assurance.cli import main
from consensus_assurance.core.config import Config, Budget
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine


def test_cli_audit_fixture_execution_and_report(tmp_path,capsys,monkeypatch):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('Legal local return remains within capacity.\n')
    submission,files=check_step()({'units':[{'id':'unit-bounded'}]})
    fixture=tmp_path/'audit.json'
    candidate,map_files=first({})
    fixture.write_text(json.dumps([{'submission':candidate,'files':map_files}, {'submission':submission,'files':files}]))
    config=Config(agent_backend='mock',fixture=str(fixture),execution_backend='python',execution_isolation='workspace',
        directed_question='Execute the supplied local return check',runs_dir=str(tmp_path/'runs'),budget=Budget(agent_calls=2,total_seconds=60))
    path=tmp_path/'config.yaml';path.write_text(config.model_dump_json())
    assert main(['run','--config',str(path),'--repo',str(repo)])==2
    root=next((tmp_path/'runs').glob('*-mock-run'))
    state=json.loads((root/'state.json').read_text())
    assert len(state['direct_checks'])==1 and state['usage']['agent_calls']==2
    assert state['agent_session_id']=='fixture-session' and len(state['agent_turns'])==2
    assert state['method_paths'] and state['run_stop']['origin']=='controller'
    assert (root/'draft').is_dir() and (root/'submissions').is_dir() and (root/'agent-source').is_dir()
    assert any(c['action']=='direct_check' and c['exit_code']==0 for c in state['checks'])
    report=(root/'report.md').read_text()
    assert 'mock' in report and '待调查线索' in report and Path(state['direct_checks'][0]['harness_path']).relative_to(root).as_posix() in report
    derived=['audit-spec.json','materials.json','graph.json','audit-progress.json','plan.json']
    assert all(not (root/name).exists() for name in derived)
    index=json.loads((root/'research.json').read_text());index.update(retained_context='obsolete',remaining_seconds=98,remaining_agent_calls=25)
    (root/'research.json').write_text(json.dumps(index))
    assert main(['report','--run',str(root)])==0
    current=json.loads((root/'research.json').read_text())
    assert current==index
    assert current['implementation']['harness_kind']=='python' and current['validation']['command']
    assert current['capacity']['remaining']['agent_calls']==0
    assert all(not (root/name).exists() for name in derived)
    assert main(['report','--run',str(root),'--export-views'])==0
    assert all((root/name).exists() for name in derived)
    assert json.loads((root/'research.json').read_text())==index
    artifact=state['direct_checks'][0]
    assert json.loads(Path(artifact['plan_path']).read_text())['claim_id']==state['claims'][0]['id']
    import re
    from urllib.parse import unquote
    for target in re.findall(r'\]\(([^)]+)\)',report):
        assert f'id="{target[1:]}"' in report if target.startswith('#') else (root/unquote(target)).is_file()
    assert main(['resume','--run',str(root),'--agent-turn-timeout','120'])==2
    resumed=json.loads((root/'state.json').read_text())
    assert resumed['config']['budget']['agent_turn_timeout']==120
    assert resumed['agent_session_id']==state['agent_session_id'] and resumed['agent_turns']==state['agent_turns']
    assert resumed['usage']==state['usage'] and resumed['direct_checks']==state['direct_checks']
    saved=(root/'state.json').read_bytes()
    with pytest.raises(ValueError,match='empty directory'):
        Engine(config,root,*assemble(config)).start(repo)
    assert main(['plan','--config',str(path),'--repo',str(repo)])==0
    fresh=next((tmp_path/'runs').glob('*-mock-plan'))
    initial=json.loads((fresh/'state.json').read_text())
    assert initial['id']!=state['id'] and initial['agent_session_id'] is None
    assert all(not initial[key] for key in ('question_candidates','units','materials','evidence','agent_turns','usage'))
    assert (root/'state.json').read_bytes()==saved
    assert not (fresh/'draft').exists()
    from consensus_assurance.adapters.agents.backend import MockAgent
    def cancel(*args,**kwargs):raise KeyboardInterrupt('Actual caller cancellation')
    monkeypatch.setattr(MockAgent,'investigate',cancel)
    previous=set((tmp_path/'runs').iterdir())
    assert main(['run','--config',str(path),'--repo',str(repo)])==130
    cancelled=next(iter(set((tmp_path/'runs').iterdir())-previous))
    saved_cancel=json.loads((cancelled/'state.json').read_text())
    assert saved_cancel['run_stop']['origin']=='controller' and saved_cancel['run_stop']['reason']=='user_stop'
    assert saved_cancel['usage']['agent_calls']==1 and '实际取消' in (cancelled/'report.md').read_text()
    old=tmp_path/'historical';old.mkdir()
    historical={'framework_revision':'audit-products-v59','native_current':{'phase':'executed'},'native_session_id':'old-session'}
    (old/'state.json').write_text(json.dumps(historical))
    (old/'report.md').write_text('历史结果：执行失败，未确认。')
    before={p.name:p.read_bytes() for p in old.iterdir()}
    assert main(['report','--run',str(old)])==0
    assert '历史结果：执行失败' in capsys.readouterr().out
    assert main(['resume','--run',str(old)])==2
    historical_engine=Engine(Config(),old,None,None,'')
    with pytest.raises(ValueError,match='original Git revision'):historical_engine.resume()
    assert {p.name:p.read_bytes() for p in old.iterdir()}==before


def test_missing_target_cli_has_no_download(tmp_path, capsys):
    assert main(["run", "--repo", str(tmp_path / "absent"), "--runs-dir", str(tmp_path / "runs")]) == 2
    assert "does not exist" in capsys.readouterr().err


import re
from consensus_assurance.cli import create_run_directory, resolve_run


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
