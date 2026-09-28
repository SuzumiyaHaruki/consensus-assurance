"""The public CLI uses the same file products as the real Codex transport."""
import json
from pathlib import Path
import pytest
from audit_support import first, check_step
from consensus_assurance.cli import main
from consensus_assurance.core.config import Config, Budget
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine


def test_cli_audit_fixture_execution_and_report(tmp_path,capsys):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('Legal local return remains within capacity.\n')
    submission,files=check_step()({'units':[{'id':'unit-bounded'}]})
    fixture=tmp_path/'audit.json'
    candidate,map_files=first({})
    fixture.write_text(json.dumps([{'submission':candidate,'files':map_files}, {'submission':submission,'files':files},
        {'submission':{'action':'stop','scope':'run','reason':'user_stop','rationale':'Explicit fixture boundary; pending review remains visible'}}]))
    config=Config(agent_backend='mock',fixture=str(fixture),execution_backend='python',execution_isolation='workspace',
        directed_question='Check the synthetic local return contract',runs_dir=str(tmp_path/'runs'),budget=Budget(agent_calls=3,total_seconds=60))
    path=tmp_path/'config.yaml';path.write_text(config.model_dump_json())
    assert main(['run','--config',str(path),'--repo',str(repo)])==0
    root=next((tmp_path/'runs').glob('*-mock-run'))
    state=json.loads((root/'state.json').read_text())
    assert len(state['direct_checks'])==1 and state['usage']['agent_calls']==3
    assert state['agent_session_id']=='fixture-session' and len(state['agent_turns'])==3
    assert state['method_paths'] and state['current_submission']['action']=='stop'
    assert not any(key.startswith('native_') for key in state)
    assert not any(p.name.startswith('native-') for p in root.iterdir())
    assert (root/'draft').is_dir() and (root/'submissions').is_dir() and (root/'agent-source').is_dir()
    assert any(c['action']=='direct_check' and c['exit_code']==0 for c in state['checks'])
    report=(root/'report.md').read_text()
    assert 'mock' in report and state['units'][0]['id'] in report
    derived=['audit-spec.json','materials.json','graph.json','audit-progress.json','plan.json']
    assert all(not (root/name).exists() for name in derived)
    index=json.loads((root/'research.json').read_text());index['retained_context']='current Agent entry'
    (root/'research.json').write_text(json.dumps(index))
    assert main(['report','--run',str(root)])==0
    assert json.loads((root/'research.json').read_text())['retained_context']=='current Agent entry'
    assert all(not (root/name).exists() for name in derived)
    assert main(['report','--run',str(root),'--export-views'])==0
    assert all((root/name).exists() for name in derived)
    artifact=state['direct_checks'][0]
    assert json.loads(Path(artifact['plan_path']).read_text())['claim_id']==state['claims'][0]['id']
    import re
    from urllib.parse import unquote
    assert all((root/unquote(target)).is_file() for target in re.findall(r'\]\(([^)]+)\)',report))
    assert main(['resume','--run',str(root),'--agent-turn-timeout','120'])==0
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
    old=tmp_path/'historical';old.mkdir()
    historical={'framework_revision':'native-products-v27','native_current':{'phase':'executed'},'native_session_id':'old-session'}
    (old/'state.json').write_text(json.dumps(historical))
    (old/'report.md').write_text('历史结果：执行失败，未确认。')
    before={p.name:p.read_bytes() for p in old.iterdir()}
    assert main(['report','--run',str(old)])==0
    assert '历史结果：执行失败' in capsys.readouterr().out
    assert main(['resume','--run',str(old)])==2
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
