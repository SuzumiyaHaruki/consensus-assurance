"""Report and observation-cache projections over synthetic saved evidence."""
import json
import pytest
from support.evidence import saved_evidence, append_interpretation
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.core.types import ExecutionStatus, Gap
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.reporting.report import render_report


@pytest.mark.parametrize('change', ['missing_cache', 'invalid_json', 'invalid_shape', 'invalid_comparison', 'method',
    'fixed_version', 'raw_replaced', 'raw_missing', 'unfinished', 'timeout', 'cache_symlink', 'raw_symlink'])
def test_measurement_fallback_never_writes_or_reuses_stale_observations(tmp_path, monkeypatch, change):
    import os
    from consensus_assurance.workflow import experiments
    state, fixed, check = saved_evidence(tmp_path)
    raw = tmp_path/'logs'/check.id/'stdout.log'
    cache = raw.with_name('observations.json')
    if change == 'missing_cache':
        cache.unlink()
    elif change == 'invalid_json':
        cache.write_text('{')
    elif change in {'invalid_shape', 'invalid_comparison', 'method'}:
        value = json.loads(cache.read_text())
        if change == 'invalid_shape':
            value['events'] = None
        elif change == 'invalid_comparison':
            value['comparisons'] = [{}]
        else:
            value['_inputs']['method'] = 'different-parser'
        cache.write_text(json.dumps(value))
    elif change == 'fixed_version':
        fixed = fixed.model_copy(update={'version':fixed.version + 1})
    elif change == 'raw_replaced':
        original = raw.stat()
        replacement = raw.with_name('replacement')
        replacement.write_text(raw.read_text().replace('"value": 0', '"value": 9'))
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(raw)
        assert raw.stat().st_size == original.st_size and raw.stat().st_mtime_ns == original.st_mtime_ns
    elif change == 'raw_missing':
        raw.unlink()
    elif change == 'unfinished':
        check = check.model_copy(update={'ended_at':None, 'status':ExecutionStatus.RUNNING})
    elif change == 'timeout':
        check = check.model_copy(update={'status':ExecutionStatus.TIMEOUT})
    else:
        path = cache if change == 'cache_symlink' else raw
        retained = path.with_name('retained')
        path.rename(retained)
        path.symlink_to(retained)
    before = {p:p.read_bytes() for p in (tmp_path/'logs').rglob('*') if p.is_file()}
    extract, calls = experiments.extract_events, []
    def counted(check):
        calls.append(check.id)
        return extract(check)
    monkeypatch.setattr(experiments, 'extract_events', counted)
    if change == 'raw_symlink':
        with pytest.raises(ValueError, match='symlink'):
            experiments.observed(fixed, check, tmp_path)
        assert not calls
    else:
        measured = experiments.observed(fixed, check, tmp_path)
        assert calls == [check.id]
        if change == 'raw_missing':
            assert not measured['events'] and measured['comparisons'][0]['outcome'] == 'unknown'
        else:
            assert measured['events'][1]['value'] == (9 if change == 'raw_replaced' else 0)
        if change == 'timeout':
            assert 'Execution did not complete: timeout' in assessment(state, tmp_path, fixed, check)['blockers']
    assert {p:p.read_bytes() for p in (tmp_path/'logs').rglob('*') if p.is_file()} == before



@pytest.mark.parametrize('case,outcome,conclusion,claim', [
    ('explore', 'unknown', 'violated', 'asserted'),
    ('mismatch', 'holds', 'violated', 'asserted'),
    ('duty', 'violated', 'violated', None),
    ('missing', 'unknown', 'conditional', 'unresolved'),
    ('gap', 'violated', 'violated', 'unresolved'),
])
def test_report_separates_comparisons_claims_and_observation_gaps(tmp_path, case, outcome, conclusion, claim):
    events = [dict(event='admitted', operation='one', value=3, limit=3),
              dict(event='returned', operation='one', value=0)]
    changes = {}
    if case == 'missing':
        events[1].pop('value')
    elif case == 'explore':
        changes = dict(requirement=None, comparisons=[])
    elif case == 'mismatch':
        events[1]['value'] = 3
    state, fixed, check = saved_evidence(tmp_path, events=events, basis_changes=changes)
    if case == 'gap':
        state.investigations[0].gaps = [Gap(id='caller', operation_id='start', question='Does the caller contract apply?')]
    append_interpretation(state, conclusion=conclusion, defect_claim=claim, executions={check.id: [1]})
    before = state.model_dump(mode='json')
    result = assessment(state, tmp_path, fixed, check)
    text = render_report(state, tmp_path).read_text()
    assert result['outcome'] == outcome
    claims, _, other = text.split('## Explicit model defect claims (subject to independent verification)', 1)[1].partition('## Other research results')
    assert (state.investigations[0].question in claims) == (claim == 'asserted')
    assert (state.investigations[0].question in other) == (claim != 'asserted')
    assert ('Interpretation differs from the mechanical result' in text) == (case == 'mismatch')
    if case == 'explore':
        assert 'mechanical comparison is undetermined, not an opposing conclusion' in text
    elif case == 'missing':
        assert 'Observation gaps' in text and not result['comparisons'][0]['valid_witness_indices']
    elif case == 'gap':
        assert state.investigations[0].gaps[0].question in text
    for path in (f'fixed-experiments/{fixed.id}/basis.json', f'logs/{check.id}/check.json', f'logs/{check.id}/observations.json'):
        assert path in text and (tmp_path / path).is_file()
    assert state.model_dump(mode='json') == before


def test_report_uses_current_claim_without_erasing_history(tmp_path):
    state, fixed, check = saved_evidence(tmp_path)
    prior = append_interpretation(state, defect_claim='asserted', rationale='Initial defect allegation')
    current = append_interpretation(state, experiment_id=None, conclusion='explained', defect_claim='refuted',
        rationale='The caller contract excludes the observed input',
        counterevidence=['The input violates the documented caller duty'], limitations=['Other callers remain open'],
        executions={check.id: [1]})
    write_json(tmp_path / 'state.json', state)
    before = state.model_dump(mode='json')
    text = render_report(state, tmp_path).read_text()
    claims, other = text.split('## Explicit model defect claims (subject to independent verification)', 1)[1].split('## Other research results', 1)
    assert state.investigations[0].question not in claims and state.investigations[0].question in other
    assert prior.rationale not in text
    for value in [current.rationale, *current.counterevidence, *current.limitations]:
        assert value in text
    assert 'model claim asserted → refuted' in text
    assert f'[{prior.id}](state.json) → [{current.id}](state.json)' in text
    assert json.loads((tmp_path / 'state.json').read_text())['interpretations'] == [
        interpretation.model_dump(mode='json') for interpretation in state.interpretations]
    result = assessment(state, tmp_path, fixed, check)
    assert result['interpretation_citations']['historical_count'] == 1
    assert [item['id'] for item in result['interpretation_citations']['current']] == [current.id]
    assert result['outcome'] == 'violated'
    assert f'logs/{check.id}/observations.json' in text and 'event indices [1]' in text
    assert state.model_dump(mode='json') == before


@pytest.mark.parametrize('superseded',[False,True])
def test_other_experiment_receipt_citations_do_not_change_direct_assessment(tmp_path,superseded):
    s, fixed, check = saved_evidence(tmp_path)
    s.investigations[0].gaps = [Gap(id='history', question='Was the producer history legal?', operation_id='start')]
    before = assessment(s, tmp_path, fixed, check)
    other, other_fixed, other_check = saved_evidence(tmp_path, name='other')
    other.investigations[0].question = 'What does this separate local call establish?'
    s.investigations.extend(other.investigations)
    s.experiments.append(other_fixed)
    s.checks.append(other_check)
    append_interpretation(s, executions={check.id: [1], other_check.id: [1]},
        joint_history='Independent calls to the same stateless function, not one distributed history')
    if superseded:
        append_interpretation(s, experiment_id=None, executions={}, conclusion='explained',
            rationale='A narrower source-only account supersedes the measured account')
    after=assessment(s,tmp_path,fixed,check)
    assert after['interpretation_id'] is None
    assert after['gap_ids'] and 'no interpretation directly attributed' in str(after['blockers'])
    assert {k:v for k,v in after.items() if k!='interpretation_citations'}=={
        k:v for k,v in before.items() if k!='interpretation_citations'}
    citations=after['interpretation_citations']
    assert citations['historical_count']==int(superseded)
    assert citations['current']==([] if superseded else [dict(id=s.interpretations[0].id,
        investigation_id=s.investigations[1].id,experiment_id=s.experiments[1].id,event_indices=[1])])
    text=render_report(s,tmp_path).read_text().split('### '+s.investigations[1].question)[0]
    assert ('Other current question interpretations explicitly citing this receipt' in text)==(not superseded)
    assert ('Historical interpretations explicitly citing this receipt: 1' in text)==superseded
    assert 'No current explicit defect assertion' in text


def test_later_experiment_gap_does_not_retroactively_block_saved_witness(tmp_path):
    state, fixed, check = saved_evidence(tmp_path)
    append_interpretation(state)
    before = assessment(state, tmp_path, fixed, check)
    successor = fixed.model_copy(update={'id': 'successor', 'previous_id': fixed.id, 'version': 2})
    state.experiments.append(successor)
    gap = Gap(id='history', operation_id='later', experiment_id=successor.id,
              question='Does the new observation establish the required service opportunity?')
    state.investigations[0].gaps.append(gap)
    assert assessment(state, tmp_path, fixed, check) == before
    gap.experiment_id = fixed.id
    after = assessment(state, tmp_path, fixed, check)
    assert after['gap_ids'] == [gap.id] and gap.question in after['blockers']
    assert after['comparisons'] == before['comparisons']
