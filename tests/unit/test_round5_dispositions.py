"""Scoped review follow-ups, handoffs and durable semantic mutations."""
import json
import shutil
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import SemanticCheck, SemanticReview, InquiryTask, Responsibility, ResponsibilityHandoff
from consensus_assurance.core.proposals import ReviewReply, ClaimDraft, GraphPatch, JudgmentChange
from consensus_assurance.workflow.reviews import record_dispositions, validate_resolutions, readiness
from consensus_assurance.workflow.inquiry import enqueue, initial_agenda, process_task, resume_deferred
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.transactions import commit_graph
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import Store
from test_round5_boundaries import revision_for


def engine_for(tmp_path,state):
    cfg=Config(implementation='toy',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'')
    engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(state.snapshot.repo,engine.root/'source')
    return engine


def items(claim,status='no_issue_found'):
    return [SemanticCheck(target_id=claim.id,aspect=a,status=status,source_ids=claim.source_ids,explanation='Check the producer responsibility under the current contract',alternatives='A consumer may provide the same guarantee through another mechanism',counterexample_reasoning='A local missing guard alone does not establish a violated responsibility') for a in ['applicability','decomposition']]


def test_completed_review_with_no_read_plan_keeps_a_planning_issue(tmp_path,prepared):
    _,state,_,_=prepared;engine=engine_for(tmp_path,state);claim=state.claims[1]
    task=enqueue(state,'review','Read missing contract','missing',target_ids=[claim.id])
    from consensus_assurance.core.types import CheckRun,ExecutionStatus
    engine.ask=lambda *a,**k:(ReviewReply(items=items(claim,'needs_reading'),limitations=[]),CheckRun(action='agent',cwd=str(engine.root),snapshot_id=state.snapshot.id,status=ExecutionStatus.COMPLETED))
    process_task(engine,task)
    stored=next(t for t in state.inquiry_tasks if t.id==task.id)
    assert stored.status=='completed'
    assert len(state.review_issues)==2
    assert all(i.disposition=='blocked' and not i.resolved_by and 'planning' in i.reason for i in state.review_issues)
    assert not state.models


def test_resolution_is_explicit_and_partial_review_cannot_clear_other_issues(prepared):
    _,state,_,_=prepared;a,b=state.claims[1:3]
    old=SemanticReview(task_id='old',check_id='check',target_versions={a.id:1,b.id:1},material_ids=a.source_ids+b.source_ids,items=items(a,'disputed')+items(b,'disputed'),origin='mock')
    state.semantic_reviews.append(old)
    record_dispositions(state,old,ReviewReply(items=old.items,limitations=[]),[])
    task=InquiryTask(kind='review',reason='Review A',trigger='new',target_ids=[a.id],target_versions={a.id:1})
    selected=[i.id for i in state.review_issues if i.target_id==a.id]
    reply=ReviewReply(items=items(a),resolves_issue_ids=selected,resolution_rationale='The same cited producer/consumer evidence addresses A in the unchanged scope',limitations=[])
    validate_resolutions(state,task,reply)
    new=SemanticReview(task_id=task.id,check_id='newcheck',target_versions={a.id:1},material_ids=a.source_ids,items=reply.items,origin='mock',resolves_issue_ids=selected)
    record_dispositions(state,new,reply,[])
    assert all(i.resolved_by==new.id for i in state.review_issues if i.target_id==a.id)
    assert all(i.resolved_by is None for i in state.review_issues if i.target_id==b.id)
    invalid=reply.model_copy(update={'resolves_issue_ids':[i.id for i in state.review_issues if i.target_id==b.id]})
    with pytest.raises(ValueError):validate_resolutions(state,task,invalid)


def test_supersession_needs_full_same_version_material_scope(tmp_path,prepared):
    _,state,_,_=prepared;engine=engine_for(tmp_path,state);a,b=state.claims[1:3]
    old=enqueue(state,'review','Two issues','old',target_ids=[a.id,b.id]);old.status='blocked';old.stop_reason='Budget exhausted or disabled: semantic_reviews'
    task=enqueue(state,'review','Revisit both','new',target_ids=[a.id,b.id])
    reply=ReviewReply(items=items(a)+items(b),supersedes_task_ids=[old.id],resolution_rationale='Both current responsibilities and all earlier evidence were reconsidered',limitations=[])
    validate_resolutions(state,task,reply)
    partial=reply.model_copy(update={'items':items(a)})
    with pytest.raises(ValueError):validate_resolutions(state,task,partial)
    review=SemanticReview(task_id=task.id,check_id='done',target_versions=task.target_versions,material_ids=old.material_ids,items=reply.items,origin='mock',supersedes_task_ids=[old.id])
    record_dispositions(state,review,reply,[])
    task.status='completed';resume_deferred(engine)
    assert old.superseded_by==review.id and state.active_inquiry_id is None


def test_grounding_only_F2_changes_scope_without_rewriting_claim(prepared):
    _,state,_,_=prepared;claim=state.claims[1];description=claim.description
    feedback=revision_for(state,[claim.id]);draft=feedback.patch.claims[0]
    draft.description=description;old=claim.grounding.model_dump(mode='json')
    draft.grounding.applicability+='; selected serial configuration only'
    feedback.grounding=draft.grounding.model_copy(update={"unresolved":[],"conflicts":[]})
    feedback.changes=[JudgmentChange(target_id=claim.id,field='grounding',old_value_json=json.dumps(old),new_value_json=json.dumps(draft.grounding.model_dump(mode='json')))]
    apply_feedback(state,state.units[0],None,feedback)
    current=next(c for c in state.claims if c.id==claim.id)
    assert current.version==2 and current.description==description
    assert 'serial configuration' in current.grounding.applicability


def test_handoff_stays_backlog_when_both_responsibilities_have_goals(tmp_path,prepared):
    _,state,_,_=prepared;engine=engine_for(tmp_path,state);source=state.materials[0].id
    state.responsibilities=[Responsibility(id='producer',description='Establish a bound',source_ids=[source],claim_ids=[state.claims[0].id],applicability='Serial fixture',handoffs=[ResponsibilityHandoff(target_id='consumer',description='Consumer relies on the input bound',source_ids=[source])]),Responsibility(id='consumer',description='Use the bound',source_ids=[source],claim_ids=[state.claims[1].id],applicability='Serial fixture')]
    from types import SimpleNamespace
    proposal=SimpleNamespace(responsibilities=state.responsibilities,exploration_requests=[],reading_requests=[])
    initial_agenda(engine,proposal);initial_agenda(engine,proposal)
    assert not state.inquiry_tasks
    assert state.responsibilities[0].handoffs[0].target_id=='consumer'
    assert all(not r.questions for r in state.responsibilities)


@pytest.mark.parametrize('interrupt',[False,True])
def test_semantic_transaction_failure_and_recovery_are_atomic(tmp_path,prepared,interrupt):
    _,state,_,_=prepared;engine=engine_for(tmp_path,state);engine.checkpoint('initial')
    before=state.model_dump(mode='json')
    def invalid(proxy):
        proxy.state.claims[1].description='must never escape failed validation'
        raise ValueError('Injected validation failure')
    with pytest.raises(ValueError):commit_graph(engine,'invalid',{'operation':'bad'},invalid)
    assert state.model_dump(mode='json')==before
    def change(proxy):
        proxy.state.claims[1].version+=1
        enqueue(proxy.state,'review','Changed scope','changed',target_ids=[state.claims[1].id])
    if interrupt:
        def crash(key):raise RuntimeError('Interrupted between manifest and state')
        engine.graph_commit_hook=crash
        with pytest.raises(RuntimeError):commit_graph(engine,'change',{'operation':'one'},change)
        assert state.claims[1].version==1
        engine.state=Store(engine.root).load();engine.budget=BudgetTracker(engine.config.budget,engine.state)
        engine.graph_commit_hook=lambda key:None
    commit_graph(engine,'change',{'operation':'one'},change)
    commit_graph(engine,'change',{'operation':'one'},change)
    assert engine.state.claims[1].version==2 and len(engine.state.inquiry_tasks)==1
    assert 'change' in Store(engine.root).load().applied_operations


def test_zero_review_budget_records_unreviewed_exploratory_permission(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import prepare_selected
    _,state,_,_=prepared;engine=engine_for(tmp_path,state)
    engine.config.budget.semantic_reviews=0;engine.config.budget.exploration_rounds=0
    assert prepare_selected(engine,state.units[0])
    assert state.units[0].semantic_readiness['status']=='unreviewed'
    assert state.units[0].semantic_readiness['unresolved']
    assert 'cannot confirm' in state.units[0].semantic_readiness['limitation']


def test_later_full_review_releases_only_current_readiness_limit(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import objects,semantic_limitations
    from consensus_assurance.workflow.reviews import material_closure,required_aspects
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    _,state,bundle,_=prepared;unit=state.units[0]
    model=save_bundle(tmp_path,state,unit,bundle,ToyImplementation())
    unit.semantic_readiness=readiness(state,unit)
    assert any('exploratory' in x for x in semantic_limitations(state,model))
    available=objects(state);ids=unit.goal_ids+unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id]
    source_ids=sorted(material_closure(state,ids)[0])
    checks=[SemanticCheck(target_id=id,aspect=aspect,status='no_issue_found',source_ids=source_ids,explanation='Explicitly reconsider all current materials',alternatives='Check the actual alternative mechanism',counterexample_reasoning='No unresolved prior counterevidence in this fixture') for id in ids for aspect in required_aspects(available[id])]
    state.semantic_reviews.append(SemanticReview(task_id='new',check_id='actual-review',target_versions={id:available[id].version for id in ids},unit_id=unit.id,unit_version=unit.version,material_ids=source_ids,items=checks,origin='mock'))
    assert not any('exploratory' in x for x in semantic_limitations(state,model))
    assert unit.semantic_readiness['status']=='unreviewed'  # Preserve historical readiness at model generation.
