"""Human reading view of retained conclusions; never executes or repairs research state."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.workflow.research import view, exploration_results, comparison_observed, execution_cost
from consensus_assurance.workflow.prompts import manifest


OUTCOME = {'holds':'有限检查未见违反', 'violated':'观察到违反',
    'tests_passed':'所执行测试通过', 'tests_failed':'所执行测试失败',
    'unknown':'结果未确定', 'not_applicable':'不适用'}
DISPOSITIONS = {'confirmed_in_scope':'已确认违反', 'bounded_no_violation':'有限检查未见违反', 'investigation_lead':'待调查线索'}
PROGRESS = {'no_fixed_check':'义务已受理，尚无固定检查记录', 'no_execution':'检查已固定，尚无执行记录',
    'execution_incomplete':'执行失败或未完成', 'no_assessment':'执行完成，尚无评估记录',
    'assessment_incomplete':'评估已保存，当前检查尚未完整处置', 'assessed':'当前检查已完整处置'}
INLINE_LIMIT = 200


def execution_summary(check):
    complete = check.status == ExecutionStatus.COMPLETED and check.exit_code in (0, None)
    phase = {'build_or_setup':'未进入测试：包发现／构建准备失败',
        'test_failure':'已进入测试，执行失败；性质归因另核',
        'panic_unattributed':'已进入测试，panic 尚未归因',
        'execution_unclassified':'未进入所选测试，失败阶段未确定'}.get(check.parameters.get('failure_class'))
    if check.outcome == 'not_applicable':phase = '所声明检查未完成：没有匹配测试或全部跳过'
    if 'probe' in check.action or check.action == 'agent_capabilities':
        return '环境／能力检查', '工具可用' if check.parameters.get('capability_available',complete) else '工具未就绪', '未检查性质'
    if check.action == 'agent_turn':
        return 'Agent 调查', 'Agent 回执已保存；产物另经校验' if complete else 'Agent 调用未完成', '不属于性质证据'
    if check.action == 'exploration':
        progress = ({0:'探索执行正常结束',None:'记录标记结束，退出信息缺失'}.get(check.exit_code,'探索执行非零退出')
            if check.status == ExecutionStatus.COMPLETED else f'探索执行未完成（status={check.status.value}）')
        return ('条件探索', (phase if check.status in {ExecutionStatus.COMPLETED,ExecutionStatus.ERROR} else None) or progress,
            '前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定')
    if check.action in {'direct_check','experiment','replay'}:
        return ('直接实现检查' if check.action == 'direct_check' else '探索／实现执行',
            phase or ('执行完成；比较见 assessment' if complete else '执行失败或未完成'), '进程退出码不等于性质判定')
    return check.action, check.status.value, '未分类执行；不推断性质结果'


def excerpt(text, limit=230):
    """An explicitly labelled excerpt is navigation, never a shortened condition."""
    return text if len(text) <= limit else text[:limit].rsplit(' ',1)[0] + '…'


def cell(value, locator=''):
    text = json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
    if len(text) > INLINE_LIMIT:
        text = f'{type(value).__name__}，{len(text)} 字符；首尾预览：{text[:INLINE_LIMIT//4]}…{text[-INLINE_LIMIT//4:]}'
    else:locator = ''
    return text.replace('|','\\|').replace('\n','<br>').replace('`','&#96;') + ('；'+locator if locator else '')


def assessment_progress(record):
    opinion = record.get('correspondence') or ('尚未记录' if 'correspondence' in record else '信息不足')
    observed=comparison_observed(record)
    return ('检查未执行到比较' if observed is False else '实际比较依据不足' if observed is None else
        '机械比较：'+OUTCOME.get(record.get('outcome'),'信息不足'))+'；对应性意见：'+opinion


def conclusion_label(result):
    if result['disposition']!='investigation_lead' or result['comparison_observed'] is True:return DISPOSITIONS[result['disposition']]
    return '检查未执行到比较' if result['comparison_observed'] is False else '实际比较依据不足'


def execution_location(check, archive):
    package = check.parameters.get('execution_package')
    filename = check.parameters.get('harness_filename')
    location = f'固定执行包 `{cell(package)}`；主文件 `{cell(filename)}`' if package is not None else (
        f'固定主文件 `{cell(filename)}`' if filename else '旧记录未固定单次位置；按历史控制器命令和输入解释，嵌套启动器不等于直接切包')
    timing=execution_cost(check)
    for key,label in [('action_seconds','目标动作总耗时'),('process_seconds','执行进程耗时')]:
        location+='；'+label+(f' {timing[key]:.2f} 秒' if timing[key] is not None else '未完整记录')
    if check.parameters.get('build_inputs'):
        location+='；'+archive.link(check.parameters['build_inputs'],'构建依据')
    if check.parameters.get('execution_backend',{}).get('name')=='cargo':location+='；'+failure_detail(check,archive)
    return location+'；'+archive.link(f'logs/{check.id}/check.json','实际命令、工具版本与输入记录')


def failure_detail(check, archive):
    """Legacy output can explain a technical turn without rewriting its saved CheckRun."""
    if check.parameters.get('execution_backend',{}).get('name')=='cargo':
        from consensus_assurance.adapters.runners.cargo_build import diagnostics
        facts=check.parameters
        if 'build_finished' not in facts:
            paths=[archive.path(p) for p in (check.stdout,check.stderr)]
            facts=diagnostics('\n'.join(p.read_text() for p in paths if p))
        if facts.get('test_started'):
            return '已观察到测试启动；'+('正常退出，性质比较另核' if check.status==ExecutionStatus.COMPLETED and check.exit_code==0 else '执行失败或未完成')
        if facts.get('build_finished') is True:return '构建完成，未观察到测试启动'
        if facts.get('build_finished') is False:return '构建失败，未观察到测试启动'
        if facts.get('build_activity'):
            return ('构建期间超时' if check.status==ExecutionStatus.TIMEOUT else '已记录构建活动，构建未完成')+'；未观察到测试启动'
        return '构建／测试阶段依据不足；'+check.status.value
    if ('failure_class' in check.parameters and 'test_started' in check.parameters
            or check.status not in {ExecutionStatus.COMPLETED,ExecutionStatus.ERROR}
            or check.parameters.get('execution_backend',{}).get('name') not in {'go_module','hashicorp_raft'}):
        return execution_summary(check)[1]
    from consensus_assurance.adapters.runners.go_module import go_test_diagnostics
    paths = [archive.path(p) for p in (check.stdout,check.stderr)]
    text = '\n'.join(p.read_text() for p in paths if p)
    facts = go_test_diagnostics(text)
    interpreted = check.model_copy(update={'parameters':{**check.parameters,**facts}})
    return '历史输出诊断：'+execution_summary(interpreted)[1]+'（原记录未改写）'


def assessment_obstacle(record, check, archive):
    """Explain the nearest recorded gap without ranking or rewriting raw blockers."""
    facts=check.parameters
    failed=check.status!=ExecutionStatus.COMPLETED or check.exit_code not in (0,None)
    stage=facts.get('preparation_stage')
    if failed and facts.get('test_started') is False and (stage or facts.get('failure_class')=='build_or_setup'
            or facts.get('build_finished') is False or facts.get('build_activity')):
        return (f'准备阶段 {stage}：'+('超时' if check.status==ExecutionStatus.TIMEOUT else '失败／未完成') if stage else failure_detail(check,archive))+'；测试未启动，尚无目标比较'
    if record.get('confirmed') and record.get('bounded_complete') is False:
        return '完整反例已确认；另有独立场景覆盖缺口'
    missing=[]
    prerequisite=record.get('prerequisites',{})
    if prerequisite.get('status') not in (None,'matched'):missing.append(prerequisite.get('reason') or '前提未完整关联')
    for prop in record.get('properties',[]):
        if prop.get('comparison_complete') is False:
            missing.append(str(prop.get('checker_id','性质'))+'：'+'；'.join(prop.get('limitations') or ['观察／关联不完整']))
    if record.get('parsing_errors'):missing.append('事件记录不完整或无法解析')
    if missing:return f'观察／关联尚不完整；执行 status={check.status.value}，exit={check.exit_code}：'+excerpt('；'.join(missing),110)
    progress=assessment_progress(record)
    if record.get('open_issue_ids') or record.get('correspondence') in {'revision_needed','disputed','insufficient_basis'}:
        return '已有复核争议，处理要求见对应争议；'+progress
    if comparison_observed(record) is True and 'correspondence' in record and record['correspondence'] is None:
        return progress+'；待当前版本复核'
    return '当前检查尚未完整处置；'+(failure_detail(check,archive) if failed else
        progress+('；'+excerpt('；'.join(record['blockers']),160) if record.get('blockers') and record.get('correspondence')=='no_issue_found' else ''))


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
    from consensus_assurance.core.events import field, MISSING
    plan = archive.read(artifact.get('plan_path'))
    if not plan:return ['固定计划字节缺失；观察范围请按保存的 assessment 和原始输出审查。']
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
        predicates = [p for p in (spec.get('trigger'),spec.get('antecedent'),spec.get('assertion')) if p]
        fields = dict.fromkeys(spec.get('identity_fields',[]) + [p['field'] for p in predicates])
        prerequisites = plan['harness'].get('prerequisites',[])
        references = dict.fromkeys(p['reference'] for p in predicates + [c for req in prerequisites for c in req['conditions']] if p.get('reference'))
        references.update({req['alias']+'.'+c['field']:None for req in prerequisites for c in req['conditions']})
        rows = {}
        for i,event in selected.items():
            locations = {key:(i,key) for key in fields}
            aliases = prop.get('correlations',{}).get(str(i),{}).get('alias_indices',{})
            locations.update({key:(aliases.get(key.partition('.')[0]),key.partition('.')[2]) for key in references})
            # Keep harness-reported scalar inputs too; their full values stay in the log.
            for key,value in event.items():
                if key.startswith('_ca_'):continue
                extras = {key+'.'+k:v for k,v in value.items()} if isinstance(value,dict) else {key:value}
                for name,extra in extras.items():
                    if not isinstance(extra,(dict,list)):
                        locations.setdefault(name,(i,name))
            values = {}
            for key,(index,name) in locations.items():
                value = field(events[index],name) if isinstance(index,int) and 0 <= index < len(events) else MISSING
                locator = archive.link(check.stdout,f'{check.id} / event[{index}] / {name}')
                values[key] = '未记录' if value is MISSING else cell(value,locator)
                fields.setdefault(key,None)
            rows[i] = values
        lines += ['| 记录字段 | '+' | '.join(f'观察 {n+1}'+('（违反见证）' if i in witnesses else '（未完成）' if i not in indices else '') for n,i in enumerate(selected))+' |',
            '| --- | '+' | '.join('---' for _ in selected)+' |']
        for key in fields:
            lines.append('| '+cell(key)+' | '+' | '.join(rows[i].get(key,'未记录') for i in selected)+' |')
        correlations = prop.get('correlations',{})
        lines += ['', '前提关联：'+'；'.join(f'观察 {n+1} → '+cell(correlations.get(str(i),{}).get('status','未记录'))
            for n,i in enumerate(selected))+'。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。', '']
    return lines


def interruption_lines(check, archive):
    from consensus_assurance.adapters.agents.backend import codex_events, codex_diagnostic
    saved = check.model_copy(update={'stdout':str(archive.path(check.stdout) or '')})
    diagnostic = codex_diagnostic(codex_events(saved)) if check.action == 'agent_turn' else {}
    limit = check.parameters.get('timeout_limit','未记录')
    seconds = check.parameters.get('timeout_seconds','未记录')
    lines = ['<details><summary>中断调用详情</summary>', '', f'中断调用 `{check.action}`：status=`{check.status.value}`；配置上限 timeout_limit=`{limit}`；timeout_seconds=`{seconds}`（配置值不表示触发了超时）。',
        '；'.join([archive.link(f'logs/{check.id}/check.json','调用记录'),archive.link(check.stdout,'stdout'),archive.link(check.stderr,'stderr')])]
    if check.status == ExecutionStatus.TIMEOUT:
        lines.append({'total_seconds':'总运行预算到达，控制器停止最后一次调用；已受理结果保留。',
            'agent_turn_timeout':'本轮 Agent 调用达到单轮上限；恢复资格仍按原合同处理。',
            'action_timeout':'目标动作达到执行上限，未完成；不据此生成 holds 或活性违反。'}.get(limit,
            '超时上限依据不足，具体原因见原始调用记录。'))
    if check.action == 'agent_turn':
        lines.append('可靠完成回执：'+('已记录完成事件；产物另行校验。' if check.parameters.get('agent_turn_completed') else '未记录；未完成草稿不受理。'))
        if diagnostic.get('message'):lines.append(('可信传输诊断（不能定位故障责任方）：' if diagnostic.get('transport_failure') else '调用诊断（不据此授权重试）：')+excerpt('\n'.join(dict.fromkeys(diagnostic['message'].splitlines()))))
    return lines + ['', '</details>']


def milestone_lines(state, research, archive, checks, titles):
    """Keep readiness and actual executions regardless of product action labels."""
    selected = {}
    changes = [s for s in state.selections if s.get('map_updated')]
    for s in changes:
        version = s['accepted_versions']['audit_spec']
        if (archive.read(f'audit-spec/v{version}.json').get('core_overview') or {}).get('status') == 'usable':
            selected[s['operation_id']] = ('双主线概览已就绪', archive.link(f'audit-spec/v{version}.json','当时地图'))
            break
    growth = [s for s in state.selections if not s.get('duplicate_of') and (s.get('map_delta') or s.get('feedback',{}).get('understanding') == 'updated'
        or s.get('accepted_versions',{}).get('artifacts') or s.get('released_candidate_ids'))]
    for s in growth[-3:]+[s for s in state.selections if s['action'] in {'review','revise_check','pause','explained','continue','obligation'} and 'accepted_versions' in s]:
        review=next((r for r in state.semantic_reviews if r.check_id==s['operation_id']),None)
        title = next((i.report_title for i in review.items if i.report_title),None) if review else None
        detail='；'+'、'.join(f'v{review.target_versions.get(i.target_id,"?")} {i.aspect}: {i.status}' for i in review.items) if review else ''
        selected.setdefault(s['operation_id'], (f'受理 {s["action"]}：'+excerpt(title or s['rationale'],140)+detail,
            archive.link(f'submissions/{s["operation_id"]}/accepted.json','完整交接')))
    from consensus_assurance.workflow.reviews import lineage
    current = {a['id'] for a in research['artifacts']}
    ancestors = set().union(*(lineage(state,a) for a in state.direct_checks if a.id in current))
    artifacts = {a.id:a for a in state.direct_checks}
    for check in checks.values():
        if check.action == 'exploration' or (check.direct_check_id) in current:
            selected[check.id] = ('实际执行：'+excerpt(titles.get(check.id,execution_summary(check)[0]),140)+'；'+execution_summary(check)[1],archive.link(f'logs/{check.id}/check.json','执行记录'))
        elif check.direct_check_id in ancestors:
            artifact=artifacts[check.direct_check_id]
            assessment=str(Path(artifact.plan_path).parent/(check.id+'-assessment.json'))
            saved=archive.read(assessment)
            comparison='；保存的机械比较：'+OUTCOME.get(saved['outcome'],saved['outcome']) if saved.get('outcome') else ''
            execution='目标进程执行成功' if check.status==ExecutionStatus.COMPLETED and check.exit_code==0 else failure_detail(check,archive)
            selected[check.id] = (f'修订前 v{artifact.version}：'+execution+comparison+'；复核与修订见各自后续节点',
                archive.link(artifact.plan_path,'原固定输入')+'；'+archive.link(f'logs/{check.id}/check.json','原执行记录')+'；'+archive.link(assessment,'原保存评估'))
    interrupted = [c for c in checks.values() if c.action == 'agent_turn' and c.status != ExecutionStatus.COMPLETED]
    for check in interrupted[-3:]:
        selected[check.id] = ('Agent 调查中断；后续记录不抹掉此失败',archive.link(f'logs/{check.id}/check.json','中断记录'))
    lines = []
    for id in sorted(selected, key=lambda id:list(checks).index(id) if id in checks else -1):
        title, link = selected[id]
        check = checks.get(id)
        timing = '时间未记录'
        if check and check.ended_at:
            minutes = (datetime.fromisoformat(check.ended_at)-datetime.fromisoformat(state.created_at)).total_seconds()/60
            timing = f'{minutes:.2f} 分钟'
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
    pending_issues={p['id'] for p in research['pending_work'] if p['kind']=='review_issue'}
    issues = {i.id:i.model_dump(mode='json') for i in state.review_issues if i.id in pending_issues}
    issue_links = {id:f'[争议 {id}](#issue-{id})（'+{'reading':'补充来源调查','revision':'修订并复核',
        'investigation':'继续核对','blocked':'保留阻塞依据'}[issue['disposition']]+'）' for id,issue in issues.items()}
    event_cache = {}
    config, capacity = state.config, research['capacity']
    provider=config.get('codex_provider')
    provider_label=provider['id'] if provider else ('Codex 默认' if 'codex_provider' in config else '未记录')
    last_turn=next((c for c in reversed(state.checks) if c.action=='agent_turn'),None)
    formal = [c for c in state.checks if c.action == 'direct_check']
    explorations = [c for c in state.checks if c.action == 'exploration']
    exploration_records = exploration_results(state, archive.read)
    failures = [c for c in formal+explorations if c.status != ExecutionStatus.COMPLETED or c.exit_code not in (0,None)]
    explained = [c for c in research['candidates'] if c['status'] == 'explained' and not c['results'] and
        not any(u['candidate_id']==c['id'] for u in research['units'])]
    ongoing = [c for c in research['candidates'] if c['status'] not in {'explained','closed'} and
        (not c['results'] or c['resume_conditions'] or any(u['candidate_id']==c['id'] and
            any(p['record_status']!='assessed' for p in u['progress']) for u in research['units']))]
    candidate_links = {c['id']:f'[候选 {n}](#candidate-{c["id"]})' for n,c in enumerate(ongoing,1)}
    claim_links = {c['id']:f'[{c["id"]}](#claim-{c["id"]})' for c in research['claims']}
    def progress_text(claim_id):
        current = [p for u in research['units'] for p in u['progress'] if p['claim_id']==claim_id and p['record_status']!='assessed']
        records=[];refs=[]
        for r in research['assessments']:
            if not any(p.get('artifact_id')==r['direct_check_id'] and p.get('check_id')==r['experiment_check_id'] for p in current):continue
            check=checks[r['experiment_check_id']]
            records.append(assessment_obstacle(r,check,archive))
            refs.extend(issue_links[id] for id in r.get('open_issue_ids',[]) if id in issue_links)
            refs.append(link(str(Path(artifacts[r['direct_check_id']]['plan_path']).parent/(check.id+'-assessment.json')),'完整评估与原因'))
        refs += [link(artifacts[p['artifact_id']]['plan_path'],'固定计划') for p in current if p['record_status'] in {'no_execution','no_assessment'}]
        refs += [link(f'logs/{p["check_id"]}/check.json','执行记录') for p in current if p['record_status']=='no_assessment']
        reasons=records or [PROGRESS[p['record_status']] for p in current]
        return '；'.join([cell(excerpt(reason,180)) for reason in list(dict.fromkeys(reasons))[:2]]+list(dict.fromkeys(refs)))
    stop = state.run_stop
    stop_label = ({'user_stop':'实际取消','resource_limit':'资源边界','tool_gap':'服务／权限／工具中断'}.get(stop.get('reason'),'中断')
        if stop.get('origin') == 'controller' else {'insufficient_basis':'研究依据不足','bounded_completed':'所声明范围完成',
        'no_actionable_direction':'未选择可推进方向'}.get(stop.get('reason'),'研究停止')) if stop else '尚未结束'
    lines = ['# 共识审计研究报告', '', '## 运行概览', '',
        f'审计目标 **{cell(config.get("target",{}).get("variant") or Path(state.snapshot.repo).name)}**；'
        f'实际持续 **{state.elapsed_seconds/60:.2f} 分钟**；结束类型：**'+
        ('控制器记录的' if stop.get('origin') == 'controller' else 'Agent 提出的' if stop else '')+stop_label+'**。',
        f'已确认违反命题 {sum(r["disposition"]=="confirmed_in_scope" for r in results)} 项；'
        f'检查／复核待办 {sum(p["kind"] in {"unit","review_issue"} for p in research["pending_work"])} 项。'
        '确认项数按义务命题计，不等于独立根因数。',
        '[当前未决事项](#pending-work)；'+link('state.json','完整停止依据与研究状态')+'。']
    details = [
        f'已受理 Candidate {len(research["candidates"])} 项；当前 Unit {len(research["units"])} 项、义务 {len(research["claims"])} 项、固定检查制品 {len(artifacts)} 项。'
        f'正式执行尝试 {len(formal)} 次；已保存评估的义务 {len(results)} 项，其中有实际比较 {sum(r["comparison_observed"] is True for r in results)} 项。'+
        '、'.join(f'{label} {sum(r["disposition"]==key and (key!="investigation_lead" or r["comparison_observed"] is True) for r in results)} 项' for key,label in DISPOSITIONS.items())+
        f'；另有已获源码解释的 Candidate {len(explained)+sum(bool(u["source_explanation"]) for u in research["units"])} 项。受理、执行与结论分别计数。', '',
        f'剩余 {capacity["remaining_seconds"]:.2f} 秒、{capacity["remaining"]["agent_calls"]} 次 Agent 调用、'
        f'{capacity["remaining"]["experiments"]} 次控制器目标执行。资源余量不表示获准恢复或重试。', '',
        '| 资源 | 配置 | 已用 | 剩余 |', '| --- | ---: | ---: | ---: |',
        f'| 总时间（秒） | {config["budget"]["total_seconds"]} | {state.elapsed_seconds:.2f} | {capacity["remaining_seconds"]:.2f} |']
    for key,label in [('agent_calls','Agent 调用'),('experiments','控制器目标执行'),('audit_units','新 Unit'),('semantic_reviews','语义复核'),('revisions','修订')]:
        enabled = config.get('allow_experiments',False) and config.get('execution_backend','none') != 'none' if key == 'experiments' else True
        details.append(f'| {label} | {config["budget"].get(key,0)} | {state.usage.get(key,0)} | '+(str(capacity['remaining'][key]) if enabled else '未启用')+' |')
    cost=research['costs'];action_cost=cost['target_action_cost']
    for value,missing,label in [(cost['formal_execution_seconds'],action_cost['process_unrecorded_check_ids'],'受控目标执行进程耗时（正式检查＋探索）'),
            (action_cost['known_seconds'],action_cost['unrecorded_check_ids'],'目标动作总耗时（含已记录的准备与复制）')]:
        details += ['', label+'：'+(f'已记录 {value:.2f} 秒' if value is not None else '未记录有效总量')+
            (f'；{len(missing)} 项未完整记录，合计不完整' if missing else '')+'。']
    details += ['', f'目标执行组成：正式检查 {len(formal)} 次＋探索 {len(explorations)} 次，其中执行工具失败／未完成 {len(failures)} 次（不统计研究前提未达）；失败和重试照常计数。'
        '会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。',
        '新 Unit 入场能力不保证剩余额度足够完成检查与复核。', '',
        f'元数据：源码 `{state.snapshot.commit or state.snapshot.id}`；实际方法 `{state.framework_revision}`；展示版本 `{manifest()["version"]}`；'
        f'模式 {state.mode}/{state.analysis_mode}；执行后端 `{config.get("execution_backend","none")}`／run 默认包 `{config.get("target",{}).get("execution_package",".")}`；'
        f'Agent `{config.get("agent_backend","未记录")}`／配置 provider `{cell(provider_label)}`／'
        f'请求模型 `{cell(config.get("agent_model") or "默认")}`／推理档位 `{cell(config.get("agent_reasoning_effort") or "默认")}`。重新渲染不代表重新审计。',
        '服务端模型／版本：未记录；'+link('config.json','非敏感连接输入（含 endpoint）')+
        ('；'+link('agent-inputs/catalog.json','固定目录来源与摘要') if provider and provider.get('model_catalog_path') else '')+
        ('；'+link(f'logs/{last_turn.id}/check.json','最近调用的 CLI、session 与 usage（缺失项仍未知）') if last_turn else '；尚无 Agent 调用记录')+'。', '',
        '停止依据（记录摘录）：'+excerpt(stop.get('rationale') or state.stop_reason,190)+'；'+link('state.json','完整停止记录')+'。', '']
    stopped_check = checks.get(stop.get('operation_id'))
    if stopped_check and (stopped_check.status != ExecutionStatus.COMPLETED or stopped_check.exit_code not in (0,None)):
        details += interruption_lines(stopped_check,archive)
    lines += ['', '## 主要结果', '']
    if research['claims'] or explained or ongoing:
        lines += ['| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |', '| --- | --- | --- | --- |']
    else:
        lines += ['尚无正式性质判定；已保存的研究记录见下文，不能据此断言目标没有问题。']
    entries = []
    for n,result in enumerate(results,1):
        records = [r for r in research['assessments'] if r.get('claim_id') == result['claim_id']]
        current_reviews=[]
        for record in records:
            latest=next((reviews[rid] for rid in reversed(record.get('review_ids',[])) if rid in reviews and
                reviews[rid].target_versions.get(record['direct_check_id'])==artifacts[record['direct_check_id']]['version']),None)
            if latest:current_reviews.append((record,latest))
        items=[i for record,review in current_reviews for i in review.items if i.target_id==record['direct_check_id']]
        title = next((i.report_title for i in reversed(items) if i.report_title),None)
        title = title or excerpt(result['question'] or result['description'],130)+'（原文摘录）'
        review_operations={review.check_id for _,review in current_reviews}
        relevant={r['direct_check_id'] for r in records}|{r['experiment_check_id'] for r in records}
        feedback=next((s.get('feedback',{}) for s in reversed(state.selections) if s['operation_id'] in review_operations and
            relevant & set(s.get('feedback',{}).get('ref_ids',[]))),{})
        answer = next((i.report_answer for i in reversed(items) if i.report_answer),None) or feedback.get('answered')
        entries.append((result,records,answer,title))
        progress = progress_text(result['claim_id'])
        disposition = conclusion_label(result)+('；另有场景尚未完成' if progress and result['disposition']=='confirmed_in_scope' else '')
        summary='；'.join(filter(None,[cell(excerpt(answer,170)) if answer else '',progress])) or cell(excerpt(result['description'],170))
        lines.append(f'| {n}. {cell(title)} | {disposition} | {summary} | {claim_links[result["claim_id"]]} |')
    for c in explained:lines.append(f'| {cell(excerpt(c["question"]["question"],130))} | 源码解释，未经性质执行 | {cell(excerpt("；".join(c["question"]["counterevidence"]),170))} | {link("state.json","候选原文与来源")} |')
    for claim in research['claims']:
        if any(r['claim_id']==claim['id'] for r in results):continue
        unit = next(u for u in research['units'] if claim['id'] in u['obligation_ids'])
        explanation=unit['source_explanation']
        disposition='源码解释结束当前怀疑；未进行性质执行' if explanation else '尚无正式判定'
        detail=link(f'submissions/{explanation}/accepted.json','来源化解释与当时问题') if explanation else progress_text(claim['id'])
        lines.append(f'| <a id="claim-{claim["id"]}"></a>{cell(excerpt(claim["description"],130))} | {disposition} | {detail} | {link("state.json",claim["id"])}；{candidate_links.get(unit["candidate_id"],"")} |')
    for c in ongoing:
        if not any(u['candidate_id']==c['id'] for u in research['units']):
            lines.append(f'| {cell(excerpt(c["question"]["question"],130))} | {"暂停调查" if c["status"]=="paused" else "研究中"}，尚无正式义务 | {cell(excerpt("；".join(c["resume_conditions"] or c["question"]["unknowns"]),170))} | {candidate_links[c["id"]]} |')
    for n,(result,records,answer,title) in enumerate(entries,1):
        scope = result['scope']
        shown_boundaries=set()
        lines += ['', f'<a id="claim-{result["claim_id"]}"></a>', '', f'### {n}. {title}', '', f'**{conclusion_label(result)}**。要求原文：{result["description"]}', '',
            '决定性范围：'+scope['description'], '；'.join(scope['assumptions'])+'。' if scope['assumptions'] else '',
            '范围参数：'+cell(scope['parameters']) if scope['parameters'] else '',
            link('state.json','完整要求、假设与排除范围')]
        for record in records:
            artifact = artifacts[record.get('direct_check_id')]
            check = checks[record['experiment_check_id']]
            lines += ['', f'制品 v{artifact["version"]}；'+('对应性意见：'+str(record.get('correspondence','信息不足')) if record.get('reviewed_complete') else
                assessment_progress(record)+f'；场景比较完整：{record.get("bounded_complete","未记录")}；独立场景完整处置：{record.get("reviewed_complete","未记录")}')+'。',
                '；'.join([link(artifact['harness_path'],'固定测试'),
                    link(artifact['plan_path'],'条件与检查器'),link(check.stdout,'原始观察'),
                    link(str(Path(artifact['plan_path']).parent / (check.id+'-assessment.json')),'assessment'),
                    *[link(f'submissions/{reviews[rid].check_id}/accepted.json','对应性复核') for rid in record.get('review_ids',[]) if rid in reviews]]), '']
            if record.get('execution_attribution'):
                lines += [f'原执行非零退出（{check.exit_code}）保留；上述复核对本次执行的指定违反见证作了独立失败归因。当前确认、其他缺口分别按评估列示。', '']
            if record.get('blockers'):
                refs=[issue_links[id] for id in record.get('open_issue_ids',[]) if id in issue_links]
                lines += ['当前争议／阻塞：'+'；'.join([assessment_obstacle(record,check,archive),*refs])+'；'+
                    link(str(Path(artifact['plan_path']).parent/(check.id+'-assessment.json')),'完整评估与阻塞'), '']
            harness = archive.read(artifact['plan_path']).get('harness',{})
            lines += ['<details><summary>固定输入、执行与观察字段</summary>', '', execution_location(check,archive)]
            boundary=harness.get('description','固定计划字节缺失')+'；'+'；'.join(harness.get('semantic_changes',[]))
            if boundary not in shown_boundaries:
                lines += ['执行边界：'+boundary];shown_boundaries.add(boundary)
            lines += observation_lines(record,artifact,check,archive,event_cache)
            lines += ['', '</details>']
    for id,issue in issues.items():
        review=reviews.get(issue['review_id'])
        lines += ['', f'<a id="issue-{id}"></a>', issue_links[id]+f'；对象 `{cell(issue["target_id"])}` v{issue["target_version"]}：'+excerpt(issue['explanation'],240),
            link(f'submissions/{review.check_id}/accepted.json','完整复核、反证与来源') if review else link('state.json','完整争议与来源')]
    interpretations = {}
    for entry in exploration_records:
        for handoff in entry['feedback']:
            interpretations.setdefault(handoff['operation_id'],set()).update(handoff['ref_ids'])
    handoff_links = {id:f'[交接 {n}](#exploration-feedback-{id})' for n,id in enumerate(interpretations,1)}
    execution_links = {c.id:f'[探索执行 {n}](#exploration-{c.id})' for n,c in enumerate(explorations,1)}
    candidate_explorations = {id:[] for id in candidate_links}
    for entry in exploration_records:
        lines += ['', '条件探索：'+excerpt(entry['question'] or '问题原稿字节缺失',200),
            link(entry['submission'],'受理问题、条件与来源')+'；'+'；'.join(link(path,'固定输入') for path in entry['inputs'])]
        referenced=set(entry['ref_ids']) | set(re.findall(r'[\w-]+',entry['question'] or ''))
        related=[id for id in candidate_links if id in referenced]
        if related:lines.append('显式引用的问题（不表示已解决）：'+'；'.join(candidate_links[id] for id in related))
        for id in related:candidate_explorations[id].extend(execution_links[x['check_id']] for x in entry['executions'])
        for execution in entry['executions']:
            check = checks[execution['check_id']]
            lines += [f'<a id="exploration-{check.id}"></a>', execution_links[check.id]+'：'+'；'.join(execution_summary(check)[1:])+'。'+link(execution['record'],'执行记录')+'；'+
                link(execution['stdout'],'实际输出')+'；'+link(execution['stderr'],'诊断'),
                execution_location(check,archive)]
            for directory,label in [('workspace-delta','执行输入文件清单'),('workspace-outcome','执行后文件清单')]:
                lines.extend(link(path,label) for path in execution['artifacts'] if Path(path).parts[-2:]==(directory,'manifest.json'))
        if not entry['executions']:lines.append('已受理问题，尚无保存的执行记录。')
        for handoff in entry['feedback']:
            lines.append('后续受理交接原文导航：'+handoff_links[handoff['operation_id']])
        if entry['without_followup']:lines.append('探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。')
    for operation, refs in interpretations.items():
        saved = f'submissions/{operation}/accepted.json'
        feedback = archive.read(saved).get('feedback') or {}
        lines += ['', f'<a id="exploration-feedback-{operation}"></a>',
            handoff_links[operation]+' · '+('共同后续说明' if len(refs)>1 else '后续说明')+'；关联：'+'、'.join(execution_links[id] for id in execution_links if id in refs),
            '后续受理交接原文（摘录，不是各次执行的独立观察）：'+excerpt(feedback.get('answered','归档字节缺失'),260),
            link(saved,'完整交接；精确引用不表示已解决或已正式化')]
    lines += ['', '## 研究过程与认识增长', '',
        'A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。',
        map_link+'。']
    if research['core_overview']:
        for key,label in [('formation','共识形成与推进'),('context','上下文／权威转换'),('connection','两条主线的连接')]:
            lines.append('- '+label+'（原文导航摘录）：'+excerpt(research['core_overview'][key]['explanation'],220))
    if research['understanding_status'] != 'usable':lines.append('双主线初始理解尚未完成；定向问题之外不能据片段宣称整体就绪。')
    titles = {r['experiment_check_id']:title for _,records,_,title in entries for r in records}
    titles.update({x['check_id']:e['rationale'] or e['question'] or '探索原稿缺失' for e in exploration_records for x in e['executions']})
    lines += ['累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。']+milestone_lines(state,research,archive,checks,titles)
    lines += ['', '<a id="pending-work"></a>', '', '## 当前未决事项', '']
    duplicates=[s for s in state.selections if s.get('duplicate_of')]
    if duplicates:
        lines += ['纯反馈重复受理 '+str(len(duplicates))+' 次，无新增认识，调用照常计数：'+
            '；'.join(link(f'submissions/{s["operation_id"]}/accepted.json','重复原稿')+' → '+
                link(f'submissions/{s["duplicate_of"]}/accepted.json','原交接') for s in duplicates)]
    unexplained = [id for entry in exploration_records for id in entry['without_followup']]
    for kinds,label in [({'unit','review_issue'},'已选检查／复核待办'),({'candidate'},'正在调查的问题')]:
        pending=[p for p in research['pending_work'] if p['kind'] in kinds]
        if pending:lines += ['',label+'：']
        elif 'unit' in kinds:lines.append('已选检查／复核暂无待办；研究范围仍可开放。')
        for item in pending:
            detail=('；'.join(claim_links[id] for id in item['remaining'])+'；具体进度与缺口见对应义务' if item['kind']=='unit' else
                issue_links.get(item['id']) or candidate_links.get(item['id']) or '；'.join(item['reasons']))
            lines.append('- '+link('research.json',item['id'])+('：'+detail if detail else '（状态与原因见记录）'))
    if unexplained:lines += ['',f'{len(unexplained)} 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：'+
        '；'.join(execution_links[id] for id in unexplained)]
    for c in ongoing:
        lines += ['', f'<a id="candidate-{c["id"]}"></a>', '', ('暂停调查：' if c['status']=='paused' else '研究中问题：')+c['question']['question'],
            link('state.json','候选原文与历史')]
        if c['question']['unknowns']:lines.append('保存的语义未知：'+'；'.join(c['question']['unknowns']))
        if c['resume_conditions']:lines.append('恢复条件：'+'；'.join(c['resume_conditions']))
        if candidate_explorations[c['id']]:lines.append('显式关联探索（不计为另一个发现）：'+'；'.join(candidate_explorations[c['id']]))
    if stop.get('resume_conditions'):lines += ['', '本轮记录的恢复条件：'+'；'.join(stop['resume_conditions'])]
    registry = [('core_overview',research['core_overview']['open_details'])] if research['core_overview'] else []
    registry += [(b['behavior_id'],b['unknowns']) for b in research['frontier']['behavior_unknowns']]
    registry += [(f['fact_id'],f['unknowns']) for f in research['frontier']['relationships'] if f['unknowns']]
    registry += [('surface:'+s['entry_point'],[s['reason']]) for s in research['frontier']['surfaces'] if s['disposition']!='mapped']
    if registry:lines += ['', '<details><summary>地图登记与研究交接</summary>', '',
        f'以下是地图 v{state.audit_spec_version} 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。'+map_link]
    for ref, questions in registry:
        if not questions:continue
        handoffs = [h for h in research['map_handoffs'] if ref in h['ref_ids']]
        lines += ['', '- '+cell(ref)+'：'+excerpt('；'.join(questions),200),
            '  相关交接：'+'；'.join(link(h['submission'],'交接 '+str(n)) for n,h in enumerate(handoffs,1))
            if handoffs else '  尚无精确对应交接。']
    if registry:lines += ['', '</details>']
    lines += ['', '## 证据与运行说明', '',
        '；'.join(link(name,label) for name,label in [('state.json','完整状态、版本与争议'),('research.json','当前研究索引'),
            ('config.json','实际配置'),('events.jsonl','事件时序'),('audit-method.md','实际加载方法')]),
        '环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。']
    lines += ['', '<details><summary>预算、执行成本与运行元数据</summary>', '', *details, '', '</details>', '']
    for c in failures:lines += ['- 失败／未完成：'+link(c.stdout,c.action)+'；'+link(c.stderr,'stderr')+'；'+link(f'logs/{c.id}/check.json','执行记录')]
    if state.current_submission.get('phase') == 'received':lines.append('可靠回执尚未受理：'+link(f'submissions/{state.current_submission["operation_id"]}/raw.json','固定原稿')+'；保存字节不产生 Evidence。')
    path = archive.root / 'report.md'
    path.write_text('\n'.join(lines)+'\n')
    return path
