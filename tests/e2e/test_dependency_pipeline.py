"""One real Engine path through interface repair, new code, draft split, scope and TLC."""
import copy,json,sys
import pytest
from test_scope_pipeline import setup,ScopeAgent
from consensus_assurance.core.types import Origin
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.workflow.engine import Engine


class RepairingScopeAgent(ScopeAgent):
    def __init__(self,data):super().__init__(data);self.bad_review=False;self.cache_requested=False
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        p=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        if response_type.__name__=='OutputRepair':
            if p['original_task']=='semantic_review':
                if not self.cache_requested:
                    self.cache_requested=True
                    response={'requests':[{'file':'counter.py','start_line':1,'end_line':4,'reason':'Inspect the current binding before correcting its classification'}],'rationale':'Reattach cached code without changing the negative judgment'}
                else:
                    target=p['repair_targets'][0];item=copy.deepcopy(target['current_value']);item['aspect']='decomposition'
                    response={'replacements':[{'path':target['path'],'value_json':json.dumps(item)}],'rationale':'Metadata correction only; producer ambiguity remains open'}
            elif p['original_task']=='graph_patch':
                assert p['active_diagnostics'][0]['object_ids'][0]=='background'
                objects=p['related_context']['objects'];old=next(o for o in objects if o['id']=='background')
                parts=[]
                for symbol,a,z in [('level',3,4),('epoch',5,6)]:
                    b=copy.deepcopy(old);b.update(id='background_'+symbol,symbol=symbol,start_line=a,end_line=z,anchor=None);parts.append(b)
                path=p['repair_targets'][0]['path'].rsplit('/',1)[0]
                response={'binding_splits':[{'path':path,'bindings':parts,'rationale':'Preserve both adjacent helpers, no behavior deletion'}],'rationale':'Split only the unaccepted location representation'}
            else:raise AssertionError(p['original_task'])
            directory.mkdir(parents=True,exist_ok=True);(directory/'prompt.txt').write_text(prompt)
            write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
            check=runner.run([sys.executable,'-c','print("Controlled repair responder")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
            return check,response_type.model_validate(response)
        check,typed=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
        response=typed.model_dump(mode='json')
        if response_type.__name__=='ReviewReply' and not self.bad_review:
            item=next((i for i in response['items'] if i['target_id']==p.get('selected_unit',{}).get('id')),None)
            if item:
                self.bad_review=True;item.update(aspect='checker_correspondence',status='disputed',rationale='The consumer boundary is grounded; the unseen producer still requires source inspection',limitations=['Upstream context is not yet explained'])
        if response_type.__name__=='GraphPatch':
            b=copy.deepcopy(response['bindings'][0]);b.update(id='background',symbol='level',start_line=3,end_line=6,anchor=None,description='Actual helper definitions used to produce the input',pending=['No independent helper guarantee is proven'])
            b['associations']=[{**copy.deepcopy(b['associations'][0]),'claim_id':'step_obligation'}]
            response['bindings'].append(b);u=response['units'][0];u['binding_ids'].append('background')
        write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
        return check,response_type.model_validate(response)


@pytest.mark.real
def test_negative_review_cached_context_new_dependencies_split_scope_and_tlc(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc)
    (repo/'upstream_support.py').write_text('def input_limit(requested):\n    return requested if requested > epoch() else level()\ndef level():\n    return 3\ndef epoch():\n    return 0\n')
    # Keep the existing actual function name consumed by the harness.
    original=prepared[0]/'limits.py';symbol=original.read_text().split('def ')[1].split('(')[0]
    file=repo/'upstream_support.py';file.write_text(file.read_text().replace('def input_limit(requested):','def '+symbol+'(requested):'))
    data=copy.deepcopy(args[1].data)
    data[3]['requests'][0]['end_line']=6
    data[4]['bindings'][0]['material_id']='upstream_support.py:1:6'
    if data[4]['bindings'][0].get('anchor'):data[4]['bindings'][0]['anchor']['material_id']='upstream_support.py:1:6'
    for assoc in data[4]['bindings'][0].get('associations',[]):assoc['source_ids']=['upstream_support.py:1:6']
    # The original responder's scope references use the acquired full source identity.
    class Agent(RepairingScopeAgent):
        def analyze(self,*a,**kw):
            check,response=super().analyze(*a,**kw)
            if type(response).__name__=='GraphPatch':
                for edge in response.relations:edge.grounding.behavior_ids=[x.replace('upstream_support.py:1:2','upstream_support.py:1:6') for x in edge.grounding.behavior_ids]
            return check,response
    args=(args[0],Agent(data),args[2],args[3],args[4]);cfg.budget.targeted_reads=2
    state=Engine(cfg,root,*args).start(repo)
    assert state.models,state.stop_reason
    assert state.units[0].obligation_ids==['step_obligation']
    assert 'background_level' in state.models[0].binding_ids and 'background_epoch' in state.models[0].binding_ids
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks),state.stop_reason
    assert any(c.action=='experiment' and c.outcome=='tests_passed' for c in state.checks)
    assert any(c.status=='compatible' for c in state.calibrations)
    assert any(i.explanation.startswith('The consumer boundary') for i in state.review_issues)
    assert state.usage['targeted_reads']==1 and state.usage['agent_calls']<=20
    assert any(p['items'] and all(i['status']=='cached' for i in p['items']) for p in state.read_plans.values())
    assert any(s['status']=='accepted' and s['task']=='graph_patch' for s in state.repair_sessions.values())
