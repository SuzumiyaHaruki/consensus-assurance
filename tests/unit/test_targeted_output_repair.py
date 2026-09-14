import json
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import BuildReply
from consensus_assurance.registry import assemble
from consensus_assurance.consensus.inquiry import INQUIRY
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.materials import ReadingPlan
from consensus_assurance.workflow.output_repair import OutputRepair, Replacement, repair_targets, apply_replacements
from consensus_assurance.workflow.modeling import validate_build_reply


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


@pytest.mark.parametrize('interrupt',[False,True])
def test_field_repair_is_executed_and_resumes_without_replacing_graph(tmp_path,prepared,interrupt):
    repo,_,_,_=prepared
    original={'requests':[{'file':'counter.py','start_line':'bad','end_line':2,'reason':'Inspect actual step'}],'rationale':'x'*30000+'preserved'}
    patch={'replacements':[{'path':'/requests/0/start_line','value_json':'1'}],'rationale':'Correct integer type'}
    fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps([original,patch]))
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    config.budget.error_context_chars=1000
    root=tmp_path/'audit'
    class ReadingEngine(Engine):
        interrupted=False
        def execute(self,**kwargs):
            return self.ask('read',ReadingPlan,{'catalogue':[]})
        def checkpoint(self,event):
            super().checkpoint(event)
            if interrupt and not self.interrupted and event=='action_result_saved' and self.state.pending_action.kind=='agent:read:repair':
                self.interrupted=True
                raise RuntimeError('After patch response before local merge')
    engine=ReadingEngine(config,root,*assemble(config),INQUIRY)
    if interrupt:
        with pytest.raises(RuntimeError):engine.start(repo)
        engine=ReadingEngine(config,root,*assemble(config),INQUIRY);engine.interrupted=True
        response,_=engine.resume()
    else:response,_=engine.start(repo)
    assert response.rationale==original['rationale']
    assert response.requests[0].start_line==1
    assert engine.state.usage['agent_calls']==2
    prompt=next(p.read_text() for p in (root/'agent').glob('*/prompt.txt') if 'repair_targets' in p.read_text())
    assert 'preserved' not in json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]).get('raw_output','')
    assert len(prompt)<12000


def test_invalid_build_artifact_is_repaired_before_commit(tmp_path,prepared):
    repo,state,bundle,_=prepared
    valid=bundle.behavior;bad=bundle.model_copy(deep=True);bad.behavior=valid.replace('Init ==','BadInit ==')
    fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps([
        BuildReply(bundle=bad,gap='').model_dump(mode='json'),
        {'replacements':[{'path':'/bundle/behavior','value_json':json.dumps(valid)}],'rationale':'Restore the declared initial operator'}]))
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture))
    from consensus_assurance.workflow.budget import BudgetTracker
    engine=Engine(config,tmp_path/'audit',*assemble(config),INQUIRY);engine.state=state;engine.budget=BudgetTracker(config.budget,state)
    unit=state.units[0]
    reply,_=engine.ask('build',BuildReply,{},lambda p:validate_build_reply(state,unit,p,engine.implementation))
    assert not (engine.root/'models').exists()
    model=engine.save_model(unit,reply.bundle)
    assert model.version==1 and len(state.models)==1
    assert (engine.root/'models/v1/commit.json').exists()
