import copy
import json
import shutil
from pathlib import Path
import pytest
from ack_support import ROOT, setup_ack
from consensus_assurance.core.types import Finding, Investigation, ExecutionStatus, Origin
from consensus_assurance.core.proposals import Comparison
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.observations import assess_execution, monitor_events
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events
from consensus_assurance.adapters.runners.python import PythonBackend


@pytest.mark.real
@pytest.mark.parametrize('reversed_order',[False,True])
def test_multiple_invariants_are_attributed_individually(tlc,tmp_path,reversed_order):
    verifier,runner=tlc
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    state,unit,bundle=setup_ack(repo)
    if reversed_order: bundle.checkers.reverse()
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    check=verifier.check(runner,model,20)
    assert check.status==ExecutionStatus.COMPLETED
    assert check.violated_invariant=='DurableAck'
    assert {r.invariant:r.outcome for r in check.checker_results}=={'MemoryAck':'unknown','DurableAck':'violated'}
    # Exercise the workflow attribution, not only the parser.
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.core.config import Config
    from consensus_assurance.adapters.agents.backend import MockAgent
    engine=Engine(Config(),runner.root,PythonBackend(),MockAgent(),verifier,'','')
    engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
    engine.search(unit,model,bundle,None)
    assert [f.claim_id for f in state.findings]==['durable']
    assert [e.claim_id for e in state.evidence]==['durable']


@pytest.mark.real
@pytest.mark.parametrize('mode,partial,confirm,variant',[('memory',False,False,'plain'),('durable',False,True,'plain'),('conflict',False,False,'plain'),('durable',True,False,'plain'),('durable',False,True,'reviewed_observation'),('durable',False,False,'wrong_monitor')])
def test_actual_contract_and_observation_determine_confirmation(tlc,tmp_path,mode,partial,confirm,variant):
    verifier,runner=tlc
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    state,unit,bundle=setup_ack(repo,mode,partial)
    if variant=='wrong_monitor':
        bundle.monitors[0].assertion=Comparison(field='state.accepted',value=False)
    if variant=='reviewed_observation':
        from consensus_assurance.core.proposals import ObservationChange
        line=next(i for i,l in enumerate(bundle.harness.source.splitlines(),1) if "print('CA_EVENT '" in l)
        bundle.harness.semantic_changes=['Add actual event printing']
        bundle.harness.observation_changes=[ObservationChange(change_index=0,start_line=line,end_line=line,binding_ids=['ack-code'],rationale='Only serial event formatting and output in this scoped experiment')]
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    workspace=runner.root/'workspace';shutil.copytree(repo,workspace)
    (workspace/'assurance_generated.py').write_text(bundle.harness.source)
    exp=run_experiment(runner,PythonBackend().experiment_command(),workspace,state.snapshot.id,20,'bwrap')
    exp.model_id=model.id;exp.input_versions=model.artifact_digests
    state.checks.append(exp)
    cal,checks=verifier.calibrate(runner,model,bundle,exp,20)
    assert cal.status=='compatible',cal.reason
    state.calibrations.append(cal);state.checks.extend(checks)
    search=verifier.check(runner,model,20);state.checks.append(search)
    assert search.outcome==('holds' if mode=='memory' else 'counterexample')
    selected='MemoryAck' if mode=='memory' else 'DurableAck'
    finding=Finding(claim_id='memory' if mode=='memory' else 'durable',checker_id=selected,model_id=model.id,check_id=search.id,origin=Origin.EXECUTED,description='Controlled sample candidate',trace_path=search.stdout)
    record=assess_execution(state,model,bundle,exp,cal,finding,extract_events(exp))
    from consensus_assurance.adapters.storage.files import write_json
    write_json(runner.root/'observation-assessment.json',{
        'fixture':'synthetic_acknowledgement_contract','mode':mode,'partial_observation':partial,
        'snapshot':state.snapshot.model_dump(mode='json'),'model':model.model_dump(mode='json'),
        'checks':[c.model_dump(mode='json') for c in state.checks],
        'calibration':cal.model_dump(mode='json'),'events':extract_events(exp),'judgment':record})
    assert record['confirmed'] is confirm,record
    assert (finding.level=='implementation_obligation') is confirm
    if mode=='memory': assert record['properties'][0]['outcome']=='holds'
    if partial: assert record['properties'][0]['outcome']=='unknown'
    if variant=='wrong_monitor': assert any('differs' in x for x in record['properties'][0]['limitations'])
    if confirm:
        # Missing any required association or applicability condition prevents upgrade.
        for missing in ['snapshot','correlation','legality','calibration']:
            e=exp.model_copy(deep=True);b=bundle.model_copy(deep=True);c=cal.model_copy(deep=True)
            if missing=='snapshot': e.snapshot_id='different'
            if missing=='correlation': b.harness.prerequisites[1].conditions[0]=Comparison(field='operation',value='wrong')
            if missing=='legality': b.harness.legality.unresolved=['External store contract unknown']
            if missing=='calibration': c.status='inconclusive'
            assert not assess_execution(state,model,b,e,c,finding,extract_events(e))['confirmed']


@pytest.mark.real
def test_legal_EXCEPT_update_reaches_real_TLC(tlc,prepared):
    verifier,runner=tlc
    _,state,bundle,_=prepared
    bundle.behavior=r'''---------------- MODULE Behavior ----------------
EXTENDS Naturals
VARIABLE slots
vars == <<slots>>
Init == slots = [n \in {1} |-> 0]
Next == /\ slots[1] < 2 /\ slots' = [slots EXCEPT ![1] = @ + 1]
Obs == [value |-> slots[1]]
===================================================
'''
    bundle.properties='---- MODULE Properties ----\nEXTENDS Behavior\nSafe == slots[1] <= 2\n====\n'
    bundle.variables=['slots']
    model=save_bundle(runner.root,state,state.units[0],bundle,PythonBackend())
    result=verifier.check(runner,model,20)
    assert result.outcome=='holds'


@pytest.mark.real
def test_unconfigured_checker_is_never_supported(tlc,tmp_path):
    verifier,runner=tlc
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    state,unit,bundle=setup_ack(repo)
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    cfg=Path(model.config_path);cfg.write_text(cfg.read_text().replace('\nDurableAck\n','\n'))
    result=verifier.check(runner,model,20)
    assert {c.invariant:c.outcome for c in result.checker_results}=={'MemoryAck':'holds','DurableAck':'unknown'}


@pytest.mark.real
def test_deadlock_and_search_constraints_are_not_invariant_results(tlc,prepared):
    verifier,runner=tlc
    _,state,bundle,_=prepared
    bundle.behavior=bundle.behavior.replace('value < 3','value < 2').replace("        \\/ /\\ value = 3 /\\ value' = 0\n",'')
    model=save_bundle(runner.root,state,state.units[0],bundle,PythonBackend())
    cfg=Path(model.config_path);cfg.write_text(cfg.read_text().replace('CHECK_DEADLOCK FALSE','CHECK_DEADLOCK TRUE'))
    result=verifier.check(runner,model,20)
    assert result.status==ExecutionStatus.COMPLETED and result.outcome=='deadlock'
    assert all(c.outcome=='unknown' for c in result.checker_results)
    cfg.write_text(cfg.read_text()+'\nCONSTRAINT HiddenFilter\n')
    blocked=verifier.check(runner,model,20)
    assert blocked.status==ExecutionStatus.NOT_SCHEDULED and 'constraints' in blocked.reason
