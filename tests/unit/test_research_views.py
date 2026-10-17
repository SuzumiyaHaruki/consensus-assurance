"""Current research views retain evidence and open questions without changing records."""
import json
import pytest
from support.evidence import saved_evidence, research_state
from consensus_assurance.workflow.research import execution_feedback, operation_summary, current_view


@pytest.mark.parametrize('large', [False, True])
def test_execution_feedback_preserves_receipts_when_events_are_omitted(tmp_path, large):
    events = [dict(event='admitted', operation='one', value=3, limit=3),
              dict(event='returned', operation='one', value=0)]
    if large:
        events.append(dict(event='extra', operation='large', value='x' * 7000))
    state, fixed, check = saved_evidence(tmp_path, events=events)
    before = state.model_dump(mode='json')
    saved = {p: p.read_bytes() for p in (tmp_path / 'logs').rglob('*') if p.is_file()}
    value = execution_feedback(state, tmp_path, fixed, check)
    raw = json.loads((tmp_path / value['observations']).read_text())
    assert value['events'] == ([] if large else raw['events'])
    assert value['event_count'] == len(raw['events'])
    assert value['events_omitted_count'] == (len(raw['events']) if large else 0)
    assert value['comparisons'][0]['result']['valid_witness_indices'] == [1]
    assert value['comparisons'][0]['definition'] == fixed.basis.comparisons[0].model_dump(mode='json')
    assert value['sources'][0]['record'] == dict(path='state.json', collection='materials', id='code')
    assert (tmp_path / value['harness']).read_text() == fixed.basis.harness.source
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
