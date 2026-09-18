import copy
import json
from pathlib import Path

import pytest

from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import BuildReply, Feedback, ReadRequest, Comparison, ReplayPlan
from consensus_assurance.core.types import CheckRun, CheckerResult, ExecutionStatus
from consensus_assurance.workflow.artifacts import save_bundle, validate_bundle
from consensus_assurance.workflow.modeling import validate_technical_repair, obligation_progress
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation


def test_technical_repair_cannot_weaken_same_named_property(prepared):
    _,_,bundle,_=prepared
    repaired=bundle.model_copy(deep=True)
    repaired.properties=repaired.properties.replace('value <= 3','TRUE')
    assert repaired.properties != bundle.properties
    assert repaired.checker_specs()==bundle.checker_specs()
    with pytest.raises(ValueError,match='property text'):
        validate_technical_repair(bundle,repaired,'search')
    repaired=bundle.model_copy(deep=True)
    repaired.behavior += '\n'
    validate_technical_repair(bundle,repaired,'search')
    with pytest.raises(ValueError,match='only the harness'):
        validate_technical_repair(bundle,repaired,'experiment')


def test_shared_read_request_types_have_concrete_wire_fields():
    assert BuildReply.model_fields['requests'].annotation == list[ReadRequest]
    assert Feedback.model_fields['requests'].annotation == list[ReadRequest]
    request=ReadRequest(file='producer.rs',start_line=4,end_line=8,reason='Find the input producer')
    assert BuildReply(bundle=None,gap='Producer unknown',requests=[request]).requests[0]==request


def test_pure_bundle_validation_has_no_files_or_state_changes(tmp_path,prepared):
    _,state,bundle,_=prepared
    before=state.model_dump(); files_before=set(tmp_path.rglob("*"))
    bad=bundle.model_copy(deep=True);bad.behavior=bad.behavior.replace('Init ==','MissingInit ==')
    with pytest.raises(ValueError,match='missing Init'):
        validate_bundle(state,state.units[0],bad,ToyImplementation())
    assert set(tmp_path.rglob("*"))==files_before and state.model_dump()==before


def test_unchecked_obligation_remains_partial_and_schedulable(tmp_path,prepared):
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.workflow.graph import select_unit
    _,state,bundle,_=prepared
    unit=state.units[0]
    unit.obligation_ids.append('input_obligation')
    model=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    spec=model.checkers[0]
    check=CheckRun(action='model_check',status=ExecutionStatus.COMPLETED,outcome='holds',cwd=str(tmp_path),snapshot_id=state.snapshot.id,model_id=model.id,search_fingerprint=model.search_fingerprint,checker_results=[CheckerResult(invariant=spec.invariant,claim_id=spec.claim_id,scope=spec.scope,outcome='holds')])
    state.checks.append(check)
    engine=Engine(Config(),tmp_path,ToyImplementation(),None,None,'','')
    engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
    engine.finish_unit(unit)
    assert unit.status=='partial'
    assert unit.remaining_obligation_ids==['input_obligation']
    assert select_unit(state) is not None
    assert state.claims[0].assessment.value=='unassessed'


@pytest.mark.parametrize('point',['partial','complete'])
def test_model_commit_recovery_uses_same_action_and_version(tmp_path,prepared,point):
    _,state,bundle,_=prepared
    before=state.model_copy(deep=True);unit=state.units[0]
    if point=='partial':
        folder=tmp_path/'models/.pending-action1';folder.mkdir(parents=True)
        (folder/'Behavior.tla').write_text('partial bytes')
    else:
        first=save_bundle(tmp_path,state,unit,bundle,ToyImplementation(),transaction_key='action1')
    restored=save_bundle(tmp_path,before,before.units[0],bundle,ToyImplementation(),transaction_key='action1')
    assert restored.version==1 and len(before.models)==1
    if point=='complete': assert restored.id==first.id
    again=save_bundle(tmp_path,before,before.units[0],bundle,ToyImplementation(),transaction_key='action1')
    assert again.id==restored.id and len(before.models)==1
    assert (tmp_path/'models/v1/commit.json').exists()


def test_model_commit_refuses_changed_inputs(tmp_path,prepared):
    _,state,bundle,_=prepared
    save_bundle(tmp_path,state,state.units[0],bundle,ToyImplementation(),transaction_key='action1')
    changed=bundle.model_copy(deep=True);changed.description='Different generation input'
    with pytest.raises(ValueError,match='differs'):
        save_bundle(tmp_path,state,state.units[0],changed,ToyImplementation(),transaction_key='action1')


def test_f2_relation_dependency_requeues_unrelated_completed_unit(tmp_path,dependency_prepared):
    from consensus_assurance.workflow.feedback import apply_feedback
    from consensus_assurance.core.proposals import GraphPatch, ClaimDraft, RelationDraft
    _,state,bundle,_=dependency_prepared
    unit=state.units[0];model=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    other=unit.model_copy(deep=True);other.id='other';other.status='checked';state.units.append(other)
    other_model=model.model_copy(deep=True);other_model.id='other-model';other_model.unit_id='other';other_model.binding_ids=[];other_model.checkers=[]
    edge=state.relations[0];other_model.graph_versions={edge.id:edge.version};state.models.append(other_model)
    claim=state.claims[0]
    changed=ClaimDraft(**{k:v for k,v in claim.model_dump().items() if k in ClaimDraft.model_fields})
    changed.description='Revised applicable responsibility'
    new_edge=RelationDraft(**{k:v for k,v in edge.model_dump().items() if k in RelationDraft.model_fields});new_edge.rationale='New applicability of this dependency'
    patch=GraphPatch(claims=[changed],relations=[new_edge],expected_versions={claim.id:claim.version,edge.id:edge.version},rationale='Reconsider dependency')
    basis=claim.grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=[]
    f=Feedback(kind='F2',rationale='Applicable contract changed',evidence_ids=claim.source_ids,target_ids=[claim.id],relation_ids=[],new_basis='New evidence reinterprets the contract',graph=None,bundle=None,patch=patch,old_judgment=claim.description,new_judgment=changed.description,grounding=basis)
    from regression_support import declared_changes
    f.target_ids.append(edge.id)
    declared_changes(state,f)
    apply_feedback(state,unit,bundle,f)
    assert next(u for u in state.units if u.id=='other').status=='pending'
    assert next(u for u in state.units if u.id=='other').recheck_reasons



def test_later_bundle_cannot_hide_an_unfinished_checker_of_same_obligation(tmp_path,prepared):
    from consensus_assurance.core.types import CheckerSpec
    _,state,bundle,_=prepared;unit=state.units[0]
    first=bundle.checker_specs()[0]
    second=CheckerSpec(invariant='Additional',claim_id=first.claim_id,scope=first.scope)
    bundle.checkers=[first,second]
    bundle.properties=bundle.properties.replace('Safe ==','Additional == TRUE\nSafe ==')
    model1=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    bundle.checkers=[first]
    model2=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    for model in [model1,model2]:
        state.checks.append(CheckRun(action='model_check',status=ExecutionStatus.COMPLETED,cwd=str(tmp_path),snapshot_id=state.snapshot.id,model_id=model.id,
            checker_results=[CheckerResult(invariant=first.invariant,claim_id=first.claim_id,scope=first.scope,outcome='holds')]))
    checked,missing=obligation_progress(state,unit)
    assert first.claim_id in missing and first.claim_id not in checked
