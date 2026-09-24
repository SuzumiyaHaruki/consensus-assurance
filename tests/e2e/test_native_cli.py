"""The public CLI uses the same file products as the real native transport."""
import json
from pathlib import Path
from native_support import products, check_step
from consensus_assurance.cli import main
from consensus_assurance.core.config import Config, Budget


def test_cli_native_fixture_execution_and_report(tmp_path,capsys):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value < limit else 0\n')
    (repo/'README.md').write_text('Legal local return remains within capacity.\n')
    submission,files=check_step()({'units':[{'id':'unit-bounded'}]})
    fixture=tmp_path/'native.json'
    fixture.write_text(json.dumps([{'submission':products()[0]}, {'submission':submission,'files':files},
        {'submission':{'action':'stop','rationale':'Explicit fixture finished'}}]))
    config=Config(agent_backend='mock',fixture=str(fixture),execution_backend='python',execution_isolation='workspace',
        runs_dir=str(tmp_path/'runs'),budget=Budget(agent_calls=3,total_seconds=60))
    path=tmp_path/'config.yaml';path.write_text(config.model_dump_json())
    assert main(['run','--config',str(path),'--repo',str(repo)])==0
    root=next((tmp_path/'runs').glob('*-mock-run'))
    state=json.loads((root/'state.json').read_text())
    assert len(state['direct_checks'])==1 and state['usage']['agent_calls']==3
    assert any(c['action']=='direct_check' and c['exit_code']==0 for c in state['checks'])
    report=(root/'report.md').read_text()
    assert 'mock' in report and state['units'][0]['id'] in report
    assert main(['report','--run',str(root)])==0
    old=tmp_path/'historical';old.mkdir()
    (old/'state.json').write_text('{"framework_revision":"old-stage"}')
    (old/'report.md').write_text('历史结果：执行失败，未确认。')
    assert main(['report','--run',str(old)])==0
    assert '历史结果：执行失败' in capsys.readouterr().out
    assert main(['resume','--run',str(old)])==2
    assert json.loads((old/'state.json').read_text())=={'framework_revision':'old-stage'}
