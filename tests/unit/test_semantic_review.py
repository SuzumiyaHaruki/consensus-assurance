"""Issue-specific dispositions, context admission and exact source sharing."""
import json,shutil
import pytest
from test_graph_mutations import controller
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
    items=[SemanticCheck(target_id=c.id,aspect=x,status='no_issue_found',source_ids=c.source_ids,rationale='Located caller identity is supported' + "\n" + 'Other callers remain outside this scope' + "\n" + 'Identity does not prove storage durability',limitations=['Storage investigation is separate'] if x=='applicability' else []) for x in ['applicability','decomposition']]
    r=IssueResolution(issue_id='A',target_version=1,original_question=a.explanation,source_ids=c.source_ids,rationale='The supplied producer and consumer identify the caller',residual_issue_ids=['B'],scope_limitations=items[0].limitations)
    return s,task,ReviewReply(items=items,resolves_issue_ids=['A'],resolutions=[r],resolution_rationale=r.rationale,limitations=[])


def test_A_resolves_while_B_remains_and_no_duplicate_issues(prepared):
    s,t,r=setup(prepared);validate_review(s,t,r)
    review=SemanticReview(task_id=t.id,check_id='fixture',target_versions=t.target_versions,material_ids=t.material_ids,items=r.items,origin='mock',resolves_issue_ids=['A'])
    record_dispositions(s,review,r,[])
    assert s.review_issues[0].resolved_by==review.id and s.review_issues[1].resolved_by is None
    assert len(s.review_issues)==2
    negative=r.items[0].model_copy(update={'status':'needs_reading','rationale':'An independent missing input'})
    review.items=[negative];record_dispositions(s,review,r,[]);count=len(s.review_issues);record_dispositions(s,review,r,[])
    assert len(s.review_issues)==count


@pytest.mark.parametrize('mutation',['root','child','rename','missing_source','missing_basis'])
def test_same_root_cannot_disappear_into_residual_or_scope(prepared,mutation):
    s,t,r=setup(prepared)
    if mutation=='root':r.resolutions[0].residual_issue_ids=['A']
    elif mutation=='child':s.review_issues[1].parent_issue_id='A'
    elif mutation=='rename':r.resolutions[0].scope_limitations=['Locate the caller'];r.items[0].limitations=['Locate the caller']
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
        contract=target_contract(s,objects[id]);items=[SemanticCheck(target_id=id,aspect=a,status='no_issue_found',source_ids=contract['required_material_ids'],rationale='Actual scoped source checked' + "\n" + 'Alternative mechanisms remain possible' + "\n" + 'Scoped dependencies retained') for a in contract['required_aspects']]
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


"""Responses derive required aspects solely from the rendered task packet."""
import json
import pytest
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.core.types import InquiryTask
from consensus_assurance.workflow.inquiry import task_context,validate_review,enqueue
from consensus_assurance.workflow.task_packet import prepare,receipt
from consensus_assurance.workflow.prompts import render
from consensus_assurance.workflow.reviews import readiness
from consensus_assurance.workflow.output_repair import apply_replacements,diagnostic_targets,OutputRepair
from consensus_assurance.workflow.repair_policy import validate_representation
from consensus_assurance.core.diagnostics import DiagnosticError
from test_graph_mutations import controller


def respond(packet):
    items=[]
    for c in packet['review_contract']:
        assert c['object_type'] and c['version'] and c['questions']
        for aspect in c['required_aspects']:
            assert c['questions'][aspect]
            items.append({'target_id':c['target_id'],'aspect':aspect,'status':'no_issue_found','source_ids':c['required_material_ids'],'limitations':[],'rationale':'The actual supplied source supports this scoped synthetic responsibility' + "\n" + 'An alternative mechanism can satisfy the same obligation' + "\n" + 'A failure would require the dependency to be broken under allowed conditions'})
    return ReviewReply(items=items,limitations=[])


def packet_for(e,ids):
    task=enqueue(e.state,'review','Check supplied objects','packet-test',target_ids=ids)
    e.state.active_inquiry_id=task.id
    packet,t=prepare(e,'semantic_review',task_context(e,task))
    prompt=render('semantic_review',packet)
    receipt(e,'semantic_review',packet,prompt,ReviewReply,t)
    return task,json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])


def test_every_actual_object_type_uses_packet_policy(tmp_path,prepared):
    from consensus_assurance.workflow.artifacts import save_bundle
    repo,state,bundle,_=prepared;e=controller(tmp_path,state)
    goal=state.claims[0].model_copy(deep=True);goal.id='environment';goal.kind='assumption';state.claims.append(goal)
    model=save_bundle(e.root,state,state.units[0],bundle,e.implementation)
    seen=set()
    for obj in [*state.claims,*state.bindings,*state.relations,*state.units,model]:
        task,packet=packet_for(e,[obj.id]);reply=respond(packet)
        validate_review(state,task,reply)
        seen.add(packet['review_contract'][0]['object_type'])
        assert not packet['catalogue'] and packet['file_lookup']
        assert len([o for key in ('target_objects','claims','bindings','units','relations') for o in packet.get(key,[]) if o['id']==obj.id])==1
    assert seen=={'goal','obligation','assumption','binding','relation','unit','model'}




def test_task_attachment_does_not_leak_and_unseen_source_rejected(tmp_path,prepared):
    from consensus_assurance.core.types import Material
    _,state,_,_=prepared;e=controller(tmp_path,state)
    other=Material(id='unrelated',file='unrelated.txt',start_line=1,end_line=1,text='Unrelated private task context',kind='document_statement',content_digest='synthetic')
    state.materials.append(other);state.attached_material_ids.append(other.id);state.task_attachments['inquiry:other']=[other.id]
    task,packet=packet_for(e,[state.bindings[0].id])
    assert other.id not in [m['id'] for m in packet['materials']]
    reply=respond(packet);reply.items[0].source_ids.append(other.id)
    with pytest.raises(DiagnosticError) as caught:validate_review(state,task,reply)
    assert caught.value.diagnostics[0].code=='review_unavailable_source'


def test_relation_packet_includes_both_endpoint_sources(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);edge=state.relations[0]
    task,packet=packet_for(e,[edge.id]);contract=packet['review_contract'][0]
    assert edge.source in contract['dependency_versions'] and edge.target in contract['dependency_versions']
    assert set(contract['required_material_ids'])<={m['id'] for m in packet['materials']}


def test_receipt_counts_actual_prompt_and_prepared_schema_files(tmp_path,prepared):
    from pathlib import Path
    _,state,_,_=prepared;e=controller(tmp_path,state);task,packet=packet_for(e,[state.bindings[0].id])
    r=state.packet_receipts[-1];prompt=render('semantic_review',packet)
    assert r['prompt_chars']==len(prompt) and r['prompt_bytes']==len(prompt.encode())
    assert r['wire_schema_chars']==len((e.root/'packets'/(r['id']+'.schema.json')).read_text())
    assert r['material_ids']==task.material_ids


def test_missing_aspect_is_one_focused_call_not_whole_response_repair(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import process_task
    from consensus_assurance.core.types import CheckRun
    _,state,_,_=prepared;e=controller(tmp_path,state)
    task=enqueue(state,'review','Review candidate relation','focused',target_ids=[state.claims[1].id])
    calls=[]
    def ask(kind,response_type,context,validator=None):
        packet,_=prepare(e,kind,context)
        calls.append(packet['required_review_pairs'])
        response=respond(packet)
        if len(calls)==1:response.items=response.items[:1]
        if validator:validator(response)
        return response,CheckRun(action='agent',cwd=str(e.root),snapshot_id=state.snapshot.id)
    e.ask=ask;process_task(e,task)
    assert len(state.semantic_reviews)==1 and len(state.semantic_reviews[0].items)==1
    follow=next(t for t in state.inquiry_tasks if t.id!=task.id)
    assert follow.requested_aspects=={state.claims[1].id:['decomposition']}
    process_task(e,follow)
    assert len(calls)==2 and len(calls[1])==1
    assert not state.repair_sessions and len(state.semantic_reviews)==2


def test_counterevidence_blocks_even_with_no_issue_status(tmp_path,prepared):
    from consensus_assurance.workflow.reviews import record_dispositions
    from consensus_assurance.core.types import SemanticReview
    _,state,_,_=prepared;e=controller(tmp_path,state);task,packet=packet_for(e,[state.claims[1].id]);reply=respond(packet)
    reply.items[0].counterevidence=['A producer failure remains unexplained']
    review=SemanticReview(task_id=task.id,check_id='fixture',target_versions=task.target_versions,material_ids=task.material_ids,items=reply.items,origin='mock')
    state.semantic_reviews.append(review);record_dispositions(state,review,reply,[])
    assert state.review_issues and readiness(state,state.units[0])['status']!='reviewed'


def test_text_view_alias_requires_explicit_original_range_selection(prepared):
    from consensus_assurance.workflow.task_packet import pool_sources
    from consensus_assurance.workflow.sources import all_materials,validate_view_citations
    from consensus_assurance.core.diagnostics import DiagnosticError
    _,state,_,_=prepared;m=state.materials[0].model_dump(mode='json')
    packet=pool_sources({'materials':[m,m]})
    view=packet['source_text_pool'][0]
    assert 'id' not in view and view['citation_ids']==[m['id']]
    assert all_materials(packet)==[m]
    item=SemanticCheck(target_id=state.claims[0].id,aspect='applicability',status='needs_reading',source_ids=[view['view_id']],rationale='Consumer contract is missing',counterevidence=['Do not infer the producer guarantee'])
    with pytest.raises(DiagnosticError) as failure:validate_view_citations(item,packet)
    d=failure.value.diagnostics[0]
    assert d.code=='source_view_citation' and d.paths==['/source_ids'] and d.material_ids==[m['id']]
    assert item.source_ids==[view['view_id']] and item.counterevidence
    item.source_ids=[m['id']];validate_view_citations(item,packet)
