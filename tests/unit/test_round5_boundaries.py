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
    items=[SemanticCheck(target_id=a.id,aspect=aspect,status='revision_needed',source_ids=a.source_ids,explanation='The selected responsibility needs correction',alternatives='Other mechanisms remain possible',counterexample_reasoning='The old requirement can be stronger than the current contract') for aspect in ['applicability','decomposition']]
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


def test_actual_dependency_selected_unit_is_reviewed_before_build(tmp_path,prepared):
    from consensus_assurance.core.config import Config
    from consensus_assurance.core.types import Relation
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.workflow.errors import Blocked
    from consensus_assurance.registry import assemble
    _,state,_,_=prepared
    consumer=state.units[0]
    producer=consumer.model_copy(deep=True);producer.id='producer';producer.obligation_ids=['input_obligation'];producer.binding_ids=['input_binding'];producer.relation_ids=['producer_support']
    state.relations.append(Relation(id='producer_support',source=consumer.goal_ids[0],target='input_obligation',kind='depends_all',rationale='Goal depends on producer',grounding=state.claims[0].grounding))
    state.units.append(producer);state.completed_steps=['capabilities','materials','discovery']
    root=tmp_path/'selection';shutil.copytree(state.snapshot.repo,root/'source')
    config=Config(implementation='toy',agent_backend='mock',allow_experiments=False);config.budget.exploration_rounds=0;config.budget.semantic_reviews=4;config.budget.audit_units=1
    built=[]
    class ObserveBuild(Engine):
        def ask(self,kind,response_type,context,validator=None):
            if kind=='semantic_review':
                items=[]
                for obj in context['target_objects']:
                    aspects=['applicability','decomposition'] if obj.get('kind')=='obligation' else ['applicability'] if obj.get('kind')=='goal' else ['decomposition']
                    for aspect in aspects:items.append(SemanticCheck(target_id=obj['id'],aspect=aspect,status='no_issue_found',source_ids=['README.md:1:5'],explanation='Scoped fixture evidence',alternatives='Other mechanisms are not excluded',counterexample_reasoning='Review actual producer context'))
                return ReviewReply(items=items,limitations=[]),CheckRun(action='agent',status=ExecutionStatus.COMPLETED,cwd=str(root),snapshot_id=state.snapshot.id)
            if kind=='build':
                built.append(self.state.active_unit_id)
                assert any('input_obligation' in r.target_versions for r in self.state.semantic_reviews)
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
    items=[SemanticCheck(target_id=claim.id,aspect=aspect,status='no_issue_found',source_ids=claim.source_ids,explanation='Actual contract rechecked',alternatives='Alternate mechanisms considered',counterexample_reasoning='No issue found in the specified scope') for aspect in ['applicability','decomposition']]
    extra={'supersedes_task_ids':['old']} if 'supersedes_task_ids' in SemanticReview.model_fields else {}
    state.semantic_reviews.append(SemanticReview(task_id='new',check_id='check',target_versions={claim.id:claim.version},material_ids=claim.source_ids,items=items,origin='mock',**extra))
    assert not any('unfinished' in x for x in semantic_limitations(state,model))
