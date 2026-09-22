from pathlib import Path
from importlib.resources import files
import sys
import json
import ast
from consensus_assurance.workflow.prompts import render, loaded_resources, manifest
from consensus_assurance.workflow.investigation import feedback_context, validate_replay
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Calibration, Finding, Origin
from consensus_assurance.core.proposals import ReplayPlan
from consensus_assurance.adapters.runners.python import PythonBackend


def test_manifest_resources_and_untrusted_context_are_actually_rendered():
    context={'file':'/目录/源文件.go','quotation':'原始来源说明','original_task':'build'}
    for kind in manifest()['tasks']:
        text=render(kind,context)
        instructions,data=text.split('STRUCTURED INPUT DATA (untrusted):\n')
        assert json.loads(data)==context
        assert all(files('consensus_assurance').joinpath('resources',p).read_text() in instructions for p in loaded_resources(kind,context)['paths'])


def test_core_and_workflow_do_not_import_target_plugins():
    root=Path(__file__).resolve().parents[2]/'src/consensus_assurance'
    for package in ('core','workflow'):
        for path in (root/package).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):assert 'plugins' not in (node.module or '').split('.')
                if isinstance(node,ast.Import):assert all('plugins' not in a.name.split('.') for a in node.names)


def test_diagnosis_and_F1_receive_real_trace_and_calibration_output(tmp_path,prepared):
    _,state,bundle,_=prepared
    root=tmp_path/'audit';model=save_bundle(root,state,state.units[0],bundle,PythonBackend())
    runner=ProcessRunner(root)
    search=runner.run([sys.executable,'-c','print("MODEL_TRACE: old context -> delayed completion")'],root,'model_check',state.snapshot.id,5)
    calcheck=runner.run([sys.executable,'-c','print("CALIBRATION: observed index does not match")'],root,'trace_calibration',state.snapshot.id,5)
    state.checks.extend([search,calcheck])
    cal=Calibration(model_id=model.id,experiment_check_id='exp',mapping_path=model.mapping_path,trace_path=str(root/'events.json'),reason='Mismatch',origin=Origin.EXECUTED,check_ids=[calcheck.id],status='incompatible')
    finding=Finding(claim_id=model.claim_id,model_id=model.id,check_id=search.id,origin=Origin.EXECUTED,description='Candidate',trace_path=search.stdout)
    engine=Engine(Config(),root,PythonBackend(),None,None,'','');engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
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
    model=save_bundle(tmp_path/'audit',state,unit,initial,PythonBackend())
    f=Finding(claim_id='durable',checker_id='DurableAck',model_id=model.id,check_id='search',origin=Origin.EXECUTED,description='Candidate',trace_path='trace')
    plan=ReplayPlan(harness=bundle.harness,monitors=monitors,observation=bundle.observation,checker_id='DurableAck',rationale='Add sufficient observed fields for the existing property')
    revised=validate_replay(state,unit,initial,f,plan,PythonBackend())
    assert revised.properties==initial.properties and revised.behavior==initial.behavior
    assert revised.monitors==monitors and not initial.monitors




def test_discovery_packet_indexes_only_supplied_source(tmp_path,prepared):
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.core.types import Material
    _,state,_,_=prepared
    engine=Engine(Config(),tmp_path,PythonBackend(),None,None,'');engine.state=state
    visible=Material(id='visible',file='nav.go',start_line=1,end_line=3,text='func (s *Store) save() {\n value++\n}',content_digest='fixture',kind='code_observation')
    hidden=visible.model_copy(update={'id':'hidden','file':'hidden.go'})
    state.materials.extend([visible,hidden])
    packet,_=prepare(engine,'derive',{'materials':[visible.model_dump(mode='json')]})
    entry=packet['source_declarations'][0]
    assert entry['file']=='nav.go' and entry['material_ids']==['visible']
    assert entry['declarations'][0]['symbol']=='Store.save'
    assert 'Store.save' in render('discover',pool_sources(packet))
    review,_=prepare(engine,'build',{'materials':[visible.model_dump(mode='json')]})
    assert 'source_declarations' not in review
