"""Scoped review follow-ups, handoffs and durable semantic mutations."""
import json
import shutil
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import SemanticCheck, SemanticReview
from consensus_assurance.core.proposals import ReviewReply, ClaimDraft, GraphPatch, JudgmentChange

from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.transactions import commit_graph
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import Store
from test_graph_mutations import revision_for


def engine_for(tmp_path,state):
    cfg=Config(execution_backend='python',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg),'')
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
