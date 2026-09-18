"""Repository-type reproductions of the four audited boundary failures."""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import ClaimDraft,GraphPatch,Feedback,JudgmentChange,ReviewReply
from consensus_assurance.core.types import CheckRun,CheckerResult,ExecutionStatus,InquiryTask,SemanticReview,SemanticCheck
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.modeling import obligation_progress
from consensus_assurance.workflow.inquiry import validate_review,semantic_limitations
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation


def revision_for(state, ids):
    drafts=[];changes=[]
    for id in ids:
        old=next(c for c in state.claims if c.id==id)
        new=ClaimDraft(**{k:v for k,v in old.model_dump().items() if k in ClaimDraft.model_fields})
        new.description=old.description+' with a weaker requirement'
        drafts.append(new)
        changes.append(JudgmentChange(target_id=id,field='description',old_value_json=json.dumps(old.description),new_value_json=json.dumps(new.description)))
    basis=drafts[0].grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=[]
    return Feedback(kind='F2',rationale='Candidate correction',evidence_ids=basis.expectation_ids or basis.behavior_ids,target_ids=[ids[0]],relation_ids=[],new_basis='Actual materials support the requested correction',graph=None,bundle=None,patch=GraphPatch(claims=drafts,expected_versions={i:1 for i in ids},rationale='Correction'),changes=changes,old_judgment=state.claims[1].description,new_judgment=drafts[0].description,grounding=basis)


def test_review_cannot_modify_an_unreviewed_obligation(prepared):
    _,state,_,_=prepared
    a,b=state.claims[1:3]
    task=InquiryTask(kind='review',reason='Review A only',trigger='test',target_ids=[a.id],unit_id=state.units[0].id)
    items=[SemanticCheck(target_id=a.id,aspect=aspect,status='revision_needed',source_ids=a.source_ids,rationale='The selected responsibility needs correction' + "\n" + 'Other mechanisms remain possible' + "\n" + 'The old requirement can be stronger than the current contract') for aspect in ['applicability','decomposition']]
    reply=ReviewReply(items=items,revision=revision_for(state,[a.id,b.id]),limitations=[])
    before=state.model_dump()
    with pytest.raises(ValueError):validate_review(state,task,reply)
    assert state.model_dump()==before


def test_same_named_stronger_unexecuted_model_is_not_covered(tmp_path,prepared):
    _,state,bundle,_=prepared;unit=state.units[0]
    old=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    spec=old.checkers[0]
    state.checks.append(CheckRun(action='model_check',status=ExecutionStatus.COMPLETED,outcome='holds',cwd=str(tmp_path),snapshot_id=state.snapshot.id,model_id=old.id,search_fingerprint=old.search_fingerprint,checker_results=[CheckerResult(invariant=spec.invariant,claim_id=spec.claim_id,scope=spec.scope,outcome='holds')]))
    assert spec.claim_id in obligation_progress(state,unit)[0]
    stronger=bundle.model_copy(deep=True);stronger.properties=stronger.properties.replace('value <= 3','value <= 2')
    save_bundle(tmp_path,state,unit,stronger,ToyImplementation(),previous=old)
    checked,missing=obligation_progress(state,unit)
    assert spec.claim_id in missing and spec.claim_id not in checked


def test_actual_dependency_selected_unit_build_is_explicitly_exploratory(tmp_path,prepared):
    from consensus_assurance.core.config import Config
    from consensus_assurance.core.types import Relation
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.workflow.errors import Blocked
    from consensus_assurance.registry import assemble
    _,state,_,_=prepared
    consumer=state.units[0]
    producer=consumer.model_copy(deep=True);producer.id='producer';producer.obligation_ids=['input_obligation'];producer.binding_ids=['input_binding'];producer.relation_ids=['producer_support']
    state.relations.append(Relation(id='producer_support',source=consumer.obligation_ids[0],target='input_obligation',kind='depends_all',rationale='Goal depends on producer',grounding=state.claims[0].grounding))
    state.units.append(producer);state.completed_steps=['capabilities','materials','understanding','discovery']
    root=tmp_path/'selection';shutil.copytree(state.snapshot.repo,root/'source')
    config=Config(implementation='toy',agent_backend='mock',allow_experiments=False);config.budget.exploration_rounds=0;config.budget.semantic_reviews=4;config.budget.audit_units=1
    built=[]
    class ObserveBuild(Engine):
        def ask(self,kind,response_type,context,validator=None,**kwargs):
            if kind=='semantic_review':
                items=[]
                for obj in context['target_objects']:
                    aspects=['applicability','decomposition'] if obj.get('kind')=='obligation' else ['applicability'] if obj.get('kind')=='obligation' else ['decomposition']
                    for aspect in aspects:items.append(SemanticCheck(target_id=obj['id'],aspect=aspect,status='no_issue_found',source_ids=[next(m.id for m in state.materials if m.file=='README.md')],rationale='Scoped fixture evidence' + "\n" + 'Other mechanisms are not excluded' + "\n" + 'Review actual producer context'))
                return ReviewReply(items=items,limitations=[]),CheckRun(action='agent',status=ExecutionStatus.COMPLETED,cwd=str(root),snapshot_id=state.snapshot.id)
            if kind=='build':
                built.append(self.state.active_unit_id)
                assert self.state.units[-1].semantic_readiness['status']=='unreviewed'
                assert not self.state.semantic_reviews
                raise Blocked('End controlled selection test')
            raise AssertionError(kind)
    engine=ObserveBuild(config,root,*assemble(config),'');engine.state=state;engine.budget=BudgetTracker(config.budget,state)
    engine.execute(probed=True)
    assert built==['producer']


def test_equivalent_explicit_review_can_replace_old_budget_blockage(tmp_path,prepared):
    _,state,bundle,_=prepared
    model=save_bundle(tmp_path,state,state.units[0],bundle,ToyImplementation())
    claim=next(c for c in state.claims if c.id==model.claim_id)
    old=InquiryTask(id='old',kind='review',reason='Review contract',trigger='before_model',target_ids=[claim.id],target_versions={claim.id:claim.version},status='blocked',stop_reason='Budget exhausted or disabled: semantic_reviews')
    state.inquiry_tasks.append(old)
    items=[SemanticCheck(target_id=claim.id,aspect=aspect,status='no_issue_found',source_ids=claim.source_ids,rationale='Actual contract rechecked' + "\n" + 'Alternate mechanisms considered' + "\n" + 'No issue found in the specified scope') for aspect in ['applicability','decomposition']]
    extra={'supersedes_task_ids':['old']} if 'supersedes_task_ids' in SemanticReview.model_fields else {}
    state.semantic_reviews.append(SemanticReview(task_id='new',check_id='check',target_versions={claim.id:claim.version},material_ids=claim.source_ids,items=items,origin='mock',**extra))
    assert not any('unfinished' in x for x in semantic_limitations(state,model))


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


@pytest.mark.parametrize('extra',['claim','relation','unit','binding'])
def test_actual_write_set_rejects_every_unreviewed_object(dependency_prepared,extra):
    _,state,bundle,_=dependency_prepared;a,b=state.claims[1:3]
    f=revision_for(state,[a.id])
    if extra=='claim':f.patch.claims.append(ClaimDraft(**{k:v for k,v in b.model_dump().items() if k in ClaimDraft.model_fields}).model_copy(update={'description':'Weakened unrelated B'}))
    if extra=='relation':
        old=state.relations[0];f.patch.relations=[RelationDraft(**{k:v for k,v in old.model_dump().items() if k in RelationDraft.model_fields}).model_copy(update={'kind':'conditional_on'})]
    if extra=='unit':
        old=state.units[0]
        f.patch.units=[UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields}).model_copy(update={'obligation_ids':[b.id]})]
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


"""Project-level reproductions of the reviewed interface boundaries."""
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Material
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.reviews import material_closure


def controller(tmp_path,state):
    cfg=Config(implementation='toy',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'');engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    return engine


def test_same_action_kind_cannot_consume_other_input(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state)
    assert e.action('agent:review','agent_calls',lambda:'first',{'task':'A','value':1})=='first'
    assert e.action('agent:review','agent_calls',lambda:'second',{'task':'B','value':2})=='second'
    assert state.usage['agent_calls']==2


def test_selected_relation_closure_contains_endpoint_contract(dependency_prepared):
    _,state,_,_=dependency_prepared
    m=Material(id='upstream-contract',file='notes.md',start_line=1,end_line=1,kind='document_statement',text='The provider accepts only bounded inputs',content_digest='fixture')
    state.materials.append(m);state.claims[2].source_ids.append(m.id)
    relation=next(r for r in state.relations if r.target==state.claims[2].id)
    materials,_=material_closure(state,[relation.id])
    assert m.id in materials
