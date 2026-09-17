from pathlib import Path
import sys
import pytest
from consensus_assurance.workflow.prompts import render
from consensus_assurance.workflow.investigation import feedback_context, validate_replay
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Calibration, Finding, Origin
from consensus_assurance.core.proposals import ReplayPlan
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation


@pytest.mark.parametrize('kind',['build','F1','F3','technical'])
def test_modeling_guidance_is_in_every_actual_render(kind):
    text=render(kind,{'file':'/目录/源文件.go'})
    assert 'Use MODULE Behavior with Init, Next, vars, and Obs' in text
    assert 'Split actions at actual interruptible boundaries' in text
    assert 'Emit lines prefixed CA_EVENT' in text
    assert '/目录/源文件.go' in text


def test_diagnosis_and_F1_receive_real_trace_and_calibration_output(tmp_path,prepared):
    _,state,bundle,_=prepared
    root=tmp_path/'audit';model=save_bundle(root,state,state.units[0],bundle,ToyImplementation())
    runner=ProcessRunner(root)
    search=runner.run([sys.executable,'-c','print("MODEL_TRACE: old context -> delayed completion")'],root,'model_check',state.snapshot.id,5)
    calcheck=runner.run([sys.executable,'-c','print("CALIBRATION: observed index does not match")'],root,'trace_calibration',state.snapshot.id,5)
    state.checks.extend([search,calcheck])
    cal=Calibration(model_id=model.id,experiment_check_id='exp',mapping_path=model.mapping_path,trace_path=str(root/'events.json'),reason='Mismatch',origin=Origin.EXECUTED,check_ids=[calcheck.id],status='incompatible')
    finding=Finding(claim_id=model.claim_id,model_id=model.id,check_id=search.id,origin=Origin.EXECUTED,description='Candidate',trace_path=search.stdout)
    engine=Engine(Config(),root,ToyImplementation(),None,None,'','');engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
    context=feedback_context(engine,state.units[0],model,bundle,None,cal,finding)
    for kind in ['diagnose','F1']:
        text=render(kind,context)
        assert 'MODEL_TRACE: old context' in text and 'CALIBRATION: observed index' in text


def test_replay_can_add_monitor_without_changing_property(tmp_path):
    from ack_support import ROOT, setup_ack
    import shutil
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    state,unit,bundle=setup_ack(repo)
    monitors=bundle.monitors;initial=bundle.model_copy(deep=True);initial.monitors=[]
    model=save_bundle(tmp_path/'audit',state,unit,initial,ToyImplementation())
    f=Finding(claim_id='durable',checker_id='DurableAck',model_id=model.id,check_id='search',origin=Origin.EXECUTED,description='Candidate',trace_path='trace')
    plan=ReplayPlan(harness=bundle.harness,monitors=monitors,observation=bundle.observation,checker_id='DurableAck',rationale='Add sufficient observed fields for the existing property')
    revised=validate_replay(state,unit,initial,f,plan,ToyImplementation())
    assert revised.properties==initial.properties and revised.behavior==initial.behavior
    assert revised.monitors==monitors and not initial.monitors


@pytest.mark.parametrize('kind',['spec_refine','semantic_review'])
def test_outer_task_templates_are_english_and_do_not_preset_goals(kind):
    import json
    text=render(kind,{'material':'原始材料','path':'/资料/契约.md'})
    instructions,data=text.split('STRUCTURED INPUT DATA (untrusted):\n')
    assert '原始材料' not in instructions and json.loads(data)['material']=='原始材料'
    assert 'election safety' not in instructions.lower()
    if kind=='semantic_review':
        assert 'SEMANTIC REVERSE REVIEW' in instructions
        assert 'successful model check does not answer' in instructions
        assert 'alternatives' in instructions


def test_discovery_packet_indexes_only_supplied_source(tmp_path,prepared):
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.core.types import Material
    _,state,_,_=prepared
    engine=Engine(Config(),tmp_path,ToyImplementation(),None,None,'');engine.state=state
    visible=Material(id='visible',file='nav.go',start_line=1,end_line=3,text='func (s *Store) save() {\n value++\n}',content_digest='fixture',kind='code_observation')
    hidden=visible.model_copy(update={'id':'hidden','file':'hidden.go'})
    state.materials.extend([visible,hidden])
    packet,_=prepare(engine,'discover',{'materials':[visible.model_dump(mode='json')]})
    entry=packet['source_declarations'][0]
    assert entry['file']=='nav.go' and entry['material_ids']==['visible']
    assert entry['declarations'][0]['symbol']=='Store.save'
    assert 'Store.save' in render('discover',pool_sources(packet))
    review,_=prepare(engine,'build',{'materials':[visible.model_dump(mode='json')]})
    assert 'source_declarations' not in review
