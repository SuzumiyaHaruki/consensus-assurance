"""Implementation inventory tests, not evidence of autonomous discovery or correctness."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from consensus_assurance.core.types import ConsensusAuditSpec, AuditQuestion, Material
from consensus_assurance.workflow.audit_spec import validate, accept, load, slice_for, validate_question, coverage_ledger
from consensus_assurance.workflow.inquiry import choose_task
from consensus_assurance.workflow.graph import select_unit


def inventory(source, variant='rsm'):
    activities=[dict(class_id='A'+str(n),applicability='applicable',purpose='End-to-end responsibility '+str(n),
        realization_summary='Sourced realization in '+variant,entry_points=['entry'+str(n)],
        unknowns=['Unrecovered branches'],source_ids=[source],coverage=dict(behavior='partial',fact='unknown',handoff='unknown')) for n in range(1,8)]
    if variant=='static_ballot':activities[3].update(applicability='not_applicable',realization_summary='The fixture has a fixed participant set')
    if variant=='primitive':
        for i in (4,6):activities[i].update(applicability='externalized',realization_summary='The caller owns service execution and completion through the exported interface')
    context='per-instance recovery ballot' if variant=='per_instance' else 'ballot' if variant=='static_ballot' else 'operation instance'
    behaviors=[dict(id='capture',primary_activity='A6',execution_owner='store producer',protocol_context=context,trigger='capture request',source_ids=[source],produces_fact_ids=['usable']),
        dict(id='restore',primary_activity='A3',execution_owner='recovering replica',protocol_context=context,trigger='restore request',source_ids=[source],consumes_fact_ids=['usable'],cross_activity_effects={'A5':'Replace application state'}),
        dict(id='replace',primary_activity='A6',execution_owner='concurrent producer',protocol_context=context,trigger='replacement',source_ids=[source],important_branches=['reject','retry','partial error'],consumes_fact_ids=['usable'],produces_fact_ids=['usable'])]
    facts=[dict(id='usable',meaning='A representation usable to reconstruct the captured history',identity={'operation':'original capture instance'},established_by=['capture','replace'],consumed_by=['restore','replace'],validity_context=context,representation=['store pointer and bytes'],invalidators=['replace'],durability='Depends on injected adapter',recovery='Consumed through restore',source_ids=[source],unknowns=['Atomic publication guarantee is unverified'])]
    handoffs=[dict(id='recovery',fact_id='usable',producer_activity='A6',consumer_activity='A3',producer_behavior_ids=['capture'],consumer_behavior_ids=['restore'],consumer_expectation='A usable representation',unresolved_gap='Adapter error handling',source_ids=[source])]
    for a in activities:
        a['behavior_ids']=[b['id'] for b in behaviors if b['primary_activity']==a['class_id']]
        if a['class_id'] in {'A6','A3'}:a.update(fact_ids=['usable'],handoff_ids=['recovery'])
    return ConsensusAuditSpec(target_profile=dict(system_boundary='Synthetic '+variant,protocol_contexts=[context],ownership=['Caller owns injected persistence adapter'],selection_injection=['Constructor parameter'],source_ids=[source]),activities=activities,behaviors=behaviors,facts=facts,handoffs=handoffs,coverage_summary=[dict(entry_point='restore',disposition='mapped',behavior_ids=['restore'],reason='Actual consumer',source_ids=[source])])


def question(source):
    return AuditQuestion(question='Does replacement preserve the representation consumed by recovery?',importance='Recovery could fail',source_ids=[source],activity_classes=['A6','A3'],behavior_ids=['capture','replace','restore'],fact_ids=['usable'],handoff_ids=['recovery'],obligation_relation_kind='preservation',counterevidence=['Caller ownership is unresolved'],unknowns=['Adapter selection'],trigger_rationale='Failure injection with an independent byte oracle',disposition='concrete_suspicion',preferred_check='direct_test')


@pytest.mark.parametrize('variant',['rsm','static_ballot','per_instance','primitive','injected_adapter'])
def test_parallel_coordinates_and_injected_ownership(prepared,tmp_path,variant):
    _,state,_,_=prepared;spec=inventory(state.materials[0].id,variant)
    assert validate(state,spec)==spec
    engine=SimpleNamespace(state=state,root=tmp_path)
    accept(engine,spec)
    assert state.audit_spec_version==1 and not hasattr(state,'responsibilities')
    assert load(state).target_profile.selection_injection==['Constructor parameter']
    assert len(coverage_ledger(state))==7
    if variant=='static_ballot':assert spec.activities[3].applicability=='not_applicable'
    if variant=='primitive':assert spec.activities[4].applicability==spec.activities[6].applicability=='externalized'
    assert len(spec.behaviors)==3  # Cross-class effect does not duplicate restore.


def test_many_to_many_cycles_identity_and_fact_not_variable(prepared):
    _,state,_,_=prepared;spec=inventory(state.materials[0].id)
    validate(state,spec)
    assert spec.facts[0].meaning!=spec.facts[0].representation[0]
    other=spec.facts[0].model_copy(deep=True);other.id='another_context';other.identity={'operation':'later instance'}
    spec.facts.append(other)
    for b in spec.behaviors:
        if b.id in other.established_by:b.produces_fact_ids.append(other.id)
        if b.id in other.consumed_by:b.consumes_fact_ids.append(other.id)
    spec.facts[0].invalidators.append('restore')
    validate(state,spec)
    assert spec.facts[0].identity!=spec.facts[1].identity
    spec.behaviors[0].produces_fact_ids=[]
    with pytest.raises(ValueError,match='indexes disagree'):validate(state,spec)
    spec=inventory(state.materials[0].id);spec.facts[0].identity={}
    with pytest.raises(ValueError,match='identity'):validate(state,spec)


def test_descriptive_repair_and_active_normative_boundary(prepared,tmp_path):
    _,state,_,_=prepared;source=state.materials[0].id;engine=SimpleNamespace(state=state,root=tmp_path)
    spec=inventory(source);accept(engine,spec)
    old=Path(state.audit_spec_path).read_bytes()
    revised=load(state);revised.target_profile.selection_injection=['Actual constructor supplies an external adapter']
    revised.activities[5].realization_summary='Adapter owns publication; caller selects it'
    revised.activities[5].applicability='externalized';accept(engine,revised)
    assert state.audit_spec_version==2 and (tmp_path/'audit-spec/v1.json').read_bytes()==old
    state.units[0].audit_question=question(source)
    changed=load(state);changed.facts[0].meaning='A stronger guaranteed durable representation'
    with pytest.raises(ValueError,match='F2'):accept(engine,changed)
    changed=load(state);changed.activities[0].applicability='externalized'
    with pytest.raises(ValueError,match='attributed'):accept(engine,changed)


def test_local_slice_keeps_interference_and_open_unknowns(prepared,tmp_path):
    _,state,_,_=prepared;source=state.materials[0].id;spec=inventory(source);accept(SimpleNamespace(state=state,root=tmp_path),spec)
    q=question(source);q.behavior_ids=['restore'];validate_question(spec,q)
    view=slice_for(state,q)
    assert {b['id'] for b in view['behaviors']}=={'capture','restore','replace'}
    assert view['facts'][0]['unknowns'] and len(view['activities'])<7
    assert 'semantic_reviews' not in view
    assert not state.units[0].scope.assumptions or 'Atomic publication guarantee' not in str(state.units[0].scope.assumptions)


def test_inventory_unknowns_do_not_enqueue_and_high_consequence_does(prepared,tmp_path):
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);spec=inventory(state.materials[0].id);accept(e,spec)
    state.units[0].audit_question=question(state.materials[0].id)
    state.units[0].audit_question.disposition='ready_for_check'
    assert choose_task(e) is None and not state.inquiry_tasks
    spec=load(state);spec.unclassified=[dict(entry_point='unexplained protocol operation',disposition='UNCLASSIFIED_PROTOCOL_RESPONSIBILITY',reason='No supported taxonomy fit',source_ids=[state.materials[0].id],high_consequence=True)]
    spec=ConsensusAuditSpec.model_validate(spec.model_dump());accept(e,spec)
    task=choose_task(e)
    assert task.kind=='spec_refine' and 'unmapped' in task.reason


def test_selection_reassesses_consequence_not_round_robin(prepared):
    _,state,_,_=prepared;u=state.units[0];u.audit_question=question(state.materials[0].id);u.audit_question.priority=1;u.status='checked'
    a=u.model_copy(deep=True);a.id='more_history';a.status='pending'
    b=u.model_copy(deep=True);b.id='decision_handoff';b.status='pending';b.audit_question.activity_classes=['A1'];b.audit_question.priority=3
    state.units.extend([a,b]);assert select_unit(state).id==b.id


def test_archived_snapshot_spec_has_unconfirmed_consumer_boundary(tmp_path):
    from consensus_assurance.workflow.history import load_analysis
    root=Path(__file__).resolve().parents[2]
    archive=root/'runs/2026-09-17_13-59-36-hashicorp_raft-real-run'
    state=load_analysis(archive/'state.json')
    fixture=json.loads((root/'tests/fixtures/snapshot_inventory.json').read_text())
    state.materials.extend(Material.model_validate(m) for m in fixture['additional_materials'])
    spec=ConsensusAuditSpec.model_validate(fixture['audit_spec']);validate(state,spec)
    accept(SimpleNamespace(state=state,root=tmp_path),spec)
    assert spec.handoffs[0].producer_activity=='A6' and spec.handoffs[0].consumer_activity=='A3'
    assert spec.facts[0].unknowns and fixture['candidate']['preferred_check']=='direct_test'
    assert not state.evidence and not state.direct_checks and not state.models
    assert 'constructor' in str(spec.target_profile.selection_injection).lower()
    assert 'startup_restore' in spec.activities[2].behavior_ids
    assert 'replace' not in spec.facts[0].established_by
    assert spec.activities[2].variants and spec.activities[2].unknowns


def test_unknown_producer_stays_unknown_and_indexes_are_derived(prepared):
    from consensus_assurance.adapters.agents.backend import wire_value
    _,state,_,_=prepared;spec=inventory(state.materials[0].id)
    raw=wire_value(spec.model_dump(mode='json'),spec.model_json_schema())
    raw['behaviors'][0]['produces_fact_ids']=[];raw['behaviors'][2]['produces_fact_ids']=[]
    raw['handoffs']=[]
    for a in raw['activities']:a['handoff_ids']=[]
    raw['facts'][0]['unknowns']=['The actual producer has not been read']
    decoded=ConsensusAuditSpec.model_validate(wire_value(raw,spec.model_json_schema(),decode=True))
    validate(state,decoded)
    assert decoded.facts[0].established_by==[] and decoded.facts[0].consumed_by==['restore','replace']
    assert decoded.facts[0].unknowns==['The actual producer has not been read']
    assert decoded.activities[5].behavior_ids==['capture','replace']


def test_recorded_semantic_references_are_diagnosed_not_invented(prepared):
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.workflow.output_repair import OutputRepair,apply_replacements
    _,state,_,_=prepared
    data=json.loads((Path(__file__).parents[1]/'fixtures/discovery_wire_failure.json').read_text())
    patch=OutputRepair.model_validate(data['attempted_repair'])
    fixed=apply_replacements(data['candidate'],[{'path':r.path} for r in patch.replacements],patch)
    spec=Discovery.model_validate(fixed).audit_spec
    before=spec.model_dump()
    with pytest.raises(DiagnosticError) as failure:validate(state,spec)
    issues=failure.value.diagnostics
    assert any(d.paths==['/audit_spec/facts/6/consumed_by'] and 'A7' in d.details['invalid_references'] for d in issues)
    assert any(d.paths==['/audit_spec/facts/0/invalidators'] for d in issues)
    assert all(d.paths and d.details['allowed_ids'] for d in issues)
    assert spec.model_dump()==before and not state.evidence


def test_recorded_subranges_resolve_but_handoff_semantics_remain_rejected():
    from consensus_assurance.core.types import Analysis, Snapshot
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.sources import citation_ranges
    data=json.loads((Path(__file__).parents[1]/'fixtures/covered_citation_failure.json').read_text())
    state=Analysis(mode='mock',config={},snapshot=Snapshot.model_validate(data['snapshot']),materials=[Material.model_validate(m) for m in data['materials']])
    original_materials=list(state.materials)
    reply=Discovery.model_validate(data['candidate']);refs=citation_ranges(reply,state)
    assert len(refs)==15 and refs['fsm.go:16:81']['end_line']==81
    for id,ref in refs.items():
        lines={n:text for m in state.materials if m.file==ref['file'] and m.content_digest==ref['content_digest'] for n,text in enumerate(m.text.splitlines(),m.start_line)}
        state.materials.append(Material(id=id,**ref,kind='code_observation',text='\n'.join(lines[n] for n in range(ref['start_line'],ref['end_line']+1))))
    reply.audit_spec.activities[1].handoff_ids=[]  # Separate known dangling draft reference.
    with pytest.raises(DiagnosticError) as failure:validate(state,reply.audit_spec)
    d=failure.value.diagnostics[0]
    assert d.code=='handoff_fact_semantics' and d.category=='semantic'
    assert d.details['handoff']['id']=='H_commit_to_apply'
    assert d.details['fact']['id']=='F_fsm_applied'
    assert reply.audit_spec.facts[0].source_ids==data['candidate']['audit_spec']['facts'][0]['source_ids']
    from consensus_assurance.workflow.output_repair import OutputRepair,apply_replacements
    from consensus_assurance.workflow.repair_policy import validate_representation
    patch=OutputRepair.model_validate(data['discarding_patch']);targets=[{'path':r.path} for r in patch.replacements]
    changed=apply_replacements(data['candidate'],targets,patch)
    with pytest.raises(ValueError,match='cannot discard evidence'):
        validate_representation(data['candidate'],changed,targets,{'materials':[m.model_dump(mode='json') for m in state.materials]})
    # Neither holes nor another content version may be silently registered.
    state.materials=[m for m in original_materials if m.file!='fsm.go' or m.end_line<=80]
    assert 'fsm.go:16:81' not in citation_ranges(reply,state)
    state.materials=original_materials
    state.snapshot.files['snapshot.go']='another-version'
    assert 'snapshot.go:125:211' not in citation_ranges(reply,state)


def test_unaccepted_handoff_can_be_corrected_without_rewriting_existing_facts(prepared):
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.output_repair import diagnostic_targets,apply_replacements,OutputRepair,Replacement
    _,state,_,_=prepared
    spec=inventory(state.materials[0].id)
    output=spec.facts[0].model_copy(deep=True);output.id='restored';output.established_by=['restore'];output.consumed_by=[]
    spec.facts.append(output);spec.behaviors[1].produces_fact_ids=['restored']
    spec.handoffs[0].fact_id='restored'
    with pytest.raises(DiagnosticError) as failure:validate(state,spec)
    d=failure.value.diagnostics[0]
    assert d.code=='handoff_fact_semantics' and 'representation' in d.allowed
    raw={'audit_spec':spec.model_dump(mode='json')}
    patch=OutputRepair(replacements=[Replacement(path='/audit_spec/handoffs/0/fact_id',value_json='"usable"')],rationale='The captured representation is the input; restoration is the output')
    corrected=apply_replacements(raw,diagnostic_targets(raw,[d],16000),patch)
    validate(state,ConsensusAuditSpec.model_validate(corrected['audit_spec']))
    assert corrected['audit_spec']['facts']==raw['audit_spec']['facts']
    assert corrected['audit_spec']['behaviors']==raw['audit_spec']['behaviors']
