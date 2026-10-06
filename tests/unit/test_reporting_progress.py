from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.reporting.chinese import render_report, execution_summary


def test_report_distinguishes_configured_provider_from_unrecorded_history(tmp_path):
    from audit_support import engine_for
    from consensus_assurance.cli import load_config
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True)
    e.state.config['agent_backend']='codex';e.state.config['agent_model']='deepseek-flash'
    provider=load_config('configs/targets/deepseek.example.yaml').codex_provider.model_dump(mode='json')
    for value,label in [(provider,'deepseek'),(None,'Codex 默认'),('absent','未记录')]:
        if value=='absent':e.state.config.pop('codex_provider')
        else:e.state.config['codex_provider']=value
        before=e.state.model_dump(mode='json')
        text=render_report(e.state,e.root).read_text()
        assert f'配置 provider `{label}`' in text and '请求模型 `deepseek-flash`' in text
        assert '服务端模型／版本：未记录' in text
        assert e.state.model_dump(mode='json')==before


def test_target_action_costs_keep_process_time_missing_data_and_identity(tmp_path):
    from types import SimpleNamespace
    from consensus_assurance.workflow.research import costs,execution_cost
    from consensus_assurance.reporting.chinese import execution_location,Archive
    cargo=CheckRun(id='cargo',action='direct_check',cwd=str(tmp_path),snapshot_id='fixture',
        started_at='2026-10-04T00:00:20+00:00',ended_at='2026-10-04T00:00:24.300000+00:00',parameters={'action_seconds':28.71})
    old=cargo.model_copy(update={'id':'old-go','action':'exploration','parameters':{}})
    child=cargo.model_copy(update={'id':'copy','action':'cargo_seed_copy','parameters':{},'started_at':'2026-10-04T00:00:00+00:00'})
    state=SimpleNamespace(checks=[cargo,old,child,cargo.model_copy(deep=True)],selections=[],usage={},elapsed_seconds=80,audit_spec_path=None)
    saved=[c.model_dump(mode='json') for c in state.checks]
    cost=costs(state)
    assert cost['formal_executions']==2 and cost['formal_execution_seconds']==8.6
    assert cost['target_action_cost']=={'known_seconds':28.71,'unrecorded_check_ids':['old-go'],'process_unrecorded_check_ids':[]}
    assert cost['elapsed_seconds']==80 and [c.model_dump(mode='json') for c in state.checks]==saved
    archive=Archive(state,tmp_path)
    assert '目标动作总耗时 28.71 秒；执行进程耗时 4.30 秒' in execution_location(cargo,archive)
    assert '目标动作总耗时未完整记录；执行进程耗时 4.30 秒' in execution_location(old,archive)
    for invalid in (None,-1,float('inf'),float('nan'),True,'28.71'):
        record=cargo.model_copy(update={'parameters':{'action_seconds':invalid},'started_at':'invalid'})
        assert execution_cost(record)=={'process_seconds':None,'action_seconds':None}
        state.checks=[record]
        assert costs(state)['formal_execution_seconds'] is None and costs(state)['target_action_cost']['known_seconds'] is None


def test_probe_and_execution_keep_different_scopes(tmp_path):
    args = dict(cwd=str(tmp_path), snapshot_id='fixture', status=ExecutionStatus.COMPLETED)
    receipt=execution_summary(CheckRun(action='agent_turn',exit_code=0,**args))
    assert '产物另经校验' in receipt[1] and '不属于性质证据' in receipt[2]
    test = CheckRun(action='capability_probe', outcome='tests_passed', exit_code=0, **args)
    failed = CheckRun(action='direct_check', exit_code=1, **args)
    assert '未检查性质' in execution_summary(test)[2]
    explore=CheckRun(action='exploration',outcome='tests_passed',exit_code=0,**args)
    assert '没有正式性质判定' in execution_summary(explore)[2]
    permission=CheckRun(action='codex_permission_probe',exit_code=0,**args)
    assert '未检查性质' in execution_summary(permission)[2]
    assert execution_summary(failed)[1] == '执行失败或未完成'
    assert execution_summary(failed)[2] == '进程退出码不等于性质判定'
    for changes,expected in [({},'探索执行正常结束'),({'exit_code':None},'退出信息缺失'),
        ({'exit_code':1},'非零退出'),({'outcome':'not_applicable'},'没有匹配测试或全部跳过'),
        ({'status':ExecutionStatus.ERROR,'parameters':{'failure_class':'build_or_setup','test_started':False}},'未进入测试'),
        ({'exit_code':1,'parameters':{'failure_class':'test_failure','test_started':True}},'已进入测试，执行失败'),
        ({'exit_code':2,'parameters':{'failure_class':'panic_unattributed','test_started':True}},'panic 尚未归因'),
        ({'status':ExecutionStatus.TIMEOUT},'status=timeout'),({'status':ExecutionStatus.ERROR},'status=error')]:
        record=explore.model_copy(update=changes);saved=record.model_dump(mode='json')
        summary=execution_summary(record)
        assert expected in summary[1] and '条件观察完成' not in summary[1]
        assert '前提是否达到' in summary[2] and record.model_dump(mode='json')==saved


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
    snapshots={}
    def review_second(state):
        sub,files=review_step()(state)
        issue=next(i for i in state['review_issues'] if i['target_id']==state['direct_checks'][-2]['id'])
        sub['resolutions']=[dict(issue_id=issue['id'],source_ids=['code','doc'],
            evidence_ids=[state['direct_checks'][-1]['id']],rationale='The revised driver checks admission before invoking the unchanged local comparison',
            residual_issue_ids=[],scope_limitations=[])]
        return sub,files
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
            plan['harness']['semantic_changes'].append('A synchronous driver replaces external caller scheduling')
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
    def challenge_second(state):
        snapshots['unreviewed']=e.state.model_copy(deep=True)
        sub,files=review_step('revision_needed')(state)
        sub['rationale']='Review the caller admission condition before revision'
        sub['review_items'][0].update(challenged_components=['driver'],
            rationale='The caller admission condition is observed but not enforced before invocation',
            counterevidence=['The driver must check admission before making the call'])
        return sub,files
    def repair_second(state):
        sub,files=second(state);sub.pop('candidate')
        sub.update(action='revise_check',unit_id=state['units'][1]['id'],previous_check_id=state['direct_checks'][-1]['id'],
            repair_issue_ids=[state['review_issues'][-1]['id']],rationale='Enforce the sourced caller admission without changing the oracle')
        plan=json.loads(files['plan.json'])
        plan['harness']['legality']['derivation']='The driver checks the documented legal input before invoking the same return comparison'
        files['plan.json']=json.dumps(plan)
        files['check.py']=files['check.py'].replace('value=step(2,3)','assert legal(2,3)\nvalue=step(2,3)')
        return sub,files
    def explained(state):
        snapshots['reviewed']=e.state.model_copy(deep=True)
        sub,_=first(state);sub.pop('map_path');sub.update(action='explained',obligation=None,bindings=[])
        sub['question'].update(question='What happens outside the selected local capacity?',
            disposition='explained_by_existing_mechanism',counterevidence=['The other branch returns zero'])
        return sub,{}
    def explore(state):
        setup="ready.append('initialized')\n" if any(c['action']=='exploration' for c in state['checks']) else ''
        return dict(action='explore',question=f'For candidate {state["question_candidates"][-1]["id"]}, under a caller-selected repeat policy, what values are produced?',
            harness_path='explore.py',rationale='Observe behavior before attributing the repeat policy'),{
                'explore.py':"from target import step\nfrom pathlib import Path\nready=[]\n"+setup+
                "print('conditional',bool(ready),step(2,3),step(3,3))\nPath(__file__).write_text('# Rewritten during execution\\n')\n"}
    def retain(answer,positions):
        def step(state):
            executions=[c['id'] for c in state['checks'] if c['action']=='exploration']
            return dict(action='research',rationale='Retain the conditional output and missing responsibility',feedback=dict(
                ref_ids=[executions[i] for i in positions]+['code','surface:external repeat policy'],answered=answer,
                remaining=['Acquire the caller repeat contract'],understanding='updated',rationale='No obligation is inferred from unequal returns')),{}
        return step
    first_answer='The first execution exited normally, but initialization did not occur; no prerequisite was reached.'
    repaired_answer='Only the second execution initialized the input and reached the comparison; this remains an exploration.'
    joint_answer='The first execution missed initialization; the second reached it and returned 3 and 4. The external caller contract remains open.'
    def independent_issue(state):
        candidate=state['question_candidates'][-1]['id']
        return dict(action='review',artifact_id=candidate,rationale='Retain an independent source applicability dispute',
            review_items=[dict(target_id=candidate,aspect='applicability',status='disputed',source_ids=['code'],
                rationale='The external caller may have another boundary',counterevidence=['External caller responsibility remains unacquired'])]),{}
    def fact_feedback(state):
        return dict(action='research',rationale='Retain a separate Fact explanation',feedback=dict(ref_ids=['result','call'],
            answered='The result Fact describes local delivery only',remaining=[],understanding='unchanged',
            rationale='Shared Fact and Behavior references do not associate this feedback with an execution')),{}
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
    steps=[initial,encoded_check(broken=True),encoded_check(revise=True),review,second,challenge_second,repair_second,review_second,explained,
        independent_issue,contract_question,explore,retain(first_answer,[0]),explore,retain(repaired_answer,[1]),retain(joint_answer,[0,1]),
        explore,fact_feedback,paused_contract,unconstructed,stop]
    e,repo=engine_for(tmp_path,steps);e.agent.mock=False;e.config.execution_isolation='bwrap'
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1 if value <= limit else 0\n')
    e.config.budget.experiments=8
    e.config.budget.semantic_reviews=5
    e.config.budget.audit_units=3
    state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.stop_reason
    assert [r['disposition'] for r in view(state)['conclusions']]==['confirmed_in_scope','bounded_no_violation']
    assert state.usage['experiments']==7 and len(state.claims)==3
    index=json.loads((e.root/'research.json').read_text())
    assert [len(entry['feedback']) for entry in index['explorations']]==[2,2,0]
    assert index['explorations'][0]['operation_id']!=index['explorations'][1]['operation_id']
    old=state.direct_checks[0];old_check=next(c for c in state.checks if c.direct_check_id==old.id)
    current=state.direct_checks[1];exploration=next(c for c in state.checks if c.action=='exploration')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot execute')))
    monkeypatch.setattr('consensus_assurance.workflow.direct_checks.compute_assessment',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot assess')))
    monkeypatch.setitem(EXECUTION_BACKENDS,'python',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Report cannot assemble')))
    def valid_links(text):
        files=set()
        for ref in re.findall(r'\]\(([^)]+)\)',text):
            if ref.startswith('#'):assert f'id="{ref[1:]}"' in text
            else:
                path=Path(unquote(ref));assert not path.is_absolute() and (moved/path).is_file(),ref
                files.add(path.as_posix())
        return files
    saved=state.model_dump(mode='json')
    live=render_report(state,e.root).read_text()
    assert list(e.root.glob('experiments/*/workspace'))
    moved=tmp_path/'moved';shutil.copytree(e.root,moved)
    for directory in [moved/'.execution',*moved.glob('experiments/*/workspace'),*moved.rglob('__pycache__')]:
        if directory.exists():shutil.rmtree(directory)
    # Publication must preserve links in the already-generated report without rerendering it.
    assert (moved/'report.md').read_text()==live
    files=valid_links(live)
    assert not any('/workspace/' in path or '/.execution/' in path for path in files)
    manifests={Path(p).parent.name:Path(p).relative_to(e.root) for p in exploration.artifacts if Path(p).name=='manifest.json'}
    input_manifest=manifests['workspace-delta'];outcome_manifest=manifests['workspace-outcome']
    assert f'[执行输入文件清单]({input_manifest})' in live and f'[执行后文件清单]({outcome_manifest})' in live
    filename=exploration.parameters['harness_filename']
    submitted=moved/index['explorations'][0]['inputs'][0]
    assert (moved/input_manifest.parent/'files'/filename).read_bytes()==submitted.read_bytes()
    assert (moved/outcome_manifest.parent/'files'/filename).read_text()=='# Rewritten during execution\n'
    assert submitted.read_bytes()!=(moved/outcome_manifest.parent/'files'/filename).read_bytes()
    for manifest,phase in [(input_manifest,'input'),(outcome_manifest,'outcome')]:
        data=json.loads((moved/manifest).read_text())
        assert data['phase']==phase and filename in data['changed_files']
    open_path=Path.open
    def archive_only(path,*args,**kwargs):
        assert not path.is_relative_to(e.root), 'Moved reports must not read the original host paths'
        return open_path(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',archive_only)
    before={p.relative_to(moved):p.read_bytes() for p in moved.rglob('*') if p.is_file()}
    text=render_report(state,moved).read_text()
    assert text==live and valid_links(text)==files
    assert state.model_dump(mode='json')==saved and all((moved/p).read_bytes()==v for p,v in before.items())
    assert '**已确认违反**' in text and '**有限检查未见违反**' in text and '源码解释' in text
    table=text.split('## 主要结果')[1].split('### 1.')[0]
    rows=[line for line in table.splitlines() if line.startswith('|')]
    for claim in ('bounded','interior','pending-bound'):
        assert sum(f'[{claim}](' in line for line in rows)==1
    pending=next(line for line in rows if '[interior](' in line)
    assert '有限检查未见违反' in pending
    complete=next(line for line in rows if '[bounded](' in line)
    assert '已确认违反' in complete
    assert text.count('本次完整观察返回 4，上限为 3。')==1 and 'A synchronous driver replaces external caller scheduling' in text
    assert 'Candidate 5 项；当前 Unit 3 项、义务 3 项、固定检查制品 2 项' in text
    assert text.count('保存的语义未知：The timing contract is unacquired')==1
    assert 'Obtain the external timing contract' in text and '义务已受理，尚无固定检查记录' in text
    assert '实际取消' in text and '配置值不表示触发了超时' in text
    handoff=next(s for s in state.selections if s.get('feedback',{}).get('answered')==joint_answer)
    assert 'Acquire the caller repeat contract' in (moved/f'submissions/{handoff["operation_id"]}/accepted.json').read_text()
    explorations=[c for c in state.checks if c.action=='exploration']
    assert 'conditional False 3 4' in (moved/Path(explorations[0].stdout).relative_to(e.root)).read_text()
    assert 'conditional True 3 4' in (moved/Path(explorations[1].stdout).relative_to(e.root)).read_text()
    assert '条件观察完成' not in text and '执行工具失败／未完成 1 次（不统计研究前提未达）' in text
    for n,(answer,positions) in enumerate([(first_answer,[0]),(joint_answer,[0,1]),(repaired_answer,[1])],1):
        related=next(s for s in state.selections if s.get('feedback',{}).get('answered')==answer)
        anchor=f'exploration-feedback-{related["operation_id"]}'
        paragraph=text.split(f'<a id="{anchor}"></a>')[1].split('\n\n')[0]
        assert text.count(answer)==1 and answer in paragraph
        for i,c in enumerate(explorations):
            assert (f'](#exploration-{c.id})' in paragraph)==(i in positions)
        assert ('共同后续说明' in paragraph)==(len(positions)>1)
        for i,entry in enumerate(index['explorations']):
            section=text.split(f'<a id="exploration-{explorations[i].id}"></a>')[1].split('\n\n')[0]
            assert (f'](#{anchor})' in section)==(i in positions)
    assert old_check.id in text and '修订前 v1' in text and current.plan_path.split('/direct-checks/')[1] in text
    assert exploration.id in text
    timeline=text.split('## 研究过程与认识增长')[1].split('## 当前未决事项')[0]
    assert '受理 review：边界返回责任' in timeline and 'Retain the conditional output and missing responsibility' in timeline
    disputed=state.direct_checks[2];disputed_check=next(c for c in state.checks if c.direct_check_id==disputed.id)
    history=next(line for line in timeline.splitlines() if f'logs/{disputed_check.id}/check.json' in line)
    assert disputed_check.exit_code==0 and '目标进程执行成功' in history and '保存的机械比较：有限检查未见违反' in history
    assert '已确认违反' not in history and '失败' not in history
    assert timeline.count(f'logs/{disputed_check.id}/check.json')==1
    assert timeline.index(disputed_check.id)<timeline.index('caller admission condition')<timeline.index('Enforce the sourced caller admission')
    assert any(i.target_id==disputed.id and i.resolved_by for i in state.review_issues)
    visible_timeline=re.sub(r'\]\([^)]*\)',']',timeline)
    assert re.search(r'\d+\.\d+ 分钟',timeline) and not re.search(r'\b[0-9a-f]{32}\b',visible_timeline)
    assert all(answer not in timeline for answer in (first_answer,repaired_answer,joint_answer))
    unresolved=text.split('## 当前未决事项')[1]
    assert '1 次探索尚无精确引用该执行的后续受理交接' in unresolved and 'external caller may have another boundary' in text
    assert '已选检查／复核待办：' in unresolved and '正在调查的问题：' not in unresolved
    assert '显式关联探索（不计为另一个发现）' in unresolved
    assert 'Acquire the caller repeat contract' not in unresolved and '地图 v1' in unresolved
    assert 'x'*200 not in text and 'z'*200 not in text and '首尾预览' in text
    assert '| state.encoded |' in text and '| start.state.encoded |' in text and '| operation | dict，' in text
    assert '| state.driver_input | str，' in text and 'y'*200 not in text
    visible=re.sub(r'\]\([^)]*\)',']',text)
    assert max(len(v.strip()) for line in visible.splitlines() if line.startswith('|') for v in line.split('|')) < 300
    assert '"bounded": true}' in text and '"bounded": false}' in text
    check=next(c for c in state.checks if c.direct_check_id==current.id)
    assert f'{check.id} / event[0] / state.encoded' in text and f'{check.id} / event[1] / state.encoded' in text
    assert '完整要求、假设与排除范围' in text and 'distributed consequences' in (moved/'state.json').read_text()
    assert '确认项数按义务命题计，不等于独立根因数' in text
    for name,snapshot in snapshots.items():
        preserved=snapshot.model_dump(mode='json')
        preview=render_report(snapshot,moved).read_text()
        row=next(line for line in preview.splitlines() if line.startswith('| 2.'))
        if name=='unreviewed':assert '待调查线索' in row and '对应性意见：尚未记录' in row
        else:assert '有限检查未见违反' in row
        assert snapshot.model_dump(mode='json')==preserved
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
    # A question plus an exploration does not imply a selected formal check or review debt.
    candidate_only=state.model_copy(deep=True)
    candidate_only.units=[];candidate_only.claims=[];candidate_only.direct_checks=[];candidate_only.monitor_results=[]
    candidate_only.semantic_reviews=[];candidate_only.review_issues=[];candidate_only.evidence=[];candidate_only.findings=[]
    candidate=next(c for c in candidate_only.question_candidates if c.resume_conditions)
    candidate.status='active';candidate.resume_conditions=[];candidate.obligation_id=None
    candidate_only.question_candidates=[candidate];candidate_only.checks=[explorations[0]]
    operation=index['explorations'][0]['operation_id']
    candidate_only.selections=[s for s in candidate_only.selections if s['operation_id']==operation]
    preserved=candidate_only.model_dump(mode='json')
    question_text=render_report(candidate_only,moved).read_text()
    assert 'Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项' in question_text
    assert '已选检查／复核待办：' not in question_text and '已选检查／争议仍有待办' not in question_text
    assert '正在调查的问题：' in question_text and '1 次探索尚无精确引用该执行的后续受理交接' in question_text
    assert f'](#candidate-{candidate.id})' in question_text and f'](#exploration-{explorations[0].id})' in question_text
    assert candidate_only.model_dump(mode='json')==preserved
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
    (moved/input_manifest).unlink()
    text=render_report(state,moved).read_text()
    assert '条件与检查器（归档字节缺失）' in text and str(e.root) not in text
    assert '问题原稿字节缺失' in text
    assert '执行输入文件清单（归档字节缺失）' in text and input_manifest.as_posix() not in valid_links(text)
    assert outcome_manifest.as_posix() in valid_links(text)
    # Later confirmation cannot fill missing historical assessment or review bytes.
    (moved/Path(disputed.plan_path).relative_to(e.root).parent/(disputed_check.id+'-assessment.json')).unlink()
    old_review=next(r for r in state.semantic_reviews if disputed.id in r.target_versions)
    (moved/f'submissions/{old_review.check_id}/accepted.json').unlink()
    history=render_report(state,moved).read_text()
    row=next(line for line in history.splitlines() if f'logs/{disputed_check.id}/check.json' in line)
    assert '原保存评估（归档字节缺失）' in row and '保存的机械比较' not in row
    assert '完整交接（归档字节缺失）' in history and '**已确认违反**' in history
    valid_links(history)
    # Exact links survive absent accepted bytes; neither state text nor an unaccepted draft fills the gap.
    missing_handoff=next(s for s in state.selections if s.get('feedback',{}).get('answered')==repaired_answer)
    (moved/f'submissions/{missing_handoff["operation_id"]}/accepted.json').unlink()
    (moved/'draft/unaccepted.json').write_text(json.dumps({'feedback':missing_handoff['feedback']}))
    missing=render_report(state,moved).read_text()
    assert repaired_answer not in missing and first_answer in missing and joint_answer in missing
    assert '完整交接；精确引用不表示已解决或已正式化（归档字节缺失）' in missing
    valid_links(missing)
    unexecuted=state.model_copy(deep=True)
    unexecuted.checks=[c for c in unexecuted.checks if c.id!=explorations[-1].id]
    assert '已受理问题，尚无保存的执行记录' in render_report(unexecuted,moved).read_text()
    assert state.model_dump(mode='json')==saved


def test_current_answer_preserves_versions_and_separate_issue_navigation(tmp_path):
    from audit_support import engine_for,first,check_step,review_step,stop
    def old_review(state):
        sub,files=review_step()(state);sub['review_items'][0]['report_answer']='旧版本已完成的回答。'
        return sub,files
    def revised(state):
        sub,files=check_step(revise=True)(state);files['check.py']+='\nprint("new fixed input version")\n'
        return sub,files
    def current_review(state):
        sub,files=review_step('revision_needed')(state)
        item=sub['review_items'][0];item.update(report_title='当前局部返回',report_answer='本次调用返回 0；驱动前提仍需复核。',
            rationale='Driver ordering needs examination. '+'Retain the complete recorded rationale. '*20)
        sub['review_items'].append(dict(item,aspect='applicability',status='disputed',report_title=None,report_answer=None,
            challenged_components=[],rationale='Independent caller responsibility remains open. '+'Retain the other issue independently. '*20))
        return sub,files
    e,repo=engine_for(tmp_path,[first,check_step(),old_review,revised,current_review,stop]);state=e.start(repo)
    assert not list((e.root/'submissions').glob('*/diagnostics.json'))
    saved=state.model_dump(mode='json');text=render_report(state,e.root).read_text()
    table=text.split('## 主要结果')[1].split('### 1.')[0]
    assert '本次调用返回 0；驱动前提仍需复核。' in table and 'revision_needed' in table and '待调查线索' in table
    assert '旧版本已完成的回答。' not in table
    assert len(state.review_issues)==2
    unresolved=text.split('## 当前未决事项')[1]
    for issue in state.review_issues:
        assert text.count(f'<a id="issue-{issue.id}"></a>')==1
        assert f'](#issue-{issue.id})' in table and f'](#issue-{issue.id})' in unresolved
        assert issue.explanation not in text
    assert state.model_dump(mode='json')==saved and len(state.direct_checks)==2
    raw={p:p.read_bytes() for folder in ('logs','direct-checks') for p in (e.root/folder).rglob('*') if p.is_file()}
    # Display-only variants retain the original review, assessment and log bytes.
    for variant in ('unreviewed','preparation','observation','confirmed_partial','unknown'):
        sample=state.model_copy(deep=True);sample.semantic_reviews=[];sample.review_issues=[]
        record=next(r for r in sample.monitor_results if r['direct_check_id']==sample.direct_checks[-1].id)
        record.update(review_ids=[],open_issue_ids=[],correspondence=None,reviewed_complete=False,
            blockers=['Direct oracle correspondence is unreviewed'])
        check=next(c for c in sample.checks if c.id==record['experiment_check_id'])
        if variant in {'unreviewed','confirmed_partial'}:
            confirmed=variant=='confirmed_partial'
            record.update(outcome='violated',confirmed=confirmed,bounded_complete=not confirmed,
                correspondence='no_issue_found' if confirmed else None)
            record['properties'][0].update(outcome='violated',witness_complete=True,confirmed=confirmed)
        else:
            record.update(confirmed=False,bounded_complete=False,properties=[],outcome='unknown')
            if variant=='preparation':
                check.status=ExecutionStatus.TIMEOUT
                check.parameters.update(execution_backend={'name':'cargo'},preparation_stage='cargo_seed_build',
                    test_started=False,build_finished=None,build_activity=True)
                record['prerequisites']={'status':'not_reached','reason':'No admission event reached'}
            elif variant=='observation':
                check.parameters['test_started']=True
                record['prerequisites']={'status':'not_reached','reason':'Operation identity does not match'}
            else:record.pop('prerequisites')
        preserved=sample.model_dump(mode='json');preview=render_report(sample,e.root).read_text()
        row=next(line for line in preview.splitlines() if line.startswith('| 1.'))
        expected={'unreviewed':'机械比较：观察到违反','preparation':'准备阶段 cargo_seed_build：超时；测试未启动，尚无目标比较',
            'observation':'Operation identity does not match','confirmed_partial':'完整反例已确认；另有独立场景覆盖缺口',
            'unknown':'当前检查尚未完整处置'}[variant]
        assert expected in row and 'Direct oracle correspondence is unreviewed' not in preview
        if variant=='unreviewed':assert '待当前版本复核' in row and '已确认违反' not in row
        if variant=='observation':assert 'status=completed' in row and '测试未启动' not in row
        if variant=='confirmed_partial':assert '已确认违反' in row
        assert sample.model_dump(mode='json')==preserved and all(p.read_bytes()==v for p,v in raw.items())
    assert state.model_dump(mode='json')==saved


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
