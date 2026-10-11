"""Actual local receipts under scripted transport, never autonomous discovery evidence."""
import json
import shutil
import pytest
from audit_support import engine_for, combined, experiment, opinion, stop
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.workflow.experiments import assessment, observed, validate_failure
from consensus_assurance.workflow.knowledge import target_receipts


def executed_case(tmp_path, tail='', review=None):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')

    def start(state):
        sub, files = combined(state)
        files['check.py'] += tail
        return sub, files

    engine, repo = engine_for(tmp_path, [start, review or opinion, stop])
    # Only transport is scripted. The target receipt and isolation are real.
    engine.agent.mock = False
    engine.config.execution_isolation = 'bwrap'
    state = engine.start(repo)
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id == fixed.id)
    return engine, fixed, check


def test_independent_incomplete_operation_preserves_completed_witness(tmp_path):
    tail = "print('CA_EVENT '+json.dumps(dict(event='admitted',operation='unfinished',value=3,limit=3)))\n"
    engine, fixed, check = executed_case(tmp_path, tail)
    result = assessment(engine.state, engine.root, fixed, check)
    assert result['confirmed'] and not result['reviewed_complete']
    assert result['comparisons'][0]['missing_indices'] == [2]
    assert result['comparisons'][0]['valid_witness_indices'] == [1]
    # An admission index cannot stand in for the actual violating result.
    engine.state.interpretations[-1].executions = {check.id: [0]}
    assert not assessment(engine.state, engine.root, fixed, check)['confirmed']
    engine.state.interpretations[-1].executions = {check.id: [1]}
    harness = engine.root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    harness.write_text(harness.read_text() + '# changed retained input\n')
    assert not assessment(engine.state, engine.root, fixed, check)['confirmed']


def test_narrow_later_failure_attribution_preserves_only_intact_witness(tmp_path):
    def review(state):
        check = next(c for c in state['checks'] if c.get('experiment_id'))
        return opinion(state, failure_attribution=dict(
            check_id=check['id'], witness_indices={0: [1]}, failure_stream='stderr',
            failure_lines=[1, 4], harness_lines=[6, 6]),
            rationale='The return was observed before the independent later fixture assertion failed')

    engine, fixed, check = executed_case(tmp_path, "assert False, 'independent later test failure'\n", review)
    result = assessment(engine.state, engine.root, fixed, check)
    assert check.exit_code == 1 and check.outcome == 'tests_failed'
    assert result['confirmed'], result['blockers']
    assert not result['reviewed_complete']
    attribution = engine.state.interpretations[-1].failure_attribution
    measurement = observed(fixed, check, engine.root)
    for update in (
        {'status': ExecutionStatus.TIMEOUT}, {'status': ExecutionStatus.CANCELLED},
        {'parameters': {**check.parameters, 'failure_class': 'build_or_setup'}},
        {'parameters': {**check.parameters, 'changed_target_files': ['target.py']}},
        {'snapshot_id': 'other'},
    ):
        altered = check.model_copy(update=update)
        state = engine.state.model_copy(deep=True)
        state.checks[state.checks.index(check)] = altered
        with pytest.raises(ValueError):
            validate_failure(state, engine.root, fixed, altered, measurement, attribution)
    for update in ({'witness_indices': {0: [0]}}, {'failure_lines': [500, 501]}, {'check_id': 'other'}):
        with pytest.raises(ValueError):
            validate_failure(engine.state, engine.root, fixed, check, measurement, {**attribution, **update})
    harness = engine.root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    harness.write_text(harness.read_text() + '# altered after execution\n')
    assert not assessment(engine.state, engine.root, fixed, check)['confirmed']


def test_same_operation_ambiguity_cannot_be_selected_away(tmp_path):
    tail = "print('CA_EVENT '+json.dumps(dict(event='returned',operation='one',value=3)))\n"
    engine, fixed, check = executed_case(tmp_path, tail + "assert False, 'later assertion'\n",
        lambda state: opinion(state, conclusion='unresolved'))
    measurement = observed(fixed, check, engine.root)
    with pytest.raises(ValueError, match='Competing same-operation'):
        validate_failure(engine.state, engine.root, fixed, check, measurement, dict(
            check_id=check.id, witness_indices={0: [1]}, failure_stream='stderr',
            failure_lines=[1, 4], harness_lines=[7, 7]))
    assert engine.state.interpretations[-1].conclusion == 'unresolved'
    assert not assessment(engine.state, engine.root, fixed, check)['confirmed']


def test_separate_receipt_requires_association_and_successor_cannot_borrow_it(tmp_path):
    def second(state):
        owner = state['investigations'][0]['id']
        request, files = experiment(owner)
        request['previous_id'] = state['experiments'][0]['id']
        request['revision_reason'] = 'Change the stated responsibility and execute it'
        request['requirement'] = 'The return stays within the legal interval'
        return {'rationale': 'A changed fixed basis', 'experiment': request}, files

    def wrong_receipt(state):
        old = next(c for c in state['checks'] if c.get('experiment_id') == state['experiments'][0]['id'])
        return opinion(state, executions={old['id']: [1]}, joint_history='Same legal input in a separate execution')

    def associate(state):
        assert state['current_submission']['phase'] == 'rejected'
        old = next(c for c in state['checks'] if c.get('experiment_id') == state['experiments'][0]['id'])
        new = next(c for c in state['checks'] if c.get('experiment_id') == state['experiments'][1]['id'])
        return opinion(state, executions={old['id']: [1], new['id']: [1]}, conclusion='conditional',
            joint_history='Both receipts use the same captured pure function and legal input; no shared mutable history is claimed')

    engine, repo = engine_for(tmp_path, [combined, second, wrong_receipt, associate, stop])
    state = engine.start(repo)
    assert len(state.interpretations) == 1
    old_check = next(c for c in state.checks if c.experiment_id == state.experiments[0].id)
    with pytest.raises(ValueError, match='joint-history'):
        target_receipts(state, engine.root, {old_check.id: [1]}, experiment_id=state.experiments[1].id)
    assert len(state.interpretations[0].executions) == 2
    assert state.experiments[0].id != state.experiments[1].id


def test_unchanged_experiment_and_exhausted_execution_budget_allow_reselection(tmp_path):
    def duplicate(state):
        request, files = experiment(state['investigations'][0]['id'])
        return {'rationale': 'Identical effective request', 'experiment': request}, files

    def changed(state):
        assert state['current_submission']['no_change']
        sub, files = duplicate(state)
        sub['experiment']['prefix'] += ' A changed assumption.'
        return sub, files

    def source_answer(state):
        assert state['current_submission']['phase'] == 'rejected'
        return {'rationale': 'Continue with available source investigation', 'interpretations': [dict(
            investigation_id=state['investigations'][0]['id'], source_ids=['code'], conclusion='explained',
            rationale='The captured boundary expression returns zero at capacity')]}, {}

    engine, repo = engine_for(tmp_path, [combined, duplicate, changed, source_answer, stop])
    engine.config.budget.experiments = 1
    state = engine.start(repo)
    assert state.usage == {'agent_calls': 5, 'experiments': 1}
    assert len(state.experiments) == len(state.interpretations) == 1
    assert len(list((engine.root / 'submissions').glob('*/raw.json'))) == 4


@pytest.mark.parametrize('raw_receipt', [False, True])
def test_completed_action_recovery_never_reexecutes_target(tmp_path, raw_receipt):
    engine, repo = engine_for(tmp_path, [combined, opinion, stop])
    original = engine.checkpoint
    interrupted = False

    def checkpoint(event):
        nonlocal interrupted
        original(event)
        if not raw_receipt and event == 'action_result_saved' and engine.state.pending_action.kind == 'experiment_execute' and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Execution result durable, acceptance still pending')

    engine.checkpoint = checkpoint
    run = engine.runner.run

    def interrupted_run(*args, **kwargs):
        nonlocal interrupted
        receipt = run(*args, **kwargs)
        if raw_receipt and receipt.action == 'experiment' and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Raw process receipt durable, action result missing')
        return receipt

    engine.runner.run = interrupted_run
    with pytest.raises(KeyboardInterrupt):
        engine.start(repo)
    assert engine.state.current_submission['phase'] == 'accepted'
    result_path = engine.root / 'actions' / engine.state.pending_action.id / 'result.json'
    if raw_receipt:
        assert not result_path.exists()
        receipt_id = next(json.loads(p.read_text())['id'] for p in (engine.root / 'logs').glob('*/check.json')
                          if json.loads(p.read_text())['action'] == 'experiment')
    else:
        receipt_id = json.loads(result_path.read_text())['id']
    engine.checkpoint = original
    state = engine.resume()
    assert state.usage['experiments'] == 1
    assert [c.id for c in state.checks if c.action == 'experiment'] == [receipt_id]
    assert len(state.interpretations) == 1
