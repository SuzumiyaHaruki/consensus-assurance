"""Scoped review follow-ups, handoffs and durable semantic mutations."""
import json
import shutil
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import JudgmentChange

from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.transactions import commit_graph
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import Store
from test_graph_mutations import revision_for


def engine_for(tmp_path,state):
    cfg=Config(execution_backend='python',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg))
    engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(state.snapshot.repo,engine.root/'source')
    return engine


def test_grounding_only_F2_changes_scope_without_rewriting_claim(prepared):
    _,state,_,_=prepared;claim=state.claims[1];description=claim.description
    feedback=revision_for(state,[claim.id]);draft=feedback.patch.claims[0]
    draft.description=description;old=claim.grounding.model_dump(mode='json')
    draft.grounding.applicability+='; selected serial configuration only'
    feedback.grounding=draft.grounding.model_copy(update={"unresolved":[],"conflicts":[]})
    feedback.changes=[JudgmentChange(target_id=claim.id,field='grounding',old_value_json=json.dumps(old),new_value_json=json.dumps(draft.grounding.model_dump(mode='json')))]
    apply_feedback(state,state.units[0],None,feedback)
    current=next(c for c in state.claims if c.id==claim.id)
    assert current.version==2 and current.description==description
    assert 'serial configuration' in current.grounding.applicability


@pytest.mark.parametrize('interrupt',[False,True])
def test_semantic_transaction_failure_and_recovery_are_atomic(tmp_path,prepared,interrupt):
    _,state,_,_=prepared;engine=engine_for(tmp_path,state);engine.checkpoint('initial')
    before=state.model_dump(mode='json')
    def invalid(proxy):
        proxy.state.claims[1].description='must never escape failed validation'
        raise ValueError('Injected validation failure')
    with pytest.raises(ValueError):commit_graph(engine,'invalid',{'operation':'bad'},invalid)
    assert state.model_dump(mode='json')==before
    def change(proxy):
        proxy.state.claims[1].version+=1
        proxy.state.native_current={'phase':'accepted','operation_id':'change'}
    if interrupt:
        def crash(key):raise RuntimeError('Interrupted between manifest and state')
        engine.graph_commit_hook=crash
        with pytest.raises(RuntimeError):commit_graph(engine,'change',{'operation':'one'},change)
        assert state.claims[1].version==1
        engine.state=Store(engine.root).load();engine.budget=BudgetTracker(engine.config.budget,engine.state)
        engine.graph_commit_hook=lambda key:None
    commit_graph(engine,'change',{'operation':'one'},change)
    commit_graph(engine,'change',{'operation':'one'},change)
    assert engine.state.claims[1].version==2 and engine.state.native_current['operation_id']=='change'
    assert 'change' in Store(engine.root).load().applied_operations


from consensus_assurance.core.proposals import ConditionDisposition
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.repair_policy import classify_conditions, condition_records


@pytest.mark.parametrize('shape,code',[('missing','condition_missing'),('extra','condition_extra'),('duplicate','condition_duplicate')])
def test_condition_reference_diagnostics_are_specific_and_do_not_erase_judgment(prepared,shape,code):
    _,state,_,_=prepared;id=state.materials[0].id
    records=condition_records(['Storage durability has not been inspected'],'issue-version-1',[id],'o',1)
    item=ConditionDisposition(condition_id=records[0]['id'],applies_to='independent_scope',rationale='This caller-location question does not establish storage behavior',source_ids=[id])
    dispositions=[] if shape=='missing' else [item,item] if shape=='duplicate' else [item,item.model_copy(update={'condition_id':'wrong'})]
    before=state.model_dump()
    with pytest.raises(DiagnosticError) as caught:
        classify_conditions(state,[r['text'] for r in records],dispositions,[id],records=records,object_ids=['o'])
    d=caught.value.diagnostics[0]
    assert d.code==code and d.details[shape] and d.allowed==['representation']
    assert state.model_dump()==before
    assert classify_conditions(state,[r['text'] for r in records],[item],[id],records=records)==[item]





@pytest.mark.parametrize('applies_to',['old_judgment','current_judgment','independent_scope'])
def test_F2_attributes_exact_conflict_without_erasing_it(prepared,applies_to):
    _,s,_,_=prepared;id=s.claims[1].id;f=revision_for(s,[id]);f.grounding.conflicts=['The previous statement also constrained object replacement']
    f.condition_dispositions=[ConditionDisposition(condition=f.grounding.conflicts[0],applies_to=applies_to,source_ids=f.evidence_ids,rationale='The source distinguishes update within one object from replacement; this is attributed to the stated judgment, not a claim about all histories')]
    apply_feedback(s,s.units[0],None,f)
    assert s.revisions[-1].status==('unresolved' if applies_to=='current_judgment' else 'applied')
    assert s.revisions[-1].after['grounding']['conflicts']==f.grounding.conflicts
    assert s.claims[1].version==(1 if applies_to=='current_judgment' else 2)



def test_F2_cannot_rename_unaddressed_condition(prepared):
    _,s,_,_=prepared;f=revision_for(s,[s.claims[1].id]);f.grounding.unresolved=['Actual input truth unverified']
    f.condition_dispositions=[ConditionDisposition(condition='Different harmless text',applies_to='old_judgment',source_ids=f.evidence_ids,rationale='Not the actual original question')]
    before=s.model_dump()
    with pytest.raises(ValueError):apply_feedback(s,s.units[0],None,f)
    assert s.model_dump()==before
