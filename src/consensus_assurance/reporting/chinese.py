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
    from consensus_assurance.workflow.research import current_view, view
    from consensus_assurance.core.config import Config
    from consensus_assurance.registry import EXECUTION_BACKENDS
    if derived:
        write_json(root/'materials.json',[m.model_dump(mode='json') for m in state.materials])
        write_json(root/'graph.json',{'version':state.graph_version,
            **{name:[x.model_dump(mode='json') for x in getattr(state,name)] for name in ('claims','bindings','relations')}})
        spec=load(state)
        if spec:write_json(root/'audit-spec.json',spec)
        write_json(root/'audit-progress.json',audit_progress(state))
        write_json(root/'plan.json',{'units':[u.model_dump(mode='json') for u in state.units],'selections':state.selections})
    config=Config.model_validate(state.config)
    implementation=EXECUTION_BACKENDS[config.execution_backend](config.target,config.budget.action_timeout)
    context=current_view(state,root,implementation)
    write_json(root/'research.json',context)
    return view(state)


def render_report(state, root, export_derived=False):
    root=Path(root)
    research=export_views(state,root,derived=export_derived)
    from urllib.parse import quote
    from consensus_assurance.workflow.audit_spec import load, audit_object_index
    from consensus_assurance.core.types import ConsensusAuditSpec
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
    dispositions={'confirmed_in_scope':'已确认违反','bounded_no_violation':'有限检查未见违反','investigation_lead':'待调查线索'}
    results=research['conclusions']
    confirmed=sum(r['disposition']=='confirmed_in_scope' for r in results)
    lines=['# 共识实现持续审计报告','',
        f'运行 `{state.id}`；模式 {state.mode}/{state.analysis_mode}；实际方法 `{state.framework_revision}`。',
        f'源码 `{state.snapshot.repo}`；提交 `{state.snapshot.commit}`。',
        f'停止原因：{research["stop_reason"]}',
        f'本轮已确认 {confirmed} 项逻辑义务违反；实际目标执行 {state.usage.get("experiments",0)} 次。',
        f'当前预算快照：耗时 {state.elapsed_seconds:.2f} 秒；剩余 {research["capacity"]["remaining_seconds"]:.2f} 秒、{research["capacity"]["remaining"]["agent_calls"]} 次 Agent 调用。',
        f'当前地图 {link(state.audit_spec_path)}；完整状态 {link(root/"state.json")}；研究索引 {link(root/"research.json")}。',
        '', '## 问题与实际结果','']
    import json
    from consensus_assurance.adapters.runners.experiment import extract_events
    for result in results:
        lines += [f'- **{dispositions[result["disposition"]]}**：{result["description"]}',
            f'  适用范围：{result["scope"]["description"]}；必要条件：{terms(result["scope"]["assumptions"])}。']
        if result['blockers']:lines.append('  当前争议／阻塞：'+terms(result['blockers']))
        for record in research['assessments']:
            if record.get('claim_id')!=result['claim_id']:continue
            check=next(c for c in state.checks if c.id==record['experiment_check_id'])
            artifact=next(a for a in state.direct_checks+state.models if a.id==(record.get('direct_check_id') or record.get('model_id')))
            review_status=record.get('correspondence') or '待复核'
            lines.append(f'  Unit `{artifact.unit_id}`／当前制品 v{artifact.version} `{artifact.id}`：执行 {check.status.value}；机械比较 {record["outcome"]}；对应性复核 {review_status}；完整处置 {record.get("reviewed_complete",False)}。')
            events=extract_events(check)
            indices=sorted({i for prop in record['properties'] for i in prop.get('valid_witness_indices',[])})
            for i in indices[:1]:
                if i<len(events):lines.append('  实际观测：`'+json.dumps(events[i],ensure_ascii=False)+'`。')
            lines.append(f'  {link(record.get("raw_log"),"原始观察")}；{link(root/"logs"/check.id/"check.json","执行记录")}。')
        lines += ['', '<details><summary>实验条件、固定制品与对应性复核</summary>','',
            f'正确性要求（Obligation）`{result["claim_id"]}`；候选 `{result["candidate_id"]}`。']
        for candidate in research['candidates']:
            if candidate['id']!=result['candidate_id']:continue
            q=candidate['question']
            lines += [f'调查问题（Candidate）`{candidate["id"]}`：调查状态 {candidate["status"]}；问题：{q["question"]}',
                f'来源：{sources(q["source_ids"])}；反证／保护：{terms(q["counterevidence"])}。',
                f'问题中保存的语义未知（执行进度以上述记录为准）：{terms(q["unknowns"])}；恢复条件：{terms(candidate["resume_conditions"])}。']
        artifacts=[a for a in research['artifacts'] if a.get('claim_id')==result['claim_id'] or any(
            c.get('claim_id')==result['claim_id'] for c in a.get('checkers',[]))]
        for artifact in artifacts:
            lines.append(f'检查制品（Check）`{artifact["id"]}` v{artifact["version"]}：{link(artifact.get("plan_path") or artifact.get("bundle_path"))}；{link(artifact.get("harness_path"),"测试源码")}。')
            if artifact.get('previous_id'):lines.append(f'旧版本 `{artifact["previous_id"]}` 的固定输入、观察和争议保留于 {link(root/"state.json","历史记录")}。')
        for review in state.semantic_reviews:
            for item in review.items:
                if item.target_id not in {a['id'] for a in artifacts}:continue
                lines.append(f'复核 `{review.id}`／{item.aspect}：{item.status}；{item.rationale}；来源：{sources(item.source_ids)}；补充说明：{terms(item.limitations)}。')
        lines += [f'范围排除：{terms(result["scope"]["excluded"])}；具体前史、适配与条件见固定计划和上述复核。','', '</details>','']
    for candidate in research['candidates']:
        if candidate['results']:continue
        q=candidate['question']
        lines += [f'- 调查问题（Candidate）`{candidate["id"]}`：{candidate["status"]}；{q["question"]}',
            f'  来源：{sources(q["source_ids"])}；反证：{terms(q["counterevidence"])}；保存的语义未知：{terms(q["unknowns"])}；恢复条件：{terms(candidate["resume_conditions"])}。']
    lines += ['', '## 双主线理解','',
        f'理解状态：{research["understanding_status"]}；当前目标：{research["next_objective"]["action"]}（{research["next_objective"]["boundary"]}）。']
    overview=research['core_overview']
    if overview:
        lines.append(f'以下是地图 v{state.audit_spec_version} 保存时的实现认识；其中的阶段性执行描述不代表当前待办，当前检查和结论见上方实际结果。')
        for key,label in [('formation','共识形成与推进'),('context','上下文／权威转换'),('connection','两条主线的连接')]:
            part=overview[key]
            lines += [f'- **{label}**：{part["explanation"]}',
                f'  行为：{objects(part["behavior_ids"],state.audit_spec_version)}。',
                f'  事实：{objects(part["fact_ids"],state.audit_spec_version)}。来源：{sources(part["source_ids"])}。']
        lines.append(f'判断依据：{overview["rationale"]}；核心断点：{terms(overview["core_gaps"])}；该版本保留的细节：{terms(overview["open_details"])}。')
    elif not state.audit_spec_path:lines.append('理解尚未登记；未受理草稿不是证据。')
    if research['understanding_status']!='usable' and research['next_objective']['boundary']!='user_directed':
        lines.append('双主线初始理解尚未完成；已保存片段不等于可以开始默认集中调查。')
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
    lines += ['', '## 当前待办','']
    shown_issues={id for record in research['assessments'] for id in record.get('open_issue_ids',[])}
    for item in research['pending_work']:
        reasons=terms(item['reasons']) if item['kind']=='review_issue' and item['id'] not in shown_issues else ''
        lines.append(f'- {link(root/"research.json",item["kind"]+": "+item["id"])}：{reasons}。')
    if not research['pending_work']:lines.append('无待完成的正式义务或未解决复核问题。')
    lines += ['', '## 研究交接与可选前沿','',
        '以下是受理时的回答与后续建议；历史“待执行”文字不覆盖上方当前执行结果，也不自动创建任务。']
    substantive=[s for s in research['handoffs'] if s.get('feedback')]
    recent=(substantive or research['handoffs'])[-1:]
    for handoff in recent:
        answer=handoff.get('feedback',{})
        lines += [f'- 最近交接 `{handoff["operation_id"]}`：{handoff["rationale"]}',
            f'  已回答：{answer.get("answered","见交接理由")}；可选下一判别：{terms(answer.get("remaining",[]))}。']
        for ref in answer.get('ref_ids',[]):
            check=next((c for c in state.checks if c.id==ref),None)
            lines.append('  依据：'+(link(check.stdout,ref) if check else sources([ref])))
    if len(research['handoffs'])>1:
        lines += ['', '<details><summary>历史交接（记录时说明）</summary>','']
        for handoff in research['handoffs']:
            if handoff in recent:continue
            answer=handoff.get('feedback',{})
            lines.append(f'- `{handoff["operation_id"]}`：{answer.get("answered",handoff["rationale"])}；当时后续：{terms(answer.get("remaining",[]))}。')
        lines += ['', '</details>','']
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
