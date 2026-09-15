import json
import pytest
from consensus_assurance.core.proposals import GraphPatch,RelationDraft,BindingDraft,UnitDraft,ClaimDraft,JudgmentChange
from consensus_assurance.core.types import CheckRun,CheckerResult,ExecutionStatus,Origin
from consensus_assurance.workflow.mutations import write_set
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.graph import apply_patch
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.modeling import obligation_progress
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
from test_round5_boundaries import revision_for


@pytest.mark.parametrize('extra',['claim','relation','unit','binding'])
def test_actual_write_set_rejects_every_unreviewed_object(prepared,extra):
    _,state,bundle,_=prepared;a,b=state.claims[1:3]
    f=revision_for(state,[a.id])
    if extra=='claim':f.patch.claims.append(ClaimDraft(**{k:v for k,v in b.model_dump().items() if k in ClaimDraft.model_fields}).model_copy(update={'description':'Weakened unrelated B'}))
    if extra=='relation':
        old=state.relations[0];f.patch.relations=[RelationDraft(**{k:v for k,v in old.model_dump().items() if k in RelationDraft.model_fields}).model_copy(update={'kind':'alternative'})]
    if extra=='unit':
        old=state.units[0];old.obligation_ids.append(b.id)
        f.patch.units=[UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields}).model_copy(update={'obligation_ids':[a.id]})]
    if extra=='binding':
        old=state.bindings[0];m=next(m for m in state.materials if m.file==old.file and m.start_line<=old.start_line<=old.end_line<=m.end_line)
        f.patch.bindings=[BindingDraft(id=old.id,claim_id=b.id,material_id=m.id,symbol=old.symbol,start_line=old.start_line,end_line=old.end_line,description=old.description,pending=old.pending)]
    for name in ('claims','relations','bindings','units'):
        for obj in getattr(f.patch,name):f.patch.expected_versions[obj.id]=1
    from regression_support import declared_changes
    declared_changes(state,f)
    before=state.model_dump()
    with pytest.raises(ValueError,match='write set'):apply_feedback(state,state.units[0],bundle,f)
    assert state.model_dump()==before


def test_cross_type_collision_and_incomplete_changes_are_atomic(prepared):
    _,state,bundle,_=prepared
    candidate=ClaimDraft(**{k:v for k,v in state.claims[0].model_dump().items() if k in ClaimDraft.model_fields})
    candidate.id=state.bindings[0].id
    before=state.model_dump()
    with pytest.raises(ValueError,match='types'):apply_patch(state,GraphPatch(claims=[candidate],expected_versions={candidate.id:1},rationale='Collision'),semantic=True)
    f=revision_for(state,[state.claims[1].id]);f.changes=[]
    with pytest.raises(ValueError,match='changes must'):apply_feedback(state,state.units[0],bundle,f)
    assert state.model_dump()==before


def complete_search(state,model,root):
    check=CheckRun(action='model_check',status=ExecutionStatus.COMPLETED,outcome='holds',cwd=str(root),snapshot_id=state.snapshot.id,model_id=model.id,search_fingerprint=model.search_fingerprint,origin=Origin.MOCK,checker_results=[CheckerResult(invariant=s.invariant,claim_id=s.claim_id,scope=s.scope,outcome='holds') for s in model.checkers])
    state.checks.append(check)
    return check


@pytest.mark.parametrize('change',['harness','constants','behavior','faults','property'])
def test_reuse_requires_identical_search_inputs_and_explicit_receipt(tmp_path,prepared,change):
    from consensus_assurance.workflow.inputs import reusable_search
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.core.config import Config
    _,state,bundle,_=prepared;unit=state.units[0]
    first=save_bundle(tmp_path,state,unit,bundle,ToyImplementation());source=complete_search(state,first,tmp_path)
    changed=bundle.model_copy(deep=True)
    if change=='harness':changed.harness.source+='\n# Observation-only formatting\n'
    if change=='constants':changed.constants='N = 2'
    if change=='behavior':changed.behavior=changed.behavior.replace('value < 3','value < 2')
    if change=='faults':changed.scope.assumptions.append('An additional crash may occur')
    if change=='property':changed.properties=changed.properties.replace('value <= 3','value <= 2')
    second=save_bundle(tmp_path,state,unit,changed,ToyImplementation(),first)
    assert unit.obligation_ids[0] in obligation_progress(state,unit)[1]
    reusable=reusable_search(state,second)
    if change!='harness':assert reusable is None;return
    assert reusable.id==source.id
    engine=Engine(Config(),tmp_path,ToyImplementation(),None,None,'','');engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
    result=engine.search(unit,second,changed,None)
    assert result.reused_from==source.id and result.model_id==second.id and result.id!=source.id
    assert unit.obligation_ids[0] in obligation_progress(state,unit)[0]
    result.checker_results[0].outcome='unknown'
    assert reusable_search(state,second) is None
    assert unit.obligation_ids[0] in obligation_progress(state,unit)[1]


def test_reused_counterexample_keeps_current_attribution_without_reexecuting(tmp_path,prepared):
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.core.config import Config
    from consensus_assurance.core.types import uid
    _,state,bundle,_=prepared;unit=state.units[0]
    old=save_bundle(tmp_path,state,unit,bundle,ToyImplementation());source=complete_search(state,old,tmp_path)
    source.outcome='counterexample';source.violated_invariant=old.checkers[0].invariant;source.checker_results[0].outcome='violated'
    revised=bundle.model_copy(deep=True);revised.harness.source+='\n# Revised observation formatting\n'
    new=save_bundle(tmp_path,state,unit,revised,ToyImplementation(),old)
    receipt=source.model_copy(update={'id':uid(),'model_id':new.id,'reused':True,'reused_from':source.id,'input_versions':new.artifact_digests},deep=True)
    state.checks.append(receipt)
    engine=Engine(Config(),tmp_path,ToyImplementation(),None,None,'','');engine.state=state;engine.budget=BudgetTracker(Config().budget,state)
    assert engine.search(unit,new,revised,None).id==receipt.id
    assert len(state.findings)==1 and state.findings[0].model_id==new.id
    assert state.findings[0].claim_id==old.checkers[0].claim_id
    assert 'model_checks' not in state.usage
