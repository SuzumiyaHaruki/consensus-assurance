"""Regression shape extracted from runs/2026-09-18_12-10-35-hashicorp_raft-real-run.
Synthetic source preserves the F5 reserve/partial-read failure without runtime answers.
"""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.types import AuditQuestion,ReadRequest,InquiryTask,Behavior,Fact
from consensus_assurance.core.proposals import Derivation,SpecRefinement,DescriptiveIssue
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow import discovery
from consensus_assurance.workflow.audit_spec import accept,load
from consensus_assurance.workflow.materials import ReadingPlan,validate_read_requests,material_allowance
from consensus_assurance.workflow.inquiry import read_purpose
from consensus_assurance.adapters.storage.snapshot import capture
from test_graph_mutations import controller
from test_audit_capabilities import inventory


@pytest.fixture
def focused(tmp_path,prepared):
    repo,state,_,responses=prepared
    e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    state.claims=[];state.units=[];state.bindings=[];state.relations=[]
    source=state.materials[0].id
    accept(e,inventory(source))
    q=AuditQuestion(question='Can a late success hide an earlier failed publication?',importance='History remains recoverable',source_ids=[source],activity_classes=['A1','A5'],behavior_ids=['producer','consumer'],fact_ids=['fact'],obligation_relation_kind='consumption',preferred_check='source_review',disposition='needs_specific_evidence',counterevidence=['Caller propagates an original error'],unknowns=['Caller contract still unread'],trigger_rationale='Inspect the remaining caller discriminator')
    return e,q,responses


def request(name):return ReadRequest(file=name,start_line=1,end_line=1,reason='Resolve caller semantics')


def sources(e,**files):
    for name,n in files.items():(e.root/'source'/name).write_text('x'*(n-1)+'\n')
    e.state.snapshot=capture(e.root/'source')
    used=material_allowance(e.state,e.config.budget,'depth')['unique_chars']
    e.config.budget.material_chars=used+1500
    e.state.config=e.config.model_dump(mode='json')
    return used


def begin(e,q,requests):
    reply=Derivation(audit_question=q,reading_requests=requests,selection_rationale='Inspect this candidate before asserting a contract')
    assert not discovery.accept_derivation(e,reply,'select')
    return discovery.active_candidate(e.state)


def test_pre_obligation_depth_and_background_breadth(focused):
    e,q,_=focused;sources(e,dependency=1000)
    request_size=1000
    assert material_allowance(e.state,e.config.budget,'breadth')['available_chars']<request_size<material_allowance(e.state,e.config.budget,'depth')['available_chars']
    candidate=begin(e,q,[request('dependency')])
    discovery.continue_candidate(e,candidate)
    receipt=e.state.read_plans[candidate.read_plan_id]
    assert receipt['purpose']=='depth' and receipt['status']=='complete'
    assert not e.state.units and not e.state.claims and not e.state.inquiry_tasks
    assert read_purpose(InquiryTask(kind='spec_refine',reason='Background inventory',trigger='background'))=='breadth'
    assert read_purpose(InquiryTask(kind='spec_refine',reason='Selected correction',trigger='opaque',candidate_id=candidate.id))=='depth'


@pytest.mark.parametrize('kind',['plan','derive','spec','question','repair','review'])
def test_all_request_responses_preflight_exact_union(focused,kind):
    e,q,_=focused;sources(e,dependency=2000)
    req=request('dependency')
    if kind=='plan':reply=ReadingPlan(requests=[req],rationale='Source')
    elif kind=='derive':reply=Derivation(audit_question=q,reading_requests=[req],selection_rationale='Source')
    elif kind=='spec':reply=SpecRefinement(understanding='Correct the inventory',requests=[req],limitations=[])
    elif kind=='question':reply=q.model_copy(update={'requests':[req]})
    elif kind=='repair':
        from consensus_assurance.workflow.output_repair import OutputRepair
        reply=OutputRepair(requests=[req],rationale='Source')
    else:
        from consensus_assurance.core.proposals import ReviewReply
        reply=ReviewReply(requests=[req],items=[{'target_id':'candidate','aspect':'applicability','status':'needs_reading','source_ids':q.source_ids,'rationale':'Inspect the caller contract'}],limitations=[])
    with pytest.raises(DiagnosticError) as caught:validate_read_requests(e.state,e.root/'source',reply,purpose='depth')
    d=caught.value.diagnostics[0]
    assert d.code=='reading_plan_budget' and d.details['projected_new_chars']==2000
    assert d.details['purpose']=='depth' and d.details['available_chars']==1500
    assert not e.state.usage.get('targeted_reads')


def test_partial_receipt_reaches_reasoning_then_explained(focused,tmp_path):
    e,q,_=focused;sources(e,A=500,B=1100,C=100)
    candidate=begin(e,q,[request('A'),request('B'),request('C')])
    discovery.continue_candidate(e,candidate)
    packet=discovery.derive_context(e)
    assert [i['status'] for i in packet['source_receipt']['items']]==['acquired','deferred','deferred']
    assert any(m['file']=='A' for m in packet['materials'])
    assert not any(m['file'] in {'B','C'} for m in packet['materials'])
    assert candidate.status=='active' and candidate.stage=='analyze'
    close=q.model_copy(update={'disposition':'explained_by_existing_mechanism','source_ids':['A:1:1'], 'counterevidence':['Acquired caller propagates the first error'], 'unknowns':[]})
    discovery.accept_derivation(e,Derivation(audit_question=close,selection_rationale='Existing caller protection explains this scoped path'),'explain')
    c=e.state.question_candidates[0]
    assert c.status=='explained' and len(c.history)==1 and not discovery.active_candidate(e.state)
    assert 'Caller contract still unread' in c.question.unknowns and q.counterevidence[0] in c.question.counterevidence
    assert not e.state.claims and not e.state.units and not e.state.models and not e.state.direct_checks and not e.state.evidence
    from consensus_assurance.reporting.chinese import render_report
    (tmp_path/'report').mkdir()
    report=render_report(e.state,tmp_path/'report').read_text()
    assert '候选问题与已有保护' in report and 'Acquired caller propagates' in report and 'Caller contract still unread' in report


def test_zero_progress_is_bounded_and_not_charged(focused):
    e,q,_=focused;sources(e,B=2000)
    c=begin(e,q,[request('B')])
    discovery.continue_candidate(e,c)
    assert discovery.derive_context(e)['source_receipt']['status']=='deferred'
    assert c.status=='active' and not e.state.usage.get('targeted_reads')
    again=Derivation(audit_question=q,reading_requests=[request('B')],selection_rationale='Still missing')
    discovery.accept_derivation(e,again,'repeat')
    discovery.continue_candidate(e,discovery.active_candidate(e.state))
    assert e.state.question_candidates[0].status=='blocked' and not e.state.usage.get('targeted_reads')


def test_escalation_preserves_identity_and_protections_without_relation(focused):
    from regression_support import bounded_derivation
    e,q,responses=focused
    begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Check actual step')])
    reply=Derivation.model_validate(bounded_derivation(responses[1]));reply.audit_question=q.model_copy(update={'requests':[],'preferred_check':'local_model','disposition':'ready_for_check','counterevidence':[]})
    discovery.accept_derivation(e,reply,'escalate')
    assert len(e.state.units)==1 and len(e.state.claims)==1 and not e.state.relations
    c=e.state.question_candidates[0]
    assert c.status=='escalated' and c.question.fact_ids==q.fact_ids and c.question.counterevidence==q.counterevidence
    assert e.state.units[0].audit_question.counterevidence==q.counterevidence


@pytest.mark.parametrize('selected',[True,False])
def test_descriptive_debt_routes_by_selected_objects(focused,selected):
    e,q,_=focused
    spec=load(e.state)
    spec.behaviors.append(Behavior(id='unrelated',primary_activity='A2',execution_owner='other loop',protocol_context='independent',trigger='timer',source_ids=q.source_ids))
    accept(e,spec)
    issue=DescriptiveIssue(object_ids=['consumer' if selected else 'unrelated'],source_ids=q.source_ids,reason='Correct the owner from source')
    reply=Derivation(audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read selected behavior')],descriptive_issues=[issue],selection_rationale='Continue selected question')
    discovery.accept_derivation(e,reply,'issue')
    c=discovery.active_candidate(e.state);task=e.state.inquiry_tasks[0]
    assert bool(c.spec_task_ids)==selected and (read_purpose(task)=='depth')==selected
    if selected:
        from consensus_assurance.adapters.agents.backend import MockAgent
        revised=load(e.state);revised.behaviors[1].execution_owner='serialized callback'
        agent=MockAgent();agent.responses=[SpecRefinement(understanding='Correct selected owner without changing fact meaning',audit_spec=revised,limitations=[]).model_dump(mode='json')];e.agent=agent
        discovery.continue_candidate(e,c)
        assert load(e.state).behaviors[1].execution_owner=='serialized callback'
        assert discovery.active_candidate(e.state).question.fact_ids==q.fact_ids
        assert e.state.inquiry_tasks[0].status=='completed'
    else:
        discovery.continue_candidate(e,c)
        assert task.status=='pending' and c.stage=='analyze'


def test_selected_packet_excludes_independent_subgraph_and_keeps_sources(focused):
    e,q,_=focused
    spec=load(e.state)
    spec.behaviors.append(Behavior(id='other',primary_activity='A2',execution_owner='independent',protocol_context='other',trigger='timer',produces_fact_ids=['other_fact'],source_ids=q.source_ids))
    spec.facts.append(Fact(id='other_fact',meaning='An independent result',identity={'other':'operation'},validity_context='other',established_by=['other'],representation=['field'],durability='volatile',recovery='discarded',unknowns=['Consumer unknown'],source_ids=q.source_ids))
    accept(e,spec);begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Inspect')])
    packet=discovery.derive_context(e)
    assert {f['id'] for f in packet['audit_spec']['facts']}=={'fact'}
    assert {b['id'] for b in packet['audit_spec']['behaviors']}=={'producer','consumer'}
    assert set(packet['required_material_ids'])<={m['id'] for m in packet['materials']}
    assert packet['selected_question']['counterevidence']==q.counterevidence
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.workflow.prompts import render
    packet,_=prepare(e,'derive',packet)
    assert len(render('derive',pool_sources(packet),e.inquiry))<e.config.budget.context_chars


def test_selected_run_preserves_unresolved_candidate_and_failure(tmp_path):
    from consensus_assurance.workflow.history import load_analysis
    from consensus_assurance.reporting.chinese import render_report
    archive=Path(__file__).resolve().parents[2]/'runs/2026-09-18_13-43-11-hashicorp_raft-real-run'
    before={name:(archive/name).read_bytes() for name in ['state.json','report.md']}
    state=load_analysis(archive/'state.json')
    assert len(state.question_candidates)==1 and not state.claims
    assert state.question_candidates[0].status=='active'
    (tmp_path/'offline').mkdir()
    report=render_report(state,tmp_path/'offline').read_text()
    assert 'Explicit semantic/scope plan requested' in report and 'F_SNAPSHOT_RECORDED' in report
    assert all((archive/name).read_bytes()==data for name,data in before.items())


def test_resumed_partial_continuation_explains_then_selects_next(focused):
    from consensus_assurance.core.types import Analysis,CheckRun,ExecutionStatus
    e,q,_=focused;sources(e,A=500,B=1100,C=100)
    begin(e,q,[request('A'),request('B'),request('C')])
    # Resume from serialized controller state, not an in-memory-only focus.
    e.state=Analysis.model_validate_json(e.state.model_dump_json())
    seen=[]
    def ask(kind,response_type,packet,validator=None,**kwargs):
        seen.append(packet)
        assert kwargs['purpose']=='depth'
        if len(seen)==2:
            assert packet['candidate_dispositions'][0]['status']=='explained' and 'selected_question' not in packet
            raise RuntimeError('Next candidate selection reached')
        assert packet['selected_question']['fact_ids']==['fact']
        assert [i['status'] for i in packet['source_receipt']['items']]==['acquired','deferred','deferred']
        reply=Derivation(audit_question=q.model_copy(update={'disposition':'explained_by_existing_mechanism','counterevidence':['The acquired caller returns the original error'],'source_ids':['A:1:1']}),selection_rationale='Source explains the scoped suspicion')
        validator(reply)
        return reply,CheckRun(id='closed',action='agent',status=ExecutionStatus.COMPLETED,cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask
    with pytest.raises(RuntimeError,match='Next candidate'):discovery.derive(e)
    assert not e.state.claims and not e.state.units and not e.state.models
    assert e.state.question_candidates[0].status=='explained' and not e.state.inquiry_tasks


def test_budget_repair_changes_only_requests_and_keeps_focus(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused;sources(e,large=2000,small=200)
    response=Derivation(audit_question=q,reading_requests=[request('large')],selection_rationale='Inspect the decisive source')
    agent=MockAgent();agent.responses=[response.model_dump(mode='json'),{'replacements':[{'path':'/reading_requests','value_json':json.dumps([request('small').model_dump(mode='json')])}],'rationale':'Use the precise caller range within the depth allowance'}];e.agent=agent
    reply,_=discovery.ask_derivation(e,discovery.derive_context(e))
    assert reply.audit_question==q and reply.reading_requests[0].file=='small'
    assert e.state.usage['agent_calls']==2 and not e.state.usage.get('targeted_reads')
    session=next(iter(e.state.repair_sessions.values()))
    assert session['status']=='accepted'


def test_fact_or_lifecycle_cannot_silently_change(focused):
    e,q,_=focused;begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read')])
    reply=Derivation(audit_question=q.model_copy(update={'obligation_relation_kind':'recovery'}),reading_requests=[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read')],selection_rationale='Different lifecycle')
    with pytest.raises(DiagnosticError,match='Finish the current candidate'):discovery.validate_derivation(e.state,reply)


def test_new_cached_attachments_are_progress_without_acquisition_charge(focused):
    e,q,_=focused
    for n,(a,b) in enumerate([(1,2),(3,4),(1,4),(1,4)]):
        reply=Derivation(audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=a,end_line=b,reason='Inspect the next cached caller segment')],selection_rationale='Resolve the same caller discriminator')
        discovery.accept_derivation(e,reply,'cached-'+str(n))
        discovery.continue_candidate(e,discovery.active_candidate(e.state))
        candidate=e.state.question_candidates[0]
        assert candidate.status==('blocked' if n==3 else 'active')
        assert not e.state.usage.get('targeted_reads')
