"""Current research views retain evidence and open questions without changing records."""
import json
import pytest
from support.evidence import saved_evidence, research_state
from consensus_assurance.workflow.research import execution_feedback, operation_summary, current_view


@pytest.mark.parametrize('shape', ['small', 'large_extra', 'many_extra', 'many_compared', 'large_compared'])
def test_execution_feedback_preserves_receipts_when_events_are_omitted(tmp_path, shape):
    from consensus_assurance.core.types import Harness, EventRequirement
    events = [dict(event='admitted', operation='one', node='n1', phase='before', value=3, limit=3),
              dict(event='returned', operation='one', node='n1', phase='after', value=0)]
    if shape == 'large_extra':
        events.append(dict(event='extra', operation='large', value='x' * 7000))
    elif shape == 'many_extra':
        events.extend(dict(event='extra', operation=str(n)) for n in range(7))
    elif shape == 'many_compared':
        for n in range(4):
            events.extend([dict(event='admitted', operation=str(n), value=3),
                           dict(event='returned', operation=str(n), value=3)])
    elif shape == 'large_compared':
        events[1]['detail'] = 'x' * 7000
    state, fixed, check = saved_evidence(tmp_path, events=events, basis_changes={'harness':Harness(
        kind='python', source='from helper import sample\n', files={'helper.py':'def sample(): return 0\n'},
        prerequisites=[EventRequirement(alias='start', event='admitted')])})
    before = state.model_dump(mode='json')
    saved = {p: p.read_bytes() for p in (tmp_path / 'logs').rglob('*') if p.is_file()}
    value = execution_feedback(state, tmp_path, fixed, check)
    raw = json.loads((tmp_path / value['observations']).read_text())
    large = shape != 'small'
    assert value['events'] == ([] if large else raw['events'])
    assert value['event_count'] == len(raw['events'])
    assert value['events_omitted_count'] == (len(raw['events']) if large else 0)
    assert value['comparisons'][0]['result']['valid_witness_indices'] == [1]
    assert value['comparisons'][0]['definition'] == fixed.basis.comparisons[0].model_dump(mode='json')
    assert value['sources'][0]['record'] == dict(path='state.json', collection='materials', id='code')
    assert (tmp_path / value['harness']).read_text() == fixed.basis.harness.source
    assert {p:(tmp_path / p).read_text() for p in value['measurement_sources']} == {
        value['harness']:fixed.basis.harness.source,
        f'fixed-experiments/{fixed.id}/helper.py':fixed.basis.harness.files['helper.py']}
    if large:
        expected = list(range(8)) if shape == 'many_compared' else [0] if shape == 'large_compared' else [0, 1]
        assert value['comparison_events'] == [dict(event_index=i, observation=raw['events'][i]) for i in expected]
        assert value['comparison_events_omitted_indices'] == (
            [8, 9] if shape == 'many_compared' else [1] if shape == 'large_compared' else [])
        assert value['comparison_events'][0]['observation']['_ca_observation']['location']['line'] == 1
    else:
        assert 'comparison_events' not in value
    assert state.model_dump(mode='json') == before
    assert all(p.read_bytes() == data for p, data in saved.items())


def test_reselection_retains_old_open_gaps_and_current_explanation(tmp_path):
    from consensus_assurance.core.types import Gap, Interpretation
    state = research_state(tmp_path)
    old = state.investigations[0]
    state.investigations += [old.model_copy(update={'id': f'question-{n}',
        'question': f'Which return condition applies to caller {n}?'}) for n in range(9)]
    pending = state.investigations[1]
    pending.gaps = [Gap(id='caller', operation_id='revisit', question='Which producer establishes the caller bound?')]
    state.interpretations = [
        Interpretation(id='prior', operation_id='start', investigation_id=old.id, source_ids=['code'],
            conclusion='unresolved', rationale='The initial caller contract still needs inspection'),
        Interpretation(id='current', operation_id='revisit', investigation_id=old.id, source_ids=['code'],
            conclusion='explained', defect_claim='refuted', rationale='The contract excludes this caller',
            counterevidence=['The input is outside the documented domain'], limitations=['Other callers remain open'])]
    state.current_submission = dict(phase='accepted', operation_id='revisit')
    before = state.model_dump(mode='json')
    answer = operation_summary(state, tmp_path)['questions'][0]['latest_interpretation']
    assert answer['defect_claim'] == 'refuted' and answer['conclusion'] == 'explained'
    assert answer['counterevidence'] == state.interpretations[-1].counterevidence
    assert answer['limitations'] == state.interpretations[-1].limitations
    assert answer['record'] == dict(path='state.json', collection='interpretations', id='current')
    index = current_view(state, tmp_path)
    questions = {q['id']: q for q in index['reselection']['questions']}
    assert set(questions) == {q.id for q in state.investigations}
    assert questions[pending.id]['open_gap_count'] == 1
    assert index['investigations'][0]['latest_interpretation'] == answer
    assert state.model_dump(mode='json') == before


@pytest.mark.parametrize('case', [
    'same', 'changed_file', 'changed_submission', 'tools', 'unknown_tools', 'diagnostic',
    'new_receipt', 'running', 'recovered', 'missing_context', 'rejected', 'repeat', 'missing_archive',
])
def test_repeat_feedback_requires_fresh_unchanged_work_and_preserves_records(tmp_path, case):
    from consensus_assurance.core.types import CheckRun, Gap, PendingAction
    from consensus_assurance.workflow.research import repeated_submission
    from support.audit import experiment
    state = research_state(tmp_path)
    state.investigations[0].gaps = [Gap(id='caller', operation_id='start', question='Which caller establishes the input?')]
    request, files = experiment('question')
    submission = dict(rationale='Retain the same source-scoped conclusion', experiment=request)
    if case == 'repeat':
        submission = dict(rationale='Check schedule stability', repeat_experiment_id='saved')
    for index, name in enumerate(('prior', 'current')):
        folder = tmp_path / 'submissions' / name
        (folder / 'inputs').mkdir(parents=True)
        # Object order and whitespace are not research changes.
        (folder / 'accepted.json').write_text(json.dumps(submission, sort_keys=bool(index), indent=index or None))
        for path, text in files.items():
            (folder / 'inputs' / path).write_text(text)
        state.checks.append(CheckRun(id=name, action='agent_turn', cwd=str(tmp_path),
            snapshot_id=state.snapshot.id, status='completed', ended_at='2026-01-01T00:00:01+00:00',
            pending_action_id=name + '-action', parameters={
                'agent_turn_completed':True, 'agent_tool_events':0,
                'agent_diagnostic':dict(message='', transport_failure=False, session_unavailable=False)}))
        state.agent_turns.append(dict(check_id=name, tool_events=0))
    state.pending_action = PendingAction(id='current-action', kind='agent_turn', status='completed')
    state.usage = dict(agent_calls=2)
    state.current_submission = dict(phase='executed', operation_id='current', no_change=True)
    previous = dict(submission=dict(phase='executed', operation_id='prior'),
        check_count=1, agent_calls=1, action_id='prior-action')
    current = tmp_path / 'submissions' / 'current'
    if case == 'changed_file':
        (current / 'inputs' / 'check.py').write_text('print("different measurement")\n')
    elif case == 'changed_submission':
        (current / 'accepted.json').write_text(json.dumps({**submission, 'rationale':'Inspect another uncertainty'}))
    elif case in {'tools', 'unknown_tools'}:
        value = 1 if case == 'tools' else None
        state.agent_turns[-1]['tool_events'] = state.checks[-1].parameters['agent_tool_events'] = value
    elif case == 'diagnostic':
        state.checks[-1].parameters['agent_diagnostic']['message'] = 'Connection recovered after a transport error'
    elif case == 'new_receipt':
        state.checks.insert(1, state.checks[0].model_copy(update={'id':'new-target', 'action':'experiment'}))
    elif case == 'running':
        state.pending_action.status = 'running'
    elif case == 'recovered':
        state.usage['agent_calls'] = previous['agent_calls']
    elif case == 'missing_context':
        previous = None
    elif case == 'rejected':
        previous['submission']['phase'] = 'rejected'
    elif case == 'missing_archive':
        (current / 'accepted.json').unlink()
    before = state.model_dump(mode='json')
    saved = {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert repeated_submission(state, tmp_path, previous) is (case == 'same')
    ordinary = operation_summary(state, tmp_path)
    feedback = operation_summary(state, tmp_path, previous)
    assert (feedback['next'] != ordinary['next']) is (case == 'same')
    assert {k:v for k,v in feedback.items() if k != 'next'} == {k:v for k,v in ordinary.items() if k != 'next'}
    assert feedback['necessary_gaps'] and feedback['allocation'] and feedback['reselection']['questions']
    assert state.model_dump(mode='json') == before
    assert {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == saved
