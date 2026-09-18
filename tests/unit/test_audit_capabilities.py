"""Stable R1-R5/R8 capabilities; R6/R7 retain actual execution and TLC suites."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from consensus_assurance.core.types import ConsensusAuditSpec,Activity,Behavior,Fact,Surface,TargetProfile,AuditQuestion
from consensus_assurance.workflow.audit_spec import validate,accept,SpecIssue,load,refinement_reason


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
    from consensus_assurance.core.proposals import SpecRefinement
    import shutil
    repo,state,_,_=prepared;e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    spec=inventory(state.materials[0].id);bad=spec.model_copy(deep=True)
    bad.behaviors[0].execution_owner='two independent loops';bad.behaviors[0].produces_fact_ids=['unrepresented']
    bad.facts[0].meaning='A transition was requested or completed';bad.surfaces[0].behavior_ids=['unrepresented']
    with pytest.raises(SpecIssue) as exc:validate(state,bad)
    path=tmp_path/'draft.json';path.write_text(json.dumps({'audit_spec':bad.model_dump(mode='json')}))
    task=enqueue(state,'spec_refine','Split the mixed producer and assertion','test')
    task.draft_path=str(path);task.diagnostics=[d.model_dump(mode='json') for d in exc.value.diagnostics]
    packet=task_context(e,task);required={id for d in task.diagnostics for id in d['material_ids']}
    assert required<={m['id'] for m in packet['materials']}
    spec.behaviors.append(Behavior(id='notifier',primary_activity='A2',execution_owner='control loop',protocol_context='one operation',trigger='timeout',produces_fact_ids=['notification'],source_ids=[state.materials[0].id],unknowns=['Completion consumer unread']))
    spec.facts.append(Fact(id='notification',meaning='A context transition has been requested',identity={'operation':'request'},validity_context='one operation',established_by=['notifier'],representation=['notification'],durability='Not persisted',recovery='Discarded',source_ids=[state.materials[0].id],unknowns=['Completion consumer unread']))
    agent=MockAgent();agent.responses=[SpecRefinement(understanding='Separate request notification from established input',audit_spec=spec,limitations=['Completion remains unknown']).model_dump(mode='json')];e.agent=agent
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


def test_R4_breadth_preserves_order_and_requests_replan(tmp_path,prepared):
    from consensus_assurance.workflow.materials import plan_read,ReadingPlan,validate_read_requests
    from consensus_assurance.core.config import Config
    from consensus_assurance.core.diagnostics import DiagnosticError
    repo,state,_,_=prepared;state.materials=[]
    budget=Config.model_validate(state.config).budget;budget.material_chars=10;state.config['budget']=budget.model_dump(mode='json')
    requests=[{'file':'counter.py','start_line':1,'end_line':10,'reason':'Priority producer'}, {'file':'limits.py','start_line':1,'end_line':1,'reason':'Secondary range'}]
    with pytest.raises(DiagnosticError) as exc:validate_read_requests(state,repo,ReadingPlan(requests=requests,rationale='Authored priority'))
    assert exc.value.diagnostics[0].code=='reading_plan_budget'
    receipt,_=plan_read(state,repo,requests,budget,purpose='breadth',partial=True)
    assert [i.request.file for i in receipt.items]==['counter.py','limits.py'] and all(i.status=='deferred' for i in receipt.items)


def test_R5_ready_evidence_precedes_unrelated_unknowns(tmp_path,prepared):
    from consensus_assurance.workflow.graph import select_unit
    _,state,_,_=prepared;spec=inventory(state.materials[0].id);accept(SimpleNamespace(state=state,root=tmp_path),spec)
    question=dict(question='Does this established input satisfy the selected obligation?',importance='Observable service consequence',source_ids=[state.materials[0].id],activity_classes=['A1','A5'],behavior_ids=['producer','consumer'],fact_ids=['fact'],obligation_relation_kind='consumption',trigger_rationale='Exercise the actual input consumption')
    unit=state.units[0];unit.audit_question=AuditQuestion(**question,disposition='ready_for_check',preferred_check='direct_test')
    other=unit.model_copy(deep=True);other.id='needs-source';other.obligation_ids=['input_obligation'];other.audit_question.disposition='needs_specific_evidence';other.audit_question.priority=3;state.units.append(other)
    assert select_unit(state).id==unit.id and refinement_reason(state) is None
    assert len(unit.obligation_ids)==1 and not state.inquiry_tasks


def test_R8_selected_archive_is_view_only(tmp_path):
    from consensus_assurance.workflow.history import load_analysis
    from consensus_assurance.reporting.chinese import render_report
    from consensus_assurance.workflow.engine import FRAMEWORK_REVISION
    root=Path(__file__).resolve().parents[2]/'runs/2026-09-18_10-29-33-hashicorp_raft-real-run'
    state=load_analysis(root/'state.json')
    assert state.framework_revision==FRAMEWORK_REVISION and state.audit_spec_path and not state.claims and not state.evidence
    report=render_report(state,root).read_text()
    assert '候选修复会话' in report and 'Audit unit references missing bindings or relations' in report
    state=state.model_copy(deep=True);state.framework_revision='historical-test-revision'
    from test_graph_mutations import controller
    engine=controller(tmp_path,state);engine.store=SimpleNamespace(load=lambda:state)
    before=dict(state.usage);assert engine.resume() is state
    assert 'Framework revision differs' in state.stop_reason and state.usage==before
