import pytest
from consensus_assurance.core.types import Analysis, CheckRun, ExecutionStatus
from consensus_assurance.core.config import Budget
from consensus_assurance.workflow.budget import BudgetTracker, BudgetExhausted
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.storage.files import Store
from consensus_assurance.workflow.engine import FRAMEWORK_REVISION


def test_execution_transition_and_budget_limits(tmp_path):
    c=CheckRun(action='test',cwd=str(tmp_path),snapshot_id='source')
    with pytest.raises(ValueError):c.transition(ExecutionStatus.COMPLETED)
    c.transition(ExecutionStatus.RUNNING);c.transition(ExecutionStatus.COMPLETED)
    state=Analysis(mode='mock',framework_revision=FRAMEWORK_REVISION,config={},snapshot=capture(tmp_path))
    tracker=BudgetTracker(Budget(agent_calls=1,experiments=0,total_seconds=10),state)
    tracker.take('agent_calls')
    with pytest.raises(BudgetExhausted):tracker.take('agent_calls')
    with pytest.raises(BudgetExhausted):tracker.take('experiments')
    assert tracker.remaining()>0
    store=Store(tmp_path/'saved');store.save(state,'test')
    assert store.load()==state
