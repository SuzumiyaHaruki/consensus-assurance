from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.reporting.chinese import render_report, execution_summary


def test_native_receipt_is_not_a_property_verdict(tmp_path):
    check = CheckRun(action='native_agent', cwd=str(tmp_path), snapshot_id='fixture',
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
