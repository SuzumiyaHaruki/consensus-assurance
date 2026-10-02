"""Human reading view of retained conclusions; never executes or repairs research state."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.workflow.research import view, exploration_results
from consensus_assurance.workflow.prompts import manifest


OUTCOME = {'holds':'有限检查未见违反', 'violated':'观察到违反', 'counterexample':'找到模型反例',
    'tests_passed':'所执行测试通过', 'tests_failed':'所执行测试失败', 'deadlock':'模型死锁诊断，性质检查未完成',
    'unknown':'结果未确定', 'not_applicable':'不适用'}
DISPOSITIONS = {'confirmed_in_scope':'已确认违反', 'bounded_no_violation':'有限检查未见违反', 'investigation_lead':'待调查线索'}


def execution_summary(check):
    complete = check.status == ExecutionStatus.COMPLETED and check.exit_code in (0, None)
    if check.action == 'model_syntax':
        return '模型模块语法解析', 'SANY 解析完成' if complete else '解析未完成', '未检查性质或实际轨迹；TLC 配置另行检查'
    if 'probe' in check.action or check.action == 'agent_capabilities':
        return '环境／能力检查', '工具可用' if check.parameters.get('capability_available',complete) else '工具未就绪', '未检查性质'
    if check.action == 'agent_turn':
        return 'Agent 调查', 'Agent 回执已保存；产物另经校验' if complete else 'Agent 调用未完成', '不属于性质证据'
    if check.action == 'exploration':
        return '条件探索', '条件观察完成' if complete else '探索执行失败或未完成', '没有正式性质判定'
    if check.action in {'direct_check','experiment','replay'}:
        return ('直接实现检查' if check.action == 'direct_check' else '探索／实现执行',
            '执行完成；比较见 assessment' if complete else '执行失败或未完成', '进程退出码不等于性质判定')
    if check.action == 'reachability':
        return '触发可达性检查', OUTCOME[check.outcome], '辅助反例不属于协议违反证据'
    if check.action == 'trace_calibration':
        return '轨迹校准', OUTCOME[check.outcome], '轨迹兼容不等于性质成立或违反'
    if check.action == 'model_check':
        return check.action, ('执行超时；' if check.status == ExecutionStatus.TIMEOUT else '')+OUTCOME[check.outcome], '性质检查未完成或无法归属' if check.outcome == 'unknown' else '限于实际 checker 和模型范围'
    return check.action, check.status.value, '未分类执行；不推断性质结果'


def excerpt(text, limit=230):
    """An explicitly labelled excerpt is navigation, never a shortened condition."""
    return text if len(text) <= limit else text[:limit].rsplit(' ',1)[0] + '…'


def cell(value):
    text = json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
    return text.replace('|','\\|').replace('\n','<br>').replace('`','&#96;')


class Archive:
    """Resolve only saved run-relative records, including after moving the archive."""
    def __init__(self, state, root):
        self.root = Path(root).resolve()
        self.original = [Path(state.audit_spec_path).parent.parent] if state.audit_spec_path else []
        self.original += [Path(c.stdout).parent.parent.parent for c in state.checks if c.stdout and Path(c.stdout).parent.parent.name == 'logs']

    def path(self, value):
        if not value:return None
        path = Path(value)
        if path.is_absolute():
            base = next((p for p in [self.root,*self.original] if path.is_relative_to(p)),None)
            if base is None:return None
            path = path.relative_to(base)
        path = self.root / path
        return path if path.resolve().is_relative_to(self.root) and path.is_file() else None

    def link(self, value, label):
        path = self.path(value)
        return f'[{cell(label)}]({quote(path.relative_to(self.root).as_posix())})' if path else f'{cell(label)}（归档字节缺失）'

    def read(self, value):
        path = self.path(value)
        return json.loads(path.read_text()) if path else {}


def report_view(state, archive):
    path = archive.path(f'audit-spec/v{state.audit_spec_version}.json')
    if path and archive.read(path).get('version') != state.audit_spec_version:path = None
    return view(state.model_copy(update={'audit_spec_path':str(path) if path else None}))


def observation_lines(record, artifact, check, archive, event_cache):
    """Select recorded comparisons and operands; never re-assess or invent an oracle."""
    from consensus_assurance.adapters.runners.experiment import extract_events
    plan = archive.read(artifact.get('plan_path'))
    if not plan:return ['模型／缺失制品的观察请按固定 assessment 和原始输出审查。']
    if check.id not in event_cache:
        event_cache[check.id] = extract_events(check.model_copy(update={'stdout':str(archive.path(check.stdout) or ''),
            'stderr':str(archive.path(check.stderr) or '')}))
    events = event_cache[check.id]
    lines = []
    for prop in record.get('properties',[]):
        spec = next((p for p in plan['observable_properties'] if p['checker_id'] == prop['checker_id']),{})
        indices = prop.get('evaluated_indices',[])
        witnesses = prop.get('valid_witness_indices',[])
        lines += [f'固定比较 `{cell(prop["checker_id"])}`：{OUTCOME.get(prop["outcome"],prop["outcome"])}；'
            f'已比较 {len(indices)} 项，完整见证 {len(witnesses)} 项，缺失 {len(prop.get("missing_indices",[]))} 项。', '']
        if prop.get('limitations'):lines += ['观察缺口：'+'；'.join(prop['limitations']), '']
        requested = dict.fromkeys(indices+prop.get('missing_indices',[]))
        selected = {i:events[i] for i in requested if 0 <= i < len(events)}
        if len(selected) != len(requested):lines.append('部分归档事件缺失；不补造观察。')
        if not selected:continue
        fields = dict.fromkeys(spec.get('identity_fields',[]) + [p['field'] for p in
            (spec.get('trigger'),spec.get('antecedent'),spec.get('assertion')) if p])
        # Small scalar records remain readable; complex representations stay in the raw log.
        rows = {}
        for i,event in selected.items():
            values = {}
            aliases = prop.get('correlations',{}).get(str(i),{}).get('alias_indices',{})
            for prerequisite in plan['harness'].get('prerequisites',[]):
                index = aliases.get(prerequisite['alias'])
                for condition in prerequisite['conditions']:
                    value = events[index] if isinstance(index,int) and 0 <= index < len(events) else {}
                    for part in condition['field'].split('.'):
                        value = value.get(part,'未记录') if isinstance(value,dict) else '未记录'
                    values[prerequisite['alias']+'.'+condition['field']] = value
            for key,value in event.items():
                if key.startswith('_ca_'):continue
                if isinstance(value,dict):
                    values.update({key+'.'+k:v for k,v in value.items() if not isinstance(v,(dict,list))})
                elif not isinstance(value,list):values[key] = value
            for key in values:fields.setdefault(key,None)
            rows[i] = values
        lines += ['| 记录字段 | '+' | '.join(f'观察 {n+1}'+('（违反见证）' if i in witnesses else '（未完成）' if i not in indices else '') for n,i in enumerate(selected))+' |',
            '| --- | '+' | '.join('---' for _ in selected)+' |']
        for key in fields:
            lines.append('| '+cell(key)+' | '+' | '.join(cell(rows[i].get(key,'未记录')) for i in selected)+' |')
        correlations = prop.get('correlations',{})
        lines += ['', '前提关联：'+'；'.join(f'观察 {n+1} → '+cell(correlations.get(str(i),{}).get('status','未记录'))
            for n,i in enumerate(selected))+'。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。', '']
    return lines


def interruption_lines(check, archive):
    from consensus_assurance.adapters.agents.backend import codex_events, codex_diagnostic
    saved = check.model_copy(update={'stdout':str(archive.path(check.stdout) or '')})
    diagnostic = codex_diagnostic(codex_events(saved)) if check.action == 'agent_turn' else {}
    limit = check.parameters.get('timeout_limit','未记录')
    seconds = check.parameters.get('timeout_seconds','未记录')
    lines = [f'中断调用 `{check.action}`：status=`{check.status.value}`；timeout_limit=`{limit}`；timeout_seconds=`{seconds}`。',
        '；'.join([archive.link(f'logs/{check.id}/check.json','调用记录'),archive.link(check.stdout,'stdout'),archive.link(check.stderr,'stderr')])]
    if check.action == 'agent_turn':
        lines.append('可靠完成回执：'+('已记录完成事件；产物另行校验。' if check.parameters.get('agent_turn_completed') else '未记录；未完成草稿不受理。'))
        lines.append(('可信传输诊断（不能定位故障责任方）：' if diagnostic.get('transport_failure') else '调用诊断（不据此授权重试）：')+
            excerpt(diagnostic['message']) if diagnostic.get('message') else '单轮超时，具体原因未知。' if check.status == ExecutionStatus.TIMEOUT else '具体原因见原始调用记录。')
    return lines


def milestone_lines(state, research, archive, checks):
    """Keep readiness and actual executions regardless of product action labels."""
    selected = {}
    changes = [s for s in state.selections if s.get('map_updated')]
    for s in changes:
        version = s['accepted_versions']['audit_spec']
        if (archive.read(f'audit-spec/v{version}.json').get('core_overview') or {}).get('status') == 'usable':
            selected[s['operation_id']] = ('双主线概览已就绪', archive.link(f'audit-spec/v{version}.json','当时地图'))
            break
    growth = [s for s in state.selections if s.get('map_delta') or s.get('feedback',{}).get('understanding') == 'updated'
        or s.get('accepted_versions',{}).get('artifacts') or s.get('released_candidate_ids')]
    for s in growth[-3:]:
        selected.setdefault(s['operation_id'], ('认识／制品更新：'+excerpt(s.get('feedback',{}).get('answered') or s['rationale'],200),
            archive.link(f'submissions/{s["operation_id"]}/accepted.json','完整交接')))
    current = {a['id'] for a in research['artifacts']}
    for check in checks.values():
        if check.action == 'exploration' or (check.direct_check_id or check.model_id) in current:
            selected[check.id] = ('实际执行：'+'；'.join(execution_summary(check)[:2]),archive.link(f'logs/{check.id}/check.json','执行记录'))
    interrupted = [c for c in checks.values() if c.action == 'agent_turn' and c.status != ExecutionStatus.COMPLETED]
    for check in interrupted[-3:]:
        selected[check.id] = ('Agent 调查中断；后续记录不抹掉此失败',archive.link(f'logs/{check.id}/check.json','中断记录'))
    lines = []
    for id in sorted(selected, key=lambda id:list(checks).index(id) if id in checks else -1):
        title, link = selected[id]
        check = checks.get(id)
        timing = '时间未记录'
        if check and check.ended_at:
            ended = datetime.fromisoformat(check.ended_at)
            timing = ended.strftime('%H:%M:%S %z') + f'（距创建墙钟 {(ended-datetime.fromisoformat(state.created_at)).total_seconds():.1f} 秒，含暂停间隔）'
            if check.started_at:
                duration = (ended-datetime.fromisoformat(check.started_at)).total_seconds()
                timing += f'；{"Agent 回合墙钟" if check.action == "agent_turn" else "目标工具耗时"} {duration:.2f} 秒'
        lines += ['', '- '+timing+' · '+title+'。'+link]
        if check in interrupted and id != state.run_stop.get('operation_id'):
            lines += interruption_lines(check,archive)
    return lines + ['', archive.link('events.jsonl','完整运行时序')+'；'+archive.link('state.json','完整研究交接与执行历史')]


def render_report(state, root):
    archive = Archive(state,root)
    research = report_view(state,archive)
    link = archive.link
    map_link = link(research['audit_spec_path'],f'地图 v{state.audit_spec_version}：概览、Behavior／Fact 与来源')
    checks = {c.id:c for c in state.checks}
    artifacts = {a['id']:a for a in research['artifacts']}
    results = sorted(research['conclusions'],key=lambda r:(list(DISPOSITIONS).index(r['disposition']),
        ['consensus_safety','bounded_liveness','implementation_semantics'].index(r['concern'])))
    reviews = {r.id:r for r in state.semantic_reviews}
    event_cache = {}
    config, capacity = state.config, research['capacity']
    formal = [c for c in state.checks if c.action == 'direct_check']
    explorations = [c for c in state.checks if c.action == 'exploration']
    exploration_records = exploration_results(state, archive.read)
    failures = [c for c in formal+explorations if c.status != ExecutionStatus.COMPLETED or c.exit_code not in (0,None)]
    explained = [c for c in research['candidates'] if c['status'] == 'explained' and not c['results']]
    stop = state.run_stop
    stop_label = ({'user_stop':'实际取消','resource_limit':'资源边界','tool_gap':'服务／权限／工具中断'}.get(stop.get('reason'),'中断')
        if stop.get('origin') == 'controller' else {'insufficient_basis':'研究依据不足','bounded_completed':'所声明范围完成',
        'no_actionable_direction':'未选择可推进方向'}.get(stop.get('reason'),'研究停止')) if stop else '尚未结束'
    lines = ['# 共识审计研究报告', '', '## 运行概览', '',
        f'审计目标 **{cell(config.get("target",{}).get("variant") or Path(state.snapshot.repo).name)}**。'
        f'本轮有 {len(results)} 项已产生观察的正式问题：'+ '、'.join(f'{label} {sum(r["disposition"]==key for r in results)} 项' for key,label in DISPOSITIONS.items())+
        f'；另有源码解释 {len(explained)} 项、探索执行 {len(explorations)} 次。正式义务共 {len(state.claims)} 项，执行次数不等于问题数。', '',
        f'实际持续 **{state.elapsed_seconds/60:.2f} 分钟**；结束类型：**'+('控制器记录的' if stop.get('origin') == 'controller' else 'Agent 提出的' if stop else '')+stop_label+'**。',
        f'剩余 {capacity["remaining_seconds"]:.2f} 秒、{capacity["remaining"]["agent_calls"]} 次 Agent 调用、'
        f'{capacity["remaining"]["experiments"]} 次控制器目标执行。源码调查能力：'+('仍有预算' if capacity['source_investigation'] else '无剩余预算')+'。', '',
        '| 资源 | 配置 | 已用 | 剩余 |', '| --- | ---: | ---: | ---: |',
        f'| 总时间（秒） | {config["budget"]["total_seconds"]} | {state.elapsed_seconds:.2f} | {capacity["remaining_seconds"]:.2f} |']
    for key,label in [('agent_calls','Agent 调用'),('experiments','控制器目标执行'),('audit_units','新 Unit'),('semantic_reviews','语义复核'),('revisions','修订'),('model_checks','模型工具')]:
        enabled = config.get('verifier_backend','none') != 'none' if key == 'model_checks' else config.get('allow_experiments',False) and config.get('execution_backend','none') != 'none' if key == 'experiments' else True
        lines.append(f'| {label} | {config["budget"].get(key,0)} | {state.usage.get(key,0)} | '+(str(capacity['remaining'][key]) if enabled else '未启用')+' |')
    lines += ['', f'目标执行组成：正式检查 {len(formal)} 次＋探索 {len(explorations)} 次，其中失败／未完成 {len(failures)} 次；失败和重试照常计数。'
        '会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。',
        f'模型检查：{config.get("verifier_backend") if config.get("verifier_backend","none") != "none" else "保留实际模型执行记录" if state.models else "未使用 TLA+／TLC"}。'
        '新 Unit 入场能力不保证剩余额度足够完成检查与复核。', '',
        f'元数据：源码 `{state.snapshot.commit or state.snapshot.id}`；实际方法 `{state.framework_revision}`；展示版本 `{manifest()["version"]}`；'
        f'模式 {state.mode}/{state.analysis_mode}；执行后端 `{config.get("execution_backend","none")}`／包 `{config.get("target",{}).get("execution_package",".")}`；'
        f'模型 `{config.get("agent_model") or "默认"}`／`{config.get("agent_reasoning_effort") or "默认"}`。重新渲染不代表重新审计。', '',
        '停止依据（记录摘录）：'+excerpt(stop.get('rationale') or state.stop_reason,190)+'；'+link('state.json','完整停止记录')+'。', '']
    stopped_check = checks.get(stop.get('operation_id'))
    if stopped_check and (stopped_check.status != ExecutionStatus.COMPLETED or stopped_check.exit_code not in (0,None)):
        lines += interruption_lines(stopped_check,archive)
    lines += ['', '## 主要结果', '']
    if results or explained:
        lines += ['| 问题 | 当前结果 | 实际回答摘录 | 证据 |', '| --- | --- | --- | --- |']
    else:
        lines += ['尚无正式性质判定；已保存的整体理解与条件探索见下文，不能据此断言目标没有问题。']
    entries = []
    rows = {key:[] for key in DISPOSITIONS}
    for n,result in enumerate(results,1):
        records = [r for r in research['assessments'] if r.get('claim_id') == result['claim_id']]
        items = [item for record in records for rid in record.get('review_ids',[]) if rid in reviews for item in reviews[rid].items
            if item.target_id == (record.get('direct_check_id') or record.get('model_id')) and
            reviews[rid].target_versions.get(item.target_id) == artifacts[item.target_id]['version']]
        title = next((i.report_title for i in reversed(items) if i.report_title),None)
        title = title or excerpt(result['question'] or result['description'],130)+'（原文摘录）'
        review_operations = {reviews[rid].check_id for record in records for rid in record.get('review_ids',[]) if rid in reviews}
        feedback = next((s.get('feedback',{}) for s in reversed(state.selections) if s['operation_id'] in review_operations),{})
        answer = next((i.report_answer for i in reversed(items) if i.report_answer),None) or feedback.get('answered')
        entries.append((result,records,answer,title))
        rows[result['disposition']].append(f'| {n}. {cell(title)} | {DISPOSITIONS[result["disposition"]]} | {cell(excerpt(answer,170)) if answer else "见下方固定观察"} | {link("state.json",result["claim_id"])} |')
    lines += rows['confirmed_in_scope']+rows['bounded_no_violation']
    for c in explained:lines.append(f'| {cell(excerpt(c["question"]["question"],130))} | 源码解释，未经性质执行 | {cell(excerpt("；".join(c["question"]["counterevidence"]),170))} | {link("state.json","候选记录")} |')
    lines += rows['investigation_lead']
    for n,(result,records,answer,title) in enumerate(entries,1):
        scope = result['scope']
        lines += ['', f'### {n}. {title}', '', f'**{DISPOSITIONS[result["disposition"]]}**。要求原文：{result["description"]}', '',
            '决定性范围：'+scope['description'], '；'.join(scope['assumptions'])+'。' if scope['assumptions'] else '',
            '范围参数：'+cell(scope['parameters']) if scope['parameters'] else '',
            '排除：'+'；'.join(scope['excluded'])+'。' if scope['excluded'] else '']
        if answer:lines += ['', '本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：'+answer]
        if result['blockers']:lines += ['', '当前争议／阻塞：'+'；'.join(result['blockers'])]
        for record in records:
            artifact = artifacts[record.get('direct_check_id') or record.get('model_id')]
            check = checks[record['experiment_check_id']]
            lines += ['', f'制品 v{artifact["version"]}；机械比较 **{OUTCOME.get(record["outcome"],record["outcome"])}**；'
                f'对应性复核 {record.get("correspondence") or "待复核"}；独立场景完整处置：{record.get("reviewed_complete",False)}。',
                '；'.join([link(artifact.get('harness_path') or artifact.get('path'),'固定测试／模型'),
                    link(artifact.get('plan_path') or artifact.get('bundle_path'),'条件与检查器'),link(check.stdout,'原始观察'),
                    link(str(Path(artifact.get('plan_path') or artifact.get('bundle_path')).parent / (check.id+'-assessment.json')),'assessment'),
                    *[link(f'submissions/{reviews[rid].check_id}/accepted.json','对应性复核') for rid in record.get('review_ids',[]) if rid in reviews]]), '']
            lines += observation_lines(record,artifact,check,archive,event_cache)
            from consensus_assurance.workflow.reviews import lineage
            ancestors=lineage(state,next(a for a in state.direct_checks+state.models if a.id==artifact['id']))
            old = [c for c in failures if c.direct_check_id in ancestors or c.model_id in ancestors]
            for failed in old:lines.append('该问题保留的失败执行：'+link(failed.stdout,'原始失败')+'；'+link(failed.stderr,'诊断')+'。旧失败不覆盖当前结果。')
    for artifact in research['artifacts']:
        if 'bundle_path' not in artifact:continue
        searches = [c for c in state.checks if c.model_id == artifact['id'] and c.action in {'model_check','model_syntax'}]
        lines += ['', '局部模型（与实现证据独立）：'+link(artifact['bundle_path'],'固定模型制品')+'；'+link(artifact['path'],'模型行为')]
        for c in {c.action:c for c in searches}.values():lines.append('- '+'；'.join(execution_summary(c))+'；'+link(c.stdout,'实际输出')+'；'+link(c.stderr,'诊断'))
    for entry in exploration_records:
        lines += ['', '条件探索：'+excerpt(entry['question'] or '问题原稿字节缺失',200),
            '所选问题／策略（原文摘录）：'+excerpt(entry['rationale'] or '见固定原稿',240),
            link(entry['submission'],'受理问题、条件与来源')+'；'+'；'.join(link(path,'固定输入') for path in entry['inputs'])]
        for execution in entry['executions']:
            check = checks[execution['check_id']]
            lines += ['；'.join(execution_summary(check)[1:])+'。'+link(execution['record'],'执行记录')+'；'+
                link(execution['stdout'],'实际输出')+'；'+link(execution['stderr'],'诊断'),
                '；'.join(link(path,'执行文件清单') for path in execution['artifacts'])]
            from consensus_assurance.adapters.runners.experiment import extract_events
            events = extract_events(check.model_copy(update={'stdout':str(archive.path(check.stdout) or ''),
                'stderr':str(archive.path(check.stderr) or '')}))
            for event in events[:2]:
                lines.append('结构化观察原值（非性质判定；全部事件见日志）：'+cell(excerpt(json.dumps(
                    {k:v for k,v in event.items() if not k.startswith('_ca_')},ensure_ascii=False),300)))
        if not entry['executions']:lines.append('已受理问题，尚无保存的执行记录。')
        if entry['feedback']:
            saved = entry['feedback'][-1]['submission']
            feedback = archive.read(saved).get('feedback') or {}
            lines += ['执行后交接摘录：'+excerpt(feedback.get('answered','归档字节缺失'),260)+'；'+link(saved,'完整解释与剩余问题')]
            if feedback.get('remaining'):lines.append('该交接保留的未知：'+'；'.join(feedback['remaining']))
        else:lines.append('尚无受理的执行后解释；原观察可继续研究，不自动生成正式义务或审批待办。')
    lines += ['', '## 研究过程与认识增长', '',
        'A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。',
        map_link+'。']
    if research['core_overview']:
        for key,label in [('formation','共识形成与推进'),('context','上下文／权威转换'),('connection','两条主线的连接')]:
            lines.append('- '+label+'（原文导航摘录）：'+excerpt(research['core_overview'][key]['explanation'],220))
    if research['understanding_status'] != 'usable':lines.append('双主线初始理解尚未完成；定向问题之外不能据片段宣称整体就绪。')
    lines += milestone_lines(state,research,archive,checks)
    lines += ['', '## 当前未决事项', '', '已选检查暂无欠账；研究范围仍可开放。' if not research['pending_work'] else '已选检查／争议仍有待办：']
    for item in research['pending_work']:lines.append('- '+link('research.json',item['id'])+'：'+'；'.join(item['reasons']))
    for surface in research['frontier']['surfaces']:
        if surface['disposition'] not in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'}:continue
        ref = 'surface:'+surface['entry_point']
        feedback = next((s['feedback'] for s in reversed(state.selections) if ref in s.get('feedback',{}).get('ref_ids',[])),{})
        options = [o for o in stop.get('frontier_comparison',[]) if ref in o['ref_ids']]
        related = [entry for entry in exploration_records if ref in entry['ref_ids'] or
            {c['check_id'] for c in entry['executions']} & set(feedback.get('ref_ids',[]))]
        lines += ['', '**开放责任：'+surface['entry_point']+'**', '',
            '保存的交接摘录：'+feedback['answered'] if feedback else '地图保留的缺口：'+surface['reason']]
        if feedback.get('remaining'):lines.append('该交接保留的未知：'+'；'.join(feedback['remaining']))
        for entry in related:
            lines.append('相关探索的实际执行与后续解释见主要结果；'+link(entry['submission'],'已受理问题与计划'))
        lines += ['可改变判断的下一步：'+'；'.join(o['next_step'] for o in options) if options else
            '已有调查计划见相关探索原稿。' if related else '尚未记录后续步骤。', map_link]
    for c in research['candidates']:
        if c['results'] and not c['resume_conditions'] or c['status'] == 'explained':continue
        lines += ['', '候选：'+c['question']['question'], '保存的语义未知：'+'；'.join(c['question']['unknowns']),
            '恢复条件：'+'；'.join(c['resume_conditions']),link('state.json','候选原文与历史')]
    if stop.get('resume_conditions'):lines += ['', '本轮记录的恢复条件：'+'；'.join(stop['resume_conditions'])]
    lines += ['', '## 证据与运行说明', '',
        '；'.join(link(name,label) for name,label in [('state.json','完整状态、版本与争议'),('research.json','当前研究索引'),
            ('config.json','实际配置'),('events.jsonl','事件时序'),('audit-method.md','实际加载方法')]),
        '环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。模型结果与实现证据分开，脚本化 Agent 产品不证明自主发现。']
    for c in failures:lines += ['- 失败／未完成：'+link(c.stdout,c.action)+'；'+link(c.stderr,'stderr')+'；'+link(f'logs/{c.id}/check.json','执行记录')]
    if state.current_submission.get('phase') == 'received':lines.append('可靠回执尚未受理：'+link(f'submissions/{state.current_submission["operation_id"]}/raw.json','固定原稿')+'；保存字节不产生 Evidence。')
    path = archive.root / 'report.md'
    path.write_text('\n'.join(lines)+'\n')
    return path
