"""Reproduce the audited controller branches using actual project records."""
import pytest
from consensus_assurance.core.proposals import Feedback,GraphPatch,BindingDraft,RelationDraft,UnitDraft,ReviewReply
from consensus_assurance.core.types import ReviewIssue,SemanticCheck
from consensus_assurance.workflow.graph import apply_patch,expand_unit
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.materials import ReadingPlan,material_allowance
from regression_support import add_reads
from consensus_assurance.workflow.inquiry import enqueue,process_task,validate_review
from consensus_assurance.workflow.errors import Blocked
from consensus_assurance.adapters.storage.snapshot import capture
from test_graph_mutations import controller


def dependency(dependency_prepared):
    repo,state,_,_=dependency_prepared
    (repo/'new_helper.py').write_text('def boundary(value):\n    return max(1, value)\n')
    state.snapshot=capture(repo)
    added=add_reads(state,repo,ReadingPlan(requests=[{'file':'new_helper.py','start_line':1,'end_line':2,'reason':'Read a previously absent provider'}],rationale='Actual new dependency'),__import__('consensus_assurance.core.config',fromlist=['Budget']).Budget())
    u=state.units[0];basis=state.relations[0].grounding.model_copy(deep=True)
    b=BindingDraft(id='fresh_provider',associations=[dict(claim_id=u.obligation_ids[0],source_ids=[added[0]],rationale='Selected fixture operation')],material_id=added[0],symbol='boundary',start_line=1,end_line=2,description='New supporting producer',pending=['Guarantee not checked'])
    edge=RelationDraft(id='fresh_dependency',source=u.obligation_ids[0],target=b.id,kind='boundary',group=None,rationale='The selected computation consumes the actual provider',pending=['Provider guarantee unverified'],grounding=basis)
    draft=UnitDraft(**{k:v for k,v in u.model_dump().items() if k in UnitDraft.model_fields})
    draft.binding_ids.append(b.id);draft.relation_ids.append(edge.id)
    return state,GraphPatch(bindings=[b],relations=[edge],units=[draft],expected_versions={u.id:u.version},rationale='Reconnect newly read producer'),added


def test_new_dependency_requires_executable_scope_continuation(dependency_prepared):
    state,patch,_=dependency(dependency_prepared);before=state.model_dump()
    with pytest.raises(ValueError):apply_patch(state,patch)
    assert state.model_dump()==before
    from consensus_assurance.workflow.scope_updates import from_patch,apply_scope_update
    update=from_patch(state,state.units[0],patch)
    new=apply_scope_update(state,update)
    assert 'fresh_provider' in new.binding_ids and new.obligation_ids==state.units[-1].obligation_ids


def test_F3_is_possible_before_first_model(dependency_prepared):
    _,state,_,_=dependency_prepared;u=state.units[0]
    f=Feedback(kind='F3',rationale='Inspect an actual dependency before building',evidence_ids=[state.materials[0].id],target_ids=[u.id],relation_ids=['input_dependency'],new_basis='',graph=None,bundle=None)
    result=apply_feedback(state,u,None,f)
    assert result.previous_id==u.id


def test_specific_issue_resolution_can_preserve_independent_limit(dependency_prepared):
    _,state,_,_=dependency_prepared;c=state.claims[1]
    issue=ReviewIssue(id='caller_missing',review_id='old',target_id=c.id,target_version=c.version,aspect='applicability',source_ids=c.source_ids,explanation='The caller has not been located',disposition='reading',reason='Locate the caller')
    state.review_issues.append(issue)
    task=enqueue(state,'review','Resolve the caller question','test',target_ids=[c.id])
    items=[SemanticCheck(target_id=c.id,aspect=a,status='no_issue_found',source_ids=c.source_ids,limitations=['Disk crash persistence remains unexamined'],rationale='The actual caller is now located' + "\n" + 'Other callers remain possible' + "\n" + 'Caller identity alone does not prove persistence') for a in ('applicability','decomposition')]
    # This old shape demonstrates why an explicit issue-specific disposition is needed.
    reply=ReviewReply(items=items,resolves_issue_ids=[issue.id],resolution_rationale='The supplied caller material resolves the identity question',limitations=[])
    # New explicit disposition retains the old issue and separates the independent boundary.
    from consensus_assurance.core.proposals import IssueResolution
    reply.resolutions=[IssueResolution(issue_id=issue.id,target_version=issue.target_version,original_question=issue.explanation,source_ids=c.source_ids,rationale='Actual supplied producer/caller references answer the located-identity question; no storage promise is inferred',residual_issue_ids=[],scope_limitations=items[0].limitations)]
    validate_review(state,task,reply)


def test_unsent_context_does_not_spend_exploration(tmp_path,dependency_prepared):
    repo,state,_,_=dependency_prepared;e=controller(tmp_path,state);e.config.budget.context_chars=1000
    import shutil
    shutil.copytree(repo,e.root/'source')
    task=enqueue(state,'spec_refine','Investigate actual responsibilities','oversize')
    with pytest.raises(Blocked) as error:process_task(e,task)
    packet=state.packet_receipts[-1]
    assert f"spec_refine: {packet['prompt_chars']} > 1000" in str(error.value)
    assert packet['status']=='blocked_context_limit'
    assert state.usage.get('exploration_rounds',0)==0
    assert state.usage.get('agent_calls',0)==0


def test_deferred_local_dependency_keeps_reserve(tmp_path,dependency_prepared):
    _,state,_,_=dependency_prepared;e=controller(tmp_path,state);state.completed_steps.append('discovery')
    for u in state.units:u.status='blocked'
    state.deferred_units[state.units[0].id]={'next_action':'build','targeted_gap':{'stage':'read'},'reason':'Waiting for actual dependency'}
    allowance=material_allowance(state,e.config.budget,'breadth')
    assert allowance['reserved_for_other_chars']>0


def test_dependency_traversal_does_not_depend_on_list_order(dependency_prepared):
    _,state,_,_=dependency_prepared;first=next(e for e in state.relations if e.id=='input_dependency')
    second=first.model_copy(deep=True);second.id='second_edge';second.source=first.target;second.target='input_binding'
    state.relations.insert(0,second)
    a=state.model_copy(deep=True);b=state.model_copy(deep=True);b.relations.reverse()
    x=expand_unit(a,a.units[0],[first.id,second.id]);y=expand_unit(b,b.units[0],[first.id,second.id])
    assert x.binding_ids==y.binding_ids and x.obligation_ids==y.obligation_ids
