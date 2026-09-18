import json
import sys
from pathlib import Path
import pytest
from pydantic import ValidationError
from consensus_assurance.core.types import *
from consensus_assurance.core.proposals import Derivation, Bundle, Feedback
from consensus_assurance.adapters.storage.files import Store
from consensus_assurance.workflow.budget import BudgetTracker, BudgetExhausted
from consensus_assurance.core.config import Budget


def test_execution_state_transitions():
    c = CheckRun(action="test", cwd="/tmp", snapshot_id="s")
    c.transition(ExecutionStatus.RUNNING); c.transition(ExecutionStatus.TIMEOUT)
    with pytest.raises(ValueError): c.transition(ExecutionStatus.COMPLETED)
    assert c.outcome == "unknown"


def test_strict_structured_result(prepared):
    _, _, _, responses = prepared
    invalid = dict(responses[1], confirmed=True)
    with pytest.raises(ValidationError): Derivation.model_validate(invalid)
    with pytest.raises(ValidationError): Bundle.model_validate({"description": "not a model"})


def test_evidence_associations_and_mock_isolation(prepared):
    _, state, _, _ = prepared
    check = CheckRun(action="test", cwd="/tmp", snapshot_id=state.snapshot.id, status=ExecutionStatus.COMPLETED, origin=Origin.MOCK)
    state.checks.append(check)
    e = Evidence(check_id=check.id, model_id=None, snapshot_id=check.snapshot_id, claim_id=None,
        origin=Origin.MOCK, level="framework_test", scope=Scope(description="Fixture"), description="Mock", assessment=Assessment.INCONCLUSIVE)
    state.add_evidence(e)
    with pytest.raises(ValueError): state.add_evidence(e.model_copy(update={"snapshot_id": "different"}))
    with pytest.raises(ValueError): state.add_evidence(e.model_copy(update={"assessment": Assessment.SUPPORTED}))
    with pytest.raises(ValueError): state.add_evidence(e.model_copy(update={"origin": Origin.EXECUTED}))
    with pytest.raises(ValueError): state.add_evidence(e.model_copy(update={"model_id": "missing"}))
    state.invalidate("Mapping changed")
    assert e.assessment == Assessment.STALE


def test_budget_has_finite_independent_limits(prepared):
    _, state, _, _ = prepared
    tracker = BudgetTracker(Budget(agent_calls=1, model_checks=0), state)
    tracker.take("agent_calls")
    with pytest.raises(BudgetExhausted): tracker.take("agent_calls")
    with pytest.raises(BudgetExhausted): tracker.take("model_checks")
    assert state.usage == {"agent_calls": 1}


def test_store_preserves_old_checkpoints(tmp_path, prepared):
    _, state, _, _ = prepared
    store = Store(tmp_path / "store")
    store.save(state, "before")
    state.gaps.append("New unresolved issue")
    store.save(state, "after")
    assert len(list((store.root / "history").glob("*.json"))) == 2
    assert store.load().gaps == state.gaps
