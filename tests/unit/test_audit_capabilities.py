"""Stable R1-R5/R8 capabilities; R6/R7 retain actual execution and TLC suites."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from consensus_assurance.core.types import ConsensusAuditSpec,Activity,Behavior,Fact,Surface,TargetProfile,AuditQuestion
from consensus_assurance.workflow.audit_spec import validate,accept,SpecIssue,load


def inventory(source,variant='local'):
    return ConsensusAuditSpec(target_profile=TargetProfile(system_boundary='Controlled '+variant,source_ids=[source]),
        activities=[Activity(class_id='A'+str(n),applicability='unknown',purpose='Coordinate '+str(n),realization_summary='Boundary remains incomplete',source_ids=[source],unknowns=['Unrecovered owner']) for n in range(1,8)],
        behaviors=[Behavior(id='producer',primary_activity='A1',execution_owner='producer loop',protocol_context='one operation',trigger='receive',produces_fact_ids=['fact'],source_ids=[source]),
            Behavior(id='consumer',primary_activity='A5',execution_owner='application loop',protocol_context='one operation',trigger='consume',consumes_fact_ids=['fact'],source_ids=[source])],
        facts=[Fact(id='fact',meaning='The scoped input has been established',identity={'operation':'request'},validity_context='one operation',representation=['queue item'],durability='Not yet established',recovery='Unread',source_ids=[source],unknowns=['Durability unverified'])],
        surfaces=[Surface(entry_point='entry',disposition='mapped',behavior_ids=['producer'],reason='Actual controlled entry',source_ids=[source])])


@pytest.mark.parametrize('applicability',['unknown','externalized','not_applicable','applicable'])
def test_R1_incomplete_coherent_inventory_and_aggregated_errors(prepared,applicability):
    _,state,_,_=prepared;spec=inventory(state.materials[0].id,applicability)
    spec.activities[2].applicability=applicability
    raw=spec.model_dump(mode='json');second=dict(raw['facts'][0],id='second')
    raw['facts'].append(second)
    raw['behaviors'][0]['produces_fact_ids'].append('second')
    raw['behaviors'][1]['produces_fact_ids']=['fact','second']
    raw['behaviors'][1]['consumes_fact_ids'].append('second')
    for fact in raw['facts']:
        fact.pop('established_by');fact.pop('consumed_by')
    spec=ConsensusAuditSpec.model_validate(raw);validate(state,spec)
    assert all(f.established_by==['producer','consumer'] for f in spec.facts)
    spec.behaviors[0].produces_fact_ids=['missing'];spec.surfaces[0].behavior_ids=['absent']
    with pytest.raises(SpecIssue) as exc:validate(state,spec)
    assert len(exc.value.diagnostics)>=2 and all(d.material_ids for d in exc.value.diagnostics)


def test_R2_object_refinement_replaces_mixed_draft_without_mechanical_pointers(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import enqueue,process_task,task_context
    from consensus_assurance.adapters.agents.backend import MockAgent
    from test_graph_mutations import controller
    from consensus_assurance.core.proposals import AuditSpecDelta,SpecRefinement
    import shutil
    repo,state,_,_=prepared;e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    spec=inventory(state.materials[0].id);bad=spec.model_copy(deep=True)
    bad.behaviors[0].execution_owner='two independent loops';bad.behaviors[0].produces_fact_ids=['unrepresented']
    bad.facts[0].meaning='A transition was requested or completed';bad.surfaces[0].behavior_ids=['unrepresented']
    with pytest.raises(SpecIssue) as exc:validate(state,bad)
    path=tmp_path/'draft.json';path.write_text(json.dumps({'audit_spec':bad.model_dump(mode='json')}))
    task=enqueue(state,'spec_refine','Split the mixed producer and assertion','test')
    task.draft_path=str(path);task.diagnostics=[d.model_dump(mode='json') for d in exc.value.diagnostics]
    from consensus_assurance.workflow.task_packet import prepare
    packet=prepare(e,'spec_refine',task_context(e,task))[0];required={id for d in task.diagnostics for id in d['material_ids']}
    assert required<={m['id'] for m in packet['materials']}
    spec.behaviors.append(Behavior(id='notifier',primary_activity='A2',execution_owner='control loop',protocol_context='one operation',trigger='timeout',produces_fact_ids=['notification'],source_ids=[state.materials[0].id],unknowns=['Completion consumer unread']))
    spec.facts.append(Fact(id='notification',meaning='A context transition has been requested',identity={'operation':'request'},validity_context='one operation',established_by=['notifier'],representation=['notification'],durability='Not persisted',recovery='Discarded',source_ids=[state.materials[0].id],unknowns=['Completion consumer unread']))
    agent=MockAgent();agent.responses=[SpecRefinement(understanding='Separate request notification from established input',delta=AuditSpecDelta(behaviors=spec.behaviors,facts=spec.facts,surfaces=spec.surfaces,rationale='Split the mixed initial inventory'),limitations=['Completion remains unknown']).model_dump(mode='json')];e.agent=agent
    process_task(e,task)
    assert load(state).facts[0].unknowns and len(load(state).behaviors)==3 and len(load(state).facts)==2
    assert not state.repair_sessions and json.loads(path.read_text())['audit_spec']['facts'][0]['meaning']==bad.facts[0].meaning


@pytest.mark.parametrize('gap',['commit establishment','snapshot selection and transfer'])
def test_R3_unread_intermediate_establishment_has_no_invented_edge(prepared,gap):
    _,state,_,_=prepared;raw=inventory(state.materials[0].id).model_dump(mode='json')
    raw['behaviors'][1]['consumes_fact_ids']=[]
    raw['facts'][0].pop('consumed_by');raw['facts'][0]['unknowns']=[gap+' is unread']
    spec=ConsensusAuditSpec.model_validate(raw);validate(state,spec)
    assert spec.facts[0].consumed_by==[] and spec.behaviors[1].consumes_fact_ids==[]


def test_R4_breadth_preserves_order_and_defers(tmp_path,prepared):
    from consensus_assurance.workflow.materials import plan_read,ReadingPlan,validate_read_requests
    from consensus_assurance.core.config import Config
    from consensus_assurance.core.diagnostics import DiagnosticError
    repo,state,_,_=prepared;state.materials=[]
    budget=Config.model_validate(state.config).budget;budget.material_chars=10;state.config['budget']=budget.model_dump(mode='json')
    requests=[{'file':'counter.py','start_line':1,'end_line':10,'reason':'Priority producer'}, {'file':'limits.py','start_line':1,'end_line':1,'reason':'Secondary range'}]
    validate_read_requests(state,repo,ReadingPlan(requests=requests,rationale='Authored priority'))
    receipt,_=plan_read(state,repo,requests,budget,purpose='breadth',partial=True)
    assert [i.request.file for i in receipt.items]==['counter.py','limits.py'] and all(i.status=='deferred' for i in receipt.items)


def test_R5_ready_evidence_precedes_unrelated_unknowns(tmp_path,prepared):
    from consensus_assurance.workflow.graph import select_unit
    from consensus_assurance.workflow.inquiry import choose_task
    from test_graph_mutations import controller
    _,state,_,_=prepared;spec=inventory(state.materials[0].id)
    spec.surfaces.append(Surface(entry_point='unread high-consequence handler',disposition='deferred',high_consequence=True,reason='Owner unread'))
    accept(SimpleNamespace(state=state,root=tmp_path),spec)
    question=dict(question='Does this established input satisfy the selected obligation?',importance='Observable service consequence',source_ids=[state.materials[0].id],activity_classes=['A1','A5'],behavior_ids=['producer','consumer'],fact_ids=['fact'],obligation_relation_kind='consumption',trigger_rationale='Exercise the actual input consumption')
    unit=state.units[0];unit.audit_question=AuditQuestion(**question,disposition='ready_for_check',preferred_check='direct_test')
    other=unit.model_copy(deep=True);other.id='needs-source';other.obligation_ids=['input_obligation'];other.audit_question.disposition='needs_specific_evidence';other.audit_question.priority=3;state.units.append(other)
    assert select_unit(state).id==unit.id
    assert choose_task(controller(tmp_path,state)) is None
    assert len(unit.obligation_ids)==1 and not state.inquiry_tasks




def test_surface_delta_split_growth_and_scope(prepared,tmp_path):
    from consensus_assurance.core.proposals import AuditSpecDelta
    from consensus_assurance.core.types import InquiryTask
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.audit_spec import merge_delta
    from test_graph_mutations import controller
    _,state,_,_=prepared;state.units=[];e=controller(tmp_path,state)
    source=state.materials[0].id;spec=inventory(source)
    spec.surfaces.append(Surface(entry_point='unread pair',disposition='deferred',high_consequence=True,reason='Independent owners unread',source_ids=[source]))
    accept(e,spec);before=load(state).model_dump_json()
    task=InquiryTask(kind='spec_refine',reason='Expand one pair',trigger='test',surface_entry_points=['unread pair'])
    new_b=spec.behaviors[0].model_copy(update={'id':'new_producer','primary_activity':'A3','produces_fact_ids':['new_fact']})
    new_f=spec.facts[0].model_copy(update={'id':'new_fact','established_by':[],'consumed_by':[]})
    delta=AuditSpecDelta(behaviors=[new_b],facts=[new_f],surfaces=[Surface(entry_point='first owner',disposition='mapped',behavior_ids=['new_producer'],reason='Acquired producer',source_ids=[source],high_consequence=True),Surface(entry_point='second owner',disposition='deferred',reason='Consumer source remains unread',high_consequence=True)],remove_surface_entry_points=['unread pair'],rationale='Split independent execution owners')
    trial=merge_delta(state,task,delta)
    assert load(state).model_dump_json()==before
    assert trial.facts[-1].established_by==['new_producer'] and trial.activities[2].behavior_ids==['new_producer']
    accept(e,trial)
    assert load(state).version==2 and len(load(state).behaviors)==3 and load(state).surfaces[-1].disposition=='deferred'
    task.surface_entry_points=['second owner']
    second=new_b.model_copy(update={'id':'new_consumer','produces_fact_ids':[],'consumes_fact_ids':['new_fact']})
    accept(e,merge_delta(state,task,AuditSpecDelta(behaviors=[second],surfaces=[Surface(entry_point='second owner',disposition='mapped',behavior_ids=[second.id],reason='Acquired consumer',source_ids=[source])],rationale='Extend the second independent path')))
    assert {b.id for b in load(state).behaviors}=={'producer','consumer','new_producer','new_consumer'}
    assert load(state).activities[2].realization_summary==spec.activities[2].realization_summary
    assert load(state).activities[2].behavior_ids==['new_producer','new_consumer']
    # A separate accepted region cannot be rewritten by a surface delta.
    for field,obj in [('behaviors',spec.behaviors[1].model_copy(update={'execution_owner':'invented owner'})),('facts',spec.facts[0].model_copy(update={'meaning':'unrelated assertion'})),('activities',spec.activities[2].model_copy(update={'realization_summary':'Only the latest consumer is known'})),('surfaces',spec.surfaces[0].model_copy(update={'reason':'unrelated change'}))]:
        with pytest.raises(DiagnosticError,match='outside this descriptive focus'):
            merge_delta(state,task,AuditSpecDelta(**{field:[obj]},rationale='Unrelated rewrite'))
    from consensus_assurance.workflow.inquiry import task_context
    from consensus_assurance.workflow.task_packet import prepare
    task.target_ids=['A3']
    task.surface_entry_points=[]
    state.inquiry_tasks.append(task)
    context=prepare(e,'spec_refine',task_context(e,task))[0]
    assert next(a for a in context['audit_spec']['activities'] if a['class_id']=='A3')==load(state).activities[2].model_dump(mode='json')
    correction=load(state).activities[2].model_copy(update={'applicability':'applicable','realization_summary':'Both producer and consumer owners are now recovered','unknowns':[]})
    accept(e,merge_delta(state,task,AuditSpecDelta(activities=[correction],rationale='Correct the responsibility using both acquired paths')))
    assert load(state).activities[2]==correction


def test_explicit_frontier_selection_preserves_navigation_and_focus(prepared,tmp_path):
    import shutil
    from consensus_assurance.core.types import QuestionCandidate
    from consensus_assurance.workflow.inquiry import choose_task,task_context,read_purpose,enqueue
    from consensus_assurance.core.proposals import Derivation
    from consensus_assurance.workflow.discovery import classify_derivation_outcome
    from consensus_assurance.workflow.materials import refresh_unread
    from test_graph_mutations import controller
    repo,state,_,_=prepared;state.units=[];e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    from consensus_assurance.cli import load_config
    target=load_config(str(Path(__file__).resolve().parents[2]/'configs/targets/hashicorp_raft.yaml'))
    assert target.activity_focus==['A1','A2'] and target.agent_reasoning_effort=='low' and not target.allow_agent_materials and not target.allow_experiments
    assert (target.budget.agent_calls,target.budget.material_chars,target.budget.total_seconds)==(40,240000,4800)
    assert (target.budget.audit_units,target.budget.experiments,target.budget.exploration_rounds,target.budget.model_checks)==(4,8,4,6)
    assert (target.budget.context_chars,target.budget.action_timeout,target.budget.material_chunks)==(180000,600,40)
    e.config.activity_focus=['A5'];state.config=e.config.model_dump(mode='json')
    source=state.materials[0].id;spec=inventory(source)
    spec.behaviors[1].implementation_guards=['Reject a mismatched operation context']
    spec.behaviors[1].important_branches=['Context mismatch returns without consumption']
    spec.behaviors[1].existing_protections=['Identity is compared before use']
    spec.behaviors[1].unknowns=['Concurrent invalidation remains unread']
    spec.surfaces.extend([Surface(entry_point='first',disposition='deferred',behavior_ids=['producer'],high_consequence=True,reason='Unread owner',source_ids=[source]),
        Surface(entry_point='second',disposition='deferred',behavior_ids=['consumer'],high_consequence=True,reason='Unread owner',source_ids=[source])])
    accept(e,spec);refresh_unread(state,e.root/'source')
    assert choose_task(e) is None


    selection=Derivation(frontier_entry_point='second',selection_rationale='The known consumer source and context guard make this frontier worth reading')
    assert classify_derivation_outcome(state,selection)=='frontier'
    task=enqueue(state,'spec_refine',selection.selection_rationale,'selected:second',activity_classes=['A5'],target_ids=['surface:second'],surface_entry_points=['second'])
    assert choose_task(e).id==task.id and read_purpose(task)=='breadth'
    from consensus_assurance.workflow.task_packet import prepare
    packet=prepare(e,'spec_refine',task_context(e,task))[0]
    assert [s['entry_point'] for s in packet['focused_surfaces']]==['second'] and packet['activity_focus']==['A5']
    consumer=next(b for b in packet['audit_spec']['behaviors'] if b['id']=='consumer')
    assert consumer['important_branches'] and consumer['implementation_guards'] and consumer['existing_protections'] and consumer['unknowns']
    assert packet['file_lookup'] and 'catalogue' not in packet and 'source_ranges' not in packet
    assert not packet.get('candidate_dispositions')
    state.mode='real';state.analysis_mode='autonomous'
    report=__import__('consensus_assurance.reporting.chinese',fromlist=['render_report']).render_report(state,e.root).read_text()
    assert "Activity 重点：`['A5']`" in report and '有明确 Activity 重点的自主发现' in report
    task.status='completed';task.admitted=True
    assert choose_task(e) is None
    q=AuditQuestion(question='Selected input question',importance='Scoped service effect',source_ids=[source],trigger_rationale='Selected discriminator',activity_classes=['A1'],behavior_ids=['producer'],fact_ids=['fact'],obligation_relation_kind='establishment')
    state.question_candidates=[QuestionCandidate(question=q)]
    assert choose_task(e) is None
    state.question_candidates[0].status='blocked'
    assert choose_task(e) is None


def test_activity_relevance_does_not_grant_global_rewrite(prepared,tmp_path):
    from consensus_assurance.core.proposals import AuditSpecDelta,Derivation
    from consensus_assurance.core.types import InquiryTask
    from consensus_assurance.workflow.audit_spec import merge_delta
    from consensus_assurance.workflow.discovery import classify_derivation_outcome
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);source=state.materials[0].id
    spec=inventory(source)
    spec.surfaces.append(Surface(entry_point='unmapped owner',disposition='deferred',reason='The owner is unread',high_consequence=True,source_ids=[source]))
    accept(e,spec)
    assert classify_derivation_outcome(state,Derivation(frontier_entry_point='unmapped owner',selection_rationale='A sourced entry point may matter to the current focus'))=='frontier'
    changed=spec.activities[0].model_copy(update={'realization_summary':'New global conclusion'})
    task=InquiryTask(kind='spec_refine',reason='Read the selected frontier',trigger='frontier',activity_classes=['A1'],surface_entry_points=['unmapped owner'],material_ids=[source],context_receipt_id='current')
    with pytest.raises(SpecIssue,match='outside this descriptive focus'):
        merge_delta(state,task,AuditSpecDelta(activities=[changed],rationale='Local reading cannot replace a global responsibility'))
    task.target_ids=['A1']
    assert merge_delta(state,task,AuditSpecDelta(activities=[changed],rationale='Explicitly revise the complete selected activity')).activities[0]==changed


@pytest.mark.parametrize('failure',['duplicate','dangling','unacquired','accepted_fact'])
def test_delta_preserves_full_inventory_validation(prepared,tmp_path,failure):
    from consensus_assurance.core.proposals import AuditSpecDelta
    from consensus_assurance.core.types import InquiryTask
    from consensus_assurance.workflow.audit_spec import merge_delta
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);source=state.materials[0].id
    spec=inventory(source);accept(e,spec)
    task=InquiryTask(kind='spec_refine',reason='Correct the selected input',trigger='test',target_ids=['producer','fact'])
    delta=AuditSpecDelta(rationale='Correct sourced description')
    if failure=='duplicate':delta.behaviors=[spec.behaviors[0],spec.behaviors[0]]
    if failure=='dangling':delta.remove_fact_ids=['fact']
    if failure=='unacquired':delta.behaviors=[spec.behaviors[0].model_copy(update={'source_ids':['unread:1:20']})]
    if failure=='accepted_fact':
        state.units[0].audit_question=AuditQuestion(question='Selected input question',importance='Scoped service effect',source_ids=[source],trigger_rationale='Selected discriminator',activity_classes=['A1'],behavior_ids=['producer'],fact_ids=['fact'],obligation_relation_kind='establishment')
        delta.facts=[spec.facts[0].model_copy(update={'meaning':'A stronger assertion'})]
    before=load(state).model_dump_json()
    with pytest.raises(ValueError):merge_delta(state,task,delta)
    assert load(state).model_dump_json()==before


def test_focused_projection_at_repository_scale(tmp_path,prepared):
    import shutil
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.workflow.prompts import render
    from consensus_assurance.workflow.materials import ReadingPlan
    from regression_support import add_reads
    from consensus_assurance.workflow.inquiry import enqueue,task_context
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.config import Budget
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);source=e.root/'source';source.mkdir()
    for n in range(88):
        name=('election' if n==0 else 'fsm' if n==1 else 'snapshot' if n==2 else 'module'+str(n))+'.py'
        (source/name).write_text(''.join(f'def handler_{n}_{i}(value):\n    return value\n' for i in range(14 if n==0 else 10)))
    state.snapshot=capture(source);state.materials=[]
    # Acquire ten ranges as profile provenance, but attach only election now.
    requests=[{'file':p.name,'start_line':1,'end_line':20,'reason':'Historical survey'} for p in list(source.glob('*.py'))[:10]]
    if not any(r['file']=='election.py' for r in requests):requests[-1]['file']='election.py'
    ids=add_reads(state,source,ReadingPlan(requests=requests,rationale='Historical provenance'),Budget())
    spec=inventory(ids[0]);spec.target_profile.source_ids=ids
    spec.surfaces.append(Surface(entry_point='election.handler_0_0',disposition='deferred',reason='Election owner unread',high_consequence=True))
    accept(e,spec);task=enqueue(state,'spec_refine','Inspect election context','surface-test',surface_entry_points=['election.handler_0_0'])
    task.material_ids=['election.py:1:20']
    packet,_=prepare(e,'spec_refine',task_context(e,task));text=render('spec_refine',pool_sources(packet),e.inquiry)
    assert len(text)<120000 and len(packet['file_lookup'])==88
    assert [m['file'] for m in packet['materials']]==['election.py']
    assert 'declaration_hints' not in packet and not {'catalogue','source_ranges','unread_ranges'}&packet.keys()
    assert len(load(state).target_profile.source_ids)==10


def test_canonical_objects_and_profile_semantic_retry(tmp_path,prepared):
    import shutil
    from consensus_assurance.workflow.audit_spec import audit_object_key,audit_object_index,audit_object_path,audit_object_sources
    from consensus_assurance.workflow.inquiry import enqueue,process_task
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.core.proposals import AuditSpecDelta,SpecRefinement
    from test_graph_mutations import controller
    repo,state,_,_=prepared;e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    spec=inventory(state.materials[0].id);spec.target_profile.protocol_contexts=['Construction and retirement unread'];accept(e,spec)
    index=audit_object_index(spec)
    for key in ['target_profile','A1','producer','fact','surface:entry']:
        assert audit_object_key(index[key])==key and audit_object_path(spec,key) and audit_object_sources(index[key])
    task=enqueue(state,'spec_refine','Interpret fresh local accounting owner','depth-test',target_ids=['producer'])
    task.material_ids=[state.materials[0].id]
    profile=spec.target_profile.model_copy(update={'protocol_contexts':['The control owner constructs fresh accounting and retires it on cleanup']})
    narrower=spec.behaviors[0].model_copy(update={'execution_owner':'fresh accounting within the control owner'})
    agent=MockAgent();agent.responses=[SpecRefinement(understanding='Observe the actual local construction',delta=AuditSpecDelta(target_profile=profile,rationale='Local source recovered'),limitations=[]).model_dump(mode='json'),SpecRefinement(understanding='Keep the new knowledge on the local producer',delta=AuditSpecDelta(behaviors=[narrower],rationale='No global orientation change required'),limitations=[]).model_dump(mode='json')];e.agent=agent
    process_task(e,task)
    task=state.inquiry_tasks[0];d=task.diagnostics[0]
    assert task.status=='pending' and task.admitted and not state.repair_sessions
    assert d['object_ids']==['target_profile'] and d['paths']==['/delta/target_profile/protocol_contexts']
    assert d['material_ids'] and d['details']['old']['protocol_contexts']==spec.target_profile.protocol_contexts
    assert d['details']['proposed']['protocol_contexts']==profile.protocol_contexts and d['details']['focus']==['producer']
    process_task(e,task)
    assert state.inquiry_tasks[0].status=='completed' and load(state).behaviors[0].execution_owner==narrower.execution_owner
    assert load(state).target_profile==spec.target_profile and not state.repair_sessions
    assert state.usage['agent_calls']==2 and state.usage.get('exploration_rounds',0)==0
    packet=next(data for p in (e.root/'agent').glob('*-spec_refine/prompt.txt') if 'attempted_delta' in (data:=json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])))
    assert packet['attempted_delta']['target_profile']==profile.model_dump(mode='json')
    assert packet['materials'] and packet['diagnostics'][0]['details']==d['details']


def test_navigation_provenance_cannot_support_unseen_delta(tmp_path,prepared):
    from consensus_assurance.workflow.audit_spec import merge_delta
    from consensus_assurance.core.types import InquiryTask
    from consensus_assurance.core.proposals import AuditSpecDelta
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);spec=inventory(state.materials[0].id);accept(e,spec)
    task=InquiryTask(kind='spec_refine',reason='Interpret the producer',trigger='unseen',target_ids=['producer'],context_receipt_id='navigation-only')
    delta=AuditSpecDelta(behaviors=[spec.behaviors[0].model_copy(update={'execution_owner':'A different owner'})],rationale='A proposed observation from historical provenance')
    with pytest.raises(SpecIssue,match='attached exact source'):merge_delta(state,task,delta)
    task.material_ids=[state.materials[0].id]
    delta.behaviors[0].source_ids.append(state.materials[-1].id)
    assert state.materials[-1].id not in task.material_ids  # Retained provenance is not a current body dependency.
    assert merge_delta(state,task,delta).behaviors[0].execution_owner=='A different owner'


@pytest.mark.parametrize('mode',['partial','complete','navigation'])
def test_composite_surface_retains_schedulable_remainder(tmp_path,prepared,mode):
    from consensus_assurance.core.proposals import AuditSpecDelta
    from consensus_assurance.core.types import InquiryTask
    from consensus_assurance.workflow.audit_spec import merge_delta
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);state.units=[]
    spec=inventory(state.materials[0].id)
    parent=Surface(entry_point='composite',disposition='deferred',high_consequence=True,reason='Two owners unread')
    spec.surfaces=[parent];accept(e,spec)
    task=InquiryTask(kind='spec_refine',reason='Interpret one owner',trigger='surface',surface_entry_points=['composite'],context_receipt_id='current',admitted=True,
        material_ids=[] if mode=='navigation' else [state.materials[0].id])
    state.inquiry_tasks=[task]
    mapped=Surface(entry_point='known owner' if mode=='partial' else 'composite',disposition='mapped',behavior_ids=['producer'],source_ids=[state.materials[0].id],reason='Exact acquired producer source')
    surfaces=[mapped]
    if mode=='partial':surfaces.append(Surface(entry_point='remaining owner',disposition='deferred',high_consequence=True,reason='Remaining independent owner is unread'))
    delta=AuditSpecDelta(surfaces=surfaces,remove_surface_entry_points=['composite'] if mode=='partial' else [],rationale='Map only the interpreted responsibility')
    if mode=='navigation':
        with pytest.raises(SpecIssue,match='attached exact source'):merge_delta(state,task,delta)
        return
    accept(e,merge_delta(state,task,delta))
    assert ('remaining owner' in {s.entry_point for s in load(state).surfaces}) is (mode=='partial')
    assert len(load(state).surfaces)==(2 if mode=='partial' else 1)


@pytest.mark.parametrize('variant',['paxos','n2paxos','swift'])
def test_variant_visibility_is_a_subset_of_safe_build_files(tmp_path,variant):
    from consensus_assurance.cli import load_config,main
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.materials import metadata,initial_materials
    repo=tmp_path/'source';repo.mkdir()
    families=['paxos','n2paxos','swift','epaxos','fastpaxos','curp']
    for family in families+['replica']:
        (repo/family).mkdir();(repo/family/'node.go').write_text('package '+family+'\n')
    (repo/'go.mod').write_text('module github.com/imdea-software/swiftpaxos\n')
    (repo/'README.md').write_text('Repository orientation')
    (repo/variant/'secret.txt').write_text('Private file')
    (repo/variant/'binary').write_bytes(b'\0')
    cfg=Path(__file__).resolve().parents[2]/f'configs/targets/swiftpaxos_{variant}.yaml'
    config=load_config(str(cfg));snapshot=capture(repo,analysis_roots=config.target.analysis_roots)
    assert all(f'{f}/node.go' in snapshot.files for f in families)
    assert {f'{variant}/node.go','replica/node.go','go.mod','README.md'}==set(snapshot.readable_files)
    for f in families:
        if f!=variant:
            with pytest.raises(PermissionError):metadata(repo,snapshot,f'{f}/node.go')
    assert {m.file for m in initial_materials(repo,snapshot,config.budget,'')}<=set(snapshot.readable_files)
    assert main(['inspect','--config',str(cfg),'--repo',str(repo),'--runs-dir',str(tmp_path/'inspect')])==0
    saved=json.loads(next((tmp_path/'inspect').glob('*/snapshot.json')).read_text())
    assert saved['files']==snapshot.files and saved['readable_files']==snapshot.readable_files
