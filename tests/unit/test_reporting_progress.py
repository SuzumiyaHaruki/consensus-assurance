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
    from consensus_assurance.workflow.research import current_view
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True)
    (e.root/'research.json').write_text(json.dumps({'remaining_seconds':98,'remaining_agent_calls':25,
        'obsolete_pending':'not executed','source_path':'wrong'}))
    e.budget.previous=e.config.budget.total_seconds
    e.state.stop_reason='Total runtime budget exhausted'
    e.checkpoint('controlled_deadline')
    compact=current_view(e.state,e.root,e.implementation,compact=True)
    full=current_view(e.state,e.root,e.implementation)
    report=render_report(e.state,e.root).read_text()
    saved=json.loads((e.root/'research.json').read_text())
    for current in (compact,full,saved):
        assert current['capacity']['remaining_seconds']==0
        assert not {'remaining_seconds','remaining_agent_calls','obsolete_pending'} & current.keys()
        assert current['source_path']==str(e.root/'agent-source')
        assert current['draft_path']==str(e.root/'draft') and current['method_path']
        assert current['validation']['command'] and current['implementation']['harness_kind']=='python'
        assert current['conclusions']==full['conclusions'] and current['stop']==full['stop']
    assert '剩余 0.00 秒' in report
