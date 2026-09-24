from pathlib import Path
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


def resource_lines(state):
    from consensus_assurance.core.config import Budget
    from consensus_assurance.workflow.materials import material_usage,material_allowance,request_label
    budget=Budget.model_validate({k:v for k,v in state.config.get("budget",{}).items() if k in Budget.model_fields})
    used=material_usage(state);breadth=material_allowance(state,budget,'breadth');depth=material_allowance(state,budget,'depth')
    lines=['','## 材料、上下文与实际产物','','字符不是 token 或费用。',
        f"唯一材料 {used['unique_chars']}/{budget.material_chars} 字符；区间并集 {used['unique_chunks']}/{budget.material_chunks}。广度当前可分配 {breadth['available_chars']}、为深度保留 {breadth['reserved_for_other_chars']}；深度可分配 {depth['available_chars']}、为广度保留 {depth['reserved_for_other_chars']}。"]
    unavailable=[(id,item) for id,p in state.read_plans.items() for item in p['items'] if item['status'] in {'deferred','unresolved'}]
    for id,item in unavailable:
        resolved=item.get('file_metadata',{}).get('resolved_range')
        location=f"；定位 {resolved['file']}:{resolved['start_line']}–{resolved['end_line']}" if resolved else ''
        label='延期读取' if item['status']=='deferred' else '查询未解决'
        lines.append(f"{label} `{id}`：{request_label(item['request'])}{location}；预计新增 {item['new_chars']} 字符；{item['reason']}")
    cached=sum(len(h.get('reattached_material_ids',[])) for h in state.reading_history)
    lines.append(f"缓存复用/重附加 {cached} 个；每包详情保留在 state.json，不重复展开。")
    interface=sum(any(d['code'].startswith('review_') for d in session.get('resolved_diagnostics',[])+session.get('diagnostics',[])) for session in state.repair_sessions.values())
    lines.append(f"复核接口修复会话 {interface}；实际 F2 语义修订 {sum(r.kind=='F2' and r.status=='applied' for r in state.revisions)}。二者不互相替代。")
    resources=[p['skill_resources'] for p in state.packet_receipts if p.get('skill_resources')]
    lines += ['', '## 实际调用与材料归属', '', f"复核复用 {len(state.review_reuses)}；上下文准备失败 {state.usage.get('packet_preparation_failures',0)}；未发送包不计调用。"]
    if resources:lines.append(f"实际包加载技能清单版本：{sorted({r['manifest_version'] for r in resources})}。")
    sent=[p for p in state.packet_receipts if p['status'] in {'executed','accepted'} and not p.get('result_reused')]
    lines.append(f"发送源码累计 {sum(p.get('source_chars_sent',0) for p in sent)} 字符（跨调用重复计数）；schema {sum(p.get('wire_schema_bytes',0) for p in sent)} 字节；不换算 token 或费用。")
    tasks={t.id:t for t in state.inquiry_tasks};artifacts={a.id:a for a in state.direct_checks};models={m.id:m for m in state.models}
    candidates={c.id:c for c in state.question_candidates}
    def family(id):
        seen=set()
        while id in candidates and candidates[id].parent_candidate_id and id not in seen:
            seen.add(id);id=candidates[id].parent_candidate_id
        return ('problem',id)
    obligation_owner={c.obligation_id:family(c.id) for c in state.question_candidates if c.obligation_id}
    unit_owner={u.id:next((obligation_owner[id] for id in u.obligation_ids if id in obligation_owner),('unit',u.id)) for u in state.units}
    def task_owner(task):
        if task.candidate_id:return family(task.candidate_id)
        if task.unit_id:return unit_owner.get(task.unit_id,('unit',task.unit_id))
        if task.surface_entry_points:return ('frontier',','.join(task.surface_entry_points))
        return ('startup','shared') if task.kind=='spec_refine' else ('unknown','unattributed')
    owners={id:family(c.id) for c in state.question_candidates for id in c.check_ids}
    owners.update({t.check_id:task_owner(t) for t in state.inquiry_tasks if t.check_id})
    packets={p['check_id']:p for p in state.packet_receipts if p.get('check_id')}
    def packet_owner(packet):
        task=tasks.get(packet.get('task_id'))
        if task:return task_owner(task)
        if packet.get('candidate_id') in candidates:return family(packet['candidate_id'])
        if packet.get('unit_id'):return unit_owner.get(packet['unit_id'],('unit',packet['unit_id']))
        return ('startup','shared') if packet['kind'] in {'read','discover','spec_refine'} else ('unknown','unattributed')
    owners.update({id:packet_owner(packet) for id,packet in packets.items() if id not in owners})
    for check in state.checks:
        if check.direct_check_id in artifacts:owners.setdefault(check.id,unit_owner.get(artifacts[check.direct_check_id].unit_id,('unit',artifacts[check.direct_check_id].unit_id)))
        if check.model_id in models:owners.setdefault(check.id,unit_owner.get(models[check.model_id].unit_id,('unit',models[check.model_id].unit_id)))
    rows={};row=lambda owner:rows.setdefault(owner,{'calls':0,'executions':0,'acquired':0,'sent':0,'result':''})
    for check in state.checks:
        owner=owners.get(check.id,('startup','shared') if check.action in PROBES else ('unknown','unattributed'));r=row(owner)
        r['calls']+=check.action=='agent' and not check.reused;r['executions']+=check.action in {'direct_check','model_check','experiment','replay'} and not check.reused
    for packet in sent:
        owner=owners.get(packet.get('check_id'),packet_owner(packet))
        row(owner)['sent']+=packet.get('source_chars_sent',0)
    row(('startup','shared'))['acquired']=max(0,used['unique_chars']-sum(a.get('new_chars',0) for a in state.material_allocations))
    histories={h['plan_id']:h for h in state.reading_history if h.get('plan_id')}
    for allocation in state.material_allocations:
        history=histories.get(allocation.get('plan_id'),{})
        related=history.get('related_ids',[])
        owner=next((family(x) for x in related if x in candidates),None) or next((unit_owner[x] for x in related if x in unit_owner),None)
        if owner is None:owner=('startup','shared') if not related or all(x in {'A1','A2','A3','A4','A5','A6','A7'} for x in related) else ('unknown','unattributed')
        row(owner)['acquired']+=allocation.get('new_chars',0)
    for candidate in state.question_candidates:
        view=__import__('consensus_assurance.workflow.task_view',fromlist=['candidate_view']).candidate_view(state,candidate);result=view['current_result']
        item=row(family(candidate.id));value=(f"{result['outcome']}; blockers={len(result['blockers'])}; boundaries={len(result['boundaries'])}" if result else candidate.status)
        item['result']='; '.join(dict.fromkeys(filter(None,[item['result'],value])))
    for unit in state.units:
        if unit_owner[unit.id][0]=='problem':continue
        row(unit_owner[unit.id])['result']='blocked' if any(r.get('bounded_complete') and r.get('blockers') and any(a.unit_id==unit.id and a.id==r.get('direct_check_id') for a in state.direct_checks) for r in state.monitor_results) else unit.status
    lines += ['', '| 工作归属 | Agent 调用 | 工具执行 | 新取得片段字符 | 发送源码字符 | 当前结果 |','| --- | --- | --- | --- | --- | --- |']
    for owner,item in rows.items():lines.append(f"| {owner[0]}:{owner[1]} | {item['calls']} | {item['executions']} | {item['acquired']} | {item['sent']} | {item['result'] or '无结果'} |")
    lines.append('统计从既有记录派生；Parent/child 合并为一个问题家族，共同启动单列，每项只归属一次，无法关联则列为 unknown。')
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
        stage=task.stage
        if stage=='read':
            stage='read（待取得或重附当前来源）'
        lines.append(f"| `{task.id[:8]}` | {kind} | {task.status}/{stage} | {text(task.reason)}；{text(task.stop_reason)} |")
    lines += ["", f"语义复核 {len(state.semantic_reviews)} 次；完整判断、来源和历史边界保留在 state.json。当前控制问题如下："]
    for issue in state.review_issues:
        lines.append(f"复核问题 `{issue.id}`：{'由 '+issue.resolved_by+' 显式解决' if issue.resolved_by else '未决'}；处置 `{issue.disposition}`；后续 {issue.task_ids}；{issue.explanation}；{issue.reason}。")
    return lines


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


def render_report(state, root):
    root = Path(root)
    export_views(state,root)
    def link(path):
        if not path:
            return "无"
        p = Path(path)
        try:
            target = p.relative_to(root)
        except ValueError:
            target = p
        return f"[{p.name}]({target})"
    focus=state.config.get('activity_focus',[])
    entry='regression' if state.mode=='mock' else state.analysis_mode
    orientation=('；Activity 重点：`'+str(focus)+'`。这是有明确 Activity 重点的自主发现，不是具体定向命题。' if focus and entry=='autonomous' else '；Activity 重点：无。' if not focus else '；Activity 重点：`'+str(focus)+'`。')
    lines = ["# 共识义务驱动局部审计报告", "", f"运行标识：`{state.id}`；模式：**{'真实工具运行' if state.mode == 'real' else 'MOCK 框架测试，不能提供实现正确性证据'}**。",
        "", "问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。",
        "", f"分析入口：`{entry}`{orientation} regression 表示预设开发回归，不能计为自主发现验收。",
        "", "## 分析输入与探索范围", "", f"仓库：`{state.snapshot.repo}`", f"提交：`{state.snapshot.commit or '无 Git 元数据'}`；分支：`{state.snapshot.branch or 'detached / unavailable'}`；脏工作区：`{state.snapshot.dirty}`。",
        f"快照：`{state.snapshot.id}`，纳入 {len(state.snapshot.files)} 个文件；读取 {len(state.materials)} 个材料片段，仍有未读范围的文件 {len(state.unexplored)} 个。完整清单见 [materials.json](materials.json) 和 [snapshot.json](snapshot.json)。",
        "候选不代表完整性；原始材料保留原文。", "", "## 义务与选择依据", ""]
    lines += ["领域引导与参考："]
    for guidance in state.guidance:
        lines += [f"- `{guidance['source']}`：{guidance['text'] or '未提供协议参考清单'}"]
    for history in state.reading_history:
        if history['gap']:
            lines += [f"定向补读：{history['gap']}；关联 {history['related_ids']}；实际新增片段 {history['added_material_ids']}。"]
    lines += ['', '## 候选问题与已有保护', '', '候选判断不是性质证据。']
    if not state.question_candidates:
        lines.append('未记录结构化候选问题。')
    from consensus_assurance.workflow.discovery import candidate_blockage
    from consensus_assurance.workflow.task_view import candidate_view
    for candidate in state.question_candidates:
        q=candidate.question;original=candidate.history[0] if candidate.history else q
        current=candidate_view(state,candidate);result=current['current_result']
        if candidate.status=='explained':
            adjacent=q.unknowns or ['当前记录未结构化列出相邻问题']
            lines.append('相邻但未检查的问题：'+str(adjacent)+'；不由本候选结论覆盖，需以独立来源和判别条件另行调查。')
        lines += [f"- 候选 `{candidate.id}`：Fact {q.fact_ids}；{q.obligation_relation_kind}；{candidate.status}/{q.disposition}；受阻 {candidate_blockage(state,candidate) or '无'}。",
            f"  {q.question}；意义：{q.importance}；上下文/路径：{q.contexts}/{q.event_paths}；来源：{q.source_ids}。",
            f"  提出时的保护与未知：{original.counterevidence}/{original.unknowns}；当前保护/反证：{q.counterevidence}；当前未决：{q.unknowns}；选择依据：{q.trigger_rationale}；义务：{candidate.obligation_id or '未生成'}；处置：{candidate.stop_reason or '继续获取证据'}；恢复判别：{candidate.resume_conditions}；历史版本 {len(candidate.history)}。"]
        if result:lines.append(f"  当前局部结果：{result}；执行/证据关联：{current['check_ids']} / {current['evidence_ids']}；当前剩余判别：{current['remaining_discriminators']}。")
        if candidate.parent_candidate_id:
            parent=next((x for x in state.question_candidates if x.id==candidate.parent_candidate_id),None)
            lines.append(f"  Parent `{candidate.parent_candidate_id}`；fork 原因：{candidate.fork_reason}；Parent 未决：{parent.question.unknowns if parent else '历史 Parent 不可用'}；child 局部义务/检查：{candidate.obligation_id or '未生成'} / {current['unit_status'] or '未形成 AuditUnit'}；Parent 原问题及未决项保持独立。")
    if state.audit_spec_path:
        from consensus_assurance.workflow.audit_spec import load,audit_object_key
        from consensus_assurance.core.types import ConsensusAuditSpec
        current=load(state);first_path=Path(state.audit_spec_path).parent/'v1.json'
        first=ConsensusAuditSpec.model_validate_json(first_path.read_text()) if first_path.exists() else current
        expansions=[t for t in state.inquiry_tasks if t.surface_entry_points]
        candidate_calls={id for c in state.question_candidates for id in c.check_ids}
        feedback=[t for t in state.inquiry_tasks if t.kind=='spec_refine' and any(t.trigger.startswith(id+':') for id in candidate_calls)]
        lines += ['', '## 描述性理解演化', '', f'AuditSpec：v{first.version} → v{current.version}；Behavior：{len(first.behaviors)} → {len(current.behaviors)}；Fact：{len(first.facts)} → {len(current.facts)}。',
            f'Surface 扩展任务：planned={len(expansions)} / prepared={sum(bool(t.context_receipt_id) for t in expansions)} / sent={sum(t.admitted for t in expansions)} / semantic_result={sum(any(p.get("check_id") and p.get("task_id")==t.id for p in state.packet_receipts) for t in expansions)} / accepted={sum(t.status=="completed" for t in expansions)}；深度分析反馈任务：{len(feedback)}（完成 {sum(t.status=="completed" for t in feedback)}）。这些是描述性进度，不是正确性覆盖率。']
        for task in expansions:lines.append(f'- 扩展 {task.surface_entry_points}：{task.status}；{task.stop_reason or task.reason}')
        for surface in current.surfaces:
            if surface.high_consequence:lines.append(f'- 高后果 Surface `{audit_object_key(surface)}`：{surface.disposition}；{surface.reason}')
    lines += inquiry_lines(state)
    lines += ['', '## 未受理草稿分析']
    import json
    drafts=list(root.glob('audit-spec/unaccepted-*.json'))+list(root.glob('agent/*/unaccepted-analysis.json'))+list(root.glob('repair-sessions/*/original.json'))
    for path in drafts:
        raw=json.loads(path.read_text());draft=raw.get('audit_spec')
        if draft:
            lines.append(f"{link(path)}：提出 {len(draft.get('activities',[]))} 类活动、{len(draft.get('behaviors',[]))} 个行为、{len(draft.get('facts',[]))} 个事实；拒绝原因见诊断。不是当前规格或性质证据。")
            for obj in draft.get('behaviors',[]):lines.append(f"草稿行为 {obj['id']}：{obj.get('execution_owner','')}；触发 {obj.get('trigger','')}；产生 {obj.get('produces_fact_ids',[])}；消费 {obj.get('consumes_fact_ids',[])}。")
            for obj in draft.get('facts',[]):lines.append(f"草稿事实 {obj['id']}：{obj.get('meaning','')}；未知 {obj.get('unknowns',[])}。")
    for claim in state.claims:
        lines += [f"- `{claim.id}`（{claim.kind}，{claim.assessment.value}）：{claim.description}",
                  f"  来源：{', '.join(claim.source_ids)}；原始待核查记录：{'；'.join(claim.pending) or '见范围假设'}；当前执行进度见候选局部结果。"]
        lines += [f"  语义版本：{claim.version}；行为材料 {claim.grounding.source_ids}；职责依据 {claim.grounding.expectation_ids}；绑定 {claim.grounding.binding_ids}。",
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
    lines += ["", "## 候选修复与模型续写", "", "模型续写保存原稿、当前工作草稿及错误，返回完整修订稿；其他对象按具体字段修复。未完成草稿不等于受理模型，调用完成也不等于语义问题已解决。"]
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
            for name in ("response.json", "validation-error.txt", "graph-validation-error.txt", "generation-error.json"):
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
    lines += ["", "## 候选发现与修订", ""]
    if not state.findings:
        lines.append("本次尚无记录的候选违反。这不代表实现没有缺陷。")
    for f in state.findings:
        lines += [f"- `{f.id}`：层级 `{f.level}`，调查阶段 `{f.stage.value}`；来源 `{f.origin.value}`。{f.description}；轨迹 {link(f.trace_path)}。",
                  f"  调查记录：{'；'.join(f.investigation_notes) or '尚待调查'}"]
        if f.confirmation_path:
            lines += [f"  实际观测、前提、合法性及性质判定：{link(f.confirmation_path)}；checker `{f.checker_id}`。"]
    current_checks=set()
    for candidate in state.question_candidates:
        artifact=next((a for a in reversed(state.direct_checks) if a.claim_id==candidate.obligation_id),None)
        result=next((r for r in reversed(state.monitor_results) if artifact and r.get('direct_check_id')==artifact.id),None)
        if result:current_checks.add(result['experiment_check_id'])
    for result in state.monitor_results:
        observed='；'.join(p['checker_id']+'='+p['outcome'] for p in result['properties'])
        completion=('有界检查完成' if result.get('bounded_complete') else '有界检查未完成') if result.get('direct_check_id') else '模型回放解释'
        label='当前' if result.get('experiment_check_id') in current_checks else '历史' if result.get('direct_check_id') else '模型'
        lines += [f"{label}观测判定 `{result.get('finding_id',result.get('direct_check_id','unknown'))}`：{completion}；实际结果 `{result.get('outcome',observed)}`；性质 `{observed}`；前提 `{result['prerequisites']['status']}`；确认层级 `{result['level']}`；归因阻塞：{result.get('blockers',result.get('limitations',[]))}；实验适配：{result.get('adaptations',[])}；范围边界：{result.get('boundaries',[])}。"]
    for decision in state.consequences:
        lines.append(f"义务→更广泛后果处置：发现 `{decision['finding_id']}`；`{decision['disposition']}`；{decision['reason']}；Parent {decision.get('parent_candidate_id') or '无'}；后续 {decision['task_ids']}；限制 {decision['limitations']}。")
    for revision in state.revisions:
        lines += [f"- {revision.kind}：{revision.rationale}；返回 `{revision.return_step}`；依赖 {revision.relation_ids}；状态 {revision.status}。"]
    if not state.revisions:
        lines.append("本次没有实际应用的修订；工具错误不冒充修订。")
    budget=state.config.get('budget',{});from consensus_assurance.workflow.materials import material_usage
    exhausted=[name for name,value in state.usage.items() if name in budget and value>=budget[name]]
    if budget.get('total_seconds') is not None and state.elapsed_seconds>=budget['total_seconds']:exhausted.append('total_seconds')
    if budget.get('material_chars') is not None and material_usage(state)['unique_chars']>=budget['material_chars']:exhausted.append('material_chars')
    lines += ["", "## 未决事项与停止原因", "", f"停止原因（原文）：{state.stop_reason}",
        f"实际耗尽：{exhausted or '无已记录上限耗尽'}；合同或能力缺口仍以候选、单元和 gap 的原始记录为准。",
        f"控制器格式：{state.framework_revision or '历史运行未记录'}；阶段：{state.framework_stage}。",
        f"恢复位置：探索/复核任务 `{state.active_inquiry_id}`；单元 `{state.active_unit_id}`，模型 `{state.active_model_id}`，反例 `{state.active_finding_id}`，下一动作 `{state.next_action}`。"]
    lines += [f"- {gap}" for gap in dict.fromkeys(state.gaps)]
    reported=sorted({(c.parameters.get('agent_model'),c.parameters.get('agent_reasoning_effort')) for c in state.checks if c.action=='agent' and c.parameters.get('agent_model')})
    lines += ["- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。",
              "- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。",
              "", "## 实际运行统计", "", f"累计执行时间：{state.elapsed_seconds:.2f} 秒；预算计数：`{state.usage}`。",
              "Agent CLI 报告："+("；".join(f"model={model}，reasoning_effort={effort or '未记录'}" for model,effort in reported) if reported else "未记录。"),
              f"首个已保存模型前耗时：{state.first_model_seconds if state.first_model_seconds is not None else '尚无模型'}；模型仍须通过实际工具检查。",
              f"审计单元 {len(state.units)}；范围扩展 {sum(x.kind == 'F3' for x in state.revisions)}；已应用修订 {sum(x.status=='applied' for x in state.revisions)}；校准 {len(state.calibrations)}。",
              "完整命令、时间、版本与制品关联见 [state.json](state.json)，图、规格和计划视图在结束或生成报告时导出；事件见 [events.jsonl](events.jsonl)。", ""]
    lines += resource_lines(state)
    path = root / "report.md"
    path.write_text("\n".join(lines))
    return path
