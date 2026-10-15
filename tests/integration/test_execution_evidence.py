"""Actual local receipts under scripted transport, never autonomous discovery evidence."""
import json
import shutil
from pathlib import Path
import pytest
from audit_support import engine_for, first, combined, experiment, opinion, stop
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.workflow.experiments import assessment, observed, validate_failure
from consensus_assurance.workflow.knowledge import target_receipts


def executed_case(tmp_path, tail='', review=None, *, second_operation=False):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')

    def start(state):
        sub, files = combined(state)
        if second_operation:
            comparison = sub['experiment']['comparisons'][0]
            sub['experiment']['comparisons'] = [
                {**comparison, 'applicability_conditions':[dict(field='operation',value=operation)]}
                for operation in ('one','two')]
            files['check.py'] += "print('CA_EVENT '+json.dumps(dict(event='admitted',operation='two',value=3,limit=3)))\n"
            files['check.py'] += "print('CA_EVENT '+json.dumps(dict(event='returned',operation='two',value=step(3,3))))\n"
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
    for update in ({'witness_indices': {0: [0]}}, {'failure_lines': [500, 501]}, {'check_id': 'other'}):
        with pytest.raises(ValueError):
            validate_failure(engine.state, engine.root, fixed, check, measurement, {**attribution, **update})
    harness = engine.root / 'fixed-experiments' / fixed.id / fixed.harness_filename
    harness.write_text(harness.read_text() + '# altered after execution\n')
    assert 'Retained experiment bytes differ' in str(assessment(engine.state, engine.root, fixed, check)['blockers'])


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


@pytest.mark.parametrize('case,outcome',[
    ('prediction','holds'), ('duty','violated'), ('mismatch','holds'),
    ('missing','unknown'), ('malformed','unknown'), ('unmatched','unknown'), ('gap','violated')])
def test_report_separates_sampled_predicate_witness_and_model_account(tmp_path,case,outcome):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')
    def start(state):
        sub,files=combined(state)
        sub['investigations'][0]['question']='Does the capacity branch preserve its input as required by the caller contract?'
        request=sub['experiment']
        request['requirement']=('The capacity call returns zero while the normal call increments'
            if case in {'prediction','mismatch'} else 'The capacity call preserves its input while the normal call increments')
        request['comparisons']=[dict(event='returned',identity_fields=['operation'],admission_alias='start',
            applicability_conditions=[dict(field='operation',value=operation)],
            assertion=dict(field='value',value=expected),description=description)
            for operation,expected,description in [('case',0 if case in {'prediction','mismatch'} else 3,'Capacity case'),
                                                  ('control',3,'Independent normal control')]]
        if case=='gap':sub['gaps']=[dict(investigation_id='@q',question='Does the caller contract apply to the admitted capacity input?')]
        files['check.py']=f'''import json
from target import step
for operation, value in [('case',3),('control',2)]:
    if not (operation=='case' and {case!r}=='unmatched'):
        print('CA_EVENT '+json.dumps(dict(event='admitted',operation=operation,value=value)))
    result=dict(event='returned',operation=operation,value=step(value,3))
    if operation=='case' and {case!r}=='missing':result.pop('value')
    print('CA_EVENT '+('{{broken' if operation=='case' and {case!r}=='malformed' else json.dumps(result)))
'''
        return sub,files
    def explain(state):
        from consensus_assurance.workflow.research import operation_summary
        fixed=e.state.experiments[0]
        check=next(c for c in e.state.checks if c.experiment_id==fixed.id)
        measured=observed(fixed,check,e.root)
        events=measured['events']
        feedback=operation_summary(e.state,e.root)['questions'][0]['execution']
        assert feedback['events']==events
        assert [c['result']['outcome'] for c in feedback['comparisons']]==[c['outcome'] for c in measured['comparisons']]
        assert [c['result']['missing_indices'] for c in feedback['comparisons']]==[c['missing_indices'] for c in measured['comparisons']]
        assert feedback['parsing_error_count']==len(measured['parsing_errors'])
        return opinion(state,conclusion='violated' if case=='mismatch' else 'conditional' if outcome=='unknown' else outcome,
            executions={check.id:[i for i,v in enumerate(events) if v['event']=='returned']},
            rationale='The sampled capacity result is undesirable under the sourced preservation contract; the control increments',
            limitations=['Incomplete samples and unresolved applicability cannot establish this account'],
            defect_claim='asserted' if case in {'prediction','mismatch'} else None if case=='duty' else 'unresolved')
    e,repo=engine_for(tmp_path,[start,explain,stop])
    e.agent.mock=False
    e.config.execution_isolation='bwrap'
    (repo/'README.md').write_text('A synchronous capacity call must preserve its input; a call below capacity must increment.\n')
    state=e.start(repo)
    fixed=state.experiments[0]
    check=next(c for c in state.checks if c.experiment_id==fixed.id)
    result=assessment(state,e.root,fixed,check)
    control_outcome='unknown' if case=='malformed' else 'holds'
    assert [r['outcome'] for r in result['comparisons']]==[outcome,control_outcome]
    assert not {'confirmed','reviewed_complete'} & result.keys()
    assert all('confirmed' not in r for r in result['comparisons'])
    assert bool(result['comparisons'][0]['valid_witness_indices']) == (outcome == 'violated')
    assert not result['comparisons'][1]['valid_witness_indices']
    if outcome!='unknown':assert [v['value'] for v in result['events'] if v['event']=='returned']==[0,3]
    from consensus_assurance.reporting.report import render_report
    before=state.model_dump(mode='json')
    report=render_report(state,e.root).read_text()
    assert state.model_dump(mode='json')==before
    assert assessment(state,e.root,fixed,check)==result
    case_text,control_text=report.split('Comparison 0 ·',1)[1].split('Comparison 1 ·',1)
    labels={'holds':'declared predicate holds','violated':'declared predicate does not hold','unknown':'comparison undetermined'}
    assert labels[outcome] in case_text
    assert labels[control_outcome] in control_text
    assert 'Directly attributed interpretation for this execution' in report and state.interpretations[0].rationale in report
    claim=state.interpretations[0].defect_claim
    labels={None:'no explicit defect claim submitted','asserted':'defect asserted (subject to independent verification)','unresolved':'unresolved'}
    assert f'Current model defect claim: {labels[claim]}' in report
    claims,_,other=report.split('## Explicit model defect claims (subject to independent verification)',1)[1].partition('## Other research results')
    assert (state.investigations[0].question in claims)==(claim=='asserted')
    assert (state.investigations[0].question in other)==(claim!='asserted')
    assert report.count('### ')==1
    assert 'confirmed=' not in report
    assert ('Interpretation differs from the mechanical result' in report)==(case=='mismatch')
    if case=='gap':assert state.investigations[0].gaps[0].question in report and 'Unresolved necessary gaps' in report
    if case in {'missing','malformed','unmatched'}:assert 'Observation gaps' in report
    for path in (f'fixed-experiments/{fixed.id}/basis.json',f'logs/{check.id}/check.json',f'logs/{check.id}/observations.json'):
        assert path in report and (e.root/path).is_file()


def test_exploratory_receipt_supports_contract_refutation_without_rerun(tmp_path):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')
    from consensus_assurance.reporting.report import render_report
    saved={}
    def start(state):
        sub,files=combined(state)
        sub['experiment'].pop('requirement')
        sub['experiment']['prefix']='Supply a capacity input to observe the boundary behavior; legality remains to be researched.'
        return sub,files
    def allegation(state):
        return opinion(state,defect_claim='asserted',rationale='The sampled reset appears to lose caller state')
    def correction(state):
        fixed=e.state.experiments[0]
        check=next(c for c in e.state.checks if c.experiment_id)
        saved['assessment']=assessment(e.state,e.root,fixed,check)
        saved['fixed'],saved['check']=fixed.model_dump(mode='json'),check.model_dump(mode='json')
        paths=[f'fixed-experiments/{fixed.id}/basis.json',f'fixed-experiments/{fixed.id}/{fixed.harness_filename}',
               *[f'logs/{check.id}/{name}' for name in ('check.json','observations.json','stdout.log','stderr.log')]]
        saved['files']={path:(e.root/path).read_bytes() for path in paths}
        claims=render_report(e.state,e.root).read_text().split('## Other research results',1)[0]
        assert e.state.investigations[0].question in claims and 'defect asserted (subject to independent verification)' in claims
        return opinion(state,experiment_id=None,conclusion='explained',defect_claim='refuted',
            rationale='The necessary legal-call premise is false; the sampled reset is outside the interface contract',
            counterevidence=['The captured caller contract requires value < limit; the supplied input equals limit'],
            limitations=['No claim about other callers or behavior within the permitted input range'])
    e,repo=engine_for(tmp_path,[start,allegation,correction,stop])
    e.agent.mock=False
    e.config.execution_isolation='bwrap'
    contract='Callers must supply 0 <= value < limit; capacity input is prohibited.\n'
    (repo/'README.md').write_text(contract)
    state=e.start(repo)
    assert state.usage['experiments']==len(state.experiments)==1
    checks=[c for c in state.checks if c.experiment_id]
    assert len(checks)==1 and checks[0].model_dump(mode='json')==saved['check']
    assert state.experiments[0].model_dump(mode='json')==saved['fixed']
    assert all((e.root/path).read_bytes()==raw for path,raw in saved['files'].items())
    result=assessment(state,e.root,state.experiments[0],checks[0])
    assert {k:v for k,v in result.items() if k!='interpretation_citations'}=={
        k:v for k,v in saved['assessment'].items() if k!='interpretation_citations'}
    assert result['events'][1]['value']==0
    assert result['interpretation_citations']['current'][0]['id']==state.interpretations[-1].id
    assert result['outcome']=='violated' and result['comparisons'][0]['valid_witness_indices']==[1]
    assert len(result['blockers'])==1
    limitation=result['blockers'][0]
    assert 'Exploratory basis has no fixed requirement' in limitation
    assert 'Retained observations still support sourced interpretation' in limitation
    assert 'no successor or rerun is required' in limitation
    assert [i.defect_claim for i in state.interpretations]==['asserted','refuted']
    assert all(i.executions=={checks[0].id:[1]} for i in state.interpretations)
    view=json.loads((e.root/'research.json').read_text())
    assert view['investigations'][0]['latest_interpretation']['defect_claim']=='refuted'
    assert view['reselection']['questions'][0]['latest_interpretation']['defect_claim']=='refuted'
    assert view['experiments'][0]['results'][0]['blockers']==[limitation]
    report=render_report(state,e.root).read_text()
    claims,_,other=report.split('## Explicit model defect claims (subject to independent verification)',1)[1].partition('## Other research results')
    assert state.investigations[0].question not in claims and state.investigations[0].question in other
    assert 'Current model defect claim: defect claim refuted within the stated scope' in other and report.count('### ')==1
    assert 'historical interpretation; the question has a later account' in other
    assert limitation in other
    assert state.interpretations[-1].rationale in report and state.interpretations[0].rationale not in report
    assert all(i.id in report for i in state.interpretations)
    assert state.interpretations[-1].counterevidence[0] in report
    assert (repo/'README.md').read_text()==contract


def test_bounded_retry_cycle_controls_and_historical_failures(tmp_path):
    """Supplied source reasoning plus real receipts, not automatic liveness inference."""
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')
    source = Path('tests/fixtures/research_protocol.py').read_text()
    tick_line = source.splitlines().index('    def tick(self):')+1
    def build(state, broken=False, cleanup=False, opportunities=True):
        sub, _ = combined(state)
        sub['sources'][0]['end_line'] = len(source.splitlines())
        sub['investigations'][0]['question'] = 'Does retry preserve progress under normal service ticks?'
        request = sub['experiment']
        request.update(prefix='Construct queue, enqueue through its producer, supply normal service ticks',
            scope={'description':'Serialized pending work without cancellation or external repair'},
            requirement='An enqueued operation completes under repeated normal service ticks',
            responsibility='enqueue creates pending work; tick is the only enabled service transition under the fixture contract',
            anchors=[dict(material_id='code',symbol='RetryQueue.tick',start_line=tick_line,end_line=len(source.splitlines()))],
            prerequisites=[dict(alias='boot',event='initialized'),dict(alias='legacy',event='never_observed')],
            comparisons=[])
        for mode in ('short','long','control'):
            request['prerequisites'].append(dict(alias=mode,event='admitted',conditions=[
                dict(field='mode',value=mode),dict(field='generation',reference='boot.generation')]))
            request['comparisons'].append(dict(event='result',identity_fields=['operation','generation'],
                admission_alias='legacy' if broken and mode=='short' else mode,
                applicability_conditions=[dict(field='mode',value=mode)],assertion=dict(field='completed',value=1)))
        code=f'''import json, time
from target import RetryQueue
for mode, reset, ticks in [('short',True,4),('long',True,6),('control',False,6)]:
    queue=RetryQueue(reset)
    def emit(event, **values):
        print('CA_EVENT '+json.dumps(dict(event=event,operation=mode,mode=mode,generation=1,**values)))
    emit('initialized')
    queue.enqueue()
    emit('admitted',pending=queue.pending)
    started=time.monotonic()
    for _ in range(ticks if {opportunities!r} else 0):
        before=queue.phase
        queue.tick()
        emit('tick',before=before,after=queue.phase,completed=queue.completed)
    emit('result',completed=queue.completed,pending=queue.pending,elapsed=time.monotonic()-started)
'''
        if cleanup:code += "raise RuntimeError('fixture cleanup failed after sampling')\n"
        if state['experiments']:
            old=state['experiments'][-1]
            request.update(investigation_id=old['investigation_id'],previous_id=old['id'],
                revision_reason='Correct association/cleanup, or separately measure without service opportunities')
            sub={'rationale':'Execute the changed fixed basis','experiment':request}
        return sub,{'check.py':code}
    def review(state, conclusion, **changes):
        fixed=e.state.experiments[-1]
        check=next(c for c in e.state.checks if c.experiment_id==fixed.id)
        events=observed(fixed,check,e.root)['events']
        return opinion(state,conclusion=conclusion,executions={check.id:[n for n,v in enumerate(events) if v['event']=='result']},**changes)
    def repair(state):
        sub,files=build(state,cleanup=True)
        sub['interpretations']=review(state,'unresolved',rationale='First comparison names an unreached admission')[0]['interpretations']
        return sub,files
    def fix_cleanup(state):
        sub,files=build(state)
        sub['interpretations']=review(state,'conditional',rationale='Later cleanup failed; retain measurements without attribution')[0]['interpretations']
        return sub,files
    def finish(state):
        sub,files=review(state,'violated',rationale='Actual enqueue is followed by four/six fair ticks cycling phase 0→1→0; '
            'the reset branch restores pending without completion. No other repair runs under these assumptions.',
            counterevidence=['Same sampling in the non-reset control completes after two ticks',
                'The superseded harness cleanup failure is retained in its own receipt'],
            limitations=['No claim about cancellation, external repair or arbitrary schedulers'])
        sub['investigations']=[dict(id=state['investigations'][0]['id'],disposition='explained')]
        return sub,files
    def no_service(state):
        return build(state,opportunities=False)
    def short_review(state):
        sub,files=review(state,'conditional',rationale='An immediate noncompletion without service does not establish a liveness failure')
        sub['gaps']=[dict(investigation_id=state['investigations'][0]['id'],experiment_id=state['experiments'][-1]['id'],
            question='This new observation supplies no service opportunity or observed retry cycle')]
        return sub,files
    e,repo=engine_for(tmp_path,[lambda s:build(s,broken=True),repair,fix_cleanup,finish,no_service,
        short_review,stop])
    e.agent.mock=False
    e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text(source)
    (repo/'README.md').write_text('Serialized enqueue and normal service ticks must complete pending work; no cancellation or external repair.\n')
    state=e.start(repo)
    assert len(state.experiments)==4 and len(state.interpretations)==4, state.current_submission
    # The later, explicitly scoped objection must not poison the earlier measured cycle.
    gap=state.investigations[0].gaps[0]
    assert gap.experiment_id==state.experiments[-1].id
    results=[assessment(state,e.root,a,next(c for c in state.checks if c.experiment_id==a.id)) for a in state.experiments]
    good=results[2]
    assert not good['blockers'] and all(r['comparison_complete'] for r in good['comparisons'])
    assert [bool(r['valid_witness_indices']) for r in good['comparisons']]==[True,True,False]
    assert [r['outcome'] for r in good['comparisons']]==['violated','violated','holds']
    assert all(results[n]['blockers'] for n in (0,1,3))
    assert state.experiments[2].previous_id==state.experiments[1].id
    assert state.interpretations[2].counterevidence and state.interpretations[2].limitations
    assert all(v['elapsed']>=0 for v in good['events'] if v['event']=='result')
    challenged=state.model_copy(deep=True)
    challenged.investigations[0].gaps[0].experiment_id=state.experiments[2].id
    assert gap.question in assessment(challenged,e.root,state.experiments[2],next(c for c in state.checks if c.experiment_id==state.experiments[2].id))['blockers']
    from consensus_assurance.reporting.report import render_report
    report=render_report(state,e.root).read_text()
    assert 'local question answered' in report and 'Directly attributed interpretation for this execution' in report and 'valid violating event indices' in report


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
        assert 'uncited_executions' not in summary
        result=current_view(engine.state,engine.root)['experiments'][0]['results'][0]
        assert result['experiment_id']==state['experiments'][0]['id']
        assert not result['interpretation_citations']['current']
        sub, files = duplicate(state)
        sub['experiment']['prefix'] += ' A changed assumption.'
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


def test_reselection_keeps_old_open_gaps_and_recent_explanations_visible(tmp_path):
    from consensus_assurance.workflow.research import operation_summary, excerpt
    counterevidence = [f'The documented caller condition {n} bounds the sampled input' for n in range(5)]
    limitations = [f'No observation establishes asynchronous completion for caller {n}' for n in range(5)]
    counterevidence[1] += '; the actual operand comes from the admitted caller' * 8
    limitations[4] += '; downstream recovery remains outside this observation' * 8
    saved = {}
    def start(state):
        sub, files = first(state)
        sub['investigations'] += [dict(question=f'Which return condition applies to caller {n}?',
            source_ids=['code']) for n in range(9)]
        sub['interpretations'] = [dict(investigation_id='@q', source_ids=['code'], conclusion='unresolved',defect_claim=None,
            rationale='The initial caller contract still needs inspection',
            limitations=['The initial caller condition is unknown'])]
        return sub, files

    def revisit(state):
        saved['initial'] = state['interpretations'][0]
        old, pending = state['investigations'][:2]
        return {'rationale':'Explain a local sample while retaining a separate caller premise',
            'interpretations':[dict(investigation_id=old['id'], source_ids=['code'], conclusion='explained',
                defect_claim='refuted', rationale='The ordinary caller return is explained by the boundary branch',
                counterevidence=counterevidence, limitations=limitations)],
            'gaps':[dict(investigation_id=pending['id'], question='Which actual producer establishes the caller bound?')]}, {}

    def another(state):
        before = engine.state.model_dump(mode='json')
        summary = operation_summary(engine.state, engine.root)
        assert engine.state.model_dump(mode='json') == before
        assert len(summary['questions']) == 1
        local = summary['questions'][0]
        assert local['id'] == state['investigations'][0]['id']
        opinion = local['latest_interpretation']
        assert opinion['id'] == state['interpretations'][-1]['id']
        assert opinion['counterevidence'] == [excerpt(v) for v in counterevidence[:3]]
        assert opinion['limitations'] == limitations[:3]
        assert opinion['counterevidence_omitted_count'] == opinion['limitations_omitted_count'] == 2
        locator = opinion['record']
        full = next(v for v in state[locator['collection']] if v['id'] == locator['id'])
        assert full['counterevidence'] == counterevidence and full['limitations'] == limitations
        assert opinion['defect_claim'] == 'refuted' and opinion['conclusion'] == 'explained'
        return {'rationale':'Inspect another sourced condition', 'investigations':[dict(
            question='Which recovery caller uses this return?', source_ids=['code'])]}, {}

    def finish(state):
        summary = operation_summary(engine.state, engine.root)
        assert len(summary['questions']) == 1
        assert summary['questions'][0]['id'] == state['investigations'][-1]['id']
        assert summary['questions'][0]['latest_interpretation'] is None
        assert len(state['interpretations']) == 2 and state['interpretations'][0] == saved['initial']
        index = json.loads((engine.root/'research.json').read_text())
        view = index['reselection']
        questions = {q['id']:q for q in view['questions']}
        old, pending = state['investigations'][:2]
        assert list(questions) == [q['id'] for q in state['investigations']]
        assert questions[pending['id']]['open_gap_count'] == 1
        assert state['investigations'][-1]['id'] in questions
        answer = next(q for q in index['investigations'] if q['id'] == old['id'])
        assert answer['discriminator'] == old['discriminator'] and answer['hypothesis'] == old['hypothesis']
        assert answer['latest_interpretation']['id'] == state['interpretations'][-1]['id']
        assert answer['latest_interpretation']['limitations'] == limitations[:3]
        assert answer['latest_interpretation']['counterevidence'] == [excerpt(v) for v in counterevidence[:3]]
        assert answer['latest_interpretation']['counterevidence_omitted_count'] == 2
        assert all(q['disposition'] == 'active' for q in state['investigations']) and not state['experiments']
        return stop(state)

    engine, repo = engine_for(tmp_path, [start, revisit, another, finish])
    engine.start(repo)


def repeat_existing(state):
    return {'rationale':'Check whether the same fixed input reproduces in another clean execution',
            'repeat_experiment_id':state['experiments'][0]['id']}, {}


def test_explicit_repeats_preserve_fixed_inputs_and_separate_receipts(tmp_path):
    saved={}
    source=experiment()[1]['check.py']+"""from pathlib import Path
marker=Path('execution-marker')
assert not marker.exists(), 'execution workspace was reused'
marker.write_text('observed one invocation')
"""
    def start(state):
        sub,files=combined(state)
        files['check.py']=source
        return sub,files
    def duplicate(state):
        fixed=engine.state.experiments[0]
        check=next(c for c in engine.state.checks if c.experiment_id)
        saved['fixed']=fixed.model_dump(mode='json')
        paths=[f'fixed-experiments/{fixed.id}/basis.json',f'fixed-experiments/{fixed.id}/{fixed.harness_filename}',
               *[f'logs/{check.id}/{name}' for name in ('check.json','observations.json','stdout.log','stderr.log')]]
        saved['files']={path:(engine.root/path).read_bytes() for path in paths}
        request,files=experiment(fixed.investigation_id,source=source)
        return {'rationale':'An unchanged submission does not request another execution','experiment':request},files
    repeated=[]
    def repeat(state):
        repeated.append(state['current_submission']['no_change'])
        sub,_=repeat_existing(state)
        return sub,{'check.py':"raise AssertionError('The current draft must not be executed by a repeat')\n"}
    def explain(state):
        from consensus_assurance.workflow.research import operation_summary, current_view
        checks=[c for c in state['checks'] if c.get('experiment_id')]
        summary=operation_summary(engine.state,engine.root)
        assert summary['questions'][0]['latest_interpretation']['executions']=={checks[0]['id']:[1]}
        assert 'uncited_executions' not in summary
        assert summary['questions'][0]['execution']['id']==checks[-1]['id']
        results=current_view(engine.state,engine.root)['experiments'][0]['results']
        assert {r['check_id'] for r in results if not r['interpretation_citations']['current']}=={c['id'] for c in checks[1:]}
        assert summary['effects']==state['current_submission']['effects']
        effect=next(e for e in summary['effects'] if e['action']=='repeat_execution')
        locator=effect['fixed_experiment']
        assert locator['experiment_id']==state['experiments'][0]['id'] and locator['version']==1
        assert (engine.root/locator['harness']).read_text()==source
        assert 'current draft is not read' in effect['input_source']
        sub,_=opinion(state)
        value=sub['interpretations'][0]
        sub['interpretations']=[{**value,'executions':{c['id']:[1]},
            'rationale':'Interpret only the observed return in receipt '+c['id']} for c in checks[1:]]
        return sub,{}
    engine,repo=engine_for(tmp_path,[start,opinion,duplicate,repeat,repeat,explain,stop])
    state=engine.start(repo)
    checks=[c for c in state.checks if c.experiment_id]
    assert repeated==[True,False] and state.usage['experiments']==3
    assert len(state.experiments)==1 and state.experiments[0].model_dump(mode='json')==saved['fixed']
    assert len(checks)==len({c.id for c in checks})==len({c.cwd for c in checks})==3
    assert all(c.status==ExecutionStatus.COMPLETED and c.exit_code==0 for c in checks)
    assert all((engine.root/path).read_bytes()==raw for path,raw in saved['files'].items())
    inputs=[json.loads((engine.root/'actions'/c.pending_action_id/'input.json').read_text()) for c in checks]
    assert len({value['operation_id'] for value in inputs})==3
    assert all(value['experiment_id']==state.experiments[0].id for value in inputs)
    results=[assessment(state,engine.root,state.experiments[0],c) for c in checks]
    assert [r['interpretation_id'] for r in results]==[i.id for i in state.interpretations]
    assert all(r['outcome']=='violated' and r['comparisons'][0]['valid_witness_indices']==[1] for r in results)
    from consensus_assurance.reporting.report import render_report
    report=render_report(state,engine.root).read_text()
    assert report.count('Fixed experiment `')==1 and all(f'Execution `{c.id}`' in report for c in checks)


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


@pytest.mark.parametrize('raw_receipt', [False, True])
@pytest.mark.parametrize('repeat', [False, True])
@pytest.mark.parametrize('expired', [False, True])
def test_completed_action_recovery_never_reexecutes_target(tmp_path, raw_receipt, repeat, expired):
    steps=[combined,*([repeat_existing] if repeat else []),opinion,stop]
    engine, repo = engine_for(tmp_path, steps)
    expected=2 if repeat else 1
    engine.config.budget.experiments=expected
    original = engine.checkpoint
    interrupted = False

    def checkpoint(event):
        nonlocal interrupted
        original(event)
        if (not raw_receipt and event == 'action_result_saved' and
                engine.state.pending_action.kind == 'experiment_execute' and
                engine.state.usage['experiments']==expected and not interrupted):
            interrupted = True
            raise KeyboardInterrupt('Execution result durable, acceptance still pending')

    engine.checkpoint = checkpoint
    run = engine.runner.run

    def interrupted_run(*args, **kwargs):
        nonlocal interrupted
        receipt = run(*args, **kwargs)
        if raw_receipt and receipt.action == 'experiment' and engine.state.usage['experiments']==expected and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Raw process receipt durable, action result missing')
        return receipt

    engine.runner.run = interrupted_run
    with pytest.raises(KeyboardInterrupt):
        engine.start(repo)
    assert engine.state.current_submission['phase'] == 'accepted'
    action_id=engine.state.pending_action.id
    result_path = engine.root / 'actions' / action_id / 'result.json'
    if raw_receipt:
        assert not result_path.exists()
        receipt_id = next(value['id'] for p in (engine.root / 'logs').glob('*/check.json')
                          if (value:=json.loads(p.read_text())).get('pending_action_id')==action_id and value['action']=='experiment')
    else:
        receipt_id = json.loads(result_path.read_text())['id']
    old_ids=[c.id for c in engine.state.checks if c.experiment_id]
    old_receipts={id:(engine.root/'logs'/id/'check.json').read_bytes() for id in old_ids}
    assert len(old_ids)==int(repeat) and receipt_id not in old_ids
    engine.checkpoint = original
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


def test_repeat_without_completed_receipt_retries_with_new_action_identity(tmp_path):
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
    assert state.usage['experiments']==3 and len(checks)==2
    assert checks[-1].pending_action_id!=lost_id and checks[-1].cwd!=checks[0].cwd
    assert any(a.id==lost_id and a.status=='outcome_unknown' for a in state.action_history)
    assert any('no completed receipt' in gap for gap in state.gaps)
