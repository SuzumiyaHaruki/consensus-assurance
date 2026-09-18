from pathlib import Path
from datetime import datetime
from consensus_assurance.core.types import ExecutionStatus

STATUS = {"completed": "正常完成", "error": "执行错误", "timeout": "超时", "tool_missing": "工具缺失",
    "login_required": "需要登录", "quota_exhausted": "额度不足", "cancelled": "取消", "running": "执行中", "not_scheduled": "未调度"}
OUTCOME = {"holds": "有限范围搜索完成，无反例", "counterexample": "找到模型反例", "tests_passed": "所执行测试通过",
    "tests_failed": "所执行测试失败", "deadlock": "模型死锁诊断，性质检查未完成", "unknown": "结果未确定", "not_applicable": "不适用"}
CALIBRATION = {"compatible": "有限观测轨迹可解释", "incompatible": "当前模型无法解释观测", "inconclusive": "不确定", "stale": "需重验", "not_scheduled": "未执行"}
LEVEL = {"model": "模型层", "implementation_test": "实现实验层（不自动确认违反）", "framework_test": "mock 框架测试层", "trace_calibration": "有限轨迹校准层"}


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
    if check.action == "agent":
        if check.reason == "Structured agent output is invalid":
            product = "回复未通过结构化校验"
        elif not complete:
            product = "未取得可用回复（" + STATUS[check.status.value] + "）"
        else:
            product = "结构化回复已返回；不代表关系图或模型已被接受"
        if (Path(check.cwd) / "graph-validation-error.txt").is_file():
            product = "回复已返回；后续工作流校验失败，见校验日志"
        task={"spec_refine":"职责覆盖探索", "semantic_review":"义务/关系语义复核"}.get(check.parameters.get("agent_task"),"Agent 分析或修复")
        return task, product, "不适用：生成候选分析，不是验证"
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


def progress_lines(state):
    checks = [c for c in state.checks if c.action == "model_check"]
    return ["", "## 本次流程进度", "",
        "工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。", "",
        "| 阶段 | 已记录的进度 |", "| --- | --- |",
        f"| 材料阅读 | {'已完成首轮阅读' if 'materials' in state.completed_steps else '首轮阅读尚未完成'}；保存 {len(state.materials)} 个片段 |",
        f"| 义务与代码关系 | {'发现结果已被工作流接受' if 'discovery' in state.completed_steps else '尚未完成发现结果的工作流接受'}；当前图有 {len(state.claims)} 项主张、{len(state.units)} 个审计单元 |",
        f"| 直接实现检查 | 已保存 {len(state.direct_checks)} 个制品；完成 {sum(c.action=='direct_check' and c.status==ExecutionStatus.COMPLETED for c in state.checks)} 次执行；不等于整体性质成立 |",
        f"| 局部模型 | 已保存 {len(state.models)} 个模型版本；保存不代表检查通过 |",
        f"| 轨迹校准 | {len(state.calibrations)} 条校准记录；不等同于性质判定 |",
        f"| 模型搜索 | {len(checks)} 次执行记录；逐项结果见下方，未执行不计通过 |",
        f"| 性质证据 | {len(state.evidence)} 条直接证据；范围与层级见证据记录 |",
        "", "若 agent 回复完成而目标发现仍未被接受，不能把该回复视为已成立的关系图。历史记录未保存具体拒绝原因时，报告不补造原因。"]


def resource_lines(state):
    from consensus_assurance.core.config import Config
    from consensus_assurance.workflow.materials import material_usage,material_allowance
    cfg=Config.model_validate(state.config)
    used=material_usage(state);breadth=material_allowance(state,cfg.budget,'breadth');depth=material_allowance(state,cfg.budget,'depth')
    stages={}
    for check in state.checks:
        key=check.parameters.get('agent_task','agent') if check.action=='agent' else check.action
        stage=stages.setdefault(key,{'calls':0,'seconds':0.0,'timed':0})
        stage['calls']+=not check.reused
        if check.started_at and check.ended_at and not check.reused:
            stage['seconds']+=(datetime.fromisoformat(check.ended_at)-datetime.fromisoformat(check.started_at)).total_seconds();stage['timed']+=1
    builds=[c for c in state.checks if c.action=='agent' and c.parameters.get('agent_task') in {'build','F3'}]
    accepted=0
    import json
    for check in builds:
        path=Path(check.cwd)/'accepted-response.json'
        if path.is_file():
            try:accepted+=isinstance(json.loads(path.read_text()).get('bundle'),dict)
            except (ValueError,OSError):pass
    lines=['','## 材料、上下文与实际产物','','字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。',
        f"唯一材料 {used['unique_chars']}/{cfg.budget.material_chars} 字符；区间并集 {used['unique_chunks']}/{cfg.budget.material_chunks}。广度当前可分配 {breadth['available_chars']}、为深度保留 {breadth['reserved_for_other_chars']}；深度可分配 {depth['available_chars']}、为广度保留 {depth['reserved_for_other_chars']}。",
        f"建模类执行记录 {len(builds)}；受理且非空 Bundle 回复 {accepted}；落盘模型版本 {len(state.models)}（仅模型阶段 {sum(m.stage=='model_only' for m in state.models)}，完整组件 {sum(m.stage=='complete' for m in state.models)}）；实际性质搜索记录 {sum(c.action=='model_check' and not c.reused for c in state.checks)}（触达与校准另列）。",
        '', '| 阶段 | 新调用记录 | 已记录时长（秒） |', '| --- | --- | --- |']
    for name,item in stages.items():lines.append(f"| {name} | {item['calls']} | {item['seconds']:.2f}（{item['timed']} 条有起止时间） |")
    deferred=[(id,item) for id,p in state.read_plans.items() for item in p['items'] if item['status']=='deferred']
    for id,item in deferred:
        q=item['request'];lines.append(f"延期读取 `{id}`：{q['file']}:{q['start_line']}–{q['end_line']}；预计新增 {item['new_chars']} 字符；{item['reason']}")
    cached=sum(len(h.get('reattached_material_ids',[])) for h in state.reading_history)
    lines += [f"缓存复用/重附加记录 {cached} 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。",'', '| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |','| --- | --- | --- | --- | --- |']
    for p in state.packet_receipts:
        lines.append(f"| {p['kind']}/{p['id'][:8]} | {p['status']} | {p['prompt_chars']}/{p['prompt_bytes']} | {p['wire_schema_chars']} | {p['duplicate_material_occurrences']}/{len(p['omitted_material_ids'])} |")
    if not state.packet_receipts:lines.append('历史运行没有任务发送 receipt；不补造输入统计。')
    interface=sum(any(d['code'].startswith('review_') for d in session.get('resolved_diagnostics',[])+session.get('diagnostics',[])) for session in state.repair_sessions.values())
    lines.append(f"复核接口修复会话 {interface}；实际 F2 语义修订 {sum(r.kind=='F2' and r.status=='applied' for r in state.revisions)}。二者不互相替代。")
    for task in state.trigger_retry_tasks:lines.append(f"触达任务 {task['model_id']}/{task['requirement_id']}：{task['status']}；尝试 {len(task['attempts'])} 次；{task['reason']}")
    lines += ['', '## 范围接回、复核复用与里程碑', '', '里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。']
    for name,value in state.milestones.items():lines.append(f'- {name}：{value}')
    lines.append(f"同语义复核复用记录 {len(state.review_reuses)}；上下文准备失败 {state.usage.get('packet_preparation_failures',0)}；未发送包不消耗实际探索/复核轮数。")
    acquired={id for id,p in state.read_plans.items() if p.get('scope_requested') and p['status']=='complete' and any(i['status']=='acquired' for i in p['items'])}
    connected={u['proposal'].get('read_plan_id') for u in state.scope_updates.values() if u['status']=='accepted'} & acquired
    plans=list(state.read_plans.values())
    source_plans=sum(any(i['status']=='acquired' for i in p['items']) for p in plans)
    cache_plans=sum(bool(p['items']) and all(i['status']=='cached' for i in p['items']) for p in plans)
    stalled=sum(s.get('stagnation',0) for s in state.repair_sessions.values())
    lines.append(f"读取计划：当前 receipt 有新源 {source_plans}、纯缓存 {cache_plans}；修复无进展次数 {stalled}。targeted_reads 按取得新源的逻辑计划计数，历史用量不重算；缓存发送仍消耗实际 agent 调用与时间。")
    for packet in state.packet_receipts:
        resources=packet.get('skill_resources')
        if resources:lines.append(f"技能加载 `{packet['id']}`：版本 {resources['manifest_version']}，{resources['paths']}；仅以实际发送状态为准。")
    lines.append(f"需接回且已取得新材料的计划 {len(acquired)}；已接回 {len(connected)}；连接率 {str(len(connected))+'/'+str(len(acquired)) if acquired else '无可计算分母/历史未记录'}。这不是语义通过率或系统覆盖率。")
    sent=[p for p in state.packet_receipts if p['status'] in {'executed','accepted'} and not p.get('result_reused')]
    lines.append(f"实际发送包中源正文累计 {sum(p.get('source_chars_sent',0) for p in sent)} 字符（跨调用重复发送会重复计入）；schema 累计 {sum(p.get('wire_schema_bytes',0) for p in sent)} 字节。无真实 token/账单字段时不换算费用。")
    for id,update in state.scope_updates.items():lines.append(f"范围提案 {id}：{update['status']}；原单元 {update['proposal']['unit_id']}；新单元 {update.get('new_unit_id','尚未接回')}。")
    for task in state.inquiry_tasks:
        if task.child_task_ids:lines.append(f"分包父任务 {task.id}：子任务 {task.child_task_ids}；父状态 {task.status}，未执行子任务不计完成。")
    return lines


def inquiry_lines(state):
    def text(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    from consensus_assurance.workflow.audit_spec import load, audit_progress
    spec=load(state)
    lines=['', '## 实现理解（支持信息）', '', '| Activity | 适用性 | 义务 | 证据 | 未知 |', '| --- | --- | --- | --- | --- |']
    for row in audit_progress(state):
        lines.append('| '+' | '.join(text(row[k]) for k in ('class_id','applicability','obligation_ids','evidence_ids','unknowns'))+' |')
    if spec:
        for surface in spec.surfaces:
            if surface.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'}:lines.append('未解释责任：'+text(surface.entry_point)+'；'+text(surface.reason))
    else:lines.append('没有已受理的当前实现规格。未受理草稿不作为证据。')
    lines += ["", "| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |", "| --- | --- | --- | --- |"]
    for task in state.inquiry_tasks:
        kind='扩展职责/交接覆盖' if task.kind=='spec_refine' else '语义复核'
        lines.append(f"| `{task.id[:8]}` | {kind} | {task.status}/{task.stage} | {text(task.reason)}；{text(task.stop_reason)} |")
    current={x.id:getattr(x,'version',1) for x in [*state.claims,*state.bindings,*state.units,*state.relations,*state.models]}
    verdicts={'no_issue_found':'本次范围内暂未发现语义问题','needs_reading':'需要补读','disputed':'解释仍有争议','revision_needed':'需要修订'}
    aspects={'applicability':'适用性','decomposition':'义务及支撑关系','checker_correspondence':'checker 语义对应'}
    lines += ["", "| 复核对象/版本 | 层面 | 判断 | 材料与推导 |", "| --- | --- | --- | --- |"]
    for review in state.semantic_reviews:
        for item in review.items:
            version=review.target_versions.get(item.target_id)
            history='历史语义版本' if current.get(item.target_id)!=version else '当前对象版本'
            lines.append(f"| {text(item.target_id)} v{version}（{history}） | {aspects[item.aspect]} | {verdicts[item.status]} | {text(item.source_ids)}：{text(item.rationale)} |")
            if item.limitations: lines.append(f"未解决的有效性条件：{text(item.limitations)}")
            if item.limitations:lines.append(f"独立范围边界：{text(item.limitations)}")
    for issue in state.review_issues:
        lines.append(f"复核问题 `{issue.id}`：{'由 '+issue.resolved_by+' 显式解决' if issue.resolved_by else '未决'}；处置 `{issue.disposition}`；后续 {issue.task_ids}；{issue.explanation}；{issue.reason}。")
    for task in state.inquiry_tasks:
        if task.superseded_by: lines.append(f"历史任务 `{task.id}` 已由复核 `{task.superseded_by}` 完整替代；保留原执行状态。")
    if not state.semantic_reviews: lines.append("尚无已执行的语义复核；有来源的候选不因此变成已确认规范。")
    lines += ["", "职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。"]
    return lines


def audit_lines(state):
    lines=['', '## 义务与有界审计结论']
    for unit in state.units:
        q=unit.audit_question
        for claim in state.claims:
            if claim.id in unit.obligation_ids:lines.append(f"{claim.id} — {claim.description}")
        code=[f"{b.symbol} @ {b.file}:{b.start_line}-{b.end_line}" for b in state.bindings if b.id in unit.binding_ids]
        lines += ['代码：'+'；'.join(code),f"问题：{q.question if q else '尚未形成'}",f"方法：{q.preferred_check if q else '未选'}；状态：{unit.status}"]
        evidence=[e for e in state.evidence if e.claim_id in unit.obligation_ids]
        lines.append('证据：'+('; '.join(e.id+': '+str(e.assessment)+' / '+e.applicability for e in evidence) if evidence else '尚无；不能宣称正确'))
        if q:
            lines.append('已有保护/反证：'+str(q.counterevidence)+'；未决：'+str(q.unknowns))
            if q.disposition=='explained_by_existing_mechanism':lines.append('疑点已由所述机制解释；仅限当前来源与适用范围。')
            if q.disposition=='needs_specific_evidence':lines.append('下一步需要：'+str([r.model_dump() for r in q.requests]))
    if not state.units:lines.append('尚无已受理的有界审计问题或结论。')
    return lines


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
    lines = ["# 共识义务驱动局部审计报告", "", f"运行标识：`{state.id}`；模式：**{'真实工具运行' if state.mode == 'real' else 'MOCK 框架测试，不能提供实现正确性证据'}**。",
        "", "问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。",
        "", f"分析入口：`{'regression' if state.mode == 'mock' else state.analysis_mode}`。regression 表示预设开发回归，不能计为自主发现验收。",
        "", "## 分析输入与探索范围", "", f"仓库：`{state.snapshot.repo}`", f"提交：`{state.snapshot.commit or '无 Git 元数据'}`；分支：`{state.snapshot.branch or 'detached / unavailable'}`；脏工作区：`{state.snapshot.dirty}`。",
        f"快照：`{state.snapshot.id}`，纳入 {len(state.snapshot.files)} 个文件；读取 {len(state.materials)} 个材料片段，仍有未读范围的文件 {len(state.unexplored)} 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。",
        "候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。", "", "## 义务与选择依据", ""]
    insert_at = lines.index("## 分析输入与探索范围")
    lines[insert_at:insert_at] = audit_lines(state) + progress_lines(state) + [""]
    lines += ["领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考："]
    for guidance in state.guidance:
        lines += [f"- `{guidance['source']}`：{guidance['text'] or '未提供协议参考清单'}"]
    for history in state.reading_history:
        if history['gap']:
            lines += [f"定向补读：{history['gap']}；关联 {history['related_ids']}；实际新增片段 {history['added_material_ids']}。"]
    lines += ['', '## 候选问题与已有保护', '', '候选解释是有来源的分析判断，不是性质证据或协议正确性证明。']
    if not state.question_candidates:
        lines.append('历史未记录结构化候选问题。' if state.framework_revision!='selected-question-v3' else '尚未记录结构化候选问题。')
    for candidate in state.question_candidates:
        q=candidate.question
        lines += [f"- 候选 `{candidate.id}`：Fact {q.fact_ids}；生命周期 {q.obligation_relation_kind}；状态 {candidate.status} / {q.disposition}。",
            f"  问题：{q.question}；意义：{q.importance}。",
            f"  适用上下文：{q.contexts}；事件路径：{q.event_paths}；来源：{q.source_ids}。",
            f"  已有保护/反证：{q.counterevidence}；剩余判别与限制：{q.unknowns}。",
            f"  选择/缩窄依据：{q.trigger_rationale}；历史问题版本：{len(candidate.history)}。",
            f"  升级义务：{candidate.obligation_id or '未生成'}；候选结论或受阻原因：{candidate.stop_reason or '继续获取证据'}。"]
    lines += inquiry_lines(state)
    lines += ['', '## 未受理草稿分析']
    import json
    drafts=list(root.glob('agent/*/unaccepted-analysis.json'))+list(root.glob('repair-sessions/*/original.json'))
    for path in drafts:
        raw=json.loads(path.read_text());draft=raw.get('audit_spec')
        if draft:
            lines.append(f"{link(path)}：提出 {len(draft.get('activities',[]))} 类活动、{len(draft.get('behaviors',[]))} 个行为、{len(draft.get('facts',[]))} 个事实；拒绝原因见诊断。不是当前规格或性质证据。")
            for obj in draft.get('behaviors',[]):lines.append(f"草稿行为 {obj['id']}：{obj.get('execution_owner','')}；触发 {obj.get('trigger','')}；产生 {obj.get('produces_fact_ids',[])}；消费 {obj.get('consumes_fact_ids',[])}。")
            for obj in draft.get('facts',[]):lines.append(f"草稿事实 {obj['id']}：{obj.get('meaning','')}；未知 {obj.get('unknowns',[])}。")
    for claim in state.claims:
        lines += [f"- `{claim.id}`（{claim.kind}，{claim.assessment.value}）：{claim.description}",
                  f"  来源：{', '.join(claim.source_ids)}；待确认：{'；'.join(claim.pending) or '见范围假设'}。"]
        lines += [f"  语义版本：{claim.version}；行为材料 {claim.grounding.behavior_ids}；职责依据 {claim.grounding.expectation_ids}；绑定 {claim.grounding.binding_ids}。",
                  f"  推导：{claim.grounding.derivation}；适用性：{claim.grounding.applicability}；未决/冲突：{claim.grounding.unresolved + claim.grounding.conflicts}。"]
    if not state.claims:
        lines.append("尚未完成自主义务发现；未补入预置义务。")
    for selection in state.selections:
        lines += ["", f"审计单元 `{selection['unit_id']}` 引用关系 {selection['relation_ids']} 和代码绑定 {selection['binding_ids']}。",
                  f"选择依据（原文）：{selection['rationale']}"]
    for unit in state.units:
        lines += ["", f"单元 `{unit.id}`：{unit.status}；{unit.rationale}", f"范围：{unit.scope.description}。"]
    from consensus_assurance.workflow.modeling import coverage_limitations
    for unit in state.units:
        if unit.audit_question:
            lines += [f"审计问题：{unit.audit_question.question}；意义：{unit.audit_question.importance}；材料：{unit.audit_question.source_ids}。"]
        lines += [f"建模前复核/探索性许可：{unit.semantic_readiness}。"]
        lines += [f"有效交互覆盖限制（独立于原始 checker 结果）：{coverage_limitations(state,unit)}。"]
        lines += [f"单元 `{unit.id}` 逐项执行进度：{unit.obligation_checks}；尚待检查：{unit.remaining_obligation_ids or ([c for c in unit.obligation_ids if c not in unit.obligation_checks] if unit.status != 'checked' else [])}。已检查仅指记录范围内的 checker，不代表义务整体成立。"]
        if unit.recheck_reasons:
            lines += [f"重验任务 `{unit.id}`：{'；'.join(unit.recheck_reasons)}；调度状态 `{unit.status}`。"]
    lines += ["", "## 候选修复会话", "", "原始候选、当前版本、修复 patch 与问题计数分开保存；调用完成不等于候选或语义已接受。"]
    for session in state.repair_sessions.values():
        lines.append(f"会话 `{session['id']}`：{session.get('status')}；候选版本 {session['version']}；修复调用 {session['attempt']}；原始候选 {link(session['original_path'])}；当前候选 {link(session['current_path'])}；问题 {session.get('error','')}。")
        lines.append(f"诊断及材料：{session.get('diagnostics',[])}；重复失败：{session.get('problem_failures',{})}；显式范围/语义计划：{session.get('proposed_change','无')}。")
    for binding in state.bindings:
        lines.append(f"代码位置 `{binding.id}`：{binding.file}:{binding.start_line}–{binding.end_line}；锚点 {binding.anchor}；候选职责关联 {[a.claim_id for a in binding.associations]}。")
    lines += ["", "## 实验能力与执行", "", "| 能力 | 状态 | 执行依据 |", "| --- | --- | --- |"]
    for cap in state.capabilities:
        lines.append(f"| {cap.name} | {cap.status} | {cap.check_id or '无执行确认'}：{cap.description} |")
    lines += ["", "默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。", "",
        "| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |", "| --- | --- | --- | --- | --- |"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    for check in state.checks:
        task, product, verdict = execution_summary(check)
        diagnostic = f"{link(check.stdout)} / {link(check.stderr)}"
        if check.action == "agent":
            for name in ("response.json", "validation-error.txt", "graph-validation-error.txt"):
                artifact = Path(check.cwd) / name
                if artifact.is_file():
                    diagnostic += " / " + link(artifact)
        if check.reason:
            diagnostic += "；原因（原文）：" + check.reason
        reuse = "；历史记录复用" if check.reused else ""
        lines.append("| " + " | ".join(cell(x) for x in (
            f"{task}：{check.action} `{check.id[:8]}`", STATUS[check.status.value] + reuse,
            product, verdict, diagnostic)) + " |")
    lines += ["", "逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）："]
    for check in state.checks:
        if check.action == "model_check":
            for result in check.checker_results:
                lines += [f"- `{result.invariant}` → `{result.claim_id}`：`{result.outcome}`；范围：{result.scope.description}；执行 `{check.id}`。"]
    for check in state.checks:
        if check.reused_from:lines.append(f"显式复用执行 `{check.id}` ← `{check.reused_from}`；匹配搜索输入 `{check.search_fingerprint}`；这不是再次执行工具。")
    for result in state.reachability_results:
        lines.append(f"触发 `{result.requirement_id}`：`{result.status}`；模型 `{result.model_id}`；实际执行 `{result.check_id}`；{result.reason}。不可达或未知不计有效交互覆盖，原始 holds 仍保留。")
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
            lines += [f"校准：**{CALIBRATION[c.status]}**；适用性 `{c.applicability}`；{c.reason}。轨迹：{link(c.trace_path)}。",
                "有限真实轨迹可解释不等于模型与实现完全等价；不能据此确认更大范围实现正确。"]
    for artifact in state.direct_checks:
        lines += ["", f"直接检查 `{artifact.id}`：义务 `{artifact.claim_id}`；计划 {link(artifact.plan_path)}；harness {link(artifact.harness_path)}；范围：{artifact.scope.description}。有限测试不证明整体义务或目标正确。"]
    for e in state.evidence:
        lines += ["", f"证据 `{e.id}`：{LEVEL[e.level]}，`{e.assessment.value}`；执行 `{e.check_id}`；关联主张 `{e.claim_id}` v{e.claim_version}；checker `{e.checker_id}`；适用性 `{e.applicability}`。",
            f"范围：{e.scope.description}；限制（原文）：{e.description}" + (f"；过期原因：{e.stale_reason}" if e.stale_reason else "")]
    lines += ["", "## 候选发现与 F1—F4", ""]
    if not state.findings:
        lines.append("本次尚无记录的候选违反。这不代表实现没有缺陷。")
    for f in state.findings:
        lines += [f"- `{f.id}`：层级 `{f.level}`，调查阶段 `{f.stage.value}`；来源 `{f.origin.value}`。{f.description}；轨迹 {link(f.trace_path)}。",
                  f"  调查记录：{'；'.join(f.investigation_notes) or '尚待调查'}"]
        if f.confirmation_path:
            lines += [f"  实际观测、前提、合法性及性质判定：{link(f.confirmation_path)}；checker `{f.checker_id}`。"]
    for result in state.monitor_results:
        lines += [f"观测判定 `{result.get('finding_id',result.get('direct_check_id','unknown'))}`：前提 `{result['prerequisites']['status']}`；确认层级 `{result['level']}`；限制：{result['limitations']}。"]
    for decision in state.consequences:
        lines.append(f"义务→更广泛后果处置：发现 `{decision['finding_id']}`；`{decision['disposition']}`；{decision['reason']}；后续 {decision['task_ids']}；限制 {decision['limitations']}。")
    for revision in state.revisions:
        lines += [f"- {revision.kind}：{revision.rationale}；返回 `{revision.return_step}`；依赖 {revision.relation_ids}；状态 {revision.status}。"]
    if not state.revisions:
        lines.append("本次没有实际应用的语义修订；工具错误不冒充 F1—F4。")
    lines += ["", "## 未决事项与停止原因", "", f"停止原因（原文）：{state.stop_reason}",
        f"控制器格式：{state.framework_revision or '历史运行未记录'}；阶段：{state.framework_stage}。",
        f"恢复位置：探索/复核任务 `{state.active_inquiry_id}`；单元 `{state.active_unit_id}`，模型 `{state.active_model_id}`，反例 `{state.active_finding_id}`，下一动作 `{state.next_action}`。"]
    lines += [f"- {gap}" for gap in dict.fromkeys(state.gaps)]
    lines += ["- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。",
              "- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。",
              "", "## 实际运行统计", "", f"累计执行时间：{state.elapsed_seconds:.2f} 秒；预算计数：`{state.usage}`。",
              f"首个已保存模型前耗时：{state.first_model_seconds if state.first_model_seconds is not None else '尚无模型'}；模型仍须通过实际工具检查。",
              f"审计单元 {len(state.units)}；范围扩展 {sum(x.kind == 'F3' for x in state.revisions)}；语义修订 {len(state.revisions)}；校准 {len(state.calibrations)}。",
              "完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。", ""]
    lines += resource_lines(state)
    first = next((c for c in state.checks if c.action == "model_check" and c.status == ExecutionStatus.COMPLETED), None)
    if first and first.started_at:
        seconds = (datetime.fromisoformat(first.started_at) - datetime.fromisoformat(state.created_at)).total_seconds()
        previous_calls = sum(c.action == "agent" and bool(c.started_at) and c.started_at < first.started_at for c in state.checks)
        lines += [f"首个经工具完成搜索确认可检查的模型：检查开始前约 {max(0, seconds):.2f} 秒，此前实际 agent 调用 {previous_calls} 次。",
            f"实际工具累计时长：{sum((datetime.fromisoformat(c.ended_at)-datetime.fromisoformat(c.started_at)).total_seconds() for c in state.checks if c.started_at and c.ended_at):.2f} 秒；新模型版本 {sum(m.previous_id is not None for m in state.models)} 个。", ""]
    path = root / "report.md"
    path.write_text("\n".join(lines))
    return path
