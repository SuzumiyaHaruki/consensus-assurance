"""Autonomous candidate disposition and progressive-frontier behavior."""
import json
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Derivation
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.registry import assemble
from regression_support import bounded_derivation


@pytest.mark.parametrize('next_outcome',['explained','escalated'])
def test_evidence_blocked_candidate_does_not_end_autonomous_selection(tmp_path,prepared,next_outcome):
    """Synthetic 13:43:11 regression: no contract source is a result, not repair."""
    from consensus_assurance.core.types import AuditQuestion,ReadRequest
    from regression_support import descriptive_inventory
    repo,_,_,responses=prepared
    source=responses[1]['claims'][0]['source_ids'][0]
    description=descriptive_inventory(source);spec=description.audit_spec
    spec.behaviors.append(spec.behaviors[0].model_copy(update={'id':'second_step','produces_fact_ids':['second_fact'],'consumes_fact_ids':['second_fact']}))
    spec.facts.append(spec.facts[0].model_copy(update={'id':'second_fact','established_by':['second_step'],'consumed_by':['second_step']}))
    first=AuditQuestion(question='Does the caller owe error propagation?',importance='A claimed publication may be absent',source_ids=[source],activity_classes=['A1'],behavior_ids=['fixture_step'],fact_ids=['fixture_value'],obligation_relation_kind='establishment',preferred_check='source_review',disposition='needs_specific_evidence',counterevidence=['First-path guard propagates reported errors'],unknowns=['Applicable caller responsibility is unassigned'],trigger_rationale='Inspect the remaining contract discriminator')
    second=first.model_copy(update={'question':'Does the independent operation establish its documented bound?','fact_ids':['second_fact'],'behavior_ids':['second_step'],'counterevidence':['Independent operation validates its bound'],'unknowns':['Selected bound requires source verification']})
    read=lambda a,b:[ReadRequest(file='counter.py',start_line=a,end_line=b,reason='Inspect the selected operation')]
    replies=[responses[0],description.model_dump(mode='json'),
        Derivation(audit_question=first,reading_requests=read(1,2),selection_rationale='Select the first discriminator').model_dump(mode='json'),
        Derivation(audit_question=first,selection_rationale='Reviewed caller and interface do not assign the responsibility; no exact next contract source is known').model_dump(mode='json'),
        Derivation(audit_question=second,reading_requests=read(1,10 if next_outcome=='escalated' else 4),selection_rationale='Select an independent bounded discriminator').model_dump(mode='json')]
    if next_outcome=='explained':
        second.disposition='explained_by_existing_mechanism'
        replies.extend([Derivation(audit_question=second,selection_rationale='The supplied independent validation explains this suspicion').model_dump(mode='json'),Derivation(selection_rationale='No additional tractable candidate follows from the current inventory and sources').model_dump(mode='json')])
    else:
        upgrade=Derivation.model_validate(bounded_derivation(responses[1]));upgrade.audit_question=second.model_copy(update={'disposition':'ready_for_check','preferred_check':'local_model'})
        replies.append(upgrade.model_dump(mode='json'))
    fixture=tmp_path/'candidate-flow.json';fixture.write_text(json.dumps(replies))
    config=Config(execution_backend='none',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    engine=Engine(config,tmp_path/'run',*assemble(config));state=engine.start(repo,plan_only=next_outcome=='escalated')
    assert [c.status for c in state.question_candidates]==['blocked',next_outcome],state.stop_reason
    assert not state.repair_sessions and state.pending_output_repair is None
    assert not state.models and not state.direct_checks and not state.evidence
    assert engine.implementation is None and state.capabilities[0].status=='unavailable'
    from consensus_assurance.workflow.direct_checks import proceed
    from consensus_assurance.workflow.errors import Blocked
    with pytest.raises(Blocked,match='no execution backend'):proceed(engine,None,'direct_check')
    first_record,second_record=state.question_candidates
    assert first_record.question.disposition=='needs_specific_evidence' and first_record.stop_reason
    assert first.counterevidence[0] not in second_record.question.counterevidence
    packets=[json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1]) for p in (engine.root/'agent').glob('*-derive/prompt.txt')]
    assert any(any(c['status']=='blocked' and c['fact_ids']==first.fact_ids for c in p.get('candidate_dispositions',[])) for p in packets)
    assert any(p.get('selected_question',{}).get('fact_ids')==second.fact_ids for p in packets)
    if next_outcome=='explained':
        assert state.stop_reason=='No pending executable audit units; unresolved gaps remain'
        assert not state.claims and not state.units and any('No additional tractable candidate selected:' in g for g in state.gaps)
        assert state.usage['agent_calls']==7
    else:
        assert len(state.claims)==len(state.units)==1 and state.units[0].relation_ids==[]
        assert state.units[0].audit_question.fact_ids==second.fact_ids
        assert second_record.obligation_id==state.units[0].obligation_ids[0]


def test_selected_frontier_continues_after_candidate_disposition(tmp_path,prepared):
    """An explicit frontier choice survives candidate disposition and name ordering."""
    from consensus_assurance.core.types import AuditQuestion,ReadRequest,Surface,Behavior,Fact
    from consensus_assurance.core.proposals import SpecRefinement,AuditSpecDelta
    from regression_support import descriptive_inventory
    repo,_,_,responses=prepared
    (repo/'latent.py').write_text('\n'*99+'def restore(value):\n    return value\n# recovery boundary\n')
    source=responses[1]['claims'][0]['source_ids'][0]
    description=descriptive_inventory(source)
    description.audit_spec.activities[0].behavior_ids=['fixture_step']
    description.audit_spec.surfaces.extend(Surface(entry_point=name,disposition='deferred',high_consequence=True,reason='Implementation owner unread',source_ids=[source]) for name in ['external boundary','recovery boundary'])
    q=AuditQuestion(question='Does the established input retain identity?',importance='Result correlation',source_ids=[source],activity_classes=['A1'],behavior_ids=['fixture_step'],fact_ids=['fixture_value'],obligation_relation_kind='consumption',preferred_check='source_review',disposition='needs_specific_evidence',counterevidence=['Scoped identity check exists'],unknowns=['Verify actual owner'],trigger_rationale='Check the selected source')
    actual='latent.py:100:102'
    behavior=Behavior(id='restore',primary_activity='A7',execution_owner='caller',protocol_context='one restore',trigger='restore call',produces_fact_ids=['restored'],source_ids=[actual])
    fact=Fact(id='restored',meaning='The supplied value is returned',identity={'operation':'restore call'},validity_context='one synchronous call',representation=['return value'],durability='No durable effect',recovery='Supplied by caller',source_ids=[actual],unknowns=['External consumer not inspected'])
    later=q.model_copy(update={'question':'Does restore return the same scoped input?','source_ids':[actual],'activity_classes':['A7'],'behavior_ids':['restore'],'fact_ids':['restored'],'counterevidence':['The acquired return preserves the supplied value']})
    reading=ReadRequest(file='latent.py',start_line=100,end_line=102,reason='Read the exact previously unread restore declaration')
    def select(question,requests):return Derivation(audit_question=question,reading_requests=requests,selection_rationale='One bounded source discriminator').model_dump(mode='json')
    def explain(question):return select(question.model_copy(update={'disposition':'explained_by_existing_mechanism'}),[])
    replies=[responses[0],description.model_dump(mode='json'),
        select(q,[ReadRequest(file='counter.py',start_line=1,end_line=10,reason='Review scoped operation')]),explain(q),
        Derivation(frontier_entry_point='recovery boundary',reading_requests=[reading],selection_rationale='The unread restore declaration is the next concrete dependency').model_dump(mode='json'),
        SpecRefinement(understanding='Recover the synchronous restore owner',delta=AuditSpecDelta(behaviors=[behavior],facts=[fact],surfaces=[Surface(entry_point='recovery boundary',disposition='mapped',behavior_ids=['restore'],reason='Acquired declaration and return',source_ids=[actual],high_consequence=True)],rationale='Add the previously absent recovery path'),limitations=['Consumer remains external']).model_dump(mode='json'),
        select(later,[reading]),explain(later),Derivation(selection_rationale='No further tractable discriminator is supported').model_dump(mode='json')]
    fixture=tmp_path/'progressive.json';fixture.write_text(json.dumps(replies))
    config=Config(execution_backend='none',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    config.budget.agent_calls=len(replies)+1  # Exact finite scripted sequence; production budgets are unchanged.
    engine=Engine(config,tmp_path/'progressive-run',*assemble(config));state=engine.start(repo)
    assert [c.status for c in state.question_candidates]==['explained','explained'],state.stop_reason
    assert state.audit_spec_version==2 and not state.repair_sessions
    tasks=[t for t in state.inquiry_tasks if t.surface_entry_points]
    assert [t.surface_entry_points for t in tasks]==[['recovery boundary']]
    assert all(t.status=='completed' for t in tasks)
    assert not state.claims and not state.units and not state.evidence
    assert [c.parameters.get('agent_task') for c in state.checks if c.parameters.get('agent_task')]==['read','discover','derive','derive','derive','spec_refine','derive','derive','derive']
    from consensus_assurance.workflow.audit_spec import load
    assert load(state).surfaces[-2].disposition=='deferred' and load(state).facts[-1].established_by==['restore']
