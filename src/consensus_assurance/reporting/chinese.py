from pathlib import Path
from datetime import datetime
from consensus_assurance.core.types import ExecutionStatus

STATUS = {"completed": "正常完成", "error": "执行错误", "timeout": "超时", "tool_missing": "工具缺失",
    "login_required": "需要登录", "quota_exhausted": "额度不足", "cancelled": "取消", "running": "执行中", "not_scheduled": "未调度"}
OUTCOME = {"holds": "有限范围搜索完成，无反例", "counterexample": "找到模型反例", "tests_passed": "所执行测试通过",
    "tests_failed": "所执行测试失败", "unknown": "结果未确定", "not_applicable": "不适用"}
CALIBRATION = {"compatible": "有限观测轨迹可解释", "incompatible": "当前模型无法解释观测", "inconclusive": "不确定", "stale": "需重验", "not_scheduled": "未执行"}
LEVEL = {"model": "模型层", "implementation_test": "实现实验层（不自动确认违反）", "framework_test": "mock 框架测试层", "trace_calibration": "有限轨迹校准层"}


def render_report(state, root):
    root = Path(root)
    def link(path):
        if not path:
            return "无"
        p = Path(path)
        try:
            target = p.relative_to(root)
        except ValueError:
            target = p
        return f"[{p.name}]({target})"
    lines = ["# 共识义务驱动局部审计报告", "", f"运行标识：`{state.id}`；模式：**{'真实工具运行' if state.mode == 'real' else 'MOCK 框架测试，不能提供目标正确性证据'}**。",
        "", "目标解释审计意义，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。",
        "", f"分析入口：`{'regression' if state.mode == 'mock' else state.analysis_mode}`。regression 表示预设开发回归，不能计为自主发现验收。",
        "", "## 分析输入与探索范围", "", f"仓库：`{state.snapshot.repo}`", f"提交：`{state.snapshot.commit or '无 Git 元数据'}`；分支：`{state.snapshot.branch or 'detached / unavailable'}`；脏工作区：`{state.snapshot.dirty}`。",
        f"快照：`{state.snapshot.id}`，纳入 {len(state.snapshot.files)} 个文件；读取 {len(state.materials)} 个材料片段，未读取 {len(state.unexplored)} 个文件。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。",
        "候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。", "", "## 目标、义务与选择依据", ""]
    for claim in state.claims:
        lines += [f"- `{claim.id}`（{claim.kind}，{claim.assessment.value}）：{claim.description}",
                  f"  来源：{', '.join(claim.source_ids)}；待确认：{'；'.join(claim.pending) or '见范围假设'}。"]
    if not state.claims:
        lines.append("尚未完成自主目标发现；未补入预置目标。")
    for selection in state.selections:
        lines += ["", f"审计单元 `{selection['unit_id']}` 引用关系 {selection['relation_ids']} 和代码绑定 {selection['binding_ids']}。",
                  f"选择依据（原文）：{selection['rationale']}"]
    for unit in state.units:
        lines += ["", f"单元 `{unit.id}`：{unit.status}；{unit.rationale}", f"范围：{unit.scope.description}；能否表达目标后果：{unit.goal_observable}。"]
    lines += ["", "## 实验能力与执行", "", "| 能力 | 状态 | 执行依据 |", "| --- | --- | --- |"]
    for cap in state.capabilities:
        lines.append(f"| {cap.name} | {cap.status} | {cap.check_id or '无执行确认'}：{cap.description} |")
    lines += ["", "默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。", "",
        "| 执行 | 状态 | 语义结果 | 原始输出 |", "| --- | --- | --- | --- |"]
    for check in state.checks:
        outcome = OUTCOME[check.outcome]
        if check.action == "trace_calibration":
            outcome = "轨迹可达性搜索（反例是匹配见证），见下方校准状态"
        lines.append(f"| {check.action} `{check.id[:8]}` | {STATUS[check.status.value]} | {outcome} | {link(check.stdout)} / {link(check.stderr)} |")
        if check.reason:
            reason = check.reason.replace("|", "\\|").replace("\n", " ")
            lines[-1] = lines[-1][:-1] + f" 限制：{reason} |"
    lines += ["", "## 模型、校准与证据范围", ""]
    if not state.models:
        lines.append("尚未生成并执行局部模型；没有模型层检查结论。")
    for model in state.models:
        cal = [c for c in state.calibrations if c.model_id == model.id]
        lines += [f"### 模型 v{model.version} `{model.id}`", "", f"来源：`{model.origin.value}`；行为/检查器：{link(model.path)}；配置：{link(model.config_path)}；观测：{link(model.mapping_path)}；实验：{link(model.harness_path)}。",
                  f"范围：{model.scope.description}", f"前提：{'；'.join(model.scope.assumptions) or '见模型约束来源'}", f"不覆盖：{'；'.join(model.scope.excluded) or '未声明，需进一步审阅'}"]
        if not cal:
            lines.append("**未完成代码轨迹校准；模型结果仅为探索性结果。**")
        for c in cal:
            lines += [f"校准：**{CALIBRATION[c.status]}**；{c.reason}。轨迹：{link(c.trace_path)}。",
                "有限真实轨迹可解释不等于模型与实现完全等价；不能据此确认更大范围实现正确。"]
    for e in state.evidence:
        lines += ["", f"证据 `{e.id}`：{LEVEL[e.level]}，`{e.assessment.value}`；执行 `{e.check_id}`；关联主张 `{e.claim_id}`。",
            f"范围：{e.scope.description}；限制（原文）：{e.description}" + (f"；过期原因：{e.stale_reason}" if e.stale_reason else "")]
    lines += ["", "## 候选发现与 F1—F4", ""]
    if not state.findings:
        lines.append("本次尚无记录的候选违反。这不代表实现没有缺陷。")
    for f in state.findings:
        lines += [f"- `{f.id}`：层级 `{f.level}`，调查阶段 `{f.stage.value}`；来源 `{f.origin.value}`。{f.description}；轨迹 {link(f.trace_path)}。",
                  f"  调查记录：{'；'.join(f.investigation_notes) or '尚待调查'}"]
    for revision in state.revisions:
        lines += [f"- {revision.kind}：{revision.rationale}；返回 `{revision.return_step}`；依赖 {revision.relation_ids}；状态 {revision.status}。"]
    if not state.revisions:
        lines.append("本次没有实际应用的语义修订；工具错误不冒充 F1—F4。")
    lines += ["", "## 未决事项与停止原因", "", f"停止原因（原文）：{state.stop_reason}"]
    lines += [f"- {gap}" for gap in dict.fromkeys(state.gaps)]
    lines += ["- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。",
              "- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认实现义务/目标违反；合法性与后果证据不足时保留未决。",
              "", "## 实际运行统计", "", f"累计执行时间：{state.elapsed_seconds:.2f} 秒；预算计数：`{state.usage}`。",
              f"首个已保存模型前耗时：{state.first_model_seconds if state.first_model_seconds is not None else '尚无模型'}；模型仍须通过实际工具检查。",
              f"审计单元 {len(state.units)}；范围扩展 {sum(x.kind == 'F3' for x in state.revisions)}；语义修订 {len(state.revisions)}；校准 {len(state.calibrations)}。",
              "完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。", ""]
    first = next((c for c in state.checks if c.action == "model_check" and c.status == ExecutionStatus.COMPLETED), None)
    if first and first.started_at:
        seconds = (datetime.fromisoformat(first.started_at) - datetime.fromisoformat(state.created_at)).total_seconds()
        previous_calls = sum(c.action == "agent" and bool(c.started_at) and c.started_at < first.started_at for c in state.checks)
        lines += [f"首个经工具完成搜索确认可检查的模型：检查开始前约 {max(0, seconds):.2f} 秒，此前实际 agent 调用 {previous_calls} 次。",
            f"实际工具累计时长：{sum((datetime.fromisoformat(c.ended_at)-datetime.fromisoformat(c.started_at)).total_seconds() for c in state.checks if c.started_at and c.ended_at):.2f} 秒；新模型版本 {sum(m.previous_id is not None for m in state.models)} 个。", ""]
    path = root / "report.md"
    path.write_text("\n".join(lines))
    return path
