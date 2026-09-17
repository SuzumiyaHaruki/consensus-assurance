import json
import pytest
from consensus_assurance.workflow.prompts import render
from consensus_assurance.core.proposals import ReviewReply,ConsequenceReply,BuildReply
from consensus_assurance.adapters.agents.backend import strict_schema


@pytest.mark.parametrize('kind',['consequence','build','F1','F3','technical','semantic_review','spec_refine'])
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


def test_actual_wire_schema_rejects_recorded_shape_and_derives_indexes(prepared):
    from copy import deepcopy
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.adapters.agents.backend import wire_value
    from test_audit_spec import inventory
    jsonschema=pytest.importorskip('jsonschema')
    _,state,_,responses=prepared
    proposal=Discovery.model_validate(responses[1]);proposal.audit_spec=inventory(state.materials[0].id)
    schema=Discovery.model_json_schema();wire=strict_schema(schema)
    encoded=wire_value(proposal.model_dump(mode='json'),schema)
    jsonschema.validate(encoded,wire)
    assert 'behavior_ids' not in encoded['audit_spec']['activities'][0]
    assert 'established_by' not in encoded['audit_spec']['facts'][0]
    decoded=Discovery.model_validate(wire_value(encoded,schema,decode=True))
    assert decoded.audit_spec==proposal.audit_spec
    for field,bad in [('coverage',{'status':'partial','reason':'Incomplete source'}),('cross_activity_effects',[{'key':'feeds','value':['B2']}])]:
        broken=deepcopy(encoded)
        owner='activities' if field=='coverage' else 'behaviors'
        broken['audit_spec'][owner][0][field]=bad
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(broken,wire)
    # A legal key cannot hide a wrongly typed value inside JSON text either.
    broken=deepcopy(encoded);broken['audit_spec']['behaviors'][0]['cross_activity_effects']=[{'key':'A5','value':['B2']}]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(broken,wire)


def test_typed_nested_dictionary_preserves_wire_value_constraints():
    from typing import Literal
    from consensus_assurance.core.types import Record
    from consensus_assurance.adapters.agents.backend import wire_value
    class Mapping(Record):
        values: dict[Literal['left','right'],dict[str,list[int]]]
    value=Mapping(values={'left':{'sequence':[1,2]}});schema=Mapping.model_json_schema()
    encoded=wire_value(value.model_dump(),schema)
    assert encoded['values'][0]['key']=='left'
    assert Mapping.model_validate(wire_value(encoded,schema,decode=True))==value
