"""Generation, diagnostics and bounded repair share the graph interface."""
import json
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import GraphDraft
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.graph import apply_graph
from consensus_assurance.workflow.graph_diagnostics import diagnose_graph
from consensus_assurance.workflow.associations import graph_contract,relevant_use
from consensus_assurance.workflow.output_repair import diagnostic_targets,diagnostic_context,apply_replacements,OutputRepair
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble


def test_saved_draft_repairs_multiple_reference_errors_with_existing_budget(tmp_path,prepared):
    from consensus_assurance.core.proposals import Derivation
    from consensus_assurance.workflow.discovery import validate_derivation
    from regression_support import bounded_derivation
    repo,source,_,responses=prepared;correct=bounded_derivation(responses[1])
    original=json.loads(json.dumps(correct));repairs=[]
    for field in ('source_ids','expectation_ids'):
        original['obligation']['grounding'][field].append('unknown-reference')
        repairs.append({'path':'/obligation/grounding/'+field,'value_json':json.dumps(correct['obligation']['grounding'][field])})
    fixture=tmp_path/'interface.json';fixture.write_text(json.dumps([original,{'replacements':repairs,'rationale':'Correct opaque references while preserving all actual source'}]))
    cfg=Config(execution_backend='python',agent_backend='mock',fixture=str(fixture),allow_experiments=False)
    class CandidateOnly(Engine):
        def execute(self,**kwargs):
            self.state.materials=source.materials;self.state.analysis_mode='regression'
            from regression_support import descriptive_inventory
            from consensus_assurance.workflow.audit_spec import accept
            accept(self,descriptive_inventory(source.materials[0].id).audit_spec)
            return self.ask('derive',Derivation,{'materials':[m.model_dump(mode='json') for m in source.materials]},lambda p:validate_derivation(self.state,p))
    engine=CandidateOnly(cfg,tmp_path/'run',*assemble(cfg));result,_=engine.start(repo)
    assert result.model_dump(mode='json')==correct and engine.state.usage['agent_calls']==2
    session=next(iter(engine.state.repair_sessions.values()))
    assert session['status']=='accepted' and json.loads(Path(session['original_path']).read_text())==original


@pytest.mark.parametrize('case',['direct','dangling','dependency','missing_support','multiple_primary','empty_question','unread_question','empty_source','wrong_claim_kind','invalid_grounding','unattributed','duplicate'])
def test_candidate_contract_parity(prepared,case):
    from consensus_assurance.core.proposals import UnitDraft,RelationDraft
    from pydantic import ValidationError
    _,state,_,responses=prepared;p=GraphDraft.model_validate(responses[1]);u=p.units[0]
    if case=='dangling':u.relation_ids=['missing']
    if case=='duplicate':p.bindings[-1].id=p.bindings[0].id
    if case=='unattributed':p.claims[0].grounding.derivation=''
    if case=='invalid_grounding':
        for c in p.claims:c.grounding.expectation_ids=['unknown-reference']
    if case in {'dependency','missing_support'}:
        u.binding_ids.append('input_binding')
        if case=='dependency':
            edge=RelationDraft(id='dependency',source='step_obligation',target='input_obligation',kind='depends_all',group=None,rationale='Actual producer dependency',pending=['Producer contract unverified'],grounding=p.claims[1].grounding)
            p.relations=[edge];u.relation_ids=[edge.id]
    if case=='multiple_primary':
        raw=u.model_dump();raw['obligation_ids'].append('input_obligation')
        with pytest.raises(ValidationError):UnitDraft.model_validate(raw)
        p.units[0]=u.model_copy(update={'obligation_ids':raw['obligation_ids']})
    if case in {'empty_question','unread_question','empty_source'}:
        from consensus_assurance.core.types import AuditQuestion
        u.audit_question=AuditQuestion(question='' if case=='empty_question' else 'An actual question',importance='Service consequence',trigger_rationale='Inspect scoped behavior',source_ids=[] if case=='empty_source' else ['missing'] if case=='unread_question' else [state.materials[0].id])
    if case=='wrong_claim_kind':next(c for c in p.claims if c.id=='step_obligation').kind='assumption'
    before=state.model_dump();issues=diagnose_graph(state,p)
    if case in {'direct','dependency'}:
        assert not issues
        trial=state.model_copy(deep=True);apply_graph(trial,p)
        assert len(trial.units[0].obligation_ids)==1
        if case=='dependency':assert 'input_binding' in trial.units[0].binding_ids and trial.units[0].obligation_ids==['step_obligation']
    else:
        assert issues and all(d.code!='unclassified_validation' and d.paths and d.object_ids for d in issues)
        if case=='dangling':assert any('/units/0/relation_ids' in d.paths for d in issues)
        with pytest.raises(DiagnosticError) as exc:apply_graph(state.model_copy(deep=True),p)
        assert exc.value.diagnostics==issues
    assert state.model_dump()==before
