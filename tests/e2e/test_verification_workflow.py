import copy
import json
import os
import shutil
from pathlib import Path
import pytest
from regression_support import fixture_config as Config
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.files import Store

ROOT=Path(__file__).resolve().parents[2]


def deferred_fixture(tmp_path, responses):
    repo=tmp_path/'deferred-repo'
    shutil.copytree(ROOT/'examples/toy_protocol',repo)
    (repo/'limits.py').rename(repo/'upstream_support.py')
    for i in range(10): (repo/f'guide{i}.py').write_text('# Supplemental independent source sample.\n')
    first=copy.deepcopy(responses[0]);first['requests']=[q for q in first['requests'] if q['file']!='limits.py']
    graph=copy.deepcopy(responses[1])
    graph['bindings']=[b for b in graph['bindings'] if b['id']!='input_binding']
    graph['relations']=[e for e in graph['relations'] if e['id']!='maps_input']
    read={'requests':[{'file':'upstream_support.py','start_line':1,'end_line':2,'reason':'Read actual producer of the unexplained boundary'}],'rationale':'Consumer needs a positive effective capacity','related_ids':['step_obligation'],'gap':'Input producer not yet read'}
    binding=copy.deepcopy(responses[1]['bindings'][1]);binding['material_id']='upstream_support.py:1:2'
    edge=next(copy.deepcopy(e) for e in responses[1]['relations'] if e['id']=='maps_input')
    edge['grounding']['behavior_ids']=['upstream_support.py:1:2']
    patch={'bindings':[binding],'relations':[edge],'rationale':'Actual new producer code explains the dependency without changing the obligation'}
    expanded=copy.deepcopy(responses[3]);expanded['harness']['source']=expanded['harness']['source'].replace('from limits import','from upstream_support import')
    for constraint in expanded['constraints']:
        constraint['source_ids']=[id.replace('limits.py:', 'upstream_support.py:') for id in constraint['source_ids']]
    fixture=tmp_path/'responses.json'
    fixture.write_text(json.dumps([first,graph,responses[2],read,patch,expanded]))
    return repo,fixture


@pytest.mark.real
def test_F3_reads_new_producer_then_generates_and_checks_new_scope(tmp_path,tlc,prepared):
    repo,fixture=deferred_fixture(tmp_path,prepared[3])
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),tlc_jar=os.environ['TLC_JAR'])
    config.budget.audit_units=3
    root=tmp_path/'audit'
    state=Engine(config,root,*assemble(config)).start(repo)
    assert state.stop_reason.startswith('No pending'),state.stop_reason
    assert len(state.models)==2
    initial=json.loads(Path(state.discovery_path).read_text())
    assert all(b['id']!='input_binding' for b in initial['bindings'])
    read=next(h for h in state.reading_history if h['related_ids']==['step_obligation'])
    assert read['added_material_ids']==['upstream_support.py:1:2']
    assert read['related_ids']==['step_obligation']
    assert state.models[0].binding_ids==['step_binding']
    assert set(state.models[1].binding_ids)=={'step_binding','input_binding'}
    assert all(c.status=='compatible' for c in state.calibrations)
    assert state.calibrations[0].applicability=='historical_scope'
    assert any('Included producer' in s for s in state.units[0].boundary_changes)
    assert all(not e.confirmed for e in state.relations if e.kind=='boundary')
    assert [c.outcome for c in state.checks if c.action=='model_check']==['holds','holds']


@pytest.mark.real
@pytest.mark.parametrize('event',['action_started','action_result_saved'])
def test_interrupted_experiment_resumes_same_model_and_action(tmp_path,tlc,prepared,event):
    repo,fixture=deferred_fixture(tmp_path,prepared[3])
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),tlc_jar=os.environ['TLC_JAR'])
    config.budget.audit_units=3;config.budget.experiments=5
    root=tmp_path/'resume'
    class Interrupted(Engine):
        interrupted=False
        def checkpoint(self,name):
            super().checkpoint(name)
            if not self.interrupted and name==event and self.state.pending_action and self.state.pending_action.kind=='experiment':
                self.interrupted=True
                raise RuntimeError('Simulated controller interruption')
    with pytest.raises(RuntimeError): Interrupted(config,root,*assemble(config)).start(repo)
    before=Store(root).load()
    assert before.next_action=='experiment' and before.active_model_id
    state=Engine(config,root,*assemble(config)).resume()
    assert state.stop_reason.startswith('No pending'),state.stop_reason
    assert len(state.models)==2 and state.models[0].id==before.active_model_id
    assert len([c for c in state.checks if c.action=='experiment'])==2
    if event=='action_started':
        assert any(a.status=='outcome_unknown' for a in state.action_history)


def test_experiments_false_prevents_probes_and_replay(tmp_path,prepared):
    from consensus_assurance.core.proposals import Bundle
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.workflow.engine import Blocked
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    repo=prepared[0]
    config=Config(implementation='toy',agent_backend='mock',allow_experiments=False)
    root=tmp_path/'disabled'
    engine=Engine(config,root,*assemble(config))
    state=engine.start(repo)
    assert not any(c.action in {'capability_probe','experiment','replay'} for c in state.checks)
    assert not (root/'experiments').exists()
    assert state.capabilities[0].status=='unavailable'
    model=save_bundle(root,prepared[1],prepared[1].units[0],prepared[2],ToyImplementation())
    with pytest.raises(Blocked,match='disabled'): engine.experiment(model,prepared[2],replay=True)


@pytest.mark.real
def test_compilation_failure_gets_actual_log_and_finite_repair(tmp_path,tlc,prepared):
    responses=copy.deepcopy(prepared[3])
    responses[1]['relations']=[e for e in responses[1]['relations'] if e['id']!='input_dependency']
    responses[1]['units'][0]['relation_ids'].remove('input_dependency')
    original=copy.deepcopy(responses[2]);broken=copy.deepcopy(original)
    broken['harness']['source']='import missing_round2_fixture_module\n'
    fixture=tmp_path/'compile.json';fixture.write_text(json.dumps([responses[0],responses[1],broken,original]))
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),tlc_jar=os.environ['TLC_JAR'])
    # Python runtime import failure is an executable harness error, never F1-F4.
    class Adapter(type(assemble(config)[0])):
        def parse_test_result(self,check,text):
            super().parse_test_result(check,text)
            if 'ModuleNotFoundError' in text:
                check.status=ExecutionStatus.ERROR;check.reason='Harness import error'
    impl,agent,verifier,knowledge=assemble(config)
    root=tmp_path/'compile'
    state=Engine(config,root,Adapter(),agent,verifier,knowledge).start(prepared[0])
    assert state.stop_reason.startswith('No pending'),state.stop_reason
    prompts=list((root/'agent').glob('*-technical/prompt.txt'))
    assert len(prompts)==1
    assert 'ModuleNotFoundError' in prompts[0].read_text() and 'missing_round2_fixture_module' in prompts[0].read_text()
    assert len(state.models)==2 and not state.revisions
    assert [c.status for c in state.checks if c.action=='experiment']==[ExecutionStatus.ERROR,ExecutionStatus.COMPLETED]


@pytest.mark.real
@pytest.mark.parametrize('interrupt_plan',[False,True])
def test_initial_replay_then_F4_and_attribution_continue(tmp_path,tlc,interrupt_plan):
    from ack_support import ROOT as TESTS, setup_ack
    from consensus_assurance.core.proposals import Discovery, ClaimDraft, BindingDraft, RelationDraft, UnitDraft, ReplayPlan, Feedback
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.core.types import Claim, Grounding
    repo=tmp_path/'ack-repo';shutil.copytree(TESTS/'fixtures/ack_service',repo)
    source_state,unit,bundle=setup_ack(repo)
    bundle.checkers=[bundle.checkers[1]]
    obligation=source_state.claims[1]
    basis=obligation.grounding
    goal=obligation.model_copy(update={'id':'ack_goal','kind':'goal','description':'Returned operations satisfy the selected configuration guarantee'})
    claims=[ClaimDraft(**{k:v for k,v in c.model_dump().items() if k in ClaimDraft.model_fields}) for c in [goal,obligation]]
    code=source_state.materials[0]
    import ast
    declaration=next(n for n in ast.parse(code.text).body if isinstance(n,ast.FunctionDef) and n.name=='execute')
    binding=BindingDraft(id='ack-code',claim_id='durable',material_id=code.id,symbol='execute',start_line=declaration.lineno,end_line=declaration.end_lineno,description='Actual acceptance and return ordering',pending=[])
    edge=RelationDraft(id='supports_ack',source='ack_goal',target='durable',kind='depends_all',group=None,rationale='Return guarantee depends on the configured durability responsibility',pending=[],grounding=basis)
    u=UnitDraft(id='ack',goal_ids=['ack_goal'],obligation_ids=['durable'],binding_ids=['ack-code'],relation_ids=['supports_ack'],scope=unit.scope,rationale='Fixture candidate selection',goal_observable=False)
    graph=Discovery(understanding='Controlled fixture',claims=claims,bindings=[binding],relations=[edge],units=[u],conflicts=[],unexplored=[],selection_rationale='Check the configured response responsibility')
    missed=bundle.harness.model_copy(deep=True)
    missed.prerequisites[0].event='not_observed_setup'
    replay=ReplayPlan(harness=missed,checker_id='DurableAck',rationale='Initial candidate experiment with an unmet prerequisite')
    corrected=bundle.model_copy(deep=True)
    fix=Feedback(kind='F4',rationale='The requested setup event never occurred; correlate the actual acceptance and response',evidence_ids=['placeholder'],target_ids=['placeholder'],relation_ids=[],new_basis='',graph=None,bundle=corrected)
    unresolved=Feedback(kind='unresolved',rationale='Explicit mock cannot confirm implementation correctness',evidence_ids=[],target_ids=[],relation_ids=[],new_basis='',graph=None,bundle=None)
    fixture=tmp_path/'replay-responses.json'
    fixture.write_text(json.dumps([{'requests':[],'rationale':'Initial files contain the complete fixture'},graph.model_dump(mode='json'),bundle.model_dump(mode='json'),replay.model_dump(mode='json'),fix.model_dump(mode='json'),unresolved.model_dump(mode='json')]))
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),tlc_jar=os.environ['TLC_JAR'])
    config.budget.replays=2;config.budget.experiments=4
    class CorrelatedMock(MockAgent):
        def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
            check,response=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
            if response_type is Feedback and response and response.kind=='F4':
                context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
                response.evidence_ids=[context['experiment']['check_id']]
                response.target_ids=[context['model_id']]
            return check,response
    impl,_,verifier,knowledge=assemble(config)
    root=tmp_path/'replay-audit'
    class Interrupted(Engine):
        interrupted=False
        def checkpoint(self,event):
            super().checkpoint(event)
            if interrupt_plan and not self.interrupted and event=='action_result_saved' and self.state.pending_action and self.state.pending_action.kind=='agent:replay':
                self.interrupted=True;raise RuntimeError('Interrupted after saving replay plan')
    engine=Interrupted(config,root,impl,CorrelatedMock(fixture),verifier,knowledge)
    if interrupt_plan:
        with pytest.raises(RuntimeError): engine.start(repo)
        before=Store(root).load()
        assert before.active_finding_id and before.next_action=='replay_plan'
        engine=Engine(config,root,impl,CorrelatedMock(fixture),verifier,knowledge)
        state=engine.resume()
    else: state=engine.start(repo)
    assert state.stop_reason.startswith('No pending'),state.stop_reason
    assert len([c for c in state.checks if c.action=='replay'])==2
    assert [r.kind for r in state.revisions]==['F4']
    assert [r['prerequisites']['status'] for r in state.monitor_results]==['not_reached','matched']
    assert state.monitor_results[-1]['properties'][0]['outcome']=='violated'
    assert not state.monitor_results[-1]['confirmed']  # Fixture agent provenance remains mock.
    assert all(e.applicability=='current' for e in state.evidence)
    assert any(p.name.endswith('-diagnose') for p in (root/'agent').iterdir())


@pytest.mark.real
def test_model_files_written_before_state_checkpoint_resume_same_generation(tmp_path,tlc,prepared):
    repo,fixture=deferred_fixture(tmp_path,prepared[3])
    config=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),tlc_jar=os.environ['TLC_JAR'])
    config.budget.audit_units=3
    root=tmp_path/'model-commit-resume'
    class Interrupted(Engine):
        crashed=False
        def model_commit_hook(self,model):
            self.crashed=True
            raise RuntimeError('Model files complete; state still references generation action')
        def checkpoint(self,event):
            if not self.crashed:
                super().checkpoint(event)
    with pytest.raises(RuntimeError):
        Interrupted(config,root,*assemble(config)).start(repo)
    before=Store(root).load()
    assert not before.models and (root/'models/v1/commit.json').exists()
    commit=json.loads((root/'models/v1/commit.json').read_text())
    calls=before.usage['agent_calls']
    state=Engine(config,root,*assemble(config)).resume()
    assert state.stop_reason.startswith('No pending'),state.stop_reason
    assert state.models[0].id==commit['model']['id']
    assert len([m for m in state.models if m.version==1])==1
    assert state.usage['agent_calls']==calls+3
    prompts=[p.read_text() for p in (root/'agent').glob('*/prompt.txt')]
    assert any('scope_delta' in p and 'Split actions at actual interruptible boundaries' in p and 'Use MODULE Behavior' in p for p in prompts)
