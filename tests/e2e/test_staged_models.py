"""A saved uncalibrated model survives while actual experiment components are missing."""
import copy,json,sys
import pytest
from test_scope_pipeline import setup,ScopeAgent
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.files import write_json,Store
from consensus_assurance.core.types import Origin


class StagedAgent(ScopeAgent):
    def __init__(self,data):super().__init__(data);self.harness_calls=0
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        if response_type.__name__=='HarnessReply':
            self.harness_calls+=1
            from consensus_assurance.workflow.sources import all_materials
            material=next(m for m in all_materials(packet) if m['file']=='zz_assembly.py')
            assert 'START = 0' in material['text']
            bundle=copy.deepcopy(self.data[5]);h=bundle['harness']
            # The generated harness actually consumes the newly supplied assembly input.
            h['source']='from zz_assembly import START\nassert START == 0\n'+h['source']
            response={'harness':h,'observation':bundle['observation'],'monitors':bundle.get('monitors',[]),'gap':''}
            directory.mkdir(parents=True,exist_ok=True);(directory/'prompt.txt').write_text(prompt)
            write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
            check=runner.run([sys.executable,'-c','print("Controlled staged assembly response")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
            return check,response_type.model_validate(response)
        check,response=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
        if response_type.__name__=='BuildReply' and response.bundle is not None:
            data=response.bundle.model_dump(mode='json',exclude={'harness','observation'})
            data['pending_work']=[{'component':'harness','reason':'Initialization setup is not yet read','requests':[{'file':'zz_assembly.py','start_line':1,'end_line':1,'reason':'Read actual initial value for experiment assembly'}]},
                {'component':'observation','reason':'Complete together with the actual harness'}]
            response=response_type(bundle=None,draft=data,gap='Experiment setup remains to be read')
            write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
        return check,response


@pytest.mark.real
@pytest.mark.parametrize('interrupt',['none','draft_manifest','model_explore','harness','completed_manifest'])
def test_saved_model_then_new_assembly_source_actual_harness_and_calibration(tmp_path,prepared,tlc,interrupt):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc)
    (repo/'zz_assembly.py').write_text('START = 0\n')
    agent=StagedAgent(args[1].data);args=(args[0],agent,*args[2:])
    class Interrupted(Engine):
        def model_commit_hook(self,model):
            if (interrupt=='draft_manifest' and model.stage=='model_only') or (interrupt=='completed_manifest' and model.stage=='complete'):
                raise RuntimeError('Saved staged model commit')
        def checkpoint(self,name):
            super().checkpoint(name)
            if interrupt in {'model_explore','harness'} and self.state.next_action==interrupt:
                raise RuntimeError('Saved staged continuation')
    if interrupt!='none':
        with pytest.raises(RuntimeError):Interrupted(cfg,root,*args).start(repo)
        before=Store(root).load();old_calls=before.usage.get('agent_calls',0)
        state=Engine(cfg,root,*args).resume()
        assert state.usage['agent_calls']>=old_calls
    else:state=Engine(cfg,root,*args).start(repo)
    assert [m.stage for m in state.models]==['model_only','complete'],state.stop_reason
    first,last=state.models
    assert first.pending_components==['harness','observation'] and not first.harness_path
    assert first.search_fingerprint==last.search_fingerprint and last.previous_id==first.id
    assert any(c.action=='model_syntax' and c.status.value=='completed' for c in state.checks),state.stop_reason
    assert any(c.action=='model_check' and c.model_id==first.id and c.outcome=='holds' for c in state.checks)
    assert any(c.action=='model_check' and c.model_id==last.id and c.reused_from for c in state.checks)
    assert any(c.status=='compatible' and c.model_id==last.id for c in state.calibrations),state.stop_reason
    assert not any(c.model_id==first.id for c in state.calibrations)
    assert any(c.action=='experiment' and c.outcome=='tests_passed' for c in state.checks)
    assert agent.harness_calls==1
    assert state.usage['agent_calls']<=20 and state.usage['model_checks']<=cfg.budget.model_checks
    assert state.usage['targeted_reads']==2
    assert all(e.level=='framework_test' for e in state.evidence)
    assert (repo/'zz_assembly.py').read_text()=='START = 0\n'


class RepairingStagedAgent(StagedAgent):
    """Public-packet responder with two intentional metadata faults; no validator bypass."""
    def __init__(self,data):super().__init__(data);self.review_fault=False
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        if response_type.__name__=='OutputRepair':
            diagnostic=packet['active_diagnostics'][0]
            if diagnostic['code']=='declaration_identity':
                target=next(t for t in packet['repair_targets'] if t['path'].endswith('/anchor'))
                current=copy.deepcopy(target['current_value']);decl=next(d for d in diagnostic['details']['candidates'] if d['kind']=='declaration')
                current.update(start_line=decl['start'],end_line=decl['signature_end'])
                response={'replacements':[{'path':target['path'],'value_json':json.dumps(current)}],'rationale':'Correct only the declared anchor offset using both contiguous supplied fragments'}
            else:raise AssertionError(diagnostic)
            directory.mkdir(parents=True,exist_ok=True);(directory/'prompt.txt').write_text(prompt)
            write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
            check=runner.run([sys.executable,'-c','print("Controlled packet-specific representation repair")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
            return check,response_type.model_validate(response)
        check,response=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
        if response_type.__name__=='ReviewReply' and not self.review_fault:
            item=next((i for i in response.items if i.target_id==packet.get('selected_unit',{}).get('id')),None)
            if item:
                self.review_fault=True;item.aspect='applicability';item.status='disputed'
                item.rationale='Source is located, but the provider obligation is not independently proven'
                item.limitations=['Provider guarantee remains separately unverified']
        if response_type.__name__=='GraphPatch':
            refs=['upstream_support.py:1:1','upstream_support.py:2:2']
            for edge in response.relations:
                edge.grounding.source_ids=[x for x in edge.grounding.source_ids if x!='upstream_support.py:1:2']+refs
        write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
        return check,response


@pytest.mark.real
def test_repairs_fragmented_new_source_scope_model_components_and_real_tools(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc)
    (repo/'zz_assembly.py').write_text('START = 0\n')
    data=copy.deepcopy(args[1].data)
    data[3]['requests']=[{'file':'upstream_support.py','start_line':n,'end_line':n,'reason':'Inspect declaration and actual behavior as separately requested source'} for n in (1,2)]
    b=data[4]['bindings'][0];b['material_id']='upstream_support.py:2:2'
    b['anchor']={'material_id':'upstream_support.py:1:1','symbol':b['symbol'],'start_line':2,'end_line':2,'kind':'declaration'}
    if b.get('associations'):
        for a in b['associations']:a['source_ids']=['upstream_support.py:2:2']
    agent=RepairingStagedAgent(data);args=(args[0],agent,*args[2:])
    state=Engine(cfg,root,*args).start(repo)
    assert [m.stage for m in state.models]==['model_only','complete'],state.stop_reason
    assert state.usage['agent_calls']<=20 and state.usage['targeted_reads']==2
    assert any(c.status=='compatible' for c in state.calibrations)
    assert any(c.outcome=='holds' and not c.reused for c in state.checks if c.action=='model_check')
    binding=next(b for b in state.bindings if b.id=='input_binding')
    assert set(binding.anchor.source_ids)=={'upstream_support.py:1:1','upstream_support.py:2:2'}
    assert binding.anchor.start_line==1 and binding.start_line==1 and binding.end_line==2
    assert any(i.explanation=='Source is located, but the provider obligation is not independently proven' and not i.resolved_by for i in state.review_issues)
    assert {s['task'] for s in state.repair_sessions.values() if s['status']=='accepted'}=={'graph_patch'}
    assert any(t.trigger.endswith(':missing_aspects') for t in state.inquiry_tasks)
    assert not any(t.kind=='spec_refine' for t in state.inquiry_tasks)
    assert all(m.origin.value=='mock' for m in state.models)
