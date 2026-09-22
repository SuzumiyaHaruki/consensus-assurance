"""A saved uncalibrated model survives while actual experiment components are missing."""
import copy,json,sys
from pathlib import Path
import pytest
from test_scope_pipeline import setup,ScopeAgent
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.files import write_json
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
            response={'harness':h,'observation':None if self.harness_calls==1 else bundle['observation'],'monitors':bundle.get('monitors',[]),'gap':''}
            if self.harness_calls==2:
                assert packet['previous_reply']['observation'] is None and packet['generation_error']
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
def test_saved_model_then_new_assembly_source_actual_harness_and_calibration(tmp_path,prepared,tlc):
    repo,cfg,args,root=setup(tmp_path,prepared,tlc)
    (repo/'zz_assembly.py').write_text('START = 0\n')
    agent=StagedAgent(args[1].data);args=(args[0],agent,*args[2:])
    state=Engine(cfg,root,*args).start(repo)
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
    assert agent.harness_calls==2
    assert state.usage['agent_calls']<=20 and state.usage['model_checks']<=cfg.budget.model_checks
    assert all(e.level=='framework_test' for e in state.evidence)
    assert (repo/'zz_assembly.py').read_text()=='START = 0\n'


@pytest.mark.real
def test_generation_continues_without_reads_then_real_syntax_repair_and_search(tmp_path,prepared,tlc):
    from consensus_assurance.core.config import Config
    from consensus_assurance.registry import assemble
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.workflow.inquiry import enqueue,wake_changed
    from consensus_assurance.core.types import ReviewIssue
    import shutil
    repo,state,bundle,_=prepared
    cfg=Config(execution_backend='none',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'');engine.state=state
    shutil.copytree(repo,engine.root/'source');original_reads=len(state.read_plans)
    engine.implementation=None;engine.verifier=tlc[0]
    engine.config.execution_backend='none';engine.config.allow_experiments=False
    engine.config.budget.agent_calls=4;engine.config.budget.model_checks=4
    engine.config.budget.semantic_reviews=1
    state.config=engine.config.model_dump(mode='json')
    engine.budget=BudgetTracker(engine.config.budget,state)
    state.completed_steps=['capabilities','materials','understanding','discovery']
    unit=state.units[0];unit.status='selected';state.active_unit_id=unit.id;state.next_action='build'
    state.usage['audit_units']=1
    enqueue(state,'review','An unexecuted result is a limit, not a reason to preempt construction','pending',unit_id=unit.id,target_ids=unit.obligation_ids)
    draft=bundle.model_dump(mode='json',exclude={'harness','observation'})
    draft['pending_work']=[{'component':c,'reason':'Implementation assembly unavailable in this source-only run'} for c in ('harness','observation')]
    unfinished=copy.deepcopy(draft)
    unfinished['pending_work'].append({'component':'behavior','reason':'Source is available; complete the transition composition','requests':[]})
    malformed=copy.deepcopy(unfinished);malformed['properties']='GENERATE_FROM_OBSERVABLE_PROPERTIES'
    malformed['observable_properties']=[{'checker_id':draft['invariants'][0],'kind':'event_assertion',
        'trigger':{'field':'state.active','op':'eq','value':True},'assertion':{'field':'state.value','op':'eq','reference':'state.prior'}}]
    syntax_error=copy.deepcopy(draft);syntax_error['behavior']=draft['behavior'].replace('Next ==','Next == UndefinedTransition \\/ ')
    class Generation(MockAgent):
        def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
            assert response_type.__name__=='BuildReply'
            packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
            if self.cursor in (1,2):
                assert packet['previous_reply']['draft']==self.responses[self.cursor-1]['draft']
                assert packet['generation_error'] and packet['materials']
                assert 'repair_targets' not in packet and not state.models
            if self.cursor==3:
                assert 'Model syntax error' in packet['failure']['reason']
                assert state.usage['agent_calls']==4
            return super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
    engine.agent=Generation()
    engine.agent.responses=[{'bundle':None,'draft':d,'gap':''} for d in (malformed,unfinished,syntax_error,draft)]
    state=engine.execute(probed=True)
    assert state.usage['agent_calls']==4,state.stop_reason
    assert len(state.models)==2 and all(m.stage=='model_only' for m in state.models)
    syntax=[c for c in state.checks if c.action=='model_syntax']
    assert [c.status.value for c in syntax]==['error','completed']
    searches=[c for c in state.checks if c.action=='model_check']
    assert len(searches)==1 and searches[0].outcome in {'holds','counterexample'}
    assert not state.calibrations and not any(c.action=='experiment' for c in state.checks)
    assert 'harness' in state.stop_reason and 'remaining agent calls=0' in state.stop_reason
    session=next(iter(state.repair_sessions.values()))
    assert session['mode']=='check_generation' and session['attempt']==2 and session['status']=='accepted'
    original=json.loads(Path(session['original_path']).read_text())
    assert original['draft']==malformed and len(state.read_plans)==original_reads
    assert not any(e.level.startswith('implementation') for e in state.evidence)
    state.review_issues.append(ReviewIssue(review_id='later',target_id=unit.id,target_version=unit.version,aspect='decomposition',source_ids=[state.materials[0].id],explanation='A later opinion does not assemble an experiment',disposition='blocked',reason='Retain limitation'))
    assert not wake_changed(engine)
