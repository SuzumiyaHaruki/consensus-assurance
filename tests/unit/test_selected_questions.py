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
    assert not c.question.unknowns and c.history[0].unknowns==q.unknowns and c.history[0].counterevidence==q.counterevidence
    assert not e.state.claims and not e.state.units and not e.state.models and not e.state.direct_checks and not e.state.evidence
    from consensus_assurance.reporting.chinese import render_report
    (tmp_path/'report').mkdir()
    report=render_report(e.state,tmp_path/'report').read_text()
    assert '候选问题与已有保护' in report and 'Acquired caller propagates' in report and 'Caller contract still unread' not in report


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
    reply=Derivation.model_validate(bounded_derivation(responses[1]));reply.audit_question=q.model_copy(update={'requests':[],'preferred_check':'local_model','disposition':'ready_for_check','counterevidence':q.counterevidence})
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
    issue=DescriptiveIssue(candidate_effect='requires_recheck' if selected else 'independent_enrichment',object_ids=['consumer' if selected else 'unrelated'],source_ids=q.source_ids,reason='Correct the owner from source')
    reply=Derivation(audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read selected behavior')],descriptive_issues=[issue],selection_rationale='Continue selected question')
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
        assert 'callback.py:1:2' in {m['id'] for m in discovery.derive_context(e)['materials']}
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
    archive=Path(__file__).resolve().parents[2]/'runs/2026-09-20_12-07-49-hashicorp_raft-real-run'
    before={name:(archive/name).read_bytes() for name in ['state.json','report.md']}
    state=load_analysis(archive/'state.json')
    state.audit_spec_path=str(archive/'audit-spec'/f'v{state.audit_spec_version}.json')
    assert [c.status for c in state.question_candidates]==['blocked','explained','active']
    assert not state.claims and not state.units and not state.evidence
    (tmp_path/'offline').mkdir()
    report=render_report(state,tmp_path/'offline').read_text()
    assert 'Budget exhausted: agent_calls' in report and 'F4' in report
    assert 'evidence_blocked=1' in report and 'workflow_blocked=0' in report and 'resource_blocked=1' in report
    assert all((archive/name).read_bytes()==data for name,data in before.items())


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
    discovery.derive(e)
    assert len(seen)==1 and e.state.last_work_kind=='candidate'
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


def test_reviewed_evidence_block_is_accepted_without_repair(focused,tmp_path):
    """13:43:11 shape: concrete source exhausted, responsibility still unattributed."""
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused
    candidate=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review the caller')])
    discovery.continue_candidate(e,candidate)
    reply=Derivation(audit_question=q.model_copy(update={'unknowns':['Applicable contract does not assign error propagation']}),selection_rationale='Caller and interface sources were reviewed; no exact remaining range can assign this responsibility')
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
    assert '候选因证据/适用合同不足延期' in report and reply.selection_rationale in report


@pytest.mark.parametrize('invalid',['initial_block','initial_exhausted','active_exhausted','unreviewed_block','unknowns_empty','wrong_check','ready_without_obligation','blank_reason'])
def test_incomplete_or_premature_outcome_is_not_an_escape(focused,invalid):
    e,q,_=focused
    if invalid not in {'initial_block','initial_exhausted'}:
        c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review')])
        if invalid!='unreviewed_block':discovery.continue_candidate(e,c)
    reply=Derivation(audit_question=q,selection_rationale='No remaining justified contract source')
    if invalid.endswith('exhausted'):reply.audit_question=None
    if invalid=='unknowns_empty':reply.audit_question=q.model_copy(update={'unknowns':[]})
    if invalid=='wrong_check':reply.audit_question=q.model_copy(update={'preferred_check':'local_model'})
    if invalid=='ready_without_obligation':reply.audit_question=q.model_copy(update={'disposition':'ready_for_check'})
    if invalid=='blank_reason':reply.selection_rationale=' '
    with pytest.raises(DiagnosticError):discovery.validate_derivation(e.state,reply)
    assert not e.state.claims and not e.state.units


def test_disposed_selection_exhausts_once_and_cannot_be_silently_reselected(focused):
    e,q,_=focused;c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review')])
    discovery.continue_candidate(e,c)
    discovery.accept_derivation(e,Derivation(audit_question=q,selection_rationale='Applicable responsibility is not established'),'block')
    repeat=Derivation(audit_question=q,reading_requests=[ReadRequest(file='counter.py',start_line=3,end_line=4,reason='Same direction')],selection_rationale='Repeat disposed direction')
    with pytest.raises(DiagnosticError,match='already has a disposition'):discovery.validate_derivation(e.state,repeat)
    end=Derivation(selection_rationale='No additional bounded discriminator is supported by current inventory/source')
    assert discovery.validate_derivation(e.state,end)=='selection_exhausted'
    assert discovery.accept_derivation(e,end,'finish')
    discovery.derive(e)  # The same inventory is not asked to select again after resume.
    assert len(e.state.question_candidates)==1 and e.state.gaps[-1].endswith(end.selection_rationale)
    assert not e.state.pending_output_repair and not e.state.claims and not e.state.units


def test_true_semantic_error_first_repair_has_local_objects_and_source(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.workflow.errors import Blocked
    from consensus_assurance.workflow.sources import all_materials
    e,q,_=focused;c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review')])
    discovery.continue_candidate(e,c)
    bad=Derivation(audit_question=q.model_copy(update={'obligation_relation_kind':'recovery'}),reading_requests=[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Read')],selection_rationale='Silently change the lifecycle')
    with pytest.raises(DiagnosticError) as caught:discovery.validate_derivation(e.state,bad)
    d=caught.value.diagnostics[0]
    assert set(q.fact_ids+q.behavior_ids)<=set(d.object_ids)
    assert set(q.source_ids+c.material_ids)<=set(d.material_ids)
    agent=MockAgent();agent.responses=[bad.model_dump(mode='json'),{'change_request':'A real lifecycle change needs explicit selection rather than representation repair','rationale':'Preserve the original question'}];e.agent=agent
    with pytest.raises(Blocked,match='Explicit semantic/scope plan'):discovery.ask_derivation(e,discovery.derive_context(e))
    repair=next(json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1]) for p in (e.root/'agent').glob('*/prompt.txt') if '"repair_targets"' in p.read_text())
    local=repair['related_context']
    assert set(d.material_ids)<={m['id'] for m in all_materials(local)}
    assert set(q.fact_ids+q.behavior_ids)<={o['id'] for o in local['objects']}
    assert discovery.active_candidate(e.state).status=='active'  # Genuine errors are not swallowed as evidence-blocked.


def test_unrelated_reusable_feedback_survives_evidence_blocked_outcome(focused):
    from consensus_assurance.workflow.inquiry import choose_task
    e,q,_=focused;c=begin(e,q,[ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Review the selected source')])
    discovery.continue_candidate(e,c)
    version=e.state.audit_spec_version
    reply=Derivation(audit_question=q,descriptive_issues=[DescriptiveIssue(candidate_effect='independent_enrichment',object_ids=['A7'],source_ids=q.source_ids,reason='Source exposes an unrepresented recovery execution owner; inspect that reusable boundary')],selection_rationale='The selected contract remains unattributed without a justified next range')
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
        discovery.accept_derivation(e,Derivation(audit_question=narrowed,reading_requests=[request('counter.py')],selection_rationale='Resolve one specific caller discriminator'),f'narrow-{n}')
    c=discovery.active_candidate(e.state)
    assert len(c.history)==3 and not c.question.unknowns and c.history[0].unknowns==original['unknowns']
    packet=discovery.derive_context(e)
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
    assert FRAMEWORK_REVISION==manifest()['version']=='selected-question-v8'


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
    reply=Derivation(audit_question=q,selection_rationale='Actual selected source determines the scoped result')
    if decision=='read':reply.reading_requests=[request('counter.py')]
    elif decision=='explained':q.disposition='explained_by_existing_mechanism'
    elif decision=='escalate':
        reply=Derivation.model_validate(bounded_derivation(responses[1]));reply.audit_question=q
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
    with pytest.raises(DiagnosticError) as exc:discovery.validate_derivation(e.state,Derivation(audit_question=q,selection_rationale='Inspect actual evidence'))
    d=exc.value.diagnostics[0]
    assert d.code==code
    assert d.paths==(['/audit_question'] if bad=='identity' else ['/audit_question/source_ids'])
    assert ('representation' in d.allowed)==(bad!='identity')


def test_three_call_tail_closes_with_independent_selected_feedback(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused;e.state.packet_receipts=[];q.source_ids=[]
    e.state.usage['agent_calls']=e.config.budget.agent_calls-3
    choose=Derivation(audit_question=q,reading_requests=[request('counter.py')],selection_rationale='Inspect the current discriminator')
    close=q.model_copy(update={'source_ids':['counter.py:1:1'],'disposition':'explained_by_existing_mechanism'})
    finish=Derivation(audit_question=close,selection_rationale='The actual guard explains this scoped question',descriptive_issues=[DescriptiveIssue(candidate_effect='independent_enrichment',object_ids=['consumer'],source_ids=close.source_ids,reason='Add the independently useful consumer detail')])
    e.agent=MockAgent();e.agent.responses=[x.model_dump(mode='json') for x in [choose,finish]]
    discovery.derive(e)
    assert e.state.question_candidates[0].status=='explained'
    assert e.state.usage['agent_calls']==e.config.budget.agent_calls-1
    assert not e.state.repair_sessions and not e.state.question_candidates[0].spec_task_ids
    assert e.state.inquiry_tasks[0].status=='pending'


def test_initial_source_token_repairs_only_source_ids(focused):
    from consensus_assurance.adapters.agents.backend import MockAgent
    e,q,_=focused;e.state.packet_receipts=[];q.source_ids=['participants']
    reply=Derivation(audit_question=q,reading_requests=[request('counter.py')],selection_rationale='Select an identity before inspecting evidence')
    actual=e.state.materials[0]
    e.agent=MockAgent();e.agent.responses=[reply.model_dump(mode='json'),{'replacements':[{'path':'/audit_question/source_ids','value_json':json.dumps([actual.id])}],'rationale':'Replace the invalid token with the supplied actual source'}]
    accepted,_=discovery.ask_derivation(e,{**discovery.derive_context(e),'materials':[actual.model_dump(mode='json')]})
    assert accepted.audit_question==q.model_copy(update={'source_ids':[actual.id]})
    session=next(iter(e.state.repair_sessions.values()))
    assert session['status']=='accepted' and e.state.usage['agent_calls']==2
    assert session['resolved_diagnostics'][0]['paths']==['/audit_question/source_ids']


def test_same_fact_distinct_discriminator_and_atomic_fork(focused):
    e,q,_=focused
    parent=begin(e,q,[request('counter.py')])
    alternate=q.model_copy(update={'question':'Does a later write republish an invalidated entry?',
        'objects':['later writer'], 'event_paths':['delete -> later write -> read'],
        'counterevidence':['GetLog does not fill the cache; writer behavior remains unread']})
    wrong=Derivation(audit_question=alternate,reading_requests=[request('counter.py')],selection_rationale='Different writer relation')
    fork=wrong.model_copy(update={'fork_from_candidate_id':parent.id,'fork_reason':'A later writer, not a read miss, can republish the entry'})
    discovery.accept_derivation(e,fork,'fork')
    child=discovery.active_candidate(e.state)
    assert child.id!=parent.id and child.parent_candidate_id==parent.id
    saved_parent=next(c for c in e.state.question_candidates if c.id==parent.id)
    assert saved_parent.status=='paused' and saved_parent.question.question==q.question and saved_parent.question.requests==[request('counter.py')] and saved_parent.stop_reason==fork.fork_reason
    assert child.question.counterevidence==alternate.counterevidence
    assert len(e.state.question_candidates)==2
    assert not discovery.accept_derivation(e,fork,'fork')
    assert len(e.state.question_candidates)==2


def test_same_fact_prose_rewrite_does_not_reopen_explained_hypothesis(focused):
    e,q,_=focused;c=begin(e,q,[request('counter.py')])
    discovery.continue_candidate(e,c)
    close=q.model_copy(update={'disposition':'explained_by_existing_mechanism','counterevidence':['The acquired caller excludes the stated path']})
    discovery.accept_derivation(e,Derivation(audit_question=close,selection_rationale='The stated path is excluded'),'closed')
    renamed=q.model_copy(update={'question':'Could late success conceal failed publication?'})
    with pytest.raises(DiagnosticError,match='already has a disposition'):
        discovery.validate_derivation(e.state,Derivation(audit_question=renamed,reading_requests=[request('counter.py')],selection_rationale='Only prose changed'))
    alternate=q.model_copy(update={'objects':['a distinct writer'],'event_paths':['writer -> delete -> read']})
    assert discovery.validate_derivation(e.state,Derivation(audit_question=alternate,reading_requests=[request('counter.py')],fork_reason='Different producer and order',selection_rationale='Inspect the distinct writer path'))=='continue_read'
    revised=q.model_copy(update={'source_ids':q.source_ids+['counter.py:1:1'],'counterevidence':['Newly acquired caller contradicts the old disposition']})
    assert discovery.validate_derivation(e.state,Derivation(audit_question=revised,reading_requests=[request('counter.py')],fork_reason='New acquired caller evidence changes the original applicability',selection_rationale='Recheck the old relation against the new source'))=='continue_read'


def test_targeted_read_quota_preflight_matches_partial_cached_receipt(focused):
    from consensus_assurance.workflow.materials import execute_read
    e,q,_=focused;sources(e,new_source=50)
    e.config.budget.targeted_reads=0;e.state.config=e.config.model_dump(mode='json')
    cached=ReadRequest(file='counter.py',start_line=1,end_line=2,reason='Reattach cached')
    fresh=request('new_source')
    with pytest.raises(DiagnosticError) as caught:
        validate_read_requests(e.state,e.root/'source',ReadingPlan(requests=[fresh],rationale='New evidence'),purpose='depth')
    assert caught.value.diagnostics[0].details['targeted_reads_remaining']==0
    receipt=execute_read(e,[fresh,cached],purpose='depth',partial=True,plan_id='bounded-plan')
    assert [i['status'] for i in receipt['items']]==['deferred','cached']
    assert not e.state.usage.get('targeted_reads')
    assert 'new_source:1:1' not in {m.id for m in e.state.materials}


def test_feedback_dedup_preserves_origins_and_distinct_meanings(focused):
    from consensus_assurance.workflow.inquiry import enqueue
    e,q,_=focused;source=q.source_ids[0]
    first=enqueue(e.state,'spec_refine','Correct actual producer ownership','review-a',target_ids=['producer'],feedback_source_ids=[source],feedback_effect='independent_enrichment')
    again=enqueue(e.state,'spec_refine','Correct actual producer ownership','review-b',target_ids=['producer'],feedback_source_ids=[source],feedback_effect='independent_enrichment')
    other=enqueue(e.state,'spec_refine','Correct retry consumer ownership','review-c',target_ids=['producer'],feedback_source_ids=[source],feedback_effect='independent_enrichment')
    assert first.id==again.id and first.origin_check_ids==['review-a','review-b']
    assert other.id!=first.id


def test_last_call_preserves_pending_source_and_pauses_question(focused):
    e,q,_=focused;c=begin(e,q,[request('counter.py')])
    e.state.usage['agent_calls']=e.config.budget.agent_calls-1
    discovery.continue_candidate(e,c)
    assert c.status=='paused' and 'judgment' in c.stop_reason
    assert c.question.requests==[request('counter.py')] and c.read_plan_id not in e.state.read_plans


def test_last_call_judges_acquired_candidate_without_new_read(focused):
    e,q,_=focused;c=begin(e,q,[request('counter.py')])
    c.material_ids=[q.source_ids[0]]
    e.state.usage['agent_calls']=e.config.budget.agent_calls-1
    discovery.continue_candidate(e,c)
    assert c.status=='active' and c.stage=='analyze'
    assert c.read_plan_id not in e.state.read_plans


def test_charged_partial_plan_continues_without_second_read_charge(focused):
    from consensus_assurance.workflow.materials import execute_read
    e,q,_=focused;sources(e,A=500,B=1100)
    e.config.budget.targeted_reads=1;e.state.config=e.config.model_dump(mode='json')
    requests=[request('A'),request('B')]
    first=execute_read(e,requests,purpose='depth',partial=True,plan_id='same-logical-plan')
    assert [i['status'] for i in first['items']]==['acquired','deferred']
    assert e.state.usage['targeted_reads']==1
    e.config.budget.material_chars=10000;e.state.config=e.config.model_dump(mode='json')
    from consensus_assurance.core.types import QuestionCandidate
    e.state.question_candidates.append(QuestionCandidate(question=q,stage='read',read_plan_id='same-logical-plan'))
    validate_read_requests(e.state,e.root/'source',ReadingPlan(requests=requests,rationale='Complete the same charged plan'),purpose='depth')
    second=execute_read(e,requests,purpose='depth',partial=True,plan_id='same-logical-plan')
    assert [i['status'] for i in second['items']]==['cached','acquired']
    assert e.state.usage['targeted_reads']==1


def test_selected_question_and_required_feedback_share_known_read_plan(focused,monkeypatch):
    from consensus_assurance.workflow.inquiry import enqueue
    e,q,_=focused;sources(e,A=80,B=80)
    candidate=begin(e,q,[request('A')])
    task=enqueue(e.state,'spec_refine','Correct the selected producer','needed',target_ids=['producer'],requests=[request('A'),request('B')])
    task.candidate_id=candidate.id;candidate.spec_task_ids=[task.id]
    seen=[]
    def complete(engine,current):
        seen.append([m.id for m in engine.state.materials])
        assert current.stage=='analyze' and {'A:1:1','B:1:1'}<=set(current.added_material_ids)
        current.status='completed'
    monkeypatch.setattr(discovery.inquiry,'process_task',complete)
    discovery.continue_candidate(e,candidate)
    receipt=e.state.read_plans[candidate.read_plan_id]
    assert len(receipt['original_requests'])==2
    assert [i['status'] for i in receipt['items']]==['acquired','acquired']
    assert e.state.usage['targeted_reads']==1 and seen
    assert {'A:1:1','B:1:1'}<=set(e.state.task_attachments['inquiry:'+task.id])
