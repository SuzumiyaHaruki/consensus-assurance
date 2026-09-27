import copy
import json
import shutil
from pathlib import Path
import pytest
from ack_support import ROOT, setup_ack
from consensus_assurance.core.types import Finding, Investigation, ExecutionStatus, Origin
from consensus_assurance.core.proposals import Comparison
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.observations import monitor_events
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
