import json
import pytest
from consensus_assurance.workflow.prompts import render
from consensus_assurance.core.proposals import ReviewReply,ConsequenceReply,BuildReply
from consensus_assurance.adapters.agents.backend import strict_schema


@pytest.mark.parametrize('kind',['consequence','build','F1','F3','technical','semantic_review','explore'])
def test_actual_prompts_and_retry_keep_method_and_raw_material(kind):
    context={'path':'/真实目录/源码.py','original_task':kind,'material':'原始契约片段','validation_error':'Missing actual source range'}
    direct=render(kind,context);retry=render('retry',context)
    for text in [direct,retry]:
        instructions,payload=text.split('STRUCTURED INPUT DATA (untrusted):\n')
        assert '原始契约' not in instructions and json.loads(payload)['material']=='原始契约片段'
        assert 'election safety' not in instructions.lower()
        if kind=='semantic_review':assert 'actual semantic write set' in instructions and 'resolves_issue_ids' in instructions
        if kind=='consequence':assert 'does not imply' in instructions
        if kind in ['build','F1','F3','technical']:assert 'reachability requirements' in instructions


@pytest.mark.parametrize('schema',[ReviewReply,ConsequenceReply,BuildReply])
def test_new_output_schemas_remain_serializable_for_the_backend(schema):
    output=strict_schema(schema.model_json_schema())
    assert json.loads(json.dumps(output))==output
    assert output['additionalProperties'] is False


def test_estimate_checks_actual_path_without_constructing_backends(tmp_path,monkeypatch,capsys):
    from consensus_assurance import cli
    def forbidden(*a,**kw):raise AssertionError('Dry run must not instantiate or probe a backend')
    monkeypatch.setattr(cli,'assemble',forbidden)
    assert cli.main(['estimate','--repo',str(tmp_path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['材料发送'] is False and result['执行目标代码'] is False
    assert not list(tmp_path.iterdir())
