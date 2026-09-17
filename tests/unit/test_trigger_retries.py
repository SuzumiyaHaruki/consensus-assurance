"""Actual controller retries incomplete tool results, never completed unreachability."""
import pytest
from consensus_assurance.core.types import CheckRun,ReachabilityResult
from consensus_assurance.core.proposals import ReachabilityRequirement
from consensus_assurance.workflow.artifacts import save_bundle
from test_graph_mutations import controller


def setup(tmp_path,prepared):
    _,state,bundle,_=prepared;e=controller(tmp_path,state)
    import re
    bundle.behavior=re.sub(r'=+\s*$', 'Used == value = 1\n====\n',bundle.behavior)
    bundle.reachability=[ReachabilityRequirement(id='used',operator='Used',claim_ids=[state.units[0].obligation_ids[0]],description='Exercise an increment')]
    model=save_bundle(e.root,state,state.units[0],bundle,e.implementation)
    e.state.active_model_id=model.id;e.state.active_unit_id=model.unit_id
    return e,model,bundle


def result(model,req,status='unknown'):
    check=CheckRun(action='reachability',cwd='synthetic',snapshot_id=model.snapshot_id,model_id=model.id,status='timeout' if status=='unknown' else 'completed',outcome='unknown' if status=='unknown' else 'holds',reason='Controlled tool interruption' if status=='unknown' else 'Controlled completed search')
    reach=ReachabilityResult(model_id=model.id,requirement_id=req.id,check_id=check.id,status=status,search_fingerprint=model.search_fingerprint,reason=check.reason)
    return reach,check


@pytest.mark.parametrize('terminal',['reachable','unreachable','unknown'])
def test_unknown_has_bounded_retry_and_preserves_attempts(tmp_path,prepared,terminal):
    e,m,b=setup(tmp_path,prepared);calls=[]
    def run(runner,model,bundle,req,timeout):
        calls.append(1);return result(model,req,'unknown' if len(calls)==1 else terminal)
    e.verifier.reachability=run;e.check_triggers(m,b)
    assert len(calls)==2 and len(e.state.reachability_results)==2
    assert e.state.reachability_results[-1].status==terminal
    e.check_triggers(m,b);assert len(calls)==2
    assert e.state.trigger_retry_tasks[0]['status']==('blocked' if terminal=='unknown' else terminal)


def test_completed_unreachable_is_not_retried_and_new_input_is_not_reused(tmp_path,prepared):
    e,m,b=setup(tmp_path,prepared);req=b.reachability[0]
    reach,check=result(m,req,'unreachable');e.state.reachability_results.append(reach);e.record(check)
    calls=[]
    def run(*args):calls.append(1);return result(m,req,'reachable')
    e.verifier.reachability=run;e.check_triggers(m,b);assert not calls
    m.search_fingerprint='changed-input-for-controller-test';e.check_triggers(m,b);assert len(calls)==1


@pytest.mark.real
def test_controlled_timeout_then_actual_tlc_witness(tmp_path,prepared,tlc):
    e,m,b=setup(tmp_path,prepared);verifier,_=tlc;actual=verifier.reachability;calls=[]
    def run(runner,model,bundle,req,timeout):
        calls.append(1)
        return result(model,req) if len(calls)==1 else actual(runner,model,bundle,req,timeout)
    e.verifier=verifier;verifier.reachability=run
    e.check_triggers(m,b)
    assert [r.status for r in e.state.reachability_results]==['unknown','reachable']
    assert e.state.checks[-1].command and e.state.checks[-1].action=='reachability'


def test_trigger_result_checkpoint_keeps_attempt_and_does_not_reexecute(tmp_path,prepared):
    from consensus_assurance.adapters.storage.files import Store
    from consensus_assurance.workflow.budget import BudgetTracker
    e,m,b=setup(tmp_path,prepared);calls=[];base=e.checkpoint
    def checkpoint(event):
        base(event)
        if event=='execution_recorded':raise RuntimeError('Interrupted after result and receipt')
    e.checkpoint=checkpoint
    def run(*args):calls.append(1);return result(m,b.reachability[0],'reachable')
    e.verifier.reachability=run
    with pytest.raises(RuntimeError):e.check_triggers(m,b)
    e.state=Store(e.root).load();e.budget=BudgetTracker(e.config.budget,e.state);e.checkpoint=base
    e.check_triggers(m,b)
    assert len(calls)==1 and len(e.state.trigger_retry_tasks[0]['attempts'])==1
    assert e.state.trigger_retry_tasks[0]['status']=='reachable'
