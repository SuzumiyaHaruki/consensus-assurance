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
    from consensus_assurance.workflow.research import view
    import json
    index=root/'research.json'
    context=json.loads(index.read_text()) if index.is_file() else {}
    context.update(view(state))
    context['rejected_drafts']=[str(p) for p in sorted((root/'native-submissions').glob('*/diagnostics.json'))]
    write_json(index,context)


def render_native_report(state, root):
    from consensus_assurance.workflow.research import view
    research = view(state)
    def link(value):
        if not value:return '无'
        path = Path(value)
        return f'[{path.name}]({path.relative_to(root) if path.is_relative_to(root) else path})'
    lines = ['# 共识实现持续审计报告', '',
        f'运行 `{state.id}`；模式 {state.mode}/{state.analysis_mode}；框架 `{state.framework_revision}`。',
        f'源码 `{state.snapshot.repo}`；提交 `{state.snapshot.commit}`；快照 `{state.snapshot.id}`。',
        f'地图 {link(state.audit_spec_path)}；版本 {state.audit_spec_version}；本次子方向 {research["activity_focus"]}。',
        '保留 Activity → Behavior → Fact → Candidate → Obligation → 执行／复核 → 理解回流。A1/A2 主导选题，五类支撑按依赖展开；局部 checked 不代表整体正确。',
        '', '## 调查与局部检查', '']
    if research['understanding_status']=='unregistered':lines.append('理解尚未登记；未受理草稿不是证据。')
    for candidate in research['candidates']:
        q = candidate['question']
        lines.append(f'- 候选 `{candidate["id"]}`：{candidate["status"]}；{q["question"]}；意义 {q["importance"]}。')
        lines.append(f'  核心与支撑 {q["activity_classes"]}；直接 Behavior {q["behavior_ids"]}；因果支撑 {q["supporting_behavior_ids"]}；Fact {q["fact_ids"]}/{q["obligation_relation_kind"]}；依据 v{q["audit_spec_version"]}。')
        lines.append(f'  来源 {q["source_ids"]}；路径 {q["event_paths"]}；反证 {q["counterevidence"]}；未知 {q["unknowns"]}；父候选 {candidate["parent_candidate_id"]}；恢复条件 {candidate["resume_conditions"]}。')
    for claim in research['claims']:
        lines.append(f'- 要求 `{claim["id"]}`：{claim["description"]}；适用依据 {claim["grounding"]}；未决 {claim["pending"]}。')
    for unit in research['units']:
        lines.append(f'- Unit `{unit["id"]}`：{unit["status"]}；Candidate `{unit["candidate_id"]}`；范围 {unit["scope"]}；未完成义务 {unit["remaining_obligation_ids"]}；原因 {unit["coverage_limitations"]}。')
    for artifact in research['artifacts']:
        lines.append(f'- 制品 `{artifact["id"]}` v{artifact["version"]}；前版 {artifact["previous_id"]}；固定输入 {link(artifact.get("plan_path") or artifact.get("bundle_path"))}。')
    for record in research['assessments']:
        lines.append(f'- 执行 `{record["experiment_check_id"]}`：归因确认 {record["confirmed"]}；范围检查完整 {record.get("bounded_complete",False)}；归因阻塞 {record["blockers"]}；边界／未测后果 {record["boundaries"]}。')
        for result in record['properties']:
            lines.append(f'  checker `{result["checker_id"]}`：{result["outcome"]}；有效见证 {result.get("valid_witness_indices",[])}；覆盖完整 {result.get("comparison_complete",False)}；范围外 {result.get("outside_applicability_indices",[])}；具体缺口 {result.get("limitations",[])}。')
    lines += ['', '## 范围内结论与研究交接', '']
    categories={'consensus_safety':'核心安全性','bounded_liveness':'有明确前提的有界活性','implementation_semantics':'相关实现语义'}
    dispositions={'confirmed_in_scope':'范围内确认','bounded_no_violation':'有限检查未见违反','investigation_lead':'待调查线索'}
    for result in research['conclusions']:
        lines.append(f'- `{result["claim_id"]}`：{categories[result["concern"]]}／{dispositions[result["disposition"]]}；{result["description"]}；范围 {result["scope"]}；未建立后果 {result["unestablished_consequences"]}。')
    lines.append(f'按逻辑义务归并当前结果 {len(research["conclusions"])} 项；制品修订不是独立发现，分类不表示自动晋升。')
    for handoff in research['handoffs']:
        lines.append(f'- 交接 `{handoff["operation_id"]}`：{handoff["action"]}/{handoff.get("scope","candidate")}；{handoff["rationale"]}；反馈 {handoff.get("feedback",{})}；下一步／恢复 {handoff.get("resume_conditions",[])}。')
    lines += ['', '## 修订与未决', '', f'当前待办：{research["pending_work"]}。',
        f'研究前沿：{research["frontier"]}。地图条目和已检查 Unit 数不是责任覆盖率。',
        f'最近决定与结果反馈：{research["latest_decision"]}。', '停止原因：'+state.stop_reason,
        f'停止范围与依据：{research["stop"]}。']
    for issue in state.review_issues:
        lines.append(f'- 复核问题 `{issue.id}`：{issue.explanation}；来源 {issue.source_ids}；解决依据 {issue.resolved_by or "未决"}。')
    for diagnostic in sorted((root/'native-submissions').glob('*/diagnostics.json')):
        lines.append(f'- 未受理提交：原稿 {link(diagnostic.parent/"raw.json")}；诊断 {link(diagnostic)}。')
    lines += ['', '## 实际调用与边界', '',
        f'CLI 调用 {state.usage.get("agent_calls",0)} 次；目标执行 {state.usage.get("experiments",0)} 次；耗时 {state.elapsed_seconds:.2f} 秒。',
        f'调用与执行成本：{research["costs"]}。退稿调用包含有效调查，不能全部视为浪费。',
        f'剩余能力与数量瓶颈：{research["capacity"]}。',
        '工具事件不等于调用次数；原始 usage 及来源保留在状态文件，累计／单 turn 口径未核实时不相加、不估算费用。']
    for check in state.checks:
        label, result, boundary = execution_summary(check)
        lines.append(f'- `{check.id}` {label}：{result}；{boundary}；输出 {link(check.stdout)}；期限 {check.parameters.get("timeout_limit","未记录")}／{check.parameters.get("timeout_seconds","未记录")} 秒。')
    lines += ['- '+gap for gap in dict.fromkeys(state.gaps)]
    lines.append(f'实际方法资源：{state.native_method_paths}；完整来源、历史、单项复核、修订及原始 usage 见 {link(root/"state.json")}。模型轨迹和脚本化产品不构成实现确认或原生自主发现。')
    path = root/'report.md'
    path.write_text('\n'.join(lines))
    return path


def render_report(state, root):
    root = Path(root)
    export_views(state, root)
    return render_native_report(state, root)
