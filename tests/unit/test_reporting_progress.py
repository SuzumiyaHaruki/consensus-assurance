"""Report and observation-cache projections over synthetic saved evidence."""
import json
from types import SimpleNamespace
import pytest
from support.evidence import saved_evidence, append_interpretation
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Gap
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.research import execution_cost, costs, current_view
from consensus_assurance.reporting.report import render_report


def test_costs_keep_missing_data_and_do_not_double_count_children(tmp_path):
    c=CheckRun(id='parent',action='experiment',cwd=str(tmp_path),snapshot_id='fixture',
        started_at='2026-10-04T00:00:01+00:00',ended_at='2026-10-04T00:00:05.300000+00:00',
        parameters={'action_seconds':28.71})
    old=c.model_copy(update={'id':'old','parameters':{}})
    child=c.model_copy(update={'id':'child','action':'cargo_seed_copy'})
    state=SimpleNamespace(checks=[c,old,child,c.model_copy(deep=True)],usage={},elapsed_seconds=80)
    result=costs(state)
    assert result['target_executions']==2 and result['process_seconds']==8.6
    assert result['action_seconds']==28.71 and result['unrecorded_action_ids']==['old']
    for invalid in (None,-1,float('inf'),float('nan'),True,'28.71'):
        assert execution_cost(c.model_copy(update={'parameters':{'action_seconds':invalid},'started_at':'invalid'}))=={'process_seconds':None,'action_seconds':None}


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
    ('explore', 'unknown', 'violated', 'asserted'), ('explore', 'unknown', 'holds', 'asserted'),
    ('prediction', 'holds', 'holds', 'asserted'), ('mismatch', 'holds', 'violated', 'asserted'),
    ('duty', 'violated', 'violated', None), ('opposing', 'violated', 'holds', 'asserted'),
    ('missing', 'unknown', 'conditional', 'unresolved'), ('malformed', 'unknown', 'conditional', 'unresolved'),
    ('unmatched', 'unknown', 'conditional', 'unresolved'), ('gap', 'violated', 'violated', 'unresolved'),
])
def test_report_separates_comparisons_claims_and_observation_gaps(tmp_path, case, outcome, conclusion, claim):
    events = [dict(event=name, operation=operation, value=value)
        for operation, admitted, returned in [('case', 3, 0), ('control', 2, 3)]
        for name, value in [('admitted', admitted), ('returned', returned)]]
    if case == 'missing':
        events[1].pop('value')
    elif case == 'malformed':
        events[1] = '{broken'
    elif case == 'unmatched':
        events.pop(0)
    changes = dict(comparisons=[dict(event='returned', identity_fields=['operation'], admission_alias='start',
        applicability_conditions=[dict(field='operation', value=operation)],
        assertion=dict(field='value', value=expected)) for operation, expected in [
            ('case', 0 if case in {'prediction', 'mismatch'} else 3), ('control', 3)]])
    if case == 'explore':
        changes.update(requirement=None, comparisons=[])
    state, fixed, check = saved_evidence(tmp_path, events=events, basis_changes=changes)
    if case == 'gap':
        state.investigations[0].gaps = [Gap(id='caller', operation_id='start', question='Does the caller contract apply?')]
    append_interpretation(state, conclusion=conclusion, defect_claim=claim,
        executions={check.id: [i for i, event in enumerate(events) if isinstance(event, dict) and event['event']=='returned']})
    before = state.model_dump(mode='json')
    result = assessment(state, tmp_path, fixed, check)
    text = render_report(state, tmp_path).read_text()
    assert result['outcome'] == outcome and not {'confirmed', 'reviewed_complete'} & result.keys()
    assert state.model_dump(mode='json') == before
    assert assessment(state, tmp_path, fixed, check) == result
    claims, _, other = text.split('## Explicit model defect claims (subject to independent verification)', 1)[1].partition('## Other research results')
    assert (state.investigations[0].question in claims) == (claim == 'asserted')
    assert (state.investigations[0].question in other) == (claim != 'asserted')
    assert text.count('### ') == 1 and 'confirmed' not in text
    assert ('Interpretation differs from the mechanical result' in text) == (case in {'mismatch', 'opposing'})
    assert ('mechanical comparison is undetermined, not an opposing conclusion' in text) == (case == 'explore')
    current = text.split(f'### {state.investigations[0].question}', 1)[1].split('Fixed experiment `', 1)[0]
    assert f'Current model interpretation `{state.interpretations[0].id}` · `{conclusion}`' in current
    assert state.interpretations[0].rationale in current and 'declared predicate' not in current
    claim_labels = {'asserted': 'defect asserted (subject to independent verification)',
                    'unresolved': 'unresolved', None: 'no explicit defect claim submitted'}
    assert f'Current model defect claim: {claim_labels[claim]}' in current
    labels = {'holds': 'declared predicate holds', 'violated': 'declared predicate does not hold', 'unknown': 'comparison undetermined'}
    if case == 'explore':
        assert not result['comparisons'] and 'No fixed comparisons declared' in text
    else:
        control = 'unknown' if case == 'malformed' else 'holds'
        assert [r['outcome'] for r in result['comparisons']] == [outcome, control]
        assert bool(result['comparisons'][0]['valid_witness_indices']) == (outcome == 'violated')
        assert not result['comparisons'][1]['valid_witness_indices']
        case_text, control_text = text.split('Comparison 0 ·', 1)[1].split('Comparison 1 ·', 1)
        assert labels[outcome] in case_text and labels[control] in control_text
    if case == 'gap':
        assert state.investigations[0].gaps[0].question in text and 'Unresolved necessary gaps' in text
    if case in {'missing', 'malformed', 'unmatched'}:
        assert 'Observation gaps' in text
    for path in (f'fixed-experiments/{fixed.id}/basis.json', f'logs/{check.id}/check.json', f'logs/{check.id}/observations.json'):
        assert path in text and (tmp_path/path).is_file()
    view = current_view(state, tmp_path)
    assert view['investigations'][0]['latest_interpretation']['conclusion'] == conclusion
    assert view['reselection']['questions'][0]['latest_interpretation']['conclusion'] == conclusion
    assert 'not provider request count' in text and 'excludes Agent local exploratory checks' in text


@pytest.mark.parametrize('claim,label',[
    ('refuted','defect claim refuted within the stated scope'), ('unresolved','unresolved'), (None,'no explicit defect claim submitted')])
def test_report_uses_actual_observations_and_preserves_opinion_history(tmp_path,claim,label):
    s, fixed, check = saved_evidence(tmp_path)
    s.investigations[0].gaps = [Gap(id=f'gap-{i}', question=question, operation_id='start')
        for i, question in enumerate(['Which caller contract applies?', 'Was the producer history legal?'])]
    append_interpretation(s, defect_claim='asserted',
        rationale='Compare the actual return. The initial model alleges a defect',
        counterevidence=['The documented input bound may exclude this caller'],
        limitations=['Only one call was observed'],
        answers={'gap-0': dict(explanation='Initial contract reading', resolved=True)})
    append_interpretation(s, experiment_id=None, conclusion='conditional',
        rationale='Caller history remains unestablished',
        counterevidence=['The actual caller duty excludes the alleged general obligation'],
        limitations=['No broader consensus conclusion follows'],
        answers={'gap-0': dict(resolved=claim != 'refuted',
            explanation='The earlier answer did not establish the actual caller condition'
                if claim == 'refuted' else 'The cited local contract controls this call')},
        defect_claim=claim, executions={check.id: [1]} if claim is not None else {})
    write_json(tmp_path / 'state.json', s)
    before=s.model_dump(mode='json')
    text=render_report(s,tmp_path).read_text()
    current,execution=text.split('Fixed experiment `',1)
    execution,history=execution.split('Interpretation history:',1)
    for value in [s.interpretations[-1].rationale,*s.interpretations[-1].counterevidence,
                  *s.interpretations[-1].limitations,*[v.explanation for v in s.interpretations[-1].answers.values()]]:
        assert value in current and text.count(value)==1
    if claim=='refuted':
        assert 'gap remains open:' in current and 'Which caller contract applies?' in current
    assert current.count('Was the producer history legal?')==1
    assert not {'counterevidence','limitations'} & s.investigations[0].model_dump().keys()
    assert 'Question counterevidence:' not in text and 'Question boundaries:' not in text
    for value in [s.interpretations[0].rationale,*s.interpretations[0].counterevidence,*s.interpretations[0].limitations]:
        assert value not in text
    saved_history=json.loads((tmp_path/'state.json').read_text())['interpretations']
    assert saved_history==[i.model_dump(mode='json') for i in s.interpretations]
    assert f'[{s.interpretations[0].id}](state.json) → [{s.interpretations[1].id}](state.json)' in history
    assert f'model claim asserted → {claim or "none"}' in history
    assert 'changed fields:' in history and 'rationale' in history and 'source_ids' not in history
    assert 'historical interpretation; the question has a later account' in execution
    assert all(i.rationale not in execution for i in s.interpretations)
    assert [i.defect_claim for i in s.interpretations]==['asserted',claim]
    claims,other=text.split('## Explicit model defect claims (subject to independent verification)',1)[1].split('## Other research results',1)
    assert s.investigations[0].question not in claims and s.investigations[0].question in other
    assert f'Current model defect claim: {label}' in text
    assert text.count('### ')==1
    assert 'Compare the actual return' in saved_history[0]['rationale']
    assert 'confirmed' not in text and 'declared predicate does not hold' in text
    check=next(c for c in s.checks if c.experiment_id)
    citations=assessment(s,tmp_path,s.experiments[0],check)['interpretation_citations']
    assert citations['historical_count']==1
    assert [i['id'] for i in citations['current']]==([s.interpretations[-1].id] if claim is not None else [])
    assert ('Other current question interpretations explicitly citing this receipt' in execution)==(claim is not None)
    observation=f'logs/{check.id}/observations.json'
    assert '[code](state.json)' in current and '[doc](state.json)' in current
    assert (f'logs/{check.id}/check.json' in current)==(claim is not None)
    assert (observation in current)==(claim is not None)
    assert ('event indices [1]' in current)==(claim is not None)
    assert ('No execution receipt explicitly cited by this interpretation' in current)==(claim is None)
    assert json.loads((tmp_path/observation).read_text())['events'][1]['value']==0
    assert s.model_dump(mode='json')==before


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
