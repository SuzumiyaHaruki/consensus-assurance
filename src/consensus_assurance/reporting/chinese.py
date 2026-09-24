from pathlib import Path
from consensus_assurance.core.types import ExecutionStatus

STATUS = {"completed": "正常完成", "error": "执行错误", "timeout": "超时", "tool_missing": "工具缺失",
    "login_required": "需要登录", "quota_exhausted": "额度不足", "cancelled": "取消", "running": "执行中", "not_scheduled": "未调度"}
OUTCOME = {"holds": "有限范围搜索完成，无反例", "counterexample": "找到模型反例", "tests_passed": "所执行测试通过",
    "tests_failed": "所执行测试失败", "deadlock": "模型死锁诊断，性质检查未完成", "unknown": "结果未确定", "not_applicable": "不适用"}

PROBES = {
    "agent_probe": "Codex 版本检查", "agent_capabilities": "Codex 参数检查",
    "java_probe": "Java 版本检查", "verifier_probe": "验证工具启动检查",
    "implementation_tool_probe": "目标工具链版本检查", "implementation_probe": "目标工具链版本检查",
}


def execution_summary(check):
    """Describe recorded outputs without promoting them to accepted analysis or proof."""
    complete = check.status == ExecutionStatus.COMPLETED and check.exit_code in (0, None)
    if check.action=='model_syntax':
        return '模型模块语法解析', ('SANY 解析完成；配置另由 TLC 检查' if check.status==ExecutionStatus.COMPLETED and check.outcome=='not_applicable' else '解析未完成，见原始诊断'), '不适用：未检查性质或实际轨迹'
    if check.action=='verifier_probe' and 'capability_available' in check.parameters:
        product='版本帮助已识别，工具可用' if check.parameters['capability_available'] else '工具能力检查未就绪'
        return PROBES[check.action],product+'；命令退出码 '+str(check.exit_code),'不适用：未检查性质'
    if check.action in PROBES:
        product = "命令完成；版本或能力详情见原始输出" if complete else "环境检查未成功完成"
        return PROBES[check.action], product, "不适用：未检查性质"
    if check.action == "native_agent":
        product = ("原生调查已返回；回执待修订：" + check.parameters['native_response_error']
            if check.parameters.get('native_response_error') else
            "原生回执已保存；产物另经校验" if complete else "原生调用未完成：" + check.reason)
        return "Codex 原生调查", product, "不属于性质证据"
    if check.action == "reachability":
        return "审计问题触发可达性", "见触发记录；辅助反例只表示触发可达", "不属于协议违反证据"
    if check.action == "trace_calibration":
        return "有限观测轨迹校准", "校准状态见下方模型记录", "轨迹兼容不等于性质成立或违反"
    if check.action=='direct_check':
        return '直接实现检查', '实际执行完成；性质判定见监视器记录' if complete else '执行失败或未完成，不能当作性质失败', '限于已观测前提和结果；不自动提升为目标结论'
    if check.action in {"capability_probe", "experiment", "replay", "direct_check"}:
        task = "现有测试与实验能力探测" if check.action == "capability_probe" else "实现实验 / 重放"
        product = OUTCOME[check.outcome] if check.outcome != "unknown" else "执行未产生可判定的测试结果"
        return task, product, "仅限实际测试覆盖；不自动证明目标或确认违反"
    product = OUTCOME[check.outcome]
    return check.action, product, ("性质检查未完成或无法归属" if check.outcome == "unknown" else "限于实际 checker 和模型范围；详见逐项结果")


def export_views(state, root):
    from consensus_assurance.adapters.storage.files import write_json
    from consensus_assurance.workflow.audit_spec import load, audit_progress
    write_json(root / "materials.json",[m.model_dump(mode="json") for m in state.materials])
    write_json(root / "graph.json", {"version": state.graph_version,
        **{name:[x.model_dump(mode="json") for x in getattr(state,name)] for name in ("claims","bindings","relations")}})
    spec=load(state)
    if spec:write_json(root / "audit-spec.json",spec)
    write_json(root / "audit-progress.json",audit_progress(state))
    write_json(root / "plan.json", {"units":[u.model_dump(mode="json") for u in state.units],"selections":state.selections})


def render_native_report(state, root):
    def link(value):
        if not value:return "无"
        path=Path(value)
        try:relative=path.relative_to(root)
        except ValueError:relative=path
        return f"[{path.name}]({relative})"
    lines=["# 共识义务驱动局部审计报告", "",
        f"运行标识：`{state.id}`；模式：{state.mode} 原生提交路径；分析入口：`{state.analysis_mode}`。",
        f"源码基准：`{state.snapshot.repo}`；提交 `{state.snapshot.commit or '无 Git 元数据'}`；快照 `{state.snapshot.id}`（{len(state.snapshot.files)} 个文件）。",
        f"框架版本：`{state.framework_revision}`；Codex 会话：`{state.native_session_id or '未建立'}`。",
        "", "## 调查与局部检查", ""]
    for check in state.checks:
        if not check.model_id and not check.direct_check_id:
            label, outcome, boundary = execution_summary(check)
            lines.append(f"- {label}：{outcome}；{boundary}；原始输出 {link(check.stdout)}。")
    if not state.question_candidates:lines.append("尚未受理候选；未受理草稿不是证据。")
    for candidate in state.question_candidates:
        question=candidate.question
        lines.append(f"- 候选 `{candidate.id}`：{candidate.status}；{question.question}；意义：{question.importance}。来源 {question.source_ids}；反证 {question.counterevidence}；未知 {question.unknowns}；父候选 {candidate.parent_candidate_id or '无'}；恢复条件 {candidate.resume_conditions}。")
    for unit in state.units:
        lines.append(f"- 单元 `{unit.id}`：{unit.status}；已记录检查 {unit.obligation_checks}；未完成义务 {unit.remaining_obligation_ids}；边界 {unit.coverage_limitations}。")
    for artifact in state.direct_checks:
        lines.append(f"- 检查 `{artifact.id}`：义务 `{artifact.claim_id}`；版本 {artifact.version}；前版 {artifact.previous_id or '无'}；计划 {link(artifact.plan_path)}；harness {link(artifact.harness_path)}。")
        for check in state.checks:
            if check.direct_check_id!=artifact.id:continue
            record=next((r for r in state.monitor_results if r.get('direct_check_id')==artifact.id and r.get('experiment_check_id')==check.id),None)
            lines.append(f"  正式执行 `{check.id}`：{check.status.value}/{check.outcome}；输出 {link(check.stdout)}；局部比较 {record.get('outcome','unknown') if record else '未评估'}；确认 {record.get('confirmed',False) if record else False}；归因阻塞 {record.get('blockers',[]) if record else ['未评估']}；边界 {record.get('boundaries',[]) if record else []}。")
    for model in state.models:
        lines.append(f"- 模型 `{model.id}`：{model.stage}；前版 {model.previous_id or '无'}；Behavior {link(str(Path(model.path).parent / 'Behavior.tla'))}；Properties {link(model.checker_path)}；范围 {model.scope.model_dump(mode='json')}。")
        for check in state.checks:
            if check.model_id==model.id:
                lines.append(f"  工具执行 `{check.id}`：{check.action}，{check.status.value}/{check.outcome}；原始输出 {link(check.stdout)}。模型检查与实现校准是不同证据。")
        for calibration in state.calibrations:
            if calibration.model_id == model.id:
                lines.append(f"  校准 `{calibration.id}`：{calibration.status}；实际实验 `{calibration.experiment_check_id}`；{calibration.reason}。")
        for result in state.monitor_results:
            if result.get('model_id') == model.id:
                lines.append(f"  实现归因：{result.get('level')}；确认 {result.get('confirmed',False)}；阻塞 {result.get('blockers',[])}；边界 {result.get('boundaries',[])}；实验 `{result.get('experiment_check_id')}`。")
    if not state.direct_checks and not state.models:lines.append("没有正式执行的检查；原生 Agent 的叙述或草稿不构成实现证据。")
    lines += ["", "## 修订与未决", ""]
    for revision in state.revisions:lines.append(f"- `{revision.id}` {revision.kind}：{revision.rationale}；旧结果保留，新输入需重执行与复核。")
    for issue in state.review_issues:
        lines.append(f"- 复核问题 `{issue.id}`：{issue.aspect}；{issue.explanation}；{'未决' if not issue.resolved_by else '由 '+issue.resolved_by+' 解决'}。")
    for diagnostic in sorted((root / "native-submissions").glob("*/diagnostics.json")):
        lines.append(f"- 未受理提交：原始字节 {link(str(diagnostic.parent / 'raw.json') if (diagnostic.parent / 'raw.json').is_file() else None)}；诊断 {link(str(diagnostic))}。它没有改变已受理产物。")
    lines.append("停止原因："+state.stop_reason)
    lines += ["- "+gap for gap in dict.fromkeys(state.gaps)]
    lines += ["", "## 实际调用与边界", "",
        f"CLI 调用 {state.usage.get('agent_calls',0)} 次；正式实验 {state.usage.get('experiments',0)} 次；耗时 {state.elapsed_seconds:.2f} 秒。原生工具事件数只计已记录事件，不等于 CLI 调用次数。",
        "读取与上下文管理由 Codex 原生会话负责；实际源码读取字符数未知，不据此推算 token 或费用。"]
    for turn in state.native_turns:
        check=next((c for c in state.checks if c.id==turn['check_id']),None)
        lines.append(f"- 原生调用 `{turn['check_id']}`：会话 `{turn['session_id']}`；工具事件 {turn['tool_events']}；模型 `{check.parameters.get('agent_model','未知') if check else '未知'}`；effort `{check.parameters.get('agent_reasoning_effort','未知') if check else '未知'}`；usage {turn['usage'] if turn['usage'] is not None else '未知'}；日志 {link(check.stdout) if check else '无'}。")
    lines.append(f"可信方法资源：{state.native_method_paths}；原始提交、错误及执行身份保存在运行目录。正式测试结果只说明固定制品在干净副本内的实际输出，不自动证明更广泛共识结论。")
    path=root/"report.md"
    path.write_text("\n".join(lines))
    return path


def render_report(state, root):
    root = Path(root)
    export_views(state, root)
    return render_native_report(state, root)
