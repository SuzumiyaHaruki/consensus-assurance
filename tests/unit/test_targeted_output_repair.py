import json
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.materials import ReadingPlan
from consensus_assurance.workflow.output_repair import OutputRepair, Replacement, repair_targets, apply_replacements


def test_large_original_tail_is_preserved_without_resending():
    original={'requests':[{'file':'producer.go','start_line':'bad','end_line':3,'reason':'Read actual input'}], 'rationale':'a'*40000+'KEEP THIS TAIL'}
    targets=repair_targets(original,[{'loc':['requests',0,'start_line'],'type':'int_parsing'}],'invalid integer',1000)
    patch=OutputRepair(replacements=[Replacement(path='/requests/0/start_line',value_json='1')],rationale='Fix integer')
    fixed=apply_replacements(original,targets,patch)
    assert fixed['rationale']==original['rationale']
    assert len(json.dumps(targets))<1000
    assert original['requests'][0]['start_line']=='bad'
    with pytest.raises(ValueError,match='unreported'):
        apply_replacements(original,targets,patch.model_copy(update={'replacements':[Replacement(path='/rationale',value_json='"different"')]}))


def test_field_repair_preserves_large_original_without_replacing_graph(tmp_path,prepared):
    repo,_,_,_=prepared
    original={'requests':[{'file':'counter.py','start_line':'bad','end_line':2,'reason':'Inspect actual step'}],'rationale':'x'*30000+'preserved'}
    patch={'replacements':[{'path':'/requests/0/start_line','value_json':'1'}],'rationale':'Correct integer type'}
    fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps([original,patch]))
    config=Config(execution_backend='python',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    config.budget.error_context_chars=1000
    root=tmp_path/'audit'
    class ReadingEngine(Engine):
        def execute(self,**kwargs):
            return self.ask('read',ReadingPlan,{'catalogue':[]})
    engine=ReadingEngine(config,root,*assemble(config))
    response,_=engine.start(repo)
    assert response.rationale==original['rationale']
    assert response.requests[0].start_line==1
    assert engine.state.usage['agent_calls']==2
    prompt=next(p.read_text() for p in (root/'agent').glob('*/prompt.txt') if 'repair_targets' in p.read_text())
    assert 'preserved' not in json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]).get('raw_output','')
    assert len(prompt)<12000


def test_schema_reference_repair_receives_owner_and_dependency_context():
    from consensus_assurance.core.proposals import GraphDraft
    from consensus_assurance.core.diagnostics import Diagnostic
    from consensus_assurance.workflow.output_repair import diagnostic_context
    candidate={'patch':{'units':[{'id':'U','obligation_ids':['O'],'binding_ids':['B'],
        'relation_ids':['R'],'obligation_ids':[]}],
        'bindings':[{'id':'B','associations':[{'claim_id':'O','source_ids':['source'],'rationale':'Existing association'}]}],
        'claims':[{'id':'O','description':'Preserved obligation','source_ids':['source']}],
        'relations':[{'id':'R','source':'O','target':'B'}],
        'unrelated':[{'id':'X','description':'DO NOT SEND'}]}}
    d=Diagnostic(code='schema_type',category='format',paths=['/patch/units/0/obligation_ids'],message='Empty reference',allowed=['representation'])
    material={'id':'source','file':'service.go','start_line':1,'end_line':1,'content_digest':'fixture','text':'actual acquired code'}
    result=diagnostic_context(candidate,[d],{'materials':[material]},4000)
    assert {o['id'] for o in result['objects']}=={'U','O','B','R'}
    assert result['materials']==[material]
    assert candidate['patch']['units'][0]['obligation_ids']==[]
    assert not result['required_objects_missing']
    small=diagnostic_context(candidate,[d],{'materials':[material]},50)
    assert small['required_objects_missing'] and not small['objects']
    repair=OutputRepair(replacements=[Replacement(path='/patch/claims/0/description',value_json='"changed"')],rationale='Not authorized')
    with pytest.raises(ValueError,match='unreported'):
        apply_replacements(candidate,[{'path':d.paths[0]}],repair)




def test_dictionary_key_repair_preserves_undiagnosed_entries_and_siblings():
    from typing import Literal
    from consensus_assurance.core.types import Record
    from pydantic import ValidationError
    class Candidate(Record):
        effects: dict[Literal['A1','A2'],str]
        unknowns: list[str]
    original={'effects':{'A1':'Known effect','feeds':['B2']},'unknowns':['Producer is unverified']}
    with pytest.raises(ValidationError) as failure:Candidate.model_validate(original)
    targets=repair_targets(original,failure.value.errors(),'invalid key',4000)
    valid=OutputRepair(replacements=[Replacement(path='/effects',value_json=json.dumps({'A1':'Known effect','A2':'Sourced context effect'}))],rationale='Correct the dictionary shape')
    result=apply_replacements(original,targets,valid);assert result['unknowns']==original['unknowns'];Candidate.model_validate(result)
    bad=valid.model_copy(deep=True);bad.replacements[0].value_json='{"A2":"Changed"}'
    with pytest.raises(ValueError,match='undiagnosed'):apply_replacements(original,targets,bad)
    bad=valid.model_copy(deep=True);bad.replacements.append(Replacement(path='/unknowns',value_json='[]'))
    with pytest.raises(ValueError,match='unreported'):apply_replacements(original,targets,bad)
    bad=valid.model_copy(deep=True);bad.replacements.append(bad.replacements[0])
    with pytest.raises(ValueError,match='duplicate'):apply_replacements(original,targets,bad)


def test_source_repair_cannot_drop_a_dependency(prepared):
    from consensus_assurance.workflow.repair_policy import validate_representation
    _,state,_,_=prepared
    code=next(m for m in state.materials if m.file=='counter.py');other=next(m for m in state.materials if m.file=='limits.py')
    with pytest.raises(ValueError,match='cannot discard evidence'):
        validate_representation({'source_ids':[code.id,other.id]}, {'source_ids':[other.id]}, [{'path':'/source_ids'}], {'materials':[m.model_dump(mode='json') for m in [code,other]]})
