"""Actual local receipts under scripted transport, never autonomous discovery evidence."""
import json
import shutil
import pytest
from support.audit import engine_for, combined, experiment, opinion, stop
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.workflow.experiments import assessment, observed, validate_failure
from consensus_assurance.workflow.knowledge import target_receipts


def isolated_engine(tmp_path, steps):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')
    engine, repo = engine_for(tmp_path, steps)
    # Only transport is scripted. The target receipt and isolation are real.
    engine.agent.mock = False
    engine.config.execution_isolation = 'bwrap'
    return engine, repo


def retained_files(root, *folders):
    return {p: p.read_bytes() for folder in folders
            for p in (root / folder).rglob('*') if p.is_file()}


def execution_submission(state, tail='', *, second_operation=False):
    sub, files = combined(state)
    if second_operation:
        comparison = sub['experiment']['comparisons'][0]
        sub['experiment']['comparisons'] = [
            {**comparison, 'applicability_conditions': [dict(field='operation', value=operation)]}
            for operation in ('one', 'two')]
        files['check.py'] += "print('CA_EVENT '+json.dumps(dict(event='admitted',operation='two',value=3,limit=3)))\n"
        files['check.py'] += "print('CA_EVENT '+json.dumps(dict(event='returned',operation='two',value=step(3,3))))\n"
    files['check.py'] += tail
    return sub, files


@pytest.mark.parametrize('collection', ['knowledge', 'interpretations'])
@pytest.mark.parametrize('fault,code', [('receipt', 'execution_reference'), ('indices', 'event_indices')])
def test_rejected_citations_repair_atomically_without_reexecution(tmp_path, collection, fault, code):
    from copy import deepcopy
    retained = {}

    def reject(state):
        sub, _ = opinion(state)
        check_id = next(iter(sub['interpretations'][0]['executions']))
        sub['knowledge'] = [dict(kind='fact', statement='The selected call returned zero.',
            conditions='The recorded admitted operation', source_ids=['code'], executions={check_id: [1]})]
        # A valid first item must not be committed when a later reference is invalid.
        sub[collection].append(deepcopy(sub[collection][0]))
        retained['repair'] = deepcopy(sub)
        sub[collection][-1]['executions'] = {check_id[:-1]: [1]} if fault == 'receipt' else {check_id: [-1, 1, 1, 2]}
        retained['receipt'] = check_id
        retained['evidence'] = retained_files(engine.root, 'fixed-experiments', f'logs/{check_id}')
        return sub, {}

    def repair(state):
        diagnostic, = state['current_submission']['rejected']['diagnostics']
        assert diagnostic['code'] == code and diagnostic['category'] == 'association'
        assert diagnostic['paths'] == [f"/{collection}/1/executions/{retained['receipt'][:-1] if fault == 'receipt' else retained['receipt']}"]
        assert not state['knowledge'] and not state['interpretations']
        return retained['repair'], {}

    engine, repo = engine_for(tmp_path, [combined, reject, repair, stop])
    state = engine.start(repo)
    assert state.knowledge[0].executions == state.interpretations[-1].executions == {retained['receipt']: [1]}
    assert state.usage['experiments'] == 1
    assert all(p.read_bytes() == data for p, data in retained['evidence'].items())


def executed_case(tmp_path, tail='', review=None, *, second_operation=False):
    def start(state):
        return execution_submission(state, tail, second_operation=second_operation)

    engine, repo = isolated_engine(tmp_path, [start, review or opinion, stop])
    state = engine.start(repo)
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id == fixed.id)
    return engine, fixed, check


def test_independent_incomplete_operation_preserves_completed_witness(tmp_path):
    tail = "print('CA_EVENT '+json.dumps(dict(event='admitted',operation='unfinished',value=3,limit=3)))\n"
    engine, fixed, check = executed_case(tmp_path, tail)
    result = assessment(engine.state, engine.root, fixed, check)
    assert not result['blockers'] and result['outcome'] == 'violated'
    assert not result['comparisons'][0]['comparison_complete']
    assert result['comparisons'][0]['missing_indices'] == [2]
    assert result['comparisons'][0]['valid_witness_indices'] == [1]
    # An admission index cannot stand in for the actual violating result.
    engine.state.interpretations[-1].executions = {check.id: [0]}
    from consensus_assurance.workflow.research import current_view
    limitations = current_view(engine.state, engine.root)['experiments'][0]['results'][0]['blockers']
    assert any('Comparison 0:' in value and 'does not cite' in value for value in limitations)
    engine.state.interpretations[-1].executions = {check.id: [1]}
    harness = engine.root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    harness.write_text(harness.read_text() + '# changed retained input\n')
    assert 'Retained experiment bytes differ' in str(assessment(engine.state, engine.root, fixed, check)['blockers'])


def test_narrow_later_failure_attribution_preserves_only_intact_witness(tmp_path):
    def review(state):
        check = next(c for c in state['checks'] if c.get('experiment_id'))
        return opinion(state, failure_attribution=dict(
            check_id=check['id'], witness_indices={0: [1]}, failure_stream='stderr',
            failure_lines=[1, 4], harness_lines=[8, 8]),
            rationale='The return was observed before the independent later fixture assertion failed')

    engine, fixed, check = executed_case(tmp_path, "assert False, 'independent later test failure'\n", review,
        second_operation=True)
    result = assessment(engine.state, engine.root, fixed, check)
    assert check.exit_code == 1 and check.outcome == 'tests_failed'
    assert [r['valid_witness_indices'] for r in result['comparisons']] == [[1], [3]]
    assert result['blockers'] and all(v.startswith('Comparison 1:') for v in result['blockers'])
    assert any('no valid independent-failure attribution' in v for v in result['blockers'])
    from consensus_assurance.workflow.research import current_view
    assert current_view(engine.state, engine.root)['experiments'][0]['results'][0]['blockers'] == result['blockers']
    from consensus_assurance.reporting.report import render_report
    report = render_report(engine.state, engine.root).read_text()
    assert 'Submitted model independent-failure attribution' in report and result['blockers'][0] in report
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
        with pytest.raises(ValueError):
            target_receipts(state, engine.root, {check.id: [0, 1]}, reuse_failure=True)
    for update in ({'witness_indices': {0: [0]}}, {'failure_lines': [500, 501]}, {'check_id': 'other'}):
        with pytest.raises(ValueError):
            validate_failure(engine.state, engine.root, fixed, check, measurement, {**attribution, **update})
    harness = engine.root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    harness.write_text(harness.read_text() + '# altered after execution\n')
    assert 'Retained experiment bytes differ' in str(assessment(engine.state, engine.root, fixed, check)['blockers'])


def test_failed_receipt_knowledge_reuses_current_attribution_atomically(tmp_path):
    from consensus_assurance.workflow.audit import validate_submission
    retained = {}
    def start(state):
        return execution_submission(state, "assert False, 'independent fixture failure'\n", second_operation=True)
    def product(state, indices=(0, 1), *, attribution=True):
        check = next(c for c in state['checks'] if c.get('experiment_id'))
        sub, files = opinion(state, failure_attribution=dict(check_id=check['id'], witness_indices={0:[1]},
            failure_stream='stderr', failure_lines=[1, 4], harness_lines=[8, 8]))
        if not attribution:
            sub.pop('interpretations')
        sub['knowledge'] = [dict(ref='@observed', kind='fact', statement='Operation one returned zero for its admitted input.',
            conditions='The intact first operation, independent of the fixture failure',
            source_ids=['code'], executions={check['id']:list(indices)})]
        if attribution:
            sub['interpretations'][0]['knowledge'] = [dict(entry_id='@observed', revision=1)]
        return sub, files
    def preflight(sub):
        path = engine.root/'draft'/'check-submission.json'
        path.write_text(json.dumps(sub))
        before = engine.state.model_dump(mode='json')
        result = validate_submission(engine.state, engine.root, path.name, engine.implementation)
        assert engine.state.model_dump(mode='json') == before
        return result
    def reject(state):
        check = next(c for c in state['checks'] if c.get('experiment_id'))
        retained['files'] = retained_files(engine.root, 'fixed-experiments', 'logs/' + check['id'])
        sub, _ = product(state, attribution=False)
        diagnostic, = preflight(sub)['diagnostics']
        assert diagnostic['paths'] == [f"/knowledge/0/executions/{check['id']}"]
        assert 'current Interpretation' in diagnostic['message'] and 'same update' in diagnostic['message']
        sub, _ = product(state)
        sub['interpretations'][0]['failure_attribution']['witness_indices'] = {0:[0]}
        diagnostic, = preflight(sub)['diagnostics']
        assert diagnostic['paths'] == [f"/interpretations/0/executions/{check['id']}"]
        assert 'no complete violating witness' in diagnostic['message']
        sub, files = product(state, indices=(0, 1, 3))
        diagnostic, = preflight(sub)['diagnostics']
        assert diagnostic['paths'] == [f"/knowledge/0/executions/{check['id']}"]
        assert 'allowed event indices: [0, 1]' in diagnostic['message']
        return sub, files
    def accept(state):
        assert state['current_submission']['phase'] == 'rejected'
        assert not state['knowledge'] and not state['interpretations']
        sub, files = product(state)
        assert preflight(sub)['valid']
        return sub, files
    def supersede(state):
        assert len(state['knowledge']) == len(state['interpretations']) == 1
        assert state['interpretations'][0]['knowledge'][0]['entry_id'] == state['knowledge'][0]['id']
        return opinion(state, conclusion='unresolved', rationale='Reconsider whether the fixture failure is independent')
    def reject_historical(state):
        sub, files = product(state, attribution=False)
        sub['knowledge'][0]['statement'] += ' A proposed later reuse.'
        assert not preflight(sub)['valid']
        return sub, files
    engine, repo = isolated_engine(tmp_path, [start, reject, accept, supersede, reject_historical, stop])
    state = engine.start(repo)
    assert state.usage['experiments'] == 1 and len(state.knowledge) == 1 and len(state.interpretations) == 2
    assert state.knowledge[0].revision == 1 and state.interpretations[-1].conclusion == 'unresolved'
    assert all(p.read_bytes() == data for p, data in retained['files'].items())


@pytest.mark.parametrize('failure',[False,True])
def test_same_operation_ambiguity_cannot_be_selected_away(tmp_path,failure):
    tail = "print('CA_EVENT '+json.dumps(dict(event='returned',operation='one',value=3)))\n"
    engine, fixed, check = executed_case(tmp_path, tail + ("assert False, 'later assertion'\n" if failure else ''),
        lambda state: opinion(state, conclusion='unresolved' if failure else 'violated'))
    measurement = observed(fixed, check, engine.root)
    assert measurement['comparisons'][0]['outcome']=='unknown'
    assert 'Contradictory same-operation' in str(measurement['comparisons'][0]['diagnostics'])
    if failure:
        with pytest.raises(ValueError, match='no complete violating witness'):
            validate_failure(engine.state, engine.root, fixed, check, measurement, dict(
                check_id=check.id, witness_indices={0: [1]}, failure_stream='stderr',
                failure_lines=[1, 4], harness_lines=[7, 7]))
    assert assessment(engine.state, engine.root, fixed, check)['comparisons'][0]['valid_witness_indices'] == []


def test_exploratory_receipt_supports_correction_without_rerun(tmp_path):
    saved = {}
    def start(state):
        sub, files = combined(state)
        sub['experiment'].pop('requirement')
        return sub, files
    def allegation(state):
        return opinion(state, defect_claim='asserted')
    def correction(state):
        saved['files'] = retained_files(engine.root, 'fixed-experiments', 'logs')
        saved['interpretations'] = list(state['interpretations'])
        return opinion(state, experiment_id=None, conclusion='explained', defect_claim='refuted',
            rationale='The necessary legal-call premise is false',
            counterevidence=['The caller contract excludes this input'])
    engine, repo = engine_for(tmp_path, [start, allegation, correction, stop])
    state = engine.start(repo)
    check, = [c for c in state.checks if c.experiment_id]
    assert state.usage['experiments'] == len(state.experiments) == 1
    assert all(path.read_bytes() == raw for path, raw in saved['files'].items())
    result = assessment(state, engine.root, state.experiments[0], check)
    assert result['outcome'] == 'violated'
    assert 'Exploratory basis has no fixed requirement' in str(result['blockers'])
    assert [item.defect_claim for item in state.interpretations] == ['asserted', 'refuted']
    assert [item.model_dump(mode='json') for item in state.interpretations[:-1]] == saved['interpretations']
    assert all(item.executions == {check.id: [1]} for item in state.interpretations)
    assert result['interpretation_citations']['current'][0]['id'] == state.interpretations[-1].id


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
    from consensus_assurance.workflow.research import current_view
    old, revised = current_view(state, engine.root)['experiments']
    assert old['version'] == 1 and old['previous_id'] is None
    assert revised['version'] == 2 and revised['previous_id'] == old['experiment_id']
    assert revised['revision_reason'] == 'Change the stated responsibility and execute it'
    saved = json.loads((engine.root / revised['basis']).read_text())
    assert revised['difference_fields'] == list(saved['difference']) == ['requirement']
    assert (engine.root / revised['harness']).read_text() == saved['basis']['harness']['source']


def test_unchanged_experiment_and_exhausted_execution_budget_allow_reselection(tmp_path):
    def duplicate(state):
        request, files = experiment(state['investigations'][0]['id'])
        return {'rationale': 'Identical effective request', 'experiment': request}, files

    def changed(state):
        assert state['current_submission']['no_change']
        from consensus_assurance.workflow.research import operation_summary, current_view
        summary=operation_summary(engine.state,engine.root)
        assert not summary['questions']
        assert 'experiment_id' not in summary and 'repeat_experiment_id' in summary['next']
        assert 'uncited_executions' not in summary
        result=current_view(engine.state,engine.root)['experiments'][0]['results'][0]
        assert result['experiment_id']==state['experiments'][0]['id']
        assert not result['interpretation_citations']['current']
        sub, files = duplicate(state)
        # The identical JSON now references changed executable bytes, so it needs capacity.
        files['check.py'] += "print('changed measurement input')\n"
        return sub, files

    def source_answer(state):
        assert state['current_submission']['phase'] == 'rejected'
        return {'rationale': 'Continue with available source investigation', 'interpretations': [dict(
            investigation_id=state['investigations'][0]['id'], source_ids=['code'], conclusion='explained',defect_claim=None,
            rationale='The captured boundary expression returns zero at capacity')]}, {}

    engine, repo = engine_for(tmp_path, [combined, duplicate, changed, source_answer, stop])
    engine.config.budget.experiments = 1
    state = engine.start(repo)
    assert state.usage == {'agent_calls': 5, 'experiments': 1}
    assert len(state.experiments) == len(state.interpretations) == 1
    assert len(list((engine.root / 'submissions').glob('*/raw.json'))) == 4


def repeat_existing(state):
    return {'rationale':'Check whether the same fixed input reproduces in another clean execution',
            'repeat_experiment_id':state['experiments'][0]['id']}, {}


def test_explicit_repeats_preserve_fixed_inputs_and_separate_receipts(tmp_path):
    saved = {}
    source = experiment()[1]['check.py'] + """from pathlib import Path
marker = Path('execution-marker')
assert not marker.exists(), 'execution workspace was reused'
marker.write_text('observed one invocation')
"""
    def start(state):
        sub, files = combined(state)
        files['check.py'] = source
        return sub, files
    def repeat(state):
        saved['fixed'] = state['experiments'][0]
        saved['files'] = retained_files(engine.root, 'fixed-experiments', 'logs')
        sub, _ = repeat_existing(state)
        return sub, {'check.py': "raise AssertionError('Repeat must not read the current draft')\n"}
    engine, repo = engine_for(tmp_path, [start, opinion, repeat, opinion, repeat, opinion, stop])
    state = engine.start(repo)
    checks = [c for c in state.checks if c.experiment_id]
    assert state.usage['experiments'] == 3 and len(state.experiments) == 1
    assert state.experiments[0].model_dump(mode='json') == saved['fixed']
    assert len(checks) == len({c.id for c in checks}) == len({c.cwd for c in checks}) == 3
    assert all(c.status == ExecutionStatus.COMPLETED and c.exit_code == 0 for c in checks)
    assert all(path.read_bytes() == raw for path, raw in saved['files'].items())
    results = [assessment(state, engine.root, state.experiments[0], c) for c in checks]
    assert [r['interpretation_id'] for r in results] == [i.id for i in state.interpretations]
    assert all(r['outcome'] == 'violated' for r in results)


@pytest.mark.parametrize('case',['unknown','experiment','stop','unauthorized','capacity'])
def test_repeat_rejection_preserves_existing_evidence(tmp_path,case):
    def invalid(state):
        sub,files=repeat_existing(state)
        sub['knowledge']=[dict(kind='fact',statement='This rejected addition must not persist',
            conditions='Rejected operation',source_ids=['code'])]
        if case=='unknown':sub['repeat_experiment_id']='missing-experiment'
        if case=='experiment':sub['experiment'],files=experiment(state['investigations'][0]['id'])
        if case=='stop':sub['stop']=dict(reason='bounded_completed',rationale='Cannot finish with a requested execution')
        if case=='unauthorized':engine.config.allow_experiments=False
        return sub,files
    def finish(state):
        assert state['current_submission']['phase']=='rejected'
        assert not state['knowledge'] and len(state['experiments'])==1
        assert len([c for c in state['checks'] if c.get('experiment_id')])==1
        engine.config.allow_experiments=True
        return stop(state)
    engine,repo=engine_for(tmp_path,[combined,invalid,finish])
    if case=='capacity':engine.config.budget.experiments=1
    state=engine.start(repo)
    assert state.usage['experiments']==1


@pytest.mark.parametrize('boundary,repeat,expired', [
    ('raw_receipt', False, False), ('action_result', True, False), ('observations', True, True),
])
def test_completed_action_recovery_never_reexecutes_target(tmp_path, monkeypatch, boundary, repeat, expired):
    steps=[combined,*([repeat_existing] if repeat else []),opinion,stop]
    engine, repo = engine_for(tmp_path, steps)
    expected=2 if repeat else 1
    engine.config.budget.experiments=expected
    original = engine.checkpoint
    interrupted = False

    def checkpoint(event):
        nonlocal interrupted
        original(event)
        if (boundary == 'action_result' and event == 'action_result_saved' and
                engine.state.pending_action.kind == 'experiment_execute' and
                engine.state.usage['experiments']==expected and not interrupted):
            interrupted = True
            raise KeyboardInterrupt('Execution result durable, acceptance still pending')

    engine.checkpoint = checkpoint
    run = engine.runner.run

    def interrupted_run(*args, **kwargs):
        nonlocal interrupted
        receipt = run(*args, **kwargs)
        if boundary == 'raw_receipt' and receipt.action == 'experiment' and engine.state.usage['experiments']==expected and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Raw process receipt durable, action result missing')
        return receipt

    engine.runner.run = interrupted_run
    record = engine.record
    def interrupted_record(check):
        nonlocal interrupted
        if (boundary == 'observations' and check.action == 'experiment' and
                engine.state.usage['experiments'] == expected and not interrupted):
            assert (engine.root/'logs'/check.id/'observations.json').is_file()
            interrupted = True
            raise KeyboardInterrupt('Measurement saved before the first execution checkpoint')
        record(check)
    engine.record = interrupted_record
    with pytest.raises(KeyboardInterrupt):
        engine.start(repo)
    assert engine.state.current_submission['phase'] == 'accepted'
    action_id=engine.state.pending_action.id
    result_path = engine.root / 'actions' / action_id / 'result.json'
    if boundary == 'raw_receipt':
        assert not result_path.exists()
        receipt_id = next(value['id'] for p in (engine.root / 'logs').glob('*/check.json')
                          if (value:=json.loads(p.read_text())).get('pending_action_id')==action_id and value['action']=='experiment')
    else:
        receipt_id = json.loads(result_path.read_text())['id']
    old_ids=[c.id for c in engine.state.checks if c.experiment_id]
    old_receipts={id:(engine.root/'logs'/id/'check.json').read_bytes() for id in old_ids}
    assert len(old_ids)==int(repeat) and receipt_id not in old_ids
    engine.checkpoint = original
    if boundary == 'observations':
        monkeypatch.setattr('consensus_assurance.workflow.experiments.extract_events',
                            lambda check: pytest.fail('Recovery must reuse the saved measurement'))
    if expired:
        engine.state.elapsed_seconds=engine.config.budget.total_seconds
        engine.store.save(engine.state,'test_deadline_elapsed')
    state = engine.resume()
    assert state.usage['experiments'] == expected
    assert [c.id for c in state.checks if c.action == 'experiment'] == [*old_ids,receipt_id]
    assert all((engine.root/'logs'/id/'check.json').read_bytes()==raw for id,raw in old_receipts.items())
    assert (engine.root/'logs'/receipt_id/'observations.json').is_file()
    assert len(state.experiments)==1 and len(state.interpretations)==(0 if expired else 1)
    if expired:assert state.current_submission['phase']=='executed'


def test_repeat_interrupted_before_target_start_resumes_reserved_action(tmp_path):
    engine,repo=engine_for(tmp_path,[combined,repeat_existing,opinion,stop])
    engine.config.budget.experiments=3
    original=engine.checkpoint
    interrupted=False
    def checkpoint(event):
        nonlocal interrupted
        original(event)
        if (event=='action_started' and engine.state.pending_action.kind=='experiment_execute' and
                engine.state.usage['experiments']==2 and not interrupted):
            interrupted=True
            raise KeyboardInterrupt('Repeat reserved but no process receipt exists')
    engine.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):engine.start(repo)
    lost_id=engine.state.pending_action.id
    engine.checkpoint=original
    state=engine.resume()
    checks=[c for c in state.checks if c.experiment_id]
    assert state.usage['experiments']==2 and len(checks)==2
    assert checks[-1].pending_action_id==lost_id and checks[-1].cwd!=checks[0].cwd
    assert not any(a.id==lost_id and a.status=='outcome_unknown' for a in state.action_history)
