"""Regression shape extracted from runs/2026-09-18_12-10-35-hashicorp_raft-real-run.
Synthetic source preserves the F5 reserve/partial-read failure without runtime answers.
"""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.types import AuditQuestion,ReadRequest,InquiryTask,Behavior,Fact
from consensus_assurance.core.proposals import Derivation,AuditSpecDelta,SpecRefinement,DescriptiveIssue
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
    from consensus_assurance.workflow.task_packet import receipt
    receipt(e,'derive',{'materials':[m.model_dump(mode='json') for m in e.state.materials]},'offline source',Derivation)
    return e,q,responses


def selected_packet(e):
    from consensus_assurance.workflow.task_packet import prepare
    return prepare(e,'derive',discovery.derive_context(e))[0]


def current_id(e):return getattr(discovery.active_candidate(e.state),'id',None)


def request(name):return ReadRequest(file=name,start_line=1,end_line=1,reason='Resolve caller semantics')


def sources(e,**files):
    for name,n in files.items():(e.root/'source'/name).write_text('x'*(n-1)+'\n')
    e.state.snapshot=capture(e.root/'source')
    used=material_allowance(e.state,e.config.budget,'depth')['unique_chars']
    e.config.budget.material_chars=used+1500
    e.state.config=e.config.model_dump(mode='json')
    return used


def begin(e,q,requests):
    reply=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=requests,selection_rationale='Inspect this candidate before asserting a contract')
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


def test_partial_receipt_reaches_reasoning_then_explained(focused,tmp_path):
    e,q,_=focused;sources(e,A=500,B=1100,C=100)
    candidate=begin(e,q,[request('A'),request('B'),request('C')])
    discovery.continue_candidate(e,candidate)
    packet=selected_packet(e)
    assert [i['status'] for i in packet['source_receipt']['items']]==['acquired','deferred','deferred']
    assert any(m['file']=='A' for m in packet['materials'])
    assert not any(m['file'] in {'B','C'} for m in packet['materials'])
    assert candidate.status=='active' and candidate.stage=='analyze'
    close=q.model_copy(update={'disposition':'explained_by_existing_mechanism','source_ids':['A:1:1'], 'counterevidence':['Acquired caller propagates the first error'], 'unknowns':[]})
    discovery.accept_derivation(e,Derivation(candidate_id=current_id(e),audit_question=close,selection_rationale='Existing caller protection explains this scoped path'),'explain')
    c=e.state.question_candidates[0]
    assert c.status=='explained' and len(c.history)==1 and not discovery.active_candidate(e.state)
    assert not c.question.unknowns and c.history[0].unknowns==q.unknowns and c.history[0].counterevidence==q.counterevidence
    assert not e.state.claims and not e.state.units and not e.state.models and not e.state.direct_checks and not e.state.evidence
    from consensus_assurance.reporting.chinese import render_report
    (tmp_path/'report').mkdir()
    report=render_report(e.state,tmp_path/'report').read_text()
    assert '候选问题与已有保护' in report and 'Acquired caller propagates' in report and 'Caller contract still unread' not in report


def test_zero_progress_is_bounded(focused):
    e,q,_=focused;sources(e,B=2000)
    c=begin(e,q,[request('B')])
    discovery.continue_candidate(e,c)
    assert selected_packet(e)['source_receipt']['status']=='deferred'
    assert c.status=='active'
    again=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=[request('B')],selection_rationale='Still missing')
    discovery.accept_derivation(e,again,'repeat')
    discovery.continue_candidate(e,discovery.active_candidate(e.state))
    assert e.state.question_candidates[0].status=='blocked'


def test_escalation_preserves_identity_and_protections_without_relation(focused):
    from regression_support import bounded_derivation
    e,q,responses=focused
    begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Check actual step')])
    reply=Derivation.model_validate(bounded_derivation(responses[1]));reply.candidate_id=current_id(e);reply.audit_question=q.model_copy(update={'requests':[],'preferred_check':'local_model','disposition':'ready_for_check','counterevidence':q.counterevidence})
    discovery.accept_derivation(e,reply,'escalate')
    assert len(e.state.units)==1 and len(e.state.claims)==1 and not e.state.relations
    c=e.state.question_candidates[0]
    assert c.status=='escalated' and c.question.fact_ids==q.fact_ids and c.question.counterevidence==q.counterevidence
    assert e.state.units[0].audit_question.counterevidence==q.counterevidence
    assert 'derived-spec:'+str(e.state.audit_spec_version) not in e.state.completed_steps
    # Once the ready unit has its disposition, the same inventory can select another question.
    e.state.units[0].status='checked'
    alternate=q.model_copy(update={'question':'Can a later writer republish an invalidated entry?'})
    discovery.accept_derivation(e,Derivation(audit_question=alternate,reading_requests=[request('counter.py')],selection_rationale='The next supported discriminator concerns a later writer'),'select-next')
    later=discovery.active_candidate(e.state)
    assert later.id!=c.id and later.question.question==alternate.question
    assert len(e.state.question_candidates)==2 and c.question.counterevidence==q.counterevidence


@pytest.mark.parametrize('selected',[True,False])
def test_descriptive_debt_routes_by_selected_objects(focused,selected):
    e,q,_=focused
    spec=load(e.state)
    spec.behaviors.append(Behavior(id='unrelated',primary_activity='A2',execution_owner='other loop',protocol_context='independent',trigger='timer',source_ids=q.source_ids))
    accept(e,spec)
    issue=DescriptiveIssue(candidate_effect='requires_recheck' if selected else 'independent_enrichment',object_ids=['consumer' if selected else 'unrelated'],source_ids=q.source_ids,reason='Correct the owner from source')
    reply=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read selected behavior')],descriptive_issues=[issue],selection_rationale='Continue selected question')
    discovery.accept_derivation(e,reply,'issue')
    c=discovery.active_candidate(e.state);task=e.state.inquiry_tasks[0]
    assert bool(c.spec_task_ids)==selected and read_purpose(task)=='depth'
    if selected:
        from consensus_assurance.adapters.agents.backend import MockAgent
        (e.root/'source'/'callback.py').write_text('def completed():\n    return True\n');e.state.snapshot=capture(e.root/'source')
        revised=load(e.state);revised.behaviors[1].execution_owner='serialized callback';revised.behaviors[1].source_ids=['callback.py:1:2']
        agent=MockAgent();agent.responses=[SpecRefinement(understanding='Read the decisive callback owner',requests=[ReadRequest(file='callback.py',start_line=1,end_line=2,reason='Resolve selected correction')],limitations=[]).model_dump(mode='json'),SpecRefinement(understanding='Correct selected owner without changing fact meaning',delta=AuditSpecDelta(behaviors=[revised.behaviors[1]],rationale='Correct the selected owner'),limitations=[]).model_dump(mode='json')];e.agent=agent
        discovery.continue_candidate(e,c)
        assert load(e.state).behaviors[1].execution_owner=='serialized callback'
        assert discovery.active_candidate(e.state).question.fact_ids==q.fact_ids
        assert e.state.inquiry_tasks[0].status=='completed'
        assert 'callback.py:1:2' in {m['id'] for m in selected_packet(e)['materials']}
        assert 'callback.py:1:2' not in q.source_ids  # Reconnection transmits correction evidence without rewriting the prior question.
    else:
        discovery.continue_candidate(e,c)
        assert task.status=='pending' and c.stage=='analyze'


def test_selected_packet_excludes_independent_subgraph_and_keeps_sources(focused):
    e,q,_=focused
    spec=load(e.state)
    spec.behaviors.append(Behavior(id='other',primary_activity='A2',execution_owner='independent',protocol_context='other',trigger='timer',produces_fact_ids=['other_fact'],source_ids=q.source_ids))
    spec.facts.append(Fact(id='other_fact',meaning='An independent result',identity={'other':'operation'},validity_context='other',established_by=['other'],representation=['field'],durability='volatile',recovery='discarded',unknowns=['Consumer unknown'],source_ids=q.source_ids))
    accept(e,spec);begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Inspect')])
    expected_question=discovery.active_candidate(e.state).question.model_dump(mode='json')
    packet=selected_packet(e)
    assert {f['id'] for f in packet['audit_spec']['facts']}=={'fact'}
    assert {b['id'] for b in packet['audit_spec']['behaviors']}=={'producer','consumer'}
    assert set(packet['required_material_ids'])<={m['id'] for m in packet['materials']}
    assert packet['selected_question']==expected_question and 'focus' not in packet
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.workflow.prompts import render
    assert packet['selected_question']==expected_question and 'focus' not in packet
    assert set(packet['required_material_ids'])<={m['id'] for m in packet['materials']}
    assert len(render('derive',pool_sources(packet),e.inquiry))<e.config.budget.context_chars


def test_v6_controller_state_cannot_resume_under_v7(focused):
    from types import SimpleNamespace
    e,_,_=focused
    e.state.framework_revision='selected-question-v6'  # Explicit compatibility fixture, not an archive rewrite.
    e.store=SimpleNamespace(load=lambda:e.state)
    usage=dict(e.state.usage)
    assert 'Framework revision differs' in e.resume().stop_reason
    assert e.state.usage==usage


def test_resumed_partial_continuation_explains_then_selects_next(focused):
    from consensus_assurance.core.types import Analysis,CheckRun,ExecutionStatus
    e,q,_=focused;sources(e,A=500,B=1100,C=100)
    begin(e,q,[request('A'),request('B'),request('C')])
    # Resume from serialized controller state, not an in-memory-only focus.
    e.state=Analysis.model_validate_json(e.state.model_dump_json())
    seen=[]
    def ask(kind,response_type,packet,validator=None,**kwargs):
        from consensus_assurance.workflow.task_packet import prepare
        packet,_=prepare(e,kind,packet)
        seen.append(packet)
        assert kwargs['purpose']=='depth'
        if len(seen)==2:
            assert packet['candidate_dispositions'][0]['status']=='explained' and 'selected_question' not in packet
            raise RuntimeError('Next candidate selection reached')
        assert packet['selected_question']['fact_ids']==['fact']
        assert [i['status'] for i in packet['source_receipt']['items']]==['acquired','deferred','deferred']
        reply=Derivation(candidate_id=current_id(e),audit_question=q.model_copy(update={'disposition':'explained_by_existing_mechanism','counterevidence':['The acquired caller returns the original error'],'source_ids':['A:1:1']}),selection_rationale='Source explains the scoped suspicion')
        validator(reply)
        return reply,CheckRun(id='closed',action='agent',status=ExecutionStatus.COMPLETED,cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask
    discovery.derive(e)
    assert len(seen)==1 and e.state.last_work_kind=='candidate'
    with pytest.raises(RuntimeError,match='Next candidate'):discovery.derive(e)
    assert not e.state.claims and not e.state.units and not e.state.models
    assert e.state.question_candidates[0].status=='explained' and not e.state.inquiry_tasks


def test_new_cached_attachments_are_progress(focused):
    e,q,_=focused
    for n,(a,b) in enumerate([(1,2),(3,4),(1,4),(1,4)]):
        reply=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=a,end_line=b,reason='Inspect the next cached caller segment')],selection_rationale='Resolve the same caller discriminator')
        discovery.accept_derivation(e,reply,'cached-'+str(n))
        discovery.continue_candidate(e,discovery.active_candidate(e.state))
        candidate=e.state.question_candidates[0]
        assert candidate.status==('blocked' if n==3 else 'active')


def test_no_local_normative_basis_remains_evidence_blocked(focused,tmp_path):
    """13:43:11 shape: concrete source exhausted, responsibility still unattributed."""
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused
    candidate=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review the caller')])
    discovery.continue_candidate(e,candidate)
    reply=Derivation(candidate_id=current_id(e),audit_question=q.model_copy(update={'unknowns':['Applicable contract does not assign error propagation']}),selection_rationale='Caller and interface sources were reviewed; no exact remaining range can assign this responsibility')
    agent=MockAgent();agent.responses=[reply.model_dump(mode='json')];e.agent=agent
    result,check=discovery.ask_derivation(e,discovery.derive_context(e))
    assert discovery.validate_derivation(e.state,result)=='blocked_evidence'
    assert not discovery.accept_derivation(e,result,check.id)
    c=e.state.question_candidates[0]
    assert c.status=='blocked' and c.stage=='analyze' and c.stop_reason==reply.selection_rationale
    assert c.history and q.counterevidence[0] in c.question.counterevidence and q.unknowns[0] in c.history[0].unknowns and q.unknowns[0] not in c.question.unknowns
    assert not discovery.active_candidate(e.state)
    assert not e.state.claims and not e.state.units and not e.state.models and not e.state.evidence
    assert e.state.pending_output_repair is None and not e.state.repair_sessions and e.state.usage['agent_calls']==1
    from consensus_assurance.reporting.chinese import render_report
    report=render_report(e.state,e.root).read_text()
    assert '受阻 evidence_blocked' in report and reply.selection_rationale in report


@pytest.mark.parametrize('invalid',['initial_block','active_exhausted','unreviewed_block','unknowns_empty','wrong_check','ready_without_obligation','blank_reason'])
def test_incomplete_or_premature_outcome_is_not_an_escape(focused,invalid):
    e,q,_=focused
    if invalid not in {'initial_block','initial_exhausted'}:
        c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review')])
        if invalid!='unreviewed_block':discovery.continue_candidate(e,c)
    reply=Derivation(candidate_id=current_id(e),audit_question=q,selection_rationale='No remaining justified contract source')
    if invalid.endswith('exhausted'):reply.audit_question=None;reply.candidate_id=None
    if invalid=='unknowns_empty':reply.audit_question=q.model_copy(update={'unknowns':[]})
    if invalid=='wrong_check':reply.audit_question=q.model_copy(update={'preferred_check':'local_model'})
    if invalid=='ready_without_obligation':reply.audit_question=q.model_copy(update={'disposition':'ready_for_check'})
    if invalid=='blank_reason':reply.selection_rationale=' '
    with pytest.raises(DiagnosticError):discovery.validate_derivation(e.state,reply)
    assert not e.state.claims and not e.state.units


def test_selection_exhausts_after_disposition(focused):
    e,q,_=focused;c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review')])
    discovery.continue_candidate(e,c)
    discovery.accept_derivation(e,Derivation(candidate_id=current_id(e),audit_question=q,selection_rationale='Applicable responsibility is not established'),'block')
    end=Derivation(candidate_id=current_id(e),selection_rationale='No additional bounded discriminator is supported by current inventory/source')
    assert discovery.validate_derivation(e.state,end)=='selection_exhausted'
    assert discovery.accept_derivation(e,end,'finish')
    discovery.derive(e)  # The same inventory is not asked to select again after resume.
    assert len(e.state.question_candidates)==1 and e.state.gaps[-1].endswith(end.selection_rationale)
    assert not e.state.pending_output_repair and not e.state.claims and not e.state.units


def test_unrelated_reusable_feedback_survives_evidence_blocked_outcome(focused):
    from consensus_assurance.workflow.inquiry import choose_task
    e,q,_=focused;c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review the selected source')])
    discovery.continue_candidate(e,c)
    version=e.state.audit_spec_version
    reply=Derivation(candidate_id=current_id(e),audit_question=q,descriptive_issues=[DescriptiveIssue(candidate_effect='independent_enrichment',object_ids=['A7'],source_ids=q.source_ids,reason='Source exposes an unrepresented recovery execution owner; inspect that reusable boundary')],selection_rationale='The selected contract remains unattributed without a justified next range')
    assert discovery.validate_derivation(e.state,reply)=='blocked_evidence'
    discovery.accept_derivation(e,reply,'blocked-with-feedback')
    assert e.state.question_candidates[0].status=='blocked' and e.state.audit_spec_version==version
    task=choose_task(e)
    assert task.target_ids==['A7'] and task.candidate_id is None and task.diagnostics


def test_three_narrowings_keep_history_out_of_current_packet(focused):
    e,q,_=focused
    q.unknowns=['First caller','Second caller','Remaining contract']
    c=begin(e,q,[request('counter.py')]);original=q.model_dump(mode='json')
    for n in range(3):
        narrowed=q.model_copy(update={'unknowns':q.unknowns[n+1:]})
        discovery.accept_derivation(e,Derivation(candidate_id=current_id(e),audit_question=narrowed,reading_requests=[request('counter.py')],selection_rationale='Resolve one specific caller discriminator'),f'narrow-{n}')
    c=discovery.active_candidate(e.state)
    assert len(c.history)==3 and not c.question.unknowns and c.history[0].unknowns==original['unknowns']
    packet=selected_packet(e)
    assert not packet['selected_question']['unknowns'] and 'history' not in packet


def test_episode_admission_and_blockage_classification(focused):
    from consensus_assurance.workflow.budget import can_start_episode
    from consensus_assurance.workflow.discovery import candidate_blockage
    from consensus_assurance.workflow.inquiry import enqueue,inquiry_resource
    from consensus_assurance.workflow.engine import FRAMEWORK_REVISION
    from consensus_assurance.workflow.prompts import manifest
    e,q,_=focused;e.state.usage['agent_calls']=e.state.config['budget']['agent_calls']-1
    assert not can_start_episode(e.state,'candidate') and not can_start_episode(e.state,'surface')
    c=begin(e,q,[request('counter.py')]);c.stage='analyze'
    assert can_start_episode(e.state,'candidate') and not can_start_episode(e.state,'surface')
    c.status='blocked';c.question.requests=[]
    assert candidate_blockage(e.state,c)=='evidence_blocked'
    task=enqueue(e.state,'spec_refine','Correct the selected producer','depth',target_ids=['producer']);task.status='blocked';c.spec_task_ids=[task.id]
    assert candidate_blockage(e.state,c)=='workflow_blocked' and inquiry_resource(task) is None
    surface=enqueue(e.state,'spec_refine','Find another owner','surface',surface_entry_points=['other'])
    assert inquiry_resource(surface)=='exploration_rounds'
    c.spec_task_ids=[];c.status='active';e.state.usage['agent_calls']+=1
    assert candidate_blockage(e.state,c)=='resource_blocked'
    assert FRAMEWORK_REVISION==manifest()['version']


@pytest.mark.parametrize('decision,effect,empty,expected',[
    ('read',None,True,'active'),('read',None,False,'active'),
    ('explained',None,True,'question_source_missing'),('explained',None,False,'explained'),
    ('explained','independent_enrichment',False,'explained'),('explained','requires_recheck',False,'active'),
    ('blocked','independent_enrichment',False,'blocked'),('escalate','independent_enrichment',False,'escalated')])
def test_candidate_decision_and_feedback_are_orthogonal(focused,decision,effect,empty,expected):
    from regression_support import bounded_derivation
    e,q,responses=focused
    c=begin(e,q,[request('counter.py')]);discovery.continue_candidate(e,c)
    q=q.model_copy(update={'source_ids':[] if empty else q.source_ids})
    reply=Derivation(candidate_id=current_id(e),audit_question=q,selection_rationale='Actual selected source determines the scoped result')
    if decision=='read':reply.reading_requests=[request('counter.py')]
    elif decision=='explained':q.disposition='explained_by_existing_mechanism'
    elif decision=='escalate':
        reply=Derivation.model_validate(bounded_derivation(responses[1]));reply.candidate_id=current_id(e);reply.audit_question=q
    if effect:reply.descriptive_issues=[DescriptiveIssue(candidate_effect=effect,object_ids=['consumer'],source_ids=e.state.materials[:1] and [e.state.materials[0].id],reason='The selected source exposes reusable consumer detail')]
    if expected.startswith('question_'):
        with pytest.raises(DiagnosticError) as exc:discovery.accept_derivation(e,reply,'matrix')
        assert exc.value.diagnostics[0].code==expected
        return
    discovery.accept_derivation(e,reply,'matrix')
    c=e.state.question_candidates[0]
    assert c.status==expected and bool(c.spec_task_ids)==(effect=='requires_recheck')
    if effect:
        task=next(t for t in e.state.inquiry_tasks if t.kind=='spec_refine')
        assert task.status=='pending' and bool(task.candidate_id)==(effect=='requires_recheck')
    assert not e.state.evidence


@pytest.mark.parametrize('bad,code',[('identity','question_identity'),('token','question_source_reference'),('unattached','question_source_missing')])
def test_question_diagnostics_preserve_identity_scope(focused,bad,code):
    e,q,_=focused;e.state.packet_receipts=[]
    if bad=='identity':q.fact_ids=['absent']
    if bad=='token':q.source_ids=['participants']
    q.disposition='explained_by_existing_mechanism'
    with pytest.raises(DiagnosticError) as exc:discovery.validate_derivation(e.state,Derivation(candidate_id=current_id(e),audit_question=q,selection_rationale='Inspect actual evidence'))
    d=exc.value.diagnostics[0]
    assert d.code==code
    assert d.paths==(['/audit_question'] if bad=='identity' else ['/audit_question/source_ids'])
    assert ('representation' in d.allowed)==(bad!='identity')


def test_two_call_tail_reads_then_closes_with_independent_feedback(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused;e.state.packet_receipts=[];q.source_ids=[]
    e.state.usage['agent_calls']=e.config.budget.agent_calls-2
    choose=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=[request('counter.py')],selection_rationale='Inspect the current discriminator')
    close=q.model_copy(update={'source_ids':['counter.py:1:1'],'disposition':'explained_by_existing_mechanism'})
    finish=Derivation(candidate_id=current_id(e),audit_question=close,selection_rationale='The actual guard explains this scoped question',descriptive_issues=[DescriptiveIssue(candidate_effect='independent_enrichment',object_ids=['consumer'],source_ids=close.source_ids,reason='Add the independently useful consumer detail')])
    e.agent=MockAgent();e.agent.responses=[x.model_dump(mode='json') for x in [choose,finish]]
    discovery.derive(e)
    assert e.state.question_candidates[0].status=='explained'
    assert e.state.usage['agent_calls']==e.config.budget.agent_calls
    assert not e.state.repair_sessions and not e.state.question_candidates[0].spec_task_ids
    assert e.state.inquiry_tasks[0].status=='pending'


def test_initial_source_token_repairs_only_source_ids(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused;e.state.packet_receipts=[];q.source_ids=['participants']
    reply=Derivation(candidate_id=current_id(e),audit_question=q,reading_requests=[request('counter.py')],selection_rationale='Select an identity before inspecting evidence')
    actual=e.state.materials[0]
    e.agent=MockAgent();e.agent.responses=[reply.model_dump(mode='json'),{'replacements':[{'path':'/audit_question/source_ids','value_json':json.dumps([actual.id])}],'rationale':'Replace the invalid token with the supplied actual source'}]
    accepted,_=discovery.ask_derivation(e,{**discovery.derive_context(e),'materials':[actual.model_dump(mode='json')]})
    assert accepted.audit_question==q.model_copy(update={'source_ids':[actual.id]})
    session=next(iter(e.state.repair_sessions.values()))
    assert session['status']=='accepted' and e.state.usage['agent_calls']==2
    assert session['resolved_diagnostics'][0]['paths']==['/audit_question/source_ids']


def fork_ready_local_obligation(focused):
    from regression_support import bounded_derivation
    e,q,responses=focused
    parent=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Inspect the local consumer boundary')])
    discovery.continue_candidate(e,parent)
    original=parent.question.model_copy(deep=True)
    child=q.model_copy(update={'question':'Does the consumer establish documented completion before interpreting the result?',
        'importance':'A local result must satisfy its interface contract before consumption; broader recovery remains unassessed',
        'contexts':['one local operation'],'event_paths':['producer completion -> consumer interpretation'],
        'unknowns':['Broader failure reachability and system consequence are excluded'],
        'requests':[],'preferred_check':'local_model','disposition':'ready_for_check',
        'trigger_rationale':'Compare the actual producer completion with the independent interface expectation'})
    reply=Derivation.model_validate(bounded_derivation(responses[1]))
    reply.candidate_id=None;reply.audit_question=child;reply.fork_from_candidate_id=parent.id
    reply.fork_reason='The sourced local completion relation is independently checkable while the Parent consequence remains unresolved'
    discovery.accept_derivation(e,reply,'fork-and-escalate')
    saved_parent=next(c for c in e.state.question_candidates if c.id==parent.id)
    return e,saved_parent,original,next(c for c in e.state.question_candidates if c.parent_candidate_id==parent.id)


def test_parent_forks_and_escalates_local_obligation_in_one_reply(focused):
    e,parent,original,child=fork_ready_local_obligation(focused)
    assert parent.status=='paused' and parent.question==original
    assert child.status=='escalated' and child.obligation_id
    unit=next(u for u in e.state.units if child.obligation_id in u.obligation_ids)
    assert unit.audit_question==child.question and unit.status=='pending'
    assert child.fork_reason==parent.stop_reason and not e.state.evidence


def test_child_result_does_not_close_parent_or_promote_consequence(focused,tmp_path):
    from consensus_assurance.core.types import Evidence,Origin,Assessment
    e,parent,original,child=fork_ready_local_obligation(focused)
    unit=next(u for u in e.state.units if child.obligation_id in u.obligation_ids);unit.status='checked'
    e.state.evidence.append(Evidence(check_id='local-check',model_id=None,snapshot_id=e.state.snapshot.id,
        claim_id=child.obligation_id,origin=Origin.EXECUTED,level='implementation_test',scope=unit.scope,
        description='Only the child local relation was observed',assessment=Assessment.INCONCLUSIVE))
    assert parent.status=='paused' and parent.question==original and parent.obligation_id is None
    assert all(x.claim_id!=parent.obligation_id for x in e.state.evidence)
    projected={x['id']:x for x in selected_packet(e)['candidate_dispositions']}
    assert projected[child.id]['evidence_ids']==[e.state.evidence[-1].id]
    assert 'local-check' in projected[child.id]['check_ids'] and projected[parent.id]['current_result'] is None
    report=__import__('consensus_assurance.reporting.chinese',fromlist=['render_report']).render_report(e.state,tmp_path).read_text()
    assert f"Parent `{parent.id}`" in report and 'Parent 原问题及未决项保持独立' in report and 'local-check' in report


def test_ready_child_check_precedes_enrichment_and_surface(focused):
    from consensus_assurance.workflow.inquiry import enqueue,choose_task
    from consensus_assurance.workflow.graph import select_unit
    e,_,_,child=fork_ready_local_obligation(focused)
    enqueue(e.state,'spec_refine','Record reusable owner','child-feedback',target_ids=['consumer'],
        diagnostics=[{'code':'audit_spec_semantics','category':'semantic','object_ids':['consumer'],'material_ids':child.question.source_ids,'message':'Record reusable owner','allowed':['semantic_revision']}])
    assert choose_task(e) is None
    assert select_unit(e.state).obligation_ids==[child.obligation_id]


def test_explicit_fork_then_resume_original_id(focused):
    e,q,_=focused
    parent=begin(e,q,[request('counter.py')])
    alternate=q.model_copy(update={'question':'Does a later write republish an invalidated entry?',
        'objects':['later writer'], 'event_paths':['delete -> later write -> read'],
        'counterevidence':['GetLog does not fill the cache; writer behavior remains unread']})
    wrong=Derivation(candidate_id=current_id(e),audit_question=alternate,reading_requests=[request('counter.py')],selection_rationale='Different writer relation')
    fork=wrong.model_copy(update={'candidate_id':None,'fork_from_candidate_id':parent.id,'fork_reason':'A later writer, not a read miss, can republish the entry'})
    discovery.accept_derivation(e,fork,'fork')
    child=discovery.active_candidate(e.state)
    assert child.id!=parent.id and child.parent_candidate_id==parent.id
    saved_parent=next(c for c in e.state.question_candidates if c.id==parent.id)
    assert saved_parent.status=='paused' and saved_parent.question.question==q.question and saved_parent.question.requests==[request('counter.py')] and saved_parent.stop_reason==fork.fork_reason
    assert child.question.counterevidence==alternate.counterevidence
    assert len(e.state.question_candidates)==2
    discovery.continue_candidate(e,child)
    close=child.question.model_copy(update={'requests':[],'disposition':'explained_by_existing_mechanism'})
    discovery.accept_derivation(e,Derivation(candidate_id=child.id,audit_question=close,selection_rationale='The acquired guard explains this independent question'),'close-child')
    discovery.accept_derivation(e,Derivation(candidate_id=parent.id,selection_rationale='Resume the saved caller question with its original source request'),'resume-parent')
    assert current_id(e)==parent.id and len(e.state.question_candidates)==2
    assert discovery.active_candidate(e.state).question==saved_parent.question
    discovery.continue_candidate(e,discovery.active_candidate(e.state))
    assert discovery.active_candidate(e.state).stage=='analyze'


def test_stale_inquiry_read_reuses_material_and_reports_analysis_pending(focused,tmp_path):
    from consensus_assurance.workflow.inquiry import enqueue,process_task
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.core.proposals import SpecRefinement
    from consensus_assurance.workflow.materials import uncovered_requests
    from consensus_assurance.reporting.chinese import render_report
    e,q,_=focused
    material=next(m for m in e.state.materials if m.file=='counter.py')
    material.end_line=material.start_line;material.text=material.text.splitlines()[0]
    partial=ReadRequest(file='counter.py',start_line=material.start_line,end_line=material.start_line+1,reason='Read only the missing suffix')
    remaining=uncovered_requests(e.state,[partial])
    assert [(r.start_line,r.end_line) for r in remaining]==[(material.start_line+1,material.start_line+1)]
    covered=ReadRequest(file='counter.py',start_line=1,end_line=1,reason='Interpret the acquired local boundary')
    task=enqueue(e.state,'spec_refine','Interpret already acquired source','stale-read',requests=[covered])
    assert not uncovered_requests(e.state,task.requests)
    assert '源码已取得，分析待处理' in render_report(e.state,tmp_path).read_text()
    e.read=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('covered source must not be read again'))
    e.agent=MockAgent();e.agent.responses=[SpecRefinement(understanding='The current inventory already represents this boundary',delta=AuditSpecDelta(rationale='No descriptive change is needed'),limitations=[]).model_dump(mode='json')]
    process_task(e,task)
    saved=next(t for t in e.state.inquiry_tasks if t.id==task.id)
    assert saved.status=='completed' and saved.stage=='done' and e.state.usage['agent_calls']==1



def test_pending_feedback_merges_opinions_without_blocking_candidate(focused):
    from consensus_assurance.workflow.inquiry import enqueue,choose_task
    e,q,_=focused;c=begin(e,q,[request('counter.py')])
    def opinion(reason):return [{'code':'audit_spec_semantics','category':'semantic','object_ids':['producer'],'material_ids':q.source_ids,'message':reason}]
    first=enqueue(e.state,'spec_refine','Check ownership','review-a',target_ids=['producer'],diagnostics=opinion('Check ownership'))
    again=enqueue(e.state,'spec_refine','Check retry branch','review-b',target_ids=['producer'],diagnostics=opinion('Check retry branch'))
    required=enqueue(e.state,'spec_refine','Correct decisive owner','review-c',target_ids=['producer'],candidate_id=c.id,diagnostics=opinion('Correct decisive owner'))
    assert first.id==again.id and len(first.diagnostics)==2 and required.id!=first.id
    assert first.candidate_id is None and not c.spec_task_ids and choose_task(e) is None
    overlap=enqueue(e.state,'spec_refine','Check shared consumer','review-d',target_ids=['producer','consumer'],diagnostics=opinion('Check shared consumer'))
    assert overlap.id==first.id and len(first.diagnostics)==3 and first.target_ids==['producer','consumer']
    c.status='explained';e.state.last_work_kind='candidate'
    required.status='completed'
    assert choose_task(e).id==first.id
    e.state.active_unit_id='ready'
    for action in ['build','direct_check','direct_execute','harness']:
        e.state.next_action=action
        assert choose_task(e) is None
    from consensus_assurance.workflow.inquiry import apply_task_response
    from consensus_assurance.core.proposals import SpecRefinement,AuditSpecDelta
    from consensus_assurance.core.types import CheckRun
    calls=e.state.usage.get('agent_calls',0)
    apply_task_response(e,first.id,SpecRefinement(understanding='The current descriptions already cover these source observations',delta=AuditSpecDelta(rationale='No descriptive changes needed'),limitations=[]),CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id))
    repeat=enqueue(e.state,'spec_refine','Covered observation','later-check',target_ids=['producer'],diagnostics=opinion('Check ownership'))
    assert repeat.id==first.id and repeat.status=='completed' and e.state.usage.get('agent_calls',0)==calls
    fresh=enqueue(e.state,'spec_refine','New evidence','review-a',target_ids=['producer'],diagnostics=opinion('A different source branch contradicts the owner'))
    assert fresh.id!=first.id and fresh.status=='pending'
