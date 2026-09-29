from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.reporting.chinese import render_report, execution_summary


def test_audit_receipt_is_not_a_property_verdict(tmp_path):
    check = CheckRun(action='agent_turn', cwd=str(tmp_path), snapshot_id='fixture',
                     status=ExecutionStatus.COMPLETED, exit_code=0)
    assert '产物另经校验' in execution_summary(check)[1]
    assert '不属于性质证据' in execution_summary(check)[2]


def test_test_pass_and_model_failure_keep_different_scopes(tmp_path):
    args = dict(cwd=str(tmp_path), snapshot_id='fixture', status=ExecutionStatus.COMPLETED)
    test = CheckRun(action='capability_probe', outcome='tests_passed', exit_code=0, **args)
    model = CheckRun(action='model_check', outcome='counterexample', exit_code=12, **args)
    unknown = CheckRun(action='model_check', **args)
    assert execution_summary(test)[1] == '所执行测试通过'
    assert '不自动证明目标' in execution_summary(test)[2]
    assert execution_summary(model)[1] == '找到模型反例'
    assert execution_summary(unknown)[2] == '性质检查未完成或无法归属'


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
