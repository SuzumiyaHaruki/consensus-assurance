"""Generation, diagnostics and bounded repair share the graph interface."""
import json
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import Discovery
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.graph import apply_discovery
from consensus_assurance.workflow.graph_diagnostics import diagnose_graph
from consensus_assurance.workflow.associations import graph_contract,use_errors,relevant_use
from consensus_assurance.workflow.output_repair import diagnostic_targets,diagnostic_context,apply_replacements,OutputRepair
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble


def broken(responses):
    candidate=Discovery.model_validate(responses[1])
    for obj in candidate.claims+candidate.relations:
        obj.grounding.behavior_ids=['invented-behavior']
        obj.grounding.expectation_ids=['invented-expectation']
    unit=candidate.units[0]
    edge=next(r for r in candidate.relations if r.source in unit.goal_ids and r.target in unit.obligation_ids)
    edge.kind='maps'
    return candidate,edge.id


def test_all_independent_graph_errors_visible_without_mutation(prepared):
    _,state,_,responses=prepared;p,_=broken(responses)
    before=state.model_dump(mode='json')
    issues=diagnose_graph(state,p)
    assert {'grounding_reference','goal_obligation_link'}<={d.code for d in issues}
    assert sum(d.code=='grounding_reference' for d in issues)==1
    with pytest.raises(DiagnosticError):apply_discovery(state,p)
    assert state.model_dump(mode='json')==before
    d=next(d for d in issues if d.code=='grounding_reference')
    targets=diagnostic_targets(p.model_dump(mode='json'),[d],16000)
    assert len(targets)==2*(len(p.claims)+len(p.relations))
    assert len({t['path'] for t in targets})==len(targets)
    assert '/claims/1/grounding/behavior_ids' in {t['path'] for t in targets}
    assert not any(t['path'].endswith('/derivation') for t in targets)
    context=diagnostic_context(p.model_dump(mode='json'),[d],{'materials':[m.model_dump(mode='json') for m in state.materials]},90000)
    assert {c.id for c in p.claims}<={o.get('id') for o in context['objects']}
    assert context['materials'] and not context['required_objects_missing']


def test_support_failure_explains_rejected_direction_and_kind(prepared):
    from consensus_assurance.core.types import CodeUse
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);u=p.units[0];b=next(b for b in p.bindings if b.id in u.binding_ids)
    u.code_uses=[CodeUse(binding_id=b.id,role='support',claim_ids=[b.associations[0].claim_id],relation_ids=u.relation_ids,
        source_ids=[b.material_id],rationale='Related background is not a producer dependency',unverified=['Contract remains unverified'])]
    errors=use_errors(u,b,p.relations,{m.id:m for m in state.materials})
    assert errors and 'directed dependency' in errors[-1]
    assert not relevant_use(u,b,p.relations,{m.id:m for m in state.materials})
    d=next(d for d in diagnose_graph(state,p) if d.code=='unit_code_use')
    assert d.details['failed_checks']==errors
    assert d.details['contract']==graph_contract()['code_use']


def test_saved_draft_repairs_multiple_reference_errors_with_existing_budget(tmp_path,prepared):
    repo,source,_,responses=prepared;p,_=broken(responses)
    original=p.model_dump(mode='json');correct=Discovery.model_validate(responses[1])
    repairs=[]
    for collection in ('claims','relations'):
        for i,obj in enumerate(getattr(correct,collection)):
            for field in ('behavior_ids','expectation_ids'):
                repairs.append({'path':f'/{collection}/{i}/grounding/{field}','value_json':json.dumps(getattr(obj.grounding,field))})
    u=correct.units[0]
    edge=next(r for r in correct.relations if r.source in u.goal_ids and r.target in u.obligation_ids).model_copy(update={'id':'new-sourced-goal-link'})
    fixture=tmp_path/'interface.json'
    fixture.write_text(json.dumps([original,{'replacements':repairs,'rationale':'Cite actual existing material without changing judgment'},
        {'replacements':[{'path':'/relations/-','value_json':edge.model_dump_json()},
            {'path':'/units/0/relation_ids','value_json':json.dumps(u.relation_ids+[edge.id])}],
         'rationale':'Add the sourced goal-to-obligation relation; preserve existing maps and checked claims'}]))
    cfg=Config(implementation='toy',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    class DiscoveryOnly(Engine):
        def execute(self,**kwargs):
            self.state.materials=source.materials
            return self.ask('discover',Discovery,{'materials':[m.model_dump(mode='json') for m in source.materials]},
                lambda candidate:apply_discovery(self.state.model_copy(deep=True),candidate))
    engine=DiscoveryOnly(cfg,tmp_path/'run',*assemble(cfg));result,_=engine.start(repo)
    assert engine.state.usage['agent_calls']==3
    assert engine.config.budget.repeated_error_revisions==1 and engine.config.budget.repair_attempts==4
    assert result.claims==correct.claims
    assert result.units[0].obligation_ids==correct.units[0].obligation_ids
    assert any(r.kind=='maps' for r in result.relations)
    assert next(iter(engine.state.repair_sessions.values()))['status']=='accepted'
    raw=Path(next(iter(engine.state.repair_sessions.values()))['original_path'])
    assert json.loads(raw.read_text())==original
    packets=[json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1]) for p in engine.root.glob('agent/*/prompt.txt')]
    assert any(p.get('graph_contract')==graph_contract() for p in packets)
    assert not engine.state.models
