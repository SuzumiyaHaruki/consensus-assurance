"""Issue-specific dispositions, context admission and exact source sharing."""
import json,shutil
import pytest
from test_round6_boundaries import controller
from consensus_assurance.core.proposals import ReviewReply,IssueResolution
from consensus_assurance.core.types import ReviewIssue,SemanticCheck,SemanticReview
from consensus_assurance.workflow.inquiry import enqueue,validate_review,review_unit,process_task
from consensus_assurance.workflow.reviews import record_dispositions
from consensus_assurance.workflow.review_contract import target_contract
from consensus_assurance.workflow.task_packet import pool_sources
from consensus_assurance.workflow.output_repair import all_materials
from consensus_assurance.workflow.errors import Blocked


def setup(prepared):
    _,s,_,_=prepared;c=s.claims[1]
    a=ReviewIssue(id='A',review_id='old',target_id=c.id,target_version=1,aspect='applicability',source_ids=c.source_ids,explanation='Locate the caller',disposition='reading',reason='Missing caller')
    b=a.model_copy(update={'id':'B','explanation':'Storage crash contract remains unresolved'})
    s.review_issues=[a,b];task=enqueue(s,'review','Resolve A while retaining B','test',target_ids=[c.id])
    items=[SemanticCheck(target_id=c.id,aspect=x,status='no_issue_found',source_ids=c.source_ids,explanation='Located caller identity is supported',alternatives='Other callers remain outside this scope',counterexample_reasoning='Identity does not prove storage durability',scope_limitations=['Storage investigation is separate']) for x in ['applicability','decomposition']]
    r=IssueResolution(issue_id='A',target_version=1,original_question=a.explanation,source_ids=c.source_ids,rationale='The supplied producer and consumer identify the caller',residual_issue_ids=['B'],scope_limitations=items[0].scope_limitations)
    return s,task,ReviewReply(items=items,resolves_issue_ids=['A'],resolutions=[r],resolution_rationale=r.rationale,limitations=[])


def test_A_resolves_while_B_remains_and_no_duplicate_issues(prepared):
    s,t,r=setup(prepared);validate_review(s,t,r)
    review=SemanticReview(task_id=t.id,check_id='fixture',target_versions=t.target_versions,material_ids=t.material_ids,items=r.items,origin='mock',resolves_issue_ids=['A'])
    record_dispositions(s,review,r,[])
    assert s.review_issues[0].resolved_by==review.id and s.review_issues[1].resolved_by is None
    assert len(s.review_issues)==2
    negative=r.items[0].model_copy(update={'status':'needs_reading','explanation':'An independent missing input'})
    review.items=[negative];record_dispositions(s,review,r,[]);count=len(s.review_issues);record_dispositions(s,review,r,[])
    assert len(s.review_issues)==count


@pytest.mark.parametrize('mutation',['root','child','rename','missing_source','missing_basis'])
def test_same_root_cannot_disappear_into_residual_or_scope(prepared,mutation):
    s,t,r=setup(prepared)
    if mutation=='root':r.resolutions[0].residual_issue_ids=['A']
    elif mutation=='child':s.review_issues[1].parent_issue_id='A'
    elif mutation=='rename':r.resolutions[0].scope_limitations=['Locate the caller'];r.items[0].scope_limitations=['Locate the caller']
    elif mutation=='missing_source':r.resolutions[0].source_ids=['absent']
    else:r.resolutions[0].rationale=''
    with pytest.raises(ValueError) as exc:validate_review(s,t,r)
    assert getattr(exc.value,'diagnostics',None)
    assert not s.review_issues[0].resolved_by


def test_source_pool_preserves_exact_overlap_and_reference_ranges(prepared):
    _,s,_,_=prepared;m=next(m for m in s.materials if m.file=='counter.py')
    short=m.model_copy(deep=True);short.id='subrange';short.start_line=2;short.end_line=3;short.text='\n'.join(m.text.splitlines()[1:3])
    packet={'materials':[m.model_dump(mode='json'),short.model_dump(mode='json')]}
    pooled=pool_sources(packet);restored={m['id']:m for m in all_materials(pooled)}
    assert restored[short.id]['text']==short.text and restored[m.id]['text']==m.text
    assert 'text' not in pooled['materials'][0] and len(pooled['source_text_pool'])==1


def test_same_review_basis_reused_different_trigger_no_new_work(tmp_path,prepared):
    _,s,_,_=prepared;e=controller(tmp_path,s);u=s.units[0];objects={o.id:o for o in s.claims+s.bindings+s.relations+s.units}
    for id in u.goal_ids+u.obligation_ids+u.binding_ids+u.relation_ids+[u.id]:
        contract=target_contract(s,objects[id]);items=[SemanticCheck(target_id=id,aspect=a,status='no_issue_found',source_ids=contract['required_material_ids'],explanation='Actual scoped source checked',alternatives='Alternative mechanisms remain possible',counterexample_reasoning='Scoped dependencies retained') for a in contract['required_aspects']]
        s.semantic_reviews.append(SemanticReview(task_id='prior',check_id='prior',target_versions={id:objects[id].version},material_ids=contract['required_material_ids'],context_dependencies={id:contract},items=items,origin='mock'))
    review_unit(e,u,'new_trigger');assert not s.inquiry_tasks and s.review_reuses
    # A real new source/version change reopens the affected target.
    s.claims[1].version+=1;review_unit(e,u,'changed');assert s.inquiry_tasks


def test_oversize_parent_splits_without_spending_actual_review_round(tmp_path,prepared):
    repo,s,_,_=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source');e.config.budget.context_chars=1000
    t=enqueue(s,'review','Review two related claims without losing their dependencies','split',target_ids=[c.id for c in s.claims[:2]])
    with pytest.raises(Blocked):process_task(e,t)
    assert s.usage.get('semantic_reviews',0)==0 and s.usage.get('agent_calls',0)==0
    assert len(t.child_task_ids)==2 and all(c.status=='pending' for c in s.inquiry_tasks if c.parent_task_id==t.id)
    receipt=s.packet_receipts[-1];disk=json.loads((e.root/'packets'/(receipt['id']+'.json')).read_text())
    assert disk['status']==receipt['status']=='blocked_context_limit'


def test_parent_completion_waits_for_all_children_and_preserves_issues(prepared):
    from consensus_assurance.workflow.inquiry import settle_parents
    s,t,r=setup(prepared)
    a=enqueue(s,'review','Part A','A-child',target_ids=[t.target_ids[0]])
    b=enqueue(s,'review','Part B','B-child',target_ids=[t.target_ids[0]])
    t.child_task_ids=[a.id,b.id];t.status='blocked';a.status='completed'
    settle_parents(s);assert t.status=='blocked'
    b.status='completed';settle_parents(s)
    assert t.status=='completed' and not t.admitted and all(i.resolved_by is None for i in s.review_issues)
