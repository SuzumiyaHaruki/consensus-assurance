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
        assert all('current_applicability' not in c for c in index['candidates'])
        pending_unit=next(u for u in index['units'] if u['id']==unit.id)
        assert pending_unit['progress'][0]['record_status']=='no_fixed_check'
        assert paused.id in index['frontier']['paused_candidate_ids']
        pending=next(c for c in index['candidates'] if c['id']==paused.id)
        assert pending['resume_conditions']==paused.resume_conditions and not pending['open_issue_ids']
        dispute=next(i for i in index['review_issues'] if i['id']=='current-dispute')
        assert (dispute['target_id'],dispute['target_version'],dispute['aspect'])==(current.id,1,'applicability')
        assert index['capacity']['remaining']['agent_calls']==e.config.budget.agent_calls-e.state.usage['agent_calls']
        assert index['claims'][0]['scope'] and index['claims'][0]['grounding']
        return {'inspected':True}
    e.agent.investigate=inspect
    e.action('agent_turn','agent_calls',lambda:e.agent.investigate(e.runner,request,e.root/'draft',state.snapshot.id,10),{'sample':1})
    before=e.state.model_dump(mode='json')
    rendered=render_report(e.state,e.root).read_text()
    assert e.state.model_dump(mode='json')==before
    assert 'Historical construction detail.' in (e.root/'state.json').read_text()
    assert 'Current identity is disputed' in rendered
    assert '义务已受理，尚无固定检查记录' in rendered
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
    # A new fixed version cannot borrow the old execution or its completed review.
    from consensus_assurance.workflow.research import view
    revised=state.model_copy(deep=True)
    artifact=revised.direct_checks[0].model_copy(update={'id':'new-artifact','version':2,'previous_id':revised.direct_checks[0].id})
    revised.direct_checks.append(artifact)
    progress=lambda:next(u for u in view(revised)['units'] if u['id']==artifact.unit_id)['progress'][0]['record_status']
    assert progress()=='no_execution'
    execution=next(c for c in revised.checks if c.direct_check_id==artifact.previous_id).model_copy(
        update={'id':'new-execution','direct_check_id':artifact.id})
    revised.checks.append(execution)
    assert progress()=='no_assessment'
    execution.status=ExecutionStatus.ERROR
    assert progress()=='execution_incomplete'


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
    def encoded_check(**options):
        def step(state):
            sub,files=check_step(**options)(state)
            plan=json.loads(files['plan.json'])
            plan['observable_properties'][0]['assertion']=dict(field='state.encoded',reference='start.state.encoded')
            files['plan.json']=json.dumps(plan)
            # A lossless string encoding of the existing boolean oracle, with a shared long prefix.
            files['check.py']=files['check.py'].replace("'operation':'one'","'operation':{'id':'identity-'+'z'*500,'parts':list(range(300))}")
            files['check.py']=files['check.py'].replace("'legal':legal(3,3)",
                "'legal':legal(3,3),'encoded':json.dumps({'padding':'x'*4000,'bounded':True})")
            files['check.py']=files['check.py'].replace("'in_range':0 <= value <= 3",
                "'in_range':0 <= value <= 3,'encoded':json.dumps({'padding':'x'*4000,'bounded':0 <= value <= 3}),'driver_input':'y'*4000+str(value)")
            return sub,files
        return step
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
        return (dict(action='research',rationale='Retain the conditional output and missing responsibility',feedback=dict(
            ref_ids=[c['id'] for c in state['checks'] if c['action']=='exploration']+['code','surface:external repeat policy'],answered='Under the chosen repeat policy the actual returns were 3 and 4.',
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
    def contract_question(state):
        sub,_=first(state);sub.pop('map_path')
        sub.update(action='continue',obligation=None,bindings=[])
        sub['question'].update(question='Does the caller permit finite callback delay?',unknowns=['The timing contract is unacquired'])
        return sub,{}
    def paused_contract(state):
        sub,_=contract_question(state)
        sub.update(action='pause',candidate_id=state['question_candidates'][-1]['id'],
            resume_conditions=['Obtain the external timing contract'])
        return sub,{}
    def unconstructed(state):
        sub,_=first(state);sub.pop('map_path')
        sub=json.loads(json.dumps(sub).replace('"bounded"','"pending-bound"').replace('"binding"','"pending-binding"'))
        sub['question']['question']='Does the second public entry preserve the local bound?'
        return sub,{}
    steps=[initial,encoded_check(broken=True),encoded_check(revise=True),review,second,explained,
        independent_issue,explore,explore,retain,explore,fact_feedback,contract_question,paused_contract,unconstructed,stop]
    e,repo=engine_for(tmp_path,steps);e.agent.mock=False;e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value <= limit else 0\n')
    e.config.budget.experiments=7
    e.config.budget.audit_units=3
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    assert [r['disposition'] for r in view(state)['conclusions']]==['confirmed_in_scope','investigation_lead']
    assert state.usage['experiments']==6 and len(state.claims)==3
    index=json.loads((e.root/'research.json').read_text())
    assert [len(entry['feedback']) for entry in index['explorations']]==[1,1,0]
    assert index['explorations'][0]['operation_id']!=index['explorations'][1]['operation_id']
    old=state.direct_checks[0];old_check=next(c for c in state.checks if c.direct_check_id==old.id)
    current=state.direct_checks[1];exploration=next(c for c in state.checks if c.action=='exploration')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot execute')))
    monkeypatch.setattr('consensus_assurance.workflow.direct_checks.compute_assessment',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot assess')))
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
    assert '**已确认违反**' in text and '**待调查线索**' in text and '源码解释' in text
    table=text.split('## 主要结果')[1].split('### 1.')[0]
    rows=[line for line in table.splitlines() if line.startswith('|')]
    for claim in ('bounded','interior','pending-bound'):
        assert sum(f'[{claim}](' in line for line in rows)==1
    pending=next(line for line in rows if '[interior](' in line)
    assert '待调查线索' in pending and '有限检查未见违反' in pending and '对应性意见：尚未记录' in pending
    assert '边界返回责任' in text and '本次完整观察返回 4' in text
    assert 'Candidate 5 项；当前 Unit 3 项、义务 3 项、固定检查制品 2 项' in text
    assert text.count('保存的语义未知：The timing contract is unacquired')==1
    assert 'Obtain the external timing contract' in text and '义务已受理，尚无固定检查记录' in text
    assert '实际取消' in text and '配置值不表示触发了超时' in text
    assert not re.search(r'^- \[.*：\s*$',text,re.M) and not re.search(r'恢复条件：\s*$',text,re.M)
    assert '| event | returned |' in text
    assert 'external repeat policy' in text and 'Acquire the caller repeat contract' in text
    assert old_check.id in text and current.plan_path.split('/direct-checks/')[1] in text
    assert exploration.id in text and text.count('该问题保留的失败执行')==1
    timeline=text.split('## 研究过程与认识增长')[1].split('## 当前未决事项')[0]
    assert '受理 review：边界返回责任' in timeline and 'Retain the conditional output and missing responsibility' in timeline
    assert 'Under the chosen repeat policy the actual returns were 3 and 4.' not in timeline
    assert text.count('实际观察已保存，尚待解释')==1 and 'external caller may have another boundary' in text
    assert text.count('后续受理解释（执行 ')==1 and '该交接当时的剩余问题（非当前欠账）' in text
    unresolved=text.split('## 当前未决事项')[1]
    assert 'Acquire the caller repeat contract' not in unresolved and '地图 v1' in unresolved
    assert 'x'*200 not in text and 'z'*200 not in text and '首尾预览' in text
    assert '| state.encoded |' in text and '| start.state.encoded |' in text and '| operation | dict，' in text
    assert '| state.driver_input | str，' in text and 'y'*200 not in text
    visible=re.sub(r'\]\([^)]*\)',']',text)
    assert max(len(v.strip()) for line in visible.splitlines() if line.startswith('|') for v in line.split('|')) < 300
    assert '"bounded": true}' in text and '"bounded": false}' in text
    check=next(c for c in state.checks if c.direct_check_id==current.id)
    assert f'{check.id} / event[0] / state.encoded' in text and f'{check.id} / event[1] / state.encoded' in text
    assert 'distributed consequences' in text and '没有正式性质判定' in execution_summary(exploration)[2]
    assert '_ca_stream' not in text and '_ca_observation' not in text and '<details>' not in text
    assert state.semantic_reviews[0].items[0].rationale not in text
    links=re.findall(r'\]\(([^)]+)\)',text)
    assert '#event=' not in text and '并非物理行号或自动跳转' in text
    for p in links:
        if p.startswith('#'):assert f'id="{p[1:]}"' in text
        else:assert not Path(unquote(p)).is_absolute() and (moved/unquote(p)).is_file()
    # Distinct obligations keep their identities even under one recorded owner.
    grouped=state.model_copy(deep=True)
    previous=grouped.units[1].candidate_id
    grouped.units[1].candidate_id=grouped.units[0].candidate_id
    grouped.question_candidates=[c for c in grouped.question_candidates if c.id!=previous]
    grouped.question_candidates[0].resume_conditions=['Obtain the independent caller lifetime contract']
    combined=render_report(grouped,moved).read_text()
    table=combined.split('## 主要结果')[1].split('### 1.')[0]
    assert table.count('[bounded](')==1 and table.count('[interior](')==1
    assert 'Obtain the independent caller lifetime contract' in combined
    assert grouped.monitor_results==state.monitor_results
    legacy=state.model_copy(deep=True)
    for key in ('correspondence','bounded_complete','reviewed_complete'):legacy.monitor_results[1].pop(key)
    legacy_text=render_report(legacy,moved).read_text()
    assert '对应性意见：信息不足' in legacy_text and '独立场景完整处置：未记录' in legacy_text
    (moved/Path(check.stdout).relative_to(e.root)).unlink()
    missing=render_report(state,moved).read_text()
    assert '部分归档事件缺失' in missing and '**已确认违反**' in missing
    assert '| state.encoded |' not in missing
    # A missing archived version must not silently resolve against the still-existing original run.
    (moved/Path(current.plan_path).relative_to(e.root)).unlink()
    (moved/index['explorations'][1]['submission']).unlink()
    text=render_report(state,moved).read_text()
    assert '条件与检查器（归档字节缺失）' in text and str(e.root) not in text
    assert '问题原稿字节缺失' in text


def test_timeout_report_uses_recorded_limit_and_preserves_transport_diagnostic(tmp_path):
    import json
    from types import SimpleNamespace
    from consensus_assurance.reporting.chinese import Archive, interruption_lines
    stdout=tmp_path/'stdout.log'
    stdout.write_text(json.dumps({'type':'error','message':'stream disconnected before completion'})+'\n')
    check=CheckRun(action='agent_turn',cwd=str(tmp_path),snapshot_id='fixture',stdout=str(stdout),status=ExecutionStatus.TIMEOUT)
    archive=Archive(SimpleNamespace(audit_spec_path=None,checks=[check]),tmp_path)
    for limit,label in [('total_seconds','总运行预算到达'),('agent_turn_timeout','单轮上限'),
        ('action_timeout','目标动作达到执行上限'),(None,'超时上限依据不足')]:
        check.parameters={'timeout_limit':limit} if limit else {}
        saved=check.model_dump(mode='json');raw=stdout.read_bytes()
        text='\n'.join(interruption_lines(check,archive))
        assert label in text and 'stream disconnected before completion' in text
        assert '单轮超时，具体原因未知' not in text
        assert check.model_dump(mode='json')==saved and stdout.read_bytes()==raw
    message='This content was flagged for possible cybersecurity risk.'
    stdout.write_text('\n'.join(json.dumps(event) for event in [dict(type='error',message=message),
        {'type':'turn.failed','error':{'message':message}}])+'\n')
    check.status=ExecutionStatus.ERROR;check.parameters={'timeout_limit':'agent_turn_timeout','timeout_seconds':900}
    raw=stdout.read_bytes();saved=check.model_dump(mode='json')
    text='\n'.join(interruption_lines(check,archive))
    assert text.count(message)==1 and 'status=`error`' in text and 'timeout_seconds=`900`' in text
    assert '达到单轮上限' not in text and '未记录；未完成草稿不受理' in text and '不据此授权重试' in text
    assert stdout.read_bytes()==raw and check.model_dump(mode='json')==saved
