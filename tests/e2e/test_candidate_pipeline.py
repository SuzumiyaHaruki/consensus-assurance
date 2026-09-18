"""Recorded derivation reaches source review offline; original evidence is read-only."""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Derivation
from consensus_assurance.workflow.engine import Engine,FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.history import load_analysis
from consensus_assurance.workflow.discovery import accept_derivation,validate_derivation,derive_context
from consensus_assurance.workflow.graph import select_unit
from consensus_assurance.workflow.direct_checks import route,continue_question
from consensus_assurance.registry import assemble
from regression_support import bounded_derivation


@pytest.mark.parametrize('debt',[None,'selected','unrelated'])
def test_recorded_derivation_contract_to_source_review(tmp_path,debt):
    archive=Path(__file__).resolve().parents[2]/'tests/fixtures/recorded_derivation_20260918'
    root=tmp_path/'offline';shutil.copytree(archive,root)
    raw=json.loads(next((archive/'agent').glob('*-derive/decoded-response.json')).read_text())
    original=json.dumps(raw,sort_keys=True)
    raw['units'][0]['relation_ids']=[]
    for use in raw['units'][0].pop('code_uses',[]):raw['bindings'][0]['pending']+=use['unverified']
    reply=Derivation.model_validate(bounded_derivation(raw))
    state=load_analysis(root/'state.json')
    old_root=str(Path(state.audit_spec_path).parent.parent);data=state.model_dump_json().replace(old_root,str(root))
    from consensus_assurance.core.types import Analysis
    state=Analysis.model_validate_json(data)
    assert Path(state.audit_spec_path).is_relative_to(root)
    state.framework_revision=FRAMEWORK_REVISION;state.pending_output_repair=None;state.pending_action=None
    config=Config(implementation='hashicorp_raft',agent_backend='mock',allow_experiments=False)
    engine=Engine(config,root,*assemble(config));engine.state=state;engine.budget=BudgetTracker(config.budget,state)
    if debt=='selected':
        from consensus_assurance.workflow.audit_spec import load
        corrected=load(state)
        broken=corrected.model_copy(deep=True)
        next(b for b in broken.behaviors if b.id=='B5').existing_protections=[]
        Path(state.audit_spec_path).write_text(broken.model_dump_json())
    if debt:
        from consensus_assurance.core.proposals import DescriptiveIssue,SpecRefinement
        reply.descriptive_issues=[DescriptiveIssue(object_ids=['B5' if debt=='selected' else 'B6'],source_ids=reply.obligation.source_ids,reason='Restore the source-backed protections omitted from the selected behavior' if debt=='selected' else 'Recheck the unrelated decomposition against actual source')]
    validate_derivation(state,reply);accepted=accept_derivation(engine,reply,'offline-recorded')
    tasks=[t for t in engine.state.inquiry_tasks if t.kind=='spec_refine' and t.diagnostics]
    assert bool(tasks)==bool(debt)
    if debt=='selected':
        assert not accepted and not engine.state.units
        from consensus_assurance.workflow.audit_spec import load
        from consensus_assurance.workflow.inquiry import process_task
        from consensus_assurance.adapters.agents.backend import MockAgent
        spec=corrected
        engine.agent=MockAgent();engine.agent.responses=[SpecRefinement(understanding='Restore the recorded protections from the supplied handler source; preserve fact meaning',audit_spec=spec,limitations=['No implementation correctness established']).model_dump(mode='json')]
        process_task(engine,tasks[0])
        assert next(t for t in engine.state.inquiry_tasks if t.id==tasks[0].id).status=='completed'
        assert load(engine.state).version==2 and next(b for b in load(engine.state).behaviors if b.id=='B5').existing_protections
        reply.descriptive_issues=[]
        assert accept_derivation(engine,reply,'offline-rederived')
    else:assert accepted
    if debt=='unrelated':assert tasks[0].status=='pending'

    selected=select_unit(engine.state)
    assert selected.obligation_ids==['O1'] and selected.relation_ids==[] and route(selected)=='question'
    assert selected.audit_question.preferred_check=='source_review' and len(selected.audit_question.requests)==4
    def scheduled(requests,**kwargs):
        assert [(r['file'],r['start_line'],r['end_line']) for r in requests]==[(r.file,r.start_line,r.end_line) for r in reply.audit_question.requests]
        raise RuntimeError('Stop before source acquisition or backend execution')
    engine.read=scheduled
    with pytest.raises(RuntimeError,match='Stop before source'):continue_question(engine,selected)
    assert not engine.state.models and not engine.state.evidence
    assert json.dumps(json.loads(next((archive/'agent').glob('*-derive/decoded-response.json')).read_text()),sort_keys=True)==original
    from consensus_assurance.workflow.task_packet import prepare,pool_sources
    from consensus_assurance.workflow.prompts import render
    packet,_=prepare(engine,'derive',derive_context(engine))
    prompt=render('derive',pool_sources(packet),engine.inquiry)
    (tmp_path/'derive-prompt-size.txt').write_text(str(len(prompt)))
    assert len(prompt)<169984 and len(prompt)<config.budget.context_chars*.9
