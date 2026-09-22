"""Actual TLC witnesses, contract alternatives and bounded consequence dispositions."""
import json
import shutil
import pytest
from consensus_assurance.core.types import ReachabilityRequirement, AuditQuestion, Claim, Finding, Origin, QuestionCandidate
from consensus_assurance.workflow.artifacts import save_bundle,validate_bundle
from consensus_assurance.workflow.modeling import obligation_progress,coverage_limitations
from consensus_assurance.workflow.investigation import record_consequence
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.runners.python import PythonBackend
from ack_support import setup_ack, ROOT


@pytest.mark.real
@pytest.mark.parametrize('predicate,expected', [('value = 1','reachable'),('value = 99','unreachable')])
def test_original_holds_and_actual_trigger_coverage_remain_separate(tlc,prepared,predicate,expected):
    verifier,runner=tlc;_,state,bundle,_=prepared;unit=state.units[0]
    unit.audit_question=AuditQuestion(question='Does the increment respect its input when a support step actually occurs?',importance='The consumer uses the produced bound',source_ids=state.claims[1].source_ids,trigger_rationale='A step must occur to exercise the increment responsibility')
    unit.audit_question=AuditQuestion(question="Is the consumer reachable?",importance="Finite scoped consequence",source_ids=state.claims[1].source_ids,trigger_rationale="Execute the actual trigger",behavior_ids=["use"])
    lines=bundle.behavior.splitlines();lines.insert(-1,'Used == '+predicate);bundle.behavior='\n'.join(lines)+'\n'
    req=ReachabilityRequirement(id='use-trigger',operator='Used',claim_ids=[unit.obligation_ids[0]],behavior_ids=['use'],description='Actual supported step is reachable')
    bundle.reachability=[req]
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    search=verifier.check(runner,model,20);state.checks.append(search)
    assert search.outcome=='holds'
    assert unit.obligation_ids[0] not in obligation_progress(state,unit)[0]
    result,check=verifier.reachability(runner,model,bundle,req,20)
    state.reachability_results.append(result);state.checks.append(check)
    assert result.status==expected,check.reason
    assert (unit.obligation_ids[0] in obligation_progress(state,unit)[0]) is (expected=='reachable')
    assert search.outcome=='holds' and not state.findings
    assert any('calibration' in limitation for limitation in coverage_limitations(state,unit))
    write_json(runner.root/'coverage-result.json',{'fixture':'bounded-support-use','search':search.model_dump(mode='json'),'reachability':result.model_dump(mode='json'),'trigger_check':check.model_dump(mode='json'),'state':state.model_dump(mode='json')})


def test_missing_trigger_or_changed_model_never_counts_as_reached(tmp_path,prepared):
    _,state,bundle,_=prepared;unit=state.units[0]
    bundle.reachability=[ReachabilityRequirement(id='missing',operator='RecoveryEntry',claim_ids=unit.obligation_ids,description='Missing actual recovery behavior')]
    with pytest.raises(ValueError,match='actual named'):validate_bundle(state,unit,bundle,PythonBackend())
    bundle.reachability=[];model=save_bundle(tmp_path,state,unit,bundle,PythonBackend())
    from pathlib import Path
    Path(model.path).write_text(Path(model.path).read_text()+'\n')
    from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
    from consensus_assurance.adapters.runners.process import ProcessRunner
    req=ReachabilityRequirement(id='changed',operator='Init',claim_ids=unit.obligation_ids,description='Recheck changed input')
    result,check=TLCVerifier(None).reachability(ProcessRunner(tmp_path/'runner'),model,bundle,req,10)
    assert result.status=='unknown' and check.status.value=='not_scheduled'




def test_consequence_disposition_is_bounded_and_idempotent(tmp_path,prepared):
    _,state,_,_=prepared;cfg=Config(execution_backend='python',agent_backend='mock')
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'');engine.state=state;engine.budget=BudgetTracker(cfg.budget,state);unit=state.units[0]
    finding=Finding(claim_id=unit.obligation_ids[0],model_id='model',check_id='search',origin=Origin.EXECUTED,description='Controlled evidence linkage only',trace_path='trace',level='implementation_obligation')
    record_consequence(engine,unit,finding)
    record_consequence(engine,unit,finding)
    assert len(state.consequences)==1 and not state.inquiry_tasks and state.consequences[0]['disposition']=='defer'
    assert finding.level=='implementation_obligation'


def test_child_consequence_reuses_existing_parent_without_duplicate_task(tmp_path,prepared):
    _,state,_,_=prepared;cfg=Config(execution_backend='python',agent_backend='mock')
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'');engine.state=state;engine.budget=BudgetTracker(cfg.budget,state);unit=state.units[0]
    q=AuditQuestion(question='Does the broader consumer retain the result?',importance='Consumer safety depends on retained support',
        activity_classes=['A1'],behavior_ids=['use'],fact_ids=['input'],obligation_relation_kind='consumption',trigger_rationale='Inspect the broader consumer')
    parent=QuestionCandidate(question=q,status='paused',stop_reason='A local child tests one necessary discriminator')
    child=QuestionCandidate(question=q,status='escalated',parent_candidate_id=parent.id,obligation_id=unit.obligation_ids[0])
    state.question_candidates=[parent,child]
    finding=Finding(claim_id=unit.obligation_ids[0],model_id='model',check_id='search',origin=Origin.EXECUTED,
        description='Only the child relation was observed',trace_path='trace',level='implementation_obligation')
    record_consequence(engine,unit,finding)
    assert not state.inquiry_tasks and state.consequences[0]['parent_candidate_id']==parent.id


@pytest.mark.parametrize('status',['tool_missing','timeout'])
def test_unfinished_trigger_execution_stays_unknown(tmp_path,prepared,status):
    from consensus_assurance.core.types import CheckRun,ExecutionStatus
    from consensus_assurance.adapters.verifiers.reachability import check_requirement
    from consensus_assurance.adapters.runners.process import ProcessRunner
    _,state,bundle,_=prepared;unit=state.units[0]
    model=save_bundle(tmp_path,state,unit,bundle,PythonBackend())
    req=ReachabilityRequirement(id='missing-tool',operator='Init',claim_ids=unit.obligation_ids,description='Controller failure-path regression')
    class Unavailable:
        def check(self,runner,model,timeout):
            return CheckRun(action='model_check',cwd=str(runner.root),snapshot_id=model.snapshot_id,model_id=model.id,status=ExecutionStatus(status),reason='Explicit simulated failure, no real TLC execution')
    result,check=check_requirement(Unavailable(),ProcessRunner(tmp_path/'runner'),model,bundle,req,1)
    assert result.status=='unknown' and check.status.value==status
