import json
import shutil
import pytest
from types import SimpleNamespace
from audit_support import engine_for, combined, experiment, opinion, stop
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.workflow.research import execution_cost, costs
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.reporting.report import render_report


def test_measurement_reused_across_current_views_and_readonly_validation(tmp_path, monkeypatch):
    import subprocess
    import sys
    from consensus_assurance.workflow import experiments
    from consensus_assurance.workflow.knowledge import target_receipts
    from consensus_assurance.workflow.research import current_view
    parsed, retained = [], {}
    extract = experiments.extract_events
    def counted(check):
        parsed.append(check.id)
        return extract(check)
    monkeypatch.setattr(experiments, 'extract_events', counted)
    def start(state):
        value, files = combined(state)
        value['gaps'] = [dict(investigation_id='@q', question='Which caller duty applies?')]
        return value, files
    def revise(state):
        fixed = e.state.experiments[0]
        check = next(c for c in e.state.checks if c.experiment_id)
        retained['before'] = assessment(e.state, e.root, fixed, check)
        retained['bytes'] = (e.root/'logs'/check.id/'observations.json').read_bytes()
        return opinion(state, experiment_id=None, executions={}, conclusion='conditional', defect_claim='unresolved',
            rationale='Source research narrows the duty; withdraw the earlier execution-based claim.',
            answers={state['investigations'][0]['gaps'][0]['id']:
                dict(resolved=True, explanation='The defining source supplies the caller duty.')})
    e, repo = engine_for(tmp_path, [start, opinion, revise, stop])
    state = e.start(repo)
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id)
    after = assessment(state, e.root, fixed, check)
    assert retained['before']['gap_ids'] and not after['gap_ids']
    assert retained['before']['interpretation_citations']['current'] and not after['interpretation_citations']['current']
    assert after['comparisons'] == retained['before']['comparisons']
    e.checkpoint('test_reuse')
    current_view(state, e.root)
    render_report(state, e.root)
    target_receipts(state, e.root, {check.id:[1]})
    sub, _ = opinion(state.model_dump(mode='json'))
    (e.root/'draft'/'reuse.json').write_text(json.dumps(sub))
    code = '''import json, sys
from pathlib import Path
from consensus_assurance.workflow import experiments
from consensus_assurance.workflow.audit import validate_submission
from consensus_assurance.workflow.history import load_analysis
from consensus_assurance.adapters.runners.python import PythonBackend
def unexpected(check):
    raise AssertionError('Independent validation reparsed finalized stdout')
experiments.extract_events = unexpected
root = Path(sys.argv[1])
print(json.dumps(validate_submission(load_analysis(root/'state.json'), root, 'reuse.json', PythonBackend())))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(e.root)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['valid']
    assert parsed == [check.id] and state.usage['experiments'] == 1
    assert (e.root/'logs'/check.id/'observations.json').read_bytes() == retained['bytes']


@pytest.mark.parametrize('change', ['missing_cache', 'invalid_json', 'invalid_shape', 'invalid_comparison', 'method',
    'fixed_version', 'raw_replaced', 'raw_missing', 'unfinished', 'timeout', 'cache_symlink', 'raw_symlink'])
def test_measurement_fallback_never_writes_or_reuses_stale_observations(tmp_path, monkeypatch, change):
    import os
    from consensus_assurance.workflow import experiments
    e, repo = engine_for(tmp_path, [combined, stop])
    state = e.start(repo)
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id)
    raw = e.root/'logs'/check.id/'stdout.log'
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
    before = {p:p.read_bytes() for p in (e.root/'logs').rglob('*') if p.is_file()}
    extract, calls = experiments.extract_events, []
    def counted(check):
        calls.append(check.id)
        return extract(check)
    monkeypatch.setattr(experiments, 'extract_events', counted)
    if change == 'raw_symlink':
        with pytest.raises(ValueError, match='symlink'):
            experiments.observed(fixed, check, e.root)
        assert not calls
    else:
        measured = experiments.observed(fixed, check, e.root)
        assert calls == [check.id]
        if change == 'raw_missing':
            assert not measured['events'] and measured['comparisons'][0]['outcome'] == 'unknown'
        else:
            assert measured['events'][1]['value'] == (9 if change == 'raw_replaced' else 0)
        if change == 'timeout':
            assert 'Execution did not complete: timeout' in assessment(state, e.root, fixed, check)['blockers']
    assert {p:p.read_bytes() for p in (e.root/'logs').rglob('*') if p.is_file()} == before


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


@pytest.mark.parametrize('outcome,conclusion',[
    ('unknown','violated'), ('unknown','holds'), ('holds','violated'), ('violated','holds')])
def test_report_distinguishes_unchecked_and_opposing_mechanical_results(tmp_path,outcome,conclusion):
    def start(state):
        value,files=combined(state)
        if outcome=='unknown':
            value['experiment'].update(requirement=None,comparisons=[])
        elif outcome=='holds':
            value['experiment']['comparisons'][0]['assertion']={'field':'value','value':0}
        return value,files
    e,repo=engine_for(tmp_path,[start,lambda s:opinion(s,conclusion=conclusion,defect_claim='asserted'),stop])
    state=e.start(repo)
    assert len(state.interpretations)==1
    check=next(c for c in state.checks if c.experiment_id)
    assert assessment(state,e.root,state.experiments[0],check)['outcome']==outcome
    before=state.model_dump(mode='json')
    text=render_report(state,e.root).read_text()
    assert state.model_dump(mode='json')==before
    current=text.split(f'### {state.investigations[0].question}',1)[1].split('Fixed experiment `',1)[0]
    assert f'Current model interpretation `{state.interpretations[0].id}` · `{conclusion}`' in current
    assert 'declared predicate' not in current
    assert ('Interpretation differs from the mechanical result' in text)==(outcome!='unknown')
    assert ('mechanical comparison is undetermined, not an opposing conclusion' in text)==(outcome=='unknown')
    assert ('No fixed comparisons declared' in text)==(outcome=='unknown')
    labels={'unknown':'comparison undetermined','holds':'declared predicate holds','violated':'declared predicate does not hold'}
    assert text.count(f'Mechanical comparison: {labels[outcome]} (`{outcome}`).')==(1 if outcome=='unknown' else 2)
    assert 'Current model defect claim: defect asserted' in text and 'confirmed' not in text
    assert 'Mechanical results evaluate declared predicates' in text
    assert 'not provider request count' in text and 'excludes Agent local exploratory checks' in text
    assert f'### {state.investigations[0].question}' in text
    assert state.interpretations[0].rationale in text
    view=json.loads((e.root/'research.json').read_text())
    assert view['investigations'][0]['latest_interpretation']['conclusion']==conclusion
    assert view['reselection']['questions'][0]['latest_interpretation']['conclusion']==conclusion


@pytest.mark.parametrize('claim,label',[
    ('refuted','defect claim refuted within the stated scope'), ('unresolved','unresolved'), (None,'no explicit defect claim submitted')])
def test_report_uses_actual_observations_and_preserves_opinion_history(tmp_path,claim,label):
    def start(state):
        value,files=combined(state)
        value['gaps']=[dict(investigation_id='@q',question=question) for question in
            ['Which caller contract applies?', 'Was the producer history legal?']]
        return value,files
    def initial(state):
        return opinion(state,defect_claim='asserted',rationale='Compare the actual return. The initial model alleges a defect',
            counterevidence=['The documented input bound may exclude this caller'],limitations=['Only one call was observed'],
            answers={state['investigations'][0]['gaps'][0]['id']:dict(explanation='Initial contract reading',resolved=True)})
    def correction(state):
        value,files=opinion(state,experiment_id=None,conclusion='conditional',rationale='Caller history remains unestablished',
            counterevidence=['The actual caller duty excludes the alleged general obligation'],
            limitations=['No broader consensus conclusion follows'],
            answers={state['investigations'][0]['gaps'][0]['id']:dict(resolved=claim!='refuted',
                explanation='The earlier answer did not establish the actual caller condition' if claim=='refuted' else 'The cited local contract controls this call')},
            defect_claim=claim)
        if claim is None:
            value['interpretations'][0].pop('executions')
        return value,files
    e,repo=engine_for(tmp_path,[start,initial,correction,stop]);s=e.start(repo)
    before=s.model_dump(mode='json')
    text=render_report(s,e.root).read_text()
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
    saved_history=json.loads((e.root/'state.json').read_text())['interpretations']
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
    citations=assessment(s,e.root,s.experiments[0],check)['interpretation_citations']
    assert citations['historical_count']==1
    assert [i['id'] for i in citations['current']]==([s.interpretations[-1].id] if claim is not None else [])
    assert ('Other current question interpretations explicitly citing this receipt' in execution)==(claim is not None)
    observation=f'logs/{check.id}/observations.json'
    assert '[code](state.json)' in current and '[doc](state.json)' in current
    assert (f'logs/{check.id}/check.json' in current)==(claim is not None)
    assert (observation in current)==(claim is not None)
    assert ('event indices [1]' in current)==(claim is not None)
    assert ('No execution receipt explicitly cited by this interpretation' in current)==(claim is None)
    assert json.loads((e.root/observation).read_text())['events'][1]['value']==0
    assert s.model_dump(mode='json')==before
    clone=tmp_path/'moved';shutil.copytree(e.root,clone)
    original=e.root.with_name('unavailable');e.root.rename(original)
    from consensus_assurance.adapters.storage.files import Store
    saved=Store(clone).load()
    assert saved.interpretations==s.interpretations
    moved=render_report(saved,clone).read_text()
    assert observation in moved and json.loads((clone/observation).read_text())['events'][1]['value']==0
    assert str(original) not in moved and str(e.root) not in moved
    import re
    for link in re.findall(r'\]\(([^)]+)\)',moved):assert (clone/link).is_file(),link


@pytest.mark.parametrize('superseded',[False,True])
def test_other_experiment_receipt_citations_do_not_change_direct_assessment(tmp_path,superseded):
    before={}
    def start(state):
        value,files=combined(state)
        value['gaps']=[dict(investigation_id='@q',question='Was the producer history legal?')]
        return value,files
    def downstream(state):
        fixed=e.state.experiments[0]
        check=next(c for c in e.state.checks if c.experiment_id==fixed.id)
        before.update(assessment(e.state,e.root,fixed,check))
        request,files=experiment('@other')
        return {'rationale':'Inspect a related local consequence',
            'investigations':[dict(ref='@other',question='What does this separate local call establish?',source_ids=['code'])],
            'experiment':request},files
    def cite(state):
        return opinion(state,executions={c['id']:[1] for c in state['checks'] if c.get('experiment_id')},
            joint_history='These are independent calls to the same stateless function, not one distributed history')
    def revise(state):
        return opinion(state,experiment_id=None,executions={},conclusion='explained',
            rationale='A narrower source-only account supersedes the measured account')
    e,repo=engine_for(tmp_path,[start,downstream,cite,*([revise] if superseded else []),stop])
    s=e.start(repo)
    fixed=s.experiments[0]
    check=next(c for c in s.checks if c.experiment_id==fixed.id)
    after=assessment(s,e.root,fixed,check)
    assert after['interpretation_id'] is None
    assert after['gap_ids'] and 'no interpretation directly attributed' in str(after['blockers'])
    assert {k:v for k,v in after.items() if k!='interpretation_citations'}=={
        k:v for k,v in before.items() if k!='interpretation_citations'}
    citations=after['interpretation_citations']
    assert citations['historical_count']==int(superseded)
    assert citations['current']==([] if superseded else [dict(id=s.interpretations[0].id,
        investigation_id=s.investigations[1].id,experiment_id=s.experiments[1].id,event_indices=[1])])
    text=render_report(s,e.root).read_text().split('### '+s.investigations[1].question)[0]
    assert ('Other current question interpretations explicitly citing this receipt' in text)==(not superseded)
    assert ('Historical interpretations explicitly citing this receipt: 1' in text)==superseded
    assert 'No current explicit defect assertion' in text
