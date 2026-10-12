"""Actual local receipts under scripted transport, never autonomous discovery evidence."""
import json
import shutil
from pathlib import Path
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
    assert not assessment(engine.state, engine.root, fixed, check)['confirmed']


@pytest.mark.parametrize('case,outcome,confirmed',[
    ('prediction','holds',False), ('duty','violated',True), ('mismatch','holds',False),
    ('missing','unknown',False), ('malformed','unknown',False), ('unmatched','unknown',False),
    ('gap','violated',False)])
def test_report_separates_sampled_predicate_witness_and_model_account(tmp_path,case,outcome,confirmed):
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
        fixed=e.state.experiments[0]
        check=next(c for c in e.state.checks if c.experiment_id==fixed.id)
        events=observed(fixed,check,e.root)['events']
        return opinion(state,conclusion='violated' if case=='mismatch' else 'conditional' if outcome=='unknown' else outcome,
            executions={check.id:[i for i,v in enumerate(events) if v['event']=='returned']},
            rationale='The sampled capacity result is undesirable under the sourced preservation contract; the control increments',
            report_answer='容量输入归零，违反所引用的局部保持值要求；普通输入仍递增。',
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
    assert result['confirmed']==confirmed and result['comparisons'][0]['confirmed']==confirmed
    assert not result['comparisons'][1]['confirmed']
    if outcome!='unknown':assert [v['value'] for v in result['events'] if v['event']=='returned']==[0,3]
    from consensus_assurance.reporting.chinese import render_report
    before=state.model_dump(mode='json')
    report=render_report(state,e.root).read_text()
    assert state.model_dump(mode='json')==before
    assert assessment(state,e.root,fixed,check)==result
    case_text,control_text=report.split('比较 0 ·',1)[1].split('比较 1 ·',1)
    labels={'holds':'所声明比较条件成立','violated':'所声明比较条件不成立','unknown':'比较未判定'}
    assert labels[outcome] in case_text and f'confirmed={str(confirmed).lower()}' in case_text
    assert labels[control_outcome] in control_text and 'confirmed=false' in control_text
    if control_outcome=='holds':assert '未产生反例见证（confirmed=false）' in control_text
    assert '该执行的模型归属解释' in report and state.interpretations[0].report_answer in report
    claim=state.interpretations[0].defect_claim
    labels={None:'未提交缺陷判断','asserted':'主张存在缺陷（待人工核验）','unresolved':'尚不能判断'}
    assert f'当前模型缺陷判断：{labels[claim]}' in report
    claims,_,other=report.split('## 模型明确主张的缺陷（待人工核验）',1)[1].partition('## 其他研究结果')
    assert (state.investigations[0].question in claims)==(claim=='asserted')
    assert (state.investigations[0].question in other)==(claim!='asserted')
    assert report.count('### ')==1
    assert '有限范围未见违反' not in report and '未确认违反' not in report
    assert ('归属判断与机械结果不一致' in report)==(case=='mismatch')
    if case=='gap':assert state.investigations[0].gaps[0].question in report and '仍未回答的必要缺口' in report
    if case in {'missing','malformed','unmatched'}:assert '观测缺口' in report
    for path in (f'fixed-experiments/{fixed.id}/basis.json',f'logs/{check.id}/check.json',f'logs/{check.id}/observations.json'):
        assert path in report and (e.root/path).is_file()


def test_exploratory_receipt_supports_contract_refutation_without_rerun(tmp_path):
    if not shutil.which('bwrap'):
        pytest.skip('bubblewrap is required for original isolated execution')
    from consensus_assurance.reporting.chinese import render_report
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
        claims=render_report(e.state,e.root).read_text().split('## 其他研究结果',1)[0]
        assert e.state.investigations[0].question in claims and '主张存在缺陷（待人工核验）' in claims
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
    assert result==saved['assessment'] and result['events'][1]['value']==0
    assert result['outcome']=='violated' and not result['confirmed']
    assert result['blockers']==['Exploratory basis has no fixed requirement']
    assert [i.defect_claim for i in state.interpretations]==['asserted','refuted']
    assert all(i.executions=={checks[0].id:[1]} for i in state.interpretations)
    view=json.loads((e.root/'research.json').read_text())
    assert view['investigations'][0]['latest_interpretation']['defect_claim']=='refuted'
    assert view['reselection']['questions'][0]['latest_interpretation']['defect_claim']=='refuted'
    report=render_report(state,e.root).read_text()
    claims,_,other=report.split('## 模型明确主张的缺陷（待人工核验）',1)[1].partition('## 其他研究结果')
    assert state.investigations[0].question not in claims and state.investigations[0].question in other
    assert '当前模型缺陷判断：当前疑点已否定' in other and report.count('### ')==1
    assert '历史解释，问题已有后续解释' in other
    assert all(i.rationale in report for i in state.interpretations)
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
    assert good['confirmed'] and good['reviewed_complete'] and not good['blockers']
    assert [r['confirmed'] for r in good['comparisons']]==[True,True,False]
    assert [r['outcome'] for r in good['comparisons']]==['violated','violated','holds']
    assert all(not results[n]['confirmed'] for n in (0,1,3))
    assert state.experiments[2].previous_id==state.experiments[1].id
    assert state.interpretations[2].counterevidence and state.interpretations[2].limitations
    assert all(v['elapsed']>=0 for v in good['events'] if v['event']=='result')
    challenged=state.model_copy(deep=True)
    challenged.investigations[0].gaps[0].experiment_id=state.experiments[2].id
    assert gap.question in assessment(challenged,e.root,state.experiments[2],next(c for c in state.checks if c.experiment_id==state.experiments[2].id))['blockers']
    from consensus_assurance.reporting.chinese import render_report
    report=render_report(state,e.root).read_text()
    assert '局部问题已回答' in report and '该执行的模型归属解释' in report and '固定比较的完整反例见证已确认' in report


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
