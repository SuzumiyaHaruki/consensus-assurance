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
    if check.action == "agent_turn":
        product = ("Codex 调查已返回；回执待修订：" + check.parameters['agent_response_error']
            if check.parameters.get('agent_response_error') else
            "Agent 回执已保存；产物另经校验" if complete else "Agent 调用未完成：" + check.reason)
        return "Codex 调查", product, "不属于性质证据"
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


def export_views(state, root, derived=False):
    from consensus_assurance.adapters.storage.files import write_json
    from consensus_assurance.workflow.audit_spec import load, audit_progress
    from consensus_assurance.workflow.research import view
    import json
    if derived:
        write_json(root/'materials.json',[m.model_dump(mode='json') for m in state.materials])
        write_json(root/'graph.json',{'version':state.graph_version,
            **{name:[x.model_dump(mode='json') for x in getattr(state,name)] for name in ('claims','bindings','relations')}})
        spec=load(state)
        if spec:write_json(root/'audit-spec.json',spec)
        write_json(root/'audit-progress.json',audit_progress(state))
        write_json(root/'plan.json',{'units':[u.model_dump(mode='json') for u in state.units],'selections':state.selections})
    index=root/'research.json'
    context=json.loads(index.read_text()) if index.is_file() else {}
    context.update(view(state))
    context['rejected_drafts']=[str(p) for p in sorted((root/'submissions').glob('*/diagnostics.json'))]
    write_json(index,context)


def render_report(state, root, export_derived=False):
    root=Path(root)
    export_views(state,root,derived=export_derived)
    from urllib.parse import quote
    from consensus_assurance.workflow.research import view
    from consensus_assurance.workflow.audit_spec import load, audit_object_index
    from consensus_assurance.core.types import ConsensusAuditSpec
    research=view(state)
    def link(value,label=None):
        if not value:return '无'
        path=Path(value);label=label or path.name
        if not path.exists():return f'`{label}`（路径未保存）'
        target=path.relative_to(root) if path.is_relative_to(root) else path
        return f'[{label}]({quote(str(target))})'
    def terms(values):return '；'.join(str(x) for x in values) or '无'
    def mapping(version):return root/'audit-spec'/f'v{version}.json'
    maps={state.audit_spec_version:load(state)}
    def objects(ids,version):
        if version not in maps and mapping(version).is_file():
            maps[version]=ConsensusAuditSpec.model_validate_json(mapping(version).read_text())
        index=audit_object_index(maps.get(version))
        return terms(link(mapping(version),id)+': '+str(index.get(id,{}).get('meaning') or index.get(id,{}).get('trigger') or index.get(id,{}).get('purpose') or id) for id in ids)
    materials={m.id:m for m in state.materials}
    def sources(ids):
        entries=[]
        for id in ids:
            m=materials.get(id)
            if not m:entries.append(f'`{id}`');continue
            path=root/'source'/m.file
            if state.snapshot.files.get(m.file)!=m.content_digest or not path.is_file():path=root/'state.json'
            entries.append(link(path,f'{id} · {m.file}:{m.start_line}–{m.end_line}'))
        return terms(entries)
    lines=['# 共识实现持续审计报告','',
        f'运行 `{state.id}`；模式 {state.mode}/{state.analysis_mode}；实际方法 `{state.framework_revision}`。',
        f'源码 `{state.snapshot.repo}`；提交 `{state.snapshot.commit}`；快照 `{state.snapshot.id}`。',
        f'当前地图 {link(state.audit_spec_path)}；配置 {link(root/"config.json")}；快照记录 {link(root/"snapshot.json")}。',
        'Activity → Behavior → Fact → Candidate → Obligation → 执行／复核 → 理解回流。局部 checked 不代表整体正确。',
        '', '## 双主线理解','',
        f'理解状态：{research["understanding_status"]}；当前目标：{research["next_objective"]["action"]}（{research["next_objective"]["boundary"]}）。']
    overview=research['core_overview']
    if overview:
        lines.append(f'以下是地图 v{state.audit_spec_version} 保存时的实现认识；其中的阶段性执行描述不代表当前待办，当前检查和结论见下方实际结果。')
        for key,label in [('formation','共识形成与推进'),('context','上下文／权威转换'),('connection','两条主线的连接')]:
            part=overview[key]
            lines += [f'- **{label}**：{part["explanation"]}',
                f'  行为：{objects(part["behavior_ids"],state.audit_spec_version)}。',
                f'  事实：{objects(part["fact_ids"],state.audit_spec_version)}。来源：{sources(part["source_ids"])}。']
        lines.append(f'判断依据：{overview["rationale"]}；核心断点：{terms(overview["core_gaps"])}；该版本保留的细节：{terms(overview["open_details"])}。')
    elif not state.audit_spec_path:lines.append('理解尚未登记；未受理草稿不是证据。')
    if research['understanding_status']!='usable' and research['next_objective']['boundary']!='user_directed':
        lines.append('双主线初始理解尚未完成；已保存片段不等于可以开始默认集中调查。')
    lines += ['', '## 问题与实际结果','', '调查状态表示当前投入与处置；实际结果按对应要求和范围列出，不自动确认原因假设、父题或更广后果。']
    for candidate in research['candidates']:
        q=candidate['question'];basis=q['audit_spec_version']
        lines += [f'- 候选 `{candidate["id"]}`：调查状态 {candidate["status"]}；{q["question"]}；意义：{q["importance"]}。',
            f'  当前适用性：{candidate["current_applicability"]}；待复核：{terms(candidate["open_issue_ids"])}。',
            f'  检查依据 {link(mapping(basis),"v"+str(basis))}；责任：{terms(q["activity_classes"])}；关系：{q["obligation_relation_kind"]}。',
            f'  直接行为：{objects(q["behavior_ids"],basis)}；支撑：{objects(q["supporting_behavior_ids"],basis)}；事实：{objects(q["fact_ids"],basis)}。',
            f'  来源：{sources(q["source_ids"])}；事件路径：{terms(q["event_paths"])}。',
            f'  反证：{terms(q["counterevidence"])}；当前未知：{terms(q["unknowns"])}；恢复条件：{terms(candidate["resume_conditions"])}。']
        for result in candidate['results']:
            lines.append(f'  对应要求 `{result["claim_id"]}`：{result["description"]}；当前结果 {result["disposition"]}（具体范围见下方结论）。')
        for execution in candidate['executions']:
            lines.append(f'  执行 {link(root/"logs"/execution["check_id"]/"check.json",execution["check_id"])}：{execution["action"]}/{execution["status"]}/{execution["outcome"]}；制品 `{execution["artifact_id"]}`。')
    for claim in research['claims']:
        grounding=claim['grounding']
        lines += [f'- 要求 `{claim["id"]}`：{claim["description"]}；适用范围：{grounding["applicability"]}；推导：{grounding["derivation"]}。',
            f'  提出时信息（不代表当前待办）：{terms(claim["pending"]+grounding["unresolved"])}；来源：{sources(claim["source_ids"])}。']
    for unit in research['units']:
        lines.append(f'- Unit `{unit["id"]}`：{unit["status"]}；候选 `{unit["candidate_id"]}`；范围：{unit["scope"]["description"]}；未完成：{terms(unit["remaining_obligation_ids"])}；{terms(unit["coverage_limitations"])}。')
    for artifact in research['artifacts']:
        lines.append(f'- 制品 `{artifact["id"]}` v{artifact["version"]}；前版 `{artifact["previous_id"]}`；固定输入 {link(artifact.get("plan_path") or artifact.get("bundle_path"))}。')
    for review in state.semantic_reviews:
        for item in review.items:
            lines.append(f'- 语义复核 `{review.id}` → `{item.target_id}`：{item.status}；{item.rationale}；来源：{sources(item.source_ids)}；边界：{terms(item.limitations)}。')
    for record in research['assessments']:
        lines.append(f'- 执行 `{record["experiment_check_id"]}`：归因确认 {record["confirmed"]}；范围检查完整 {record.get("bounded_complete",False)}；归因阻塞：{terms(record["blockers"])}；边界／未测后果：{terms(record["boundaries"])}；{link(record.get("raw_log"),"原始观察")}。')
        for result in record['properties']:
            lines.append(f'  checker `{result["checker_id"]}`：{result["outcome"]}；有效见证索引 {result.get("valid_witness_indices",[])}；覆盖完整 {result.get("comparison_complete",False)}；范围外索引 {result.get("outside_applicability_indices",[])}；缺口：{terms(result.get("limitations",[]))}。')
    categories={'consensus_safety':'核心安全性','bounded_liveness':'有明确前提的有界活性','implementation_semantics':'相关实现语义'}
    dispositions={'confirmed_in_scope':'范围内确认','bounded_no_violation':'有限检查未见违反','investigation_lead':'待调查线索'}
    for result in research['conclusions']:
        lines.append(f'- 结论 `{result["claim_id"]}`（候选 `{result["candidate_id"]}`）：{categories[result["concern"]]}／{dispositions[result["disposition"]]}；{result["description"]}；范围：{result["scope"]["description"]}；未建立后果：{terms(result["unestablished_consequences"])}。')
    lines += ['', '## 本轮理解变化','']
    for change in research['understanding_changes']:
        version=change['version'];operation=change['operation_id']
        lines.append(f'- {link(mapping(version),"地图 v"+str(version))}：{link(root/"graph-commits"/f"submission-{operation}.json","受理差异与历史状态")}。')
        for id,delta in change['delta'].items():
            kind='新增' if not delta['before'] else '移除' if not delta['after'] else '修正／增补'
            fields=[k for k in delta['before'].keys()|delta['after'].keys() if delta['before'].get(k)!=delta['after'].get(k)]
            declaration=change['explanations'].get(id,{})
            lines.append(f'  {kind} `{id}`（{terms(sorted(fields))}）：{declaration.get("rationale","新登记的实现认识")}；{sources(declaration.get("source_ids",[]))}。')
        for id,effects in change['effects'].items():
            for effect in effects:
                label='待核实' if effect['status']=='challenged' else '原范围保留'
                lines.append(f'  候选 `{id}`／{effect["object_id"]}：{label}；{effect["reason"]}。')
    for draft in research['drafts']:
        lines.append(f'- 未受理稿 `{draft["draft_id"]}`：{draft["draft_status"]}；{draft["rationale"]}；{link(draft.get("raw_path"),"完整原稿")}。')
    lines += ['', '## 当前待办与研究交接','']
    for item in research['pending_work']:lines.append(f'- {item["kind"]} `{item["id"]}`：{terms(item["reasons"])}。')
    for issue in state.review_issues:
        lines.append(f'- 复核问题 `{issue.id}` → `{issue.target_id}` v{issue.target_version}：{issue.explanation}；来源：{sources(issue.source_ids)}；解决依据 `{issue.resolved_by or "未决"}`。')
    for handoff in research['handoffs']:
        answer=handoff.get('feedback',{})
        lines.append(f'- 交接 `{handoff["operation_id"]}`：{handoff["rationale"]}；已回答：{answer.get("answered","未提交反馈")}；仍待调查：{terms(answer.get("remaining",[]))}。')
    lines += [f'当前前沿与预算：{link(root/"research.json")}。地图条目和已检查 Unit 数不是责任覆盖率。',
        '停止原因：'+state.stop_reason, '', '## 日志、原稿与恢复记录','',
        f'CLI 调用 {state.usage.get("agent_calls",0)} 次；目标执行 {state.usage.get("experiments",0)} 次；耗时 {state.elapsed_seconds:.2f} 秒。',
        f'工具版本、实际 usage、修订和历史判断：{link(root/"state.json")}；正式调用及修复成本：{link(root/"research.json")}。退稿包含有效调查，不能全部视作浪费。']
    for check in state.checks:
        label,result,boundary=execution_summary(check)
        lines.append(f'- `{check.id}` {label}：{result}；{boundary}；{link(check.stdout,"stdout")}；{link(check.stderr,"stderr")}；期限 {check.parameters.get("timeout_limit","未记录")}／{check.parameters.get("timeout_seconds","未记录")} 秒。')
    for diagnostic in sorted((root/'submissions').glob('*/diagnostics.json')):
        lines.append(f'- 历史退稿：{link(diagnostic.parent/"raw.json","原稿")}；{link(diagnostic,"诊断")}。是否仍待修正见上方草稿状态。')
    lines += ['- '+gap for gap in dict.fromkeys(state.gaps)]
    lines.append(f'实际方法路径：{terms(state.method_paths)}。模型轨迹和脚本化产品不构成实现确认或自主发现。')
    path=root/'report.md';path.write_text('\n'.join(lines))
    return path
