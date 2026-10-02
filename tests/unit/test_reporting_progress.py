from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.reporting.chinese import render_report, execution_summary


def test_audit_receipt_is_not_a_property_verdict(tmp_path):
    check = CheckRun(action='agent_turn', cwd=str(tmp_path), snapshot_id='fixture',
                     status=ExecutionStatus.COMPLETED, exit_code=0)
    assert '产物另经校验' in execution_summary(check)[1]
    assert '不属于性质证据' in execution_summary(check)[2]


def test_probe_and_execution_keep_different_scopes(tmp_path):
    args = dict(cwd=str(tmp_path), snapshot_id='fixture', status=ExecutionStatus.COMPLETED)
    test = CheckRun(action='capability_probe', outcome='tests_passed', exit_code=0, **args)
    failed = CheckRun(action='direct_check', exit_code=1, **args)
    assert '未检查性质' in execution_summary(test)[2]
    explore=CheckRun(action='exploration',outcome='tests_passed',exit_code=0,**args)
    assert '没有正式性质判定' in execution_summary(explore)[2]
    permission=CheckRun(action='codex_permission_probe',exit_code=0,**args)
    assert '未检查性质' in execution_summary(permission)[2]
    assert execution_summary(failed)[1] == '执行失败或未完成'
    assert execution_summary(failed)[2] == '进程退出码不等于性质判定'


def test_current_projection_rebuilds_at_deadline_without_old_budget_or_paths(tmp_path):
    import json
    from audit_support import engine_for
    from consensus_assurance.workflow.research import current_view, view
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True)
    (e.root/'research.json').write_text(json.dumps({'remaining_seconds':98,'remaining_agent_calls':25,
        'obsolete_pending':'not executed','source_path':'wrong'}))
    e.budget.previous=e.config.budget.total_seconds
    e.state.stop_reason='Total runtime budget exhausted'
    e.checkpoint('controlled_deadline')
    compact=current_view(e.state,e.root,e.implementation)
    full=view(e.state)
    report=render_report(e.state,e.root).read_text()
    saved=json.loads((e.root/'research.json').read_text())
    for current in (compact,saved):
        assert current['capacity']['remaining_seconds']==0
        assert not {'remaining_seconds','remaining_agent_calls','obsolete_pending'} & current.keys()
        assert current['source_path']==str(e.root/'agent-source')
        assert current['draft_path']==str(e.root/'draft') and current['method_path']
        assert current['validation']['command'] and current['implementation']['harness_kind']=='python'
        assert current['conclusions']==full['conclusions'] and current['stop']==full['stop']
    assert '剩余 0.00 秒' in report


def test_agent_reads_work_index_after_action_checkpoint_report_and_resume(tmp_path):
    import json
    from audit_support import engine_for, first, check_step, review_step, stop
    from consensus_assurance.core.types import ReviewIssue
    from consensus_assurance.workflow.audit import prompt
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),stop])
    e.config.budget.agent_calls=6
    e.start(repo)
    state=e.state
    old=state.question_candidates[0]
    old.status='paused'
    old.question.trigger_rationale='Historical construction detail. '*500
    paused=old.model_copy(deep=True);paused.id='paused-external';paused.obligation_id=None
    paused.resume_conditions=['Provide the external caller contract']
    state.question_candidates.append(paused)
    current=old.model_copy(deep=True)
    current.id='current-question';current.status='escalated'
    current.question.counterevidence=['The current delivery may belong to another operation']
    current.question.trigger_rationale='Inspect the current operation identity'
    state.question_candidates.append(current)
    unit=state.units[0].model_copy(deep=True)
    unit.id='current-unit';unit.candidate_id=current.id;unit.status='partial'
    state.units.append(unit);state.active_unit_id=unit.id
    state.review_issues.append(ReviewIssue(id='current-dispute',review_id='review',target_id=current.id,
        target_version=1,aspect='applicability',source_ids=['code'],explanation='Current identity is disputed',
        disposition='investigation',reason='Read the actual receiver'))
    e.checkpoint('controlled_history')
    request=prompt(e,'method')
    seen=[]
    def inspect(runner, request, directory, snapshot_id, timeout, session_id=None):
        index=json.loads((runner.root/'research.json').read_text())
        seen.append(index)
        assert 'Historical construction detail.' not in json.dumps(index)
        previous=next(c for c in index['candidates'] if c['id']==old.id)
        ref=previous['record']
        saved=json.loads((runner.root/ref['path']).read_text())
        record=next(x for x in saved[ref['collection']] if all(x[k]==v for k,v in ref['match'].items()))
        assert record['question']['trigger_rationale']==old.question.trigger_rationale
        selected=next(c for c in index['candidates'] if c['id']==current.id)
        assert selected['question']['counterevidence']==current.question.counterevidence
        assert old.id not in index['frontier']['comparison_refs']
        assert paused.id in index['frontier']['paused_candidate_ids']
        assert next(c for c in index['candidates'] if c['id']==paused.id)['resume_conditions']==paused.resume_conditions
        assert any(i['id']=='current-dispute' for i in index['review_issues'])
        assert index['capacity']['remaining']['agent_calls']==e.config.budget.agent_calls-e.state.usage['agent_calls']
        assert index['claims'][0]['scope'] and index['claims'][0]['grounding']
        return {'inspected':True}
    e.agent.investigate=inspect
    e.action('agent_turn','agent_calls',lambda:e.agent.investigate(e.runner,request,e.root/'draft',state.snapshot.id,10),{'sample':1})
    rendered=render_report(e.state,e.root).read_text()
    assert 'Historical construction detail.' in (e.root/'state.json').read_text()
    assert 'Current identity is disputed' in rendered
    exported=json.loads((e.root/'research.json').read_text())
    for key in ('candidates','handoffs','review_issues','conclusions'):assert exported[key]==seen[-1][key]
    e.advance('audit')
    e.resume()
    e.action('agent_turn','agent_calls',lambda:e.agent.investigate(e.runner,request,e.root/'draft',state.snapshot.id,10),{'sample':2})
    assert len(seen)==2

    state=e.state
    old_claim=state.claims[0].model_dump(mode='json')
    state.graph_history.append({'kind':'claims','id':old_claim['id'],'version':old_claim['version'],
        'record':old_claim,'reason':'Explicit historical version control'})
    state.claims[0].version+=1
    state.claims[0].description='A different current requirement'
    e.checkpoint('controlled_new_version')
    index=json.loads((e.root/'research.json').read_text())
    ref=next(r for r in index['artifacts'][0]['basis'] if r['match'].get('kind')=='claims')
    history=json.loads((e.root/ref['path']).read_text())[ref['collection']]
    original=next(h for h in history if all(h[k]==v for k,v in ref['match'].items()))[ref['field']]
    assert original==old_claim and original['description']!=state.claims[0].description


def test_mixed_report_reads_fixed_results_and_moves_without_side_effects(tmp_path,monkeypatch):
    import json,re,shutil
    from pathlib import Path
    from urllib.parse import unquote
    from audit_support import engine_for,first,products,check_step,review_step,stop
    from consensus_assurance.workflow.research import view
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.registry import EXECUTION_BACKENDS
    def initial(state):
        sub,files=first(state);spec=json.loads(files['map.json'])
        spec['surfaces']=[dict(entry_point='external repeat policy',disposition='UNCLASSIFIED_PROTOCOL_RESPONSIBILITY',
            source_ids=['code'],reason='Caller repetition responsibility is unspecified')]
        files['map.json']=json.dumps(spec)
        return sub,files
    def review(state):
        sub,files=review_step()(state)
        sub['review_items'][0].update(report_title='边界返回责任',report_answer='本次完整观察返回 4，上限为 3。')
        return sub,files
    def second(state):
        candidate,files=first(state)
        candidate.pop('map_path');files={}
        candidate=json.loads(json.dumps(candidate).replace('"bounded"','"interior"').replace('"binding"','"interior-binding"'))
        candidate['question']['question']='Does an interior input respect the same local capacity?'
        _,plan,harness=products()
        plan=json.loads(json.dumps(plan).replace('"bounded"','"interior"').replace('"binding"','"interior-binding"'))
        return dict(action='check',candidate=candidate,plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},
            rationale='Independently check another legal input'),{'plan.json':json.dumps(plan),
            'check.py':harness.replace('step(3,3)','step(2,3)'), 'helper.py':'def legal(v,n): return 0 <= v <= n\n'}
    def explained(state):
        sub,_=first(state);sub.pop('map_path');sub.update(action='explained',obligation=None,bindings=[])
        sub['question'].update(question='What happens outside the selected local capacity?',
            disposition='explained_by_existing_mechanism',counterevidence=['The other branch returns zero'])
        return sub,{}
    def explore(state):
        return dict(action='explore',question='Under a caller-selected repeat policy, what values are produced?',
            harness_path='explore.py',rationale='Observe behavior before attributing the repeat policy'),{'explore.py':"from target import step\nprint('conditional',step(2,3),step(3,3))\n"}
    def retain(state):
        check=next(c for c in state['checks'] if c['action']=='exploration')
        return (dict(action='research',rationale='Retain the conditional output and missing responsibility',feedback=dict(
            ref_ids=[check['id'],'code','surface:external repeat policy'],answered='Under the chosen repeat policy the actual returns were 3 and 4.',
            remaining=['Acquire the caller repeat contract'],understanding='updated',rationale='No obligation is inferred from unequal returns')),
            {})
    def independent_issue(state):
        candidate=state['question_candidates'][-1]['id']
        return dict(action='review',artifact_id=candidate,rationale='Retain an independent source applicability dispute',
            review_items=[dict(target_id=candidate,aspect='applicability',status='disputed',source_ids=['code'],
                rationale='The external caller may have another boundary',counterevidence=['External caller responsibility remains unacquired'])]),{}
    def fact_feedback(state):
        return dict(action='research',rationale='Retain a separate Fact explanation',feedback=dict(ref_ids=['result'],
            answered='The result Fact describes local delivery only',remaining=[],understanding='unchanged',
            rationale='A shared Fact does not associate this feedback with an execution')),{}
    steps=[initial,check_step(broken=True),check_step(revise=True),review,second,review_step(),explained,
        independent_issue,explore,retain,explore,fact_feedback,stop]
    e,repo=engine_for(tmp_path,steps);e.agent.mock=False;e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value <= limit else 0\n')
    e.config.budget.experiments=5
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    assert [r['disposition'] for r in view(state)['conclusions']]==['confirmed_in_scope','bounded_no_violation']
    assert state.usage['experiments']==5 and len(state.claims)==2
    index=json.loads((e.root/'research.json').read_text())
    assert [len(entry['feedback']) for entry in index['explorations']]==[1,0]
    assert index['explorations'][0]['operation_id']!=index['explorations'][1]['operation_id']
    old=state.direct_checks[0];old_check=next(c for c in state.checks if c.direct_check_id==old.id)
    current=state.direct_checks[1];exploration=next(c for c in state.checks if c.action=='exploration')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot execute')))
    monkeypatch.setitem(EXECUTION_BACKENDS,'python',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot assemble')))
    moved=tmp_path/'moved';shutil.copytree(e.root,moved)
    read_text=Path.read_text
    def archive_only(path,*args,**kwargs):
        assert not path.is_relative_to(e.root), 'Moved reports must not read the original host paths'
        return read_text(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',archive_only)
    before={p.relative_to(moved):p.read_bytes() for p in moved.rglob('*') if p.is_file()}
    saved=state.model_dump(mode='json');text=render_report(state,moved).read_text()
    assert state.model_dump(mode='json')==saved and all((moved/p).read_bytes()==v for p,v in before.items())
    assert '**已确认违反**' in text and '**有限检查未见违反**' in text and '源码解释' in text
    assert '边界返回责任' in text and '本次完整观察返回 4' in text
    assert '| event | returned |' in text
    assert 'external repeat policy' in text and 'Acquire the caller repeat contract' in text
    assert old_check.id in text and current.plan_path.split('/direct-checks/')[1] in text
    assert exploration.id in text and text.count('该问题保留的失败执行')==1
    assert text.count('尚无受理的执行后解释')==1 and 'external caller may have another boundary' in text
    assert 'distributed consequences' in text and '没有正式性质判定' in execution_summary(exploration)[2]
    assert '_ca_stream' not in text and '_ca_observation' not in text and '<details>' not in text
    assert state.semantic_reviews[0].items[0].rationale not in text
    links=re.findall(r'\]\(([^)]+)\)',text)
    assert all(not Path(unquote(p)).is_absolute() and (moved/unquote(p)).is_file() for p in links)
    # A missing archived version must not silently resolve against the still-existing original run.
    (moved/Path(current.plan_path).relative_to(e.root)).unlink()
    (moved/index['explorations'][1]['submission']).unlink()
    text=render_report(state,moved).read_text()
    assert '条件与检查器（归档字节缺失）' in text and str(e.root) not in text
    assert '问题原稿字节缺失' in text
