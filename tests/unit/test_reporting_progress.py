from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.reporting.chinese import render_report, execution_summary


def test_environment_and_agent_are_not_property_unknown(tmp_path, prepared):
    _, state, _, _ = prepared
    state.checks = [
        CheckRun(action='java_probe', cwd=str(tmp_path), snapshot_id=state.snapshot.id,
                 status=ExecutionStatus.COMPLETED, exit_code=0),
        CheckRun(action='agent', cwd=str(tmp_path), snapshot_id=state.snapshot.id,
                 status=ExecutionStatus.COMPLETED, exit_code=0),
        CheckRun(action='agent', cwd=str(tmp_path), snapshot_id=state.snapshot.id,
                 status=ExecutionStatus.TIMEOUT, reason='Action timeout exceeded'),
    ]
    state.stop_reason='Authentication unavailable'
    before = state.model_dump(mode='json')
    text = render_report(state, tmp_path).read_text()
    assert 'Authentication unavailable' in text and state.snapshot.id in text and 'MOCK' in text
    assert '结果未确定' not in text
    assert '不适用：未检查性质' in text
    assert '结构化回复已返回；不代表关系图或模型已被接受' in text
    assert '尚未完成发现结果的工作流接受' in text
    assert '未取得可用回复（超时）' in text
    assert state.model_dump(mode='json') == before


def test_graph_rejection_has_separate_artifact_status(tmp_path):
    (tmp_path / 'graph-validation-error.txt').write_text('Binding b: invalid symbol')
    check = CheckRun(action='agent', cwd=str(tmp_path), snapshot_id='fixture',
                     status=ExecutionStatus.COMPLETED, exit_code=0)
    assert '后续工作流校验失败' in execution_summary(check)[1]
    assert check.status == ExecutionStatus.COMPLETED


def test_test_pass_and_model_failure_keep_different_scopes(tmp_path):
    args = dict(cwd=str(tmp_path), snapshot_id='fixture', status=ExecutionStatus.COMPLETED)
    test = CheckRun(action='capability_probe', outcome='tests_passed', exit_code=0, **args)
    model = CheckRun(action='model_check', outcome='counterexample', exit_code=12, **args)
    unknown = CheckRun(action='model_check', **args)
    assert execution_summary(test)[1] == '所执行测试通过'
    assert '不自动证明目标' in execution_summary(test)[2]
    assert execution_summary(model)[1] == '找到模型反例'
    assert execution_summary(unknown)[2] == '性质检查未完成或无法归属'
