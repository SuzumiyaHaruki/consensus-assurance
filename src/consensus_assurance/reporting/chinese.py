"""Portable human report derived from saved inputs, raw receipts and attributed opinions."""
import json
from pathlib import Path
from consensus_assurance.core.types import FixedExperiment
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import open_gaps
from consensus_assurance.workflow.research import costs


def execution_summary(check):
    from consensus_assurance.workflow.research import execution_cost
    return execution_cost(check)


def render_report(state, root):
    root = Path(root)
    labels = {'active':'调查中','paused':'暂停','explained':'局部问题已回答','closed':'局部问题已处置'}
    conclusions = {'explained':'源码解释','conditional':'条件性结果','violated':'违反判断',
                   'holds':'有限范围未见违反','unresolved':'未解决'}
    rows = ['# 共识审计研究报告', '',
        f"方法 `{state.framework_revision}`；模式 `{state.mode}/{state.analysis_mode}`；持续 {state.elapsed_seconds / 60:.2f} 分钟。",
        f"停止原因：{state.stop_reason}", '', '## 问题与证据', '']
    if not state.investigations:
        rows.append('尚无受理问题或正式结论；中断记录不代表目标没有问题。')
    for q in state.investigations:
        opinions = [i for i in state.interpretations if i.investigation_id == q.id]
        title = opinions[-1].report_title if opinions else None
        rows.extend([f'### {title or q.question}', '', f'当前处置：{labels[q.disposition]}。',
                     f'问题 `{q.id}` v{q.version}；来源：{", ".join(q.source_ids)}（[完整引用](state.json)）。'])
        if title:
            rows.append('原命题：' + q.question)
        if q.parent_id:
            rows.append(f'关联父问题：`{q.parent_id}`；本问题的结果不自动关闭父问题。')
        if q.hypothesis:
            rows.append('假设：' + q.hypothesis)
        if q.discriminator:
            rows.append('下一判别条件：' + q.discriminator)
        if q.counterevidence:
            rows.append('问题反证：' + '；'.join(q.counterevidence))
        if q.limitations:
            rows.append('问题边界：' + '；'.join(q.limitations))
        for raw in state.experiments:
            a = FixedExperiment.model_validate(raw)
            if a.investigation_id != q.id:
                continue
            rows.extend(['', f"固定实验 `{a.id}` v{a.version}：[原始依据](fixed-experiments/{a.id}/basis.json)。",
                         '范围：' + a.basis.scope.description, '前史／供给条件：' + a.basis.prefix])
            if a.basis.scope.assumptions:
                rows.append('假设：' + '；'.join(a.basis.scope.assumptions))
            if a.basis.scope.excluded:
                rows.append('范围外：' + '；'.join(a.basis.scope.excluded))
            if a.previous_id:
                rows.append(f'前驱 `{a.previous_id}`；修订原因：{a.revision_reason}；实际变化：' + ', '.join(a.difference))
            rows.append('书面要求：' + (a.basis.requirement or '探索尚未固定要求，不产生正式确认。'))
            checks = [c for c in state.checks if c.experiment_id == a.id]
            if not checks:
                rows.append('已受理，尚无实际执行记录。')
            for c in checks:
                result = assessment(state, root, a, c)
                rows.append(f"执行 `{c.id}`：{c.status.value}，退出码 {c.exit_code}；[回执](logs/{c.id}/check.json)、[stdout](logs/{c.id}/stdout.log)、[stderr](logs/{c.id}/stderr.log)。")
                rows.append('机械比较：' + result['outcome'] + '；当前确认：' + ('已确认有界违反' if result['confirmed'] else '未确认违反'))
                current = next((i for i in opinions if i.id == result['interpretation_id']), None)
                if current:
                    rows.append(f'当前归属解释 `{current.id}`：{conclusions[current.conclusion]}；' + (current.report_answer or current.rationale))
                if result['events']:
                    rows.extend(['', '实际观察（前 8 条，完整记录见原始输出）：', '', '```json',
                                 json.dumps(result['events'][:8], ensure_ascii=False, indent=2), '```'])
                if result['blockers']:
                    rows.append('待解决：' + '；'.join(result['blockers']))
                for comparison in result['comparisons']:
                    if comparison['limitations']:
                        rows.append('观测缺口：' + '；'.join(comparison['limitations']))
        if opinions:
            rows.extend(['', '归属解释历史：', ''])
        for i in opinions:
            rows.append(f'- `{i.id}` · {conclusions[i.conclusion]}：{i.report_answer or i.rationale}；依据来源 {", ".join(i.source_ids)}，执行 {", ".join(i.executions) or "无（源码解释）"}。')
            if i.counterevidence:
                rows.append('  反证：' + '；'.join(i.counterevidence))
            if i.limitations:
                rows.append('  限制：' + '；'.join(i.limitations))
            if i.answers:
                rows.append('  缺口答复：' + '；'.join(k + ': ' + v for k,v in i.answers.items()))
        pending = open_gaps(state, q.id)
        if pending:
            rows.extend(['', '仍未回答的必要缺口：', '', *[f'- `{g.id}`：{g.question}' for g in pending]])
        if q.resume_conditions:
            rows.append('恢复条件：' + '；'.join(q.resume_conditions))
    rows.extend(['', '## 共享理解与修订', ''])
    for e in state.knowledge:
        rows.append(f'- `{e.id}` r{e.revision} · {e.kind}：{e.statement}；条件：{e.conditions}。')
        for h in e.history:
            rows.append(f"  原 r{h['revision']}：{h['statement']}；更正：{h.get('correction','')}；受影响引用：{', '.join(h.get('affected_uses',[])) or '无登记'}。")
    cost = costs(state)
    rows.extend(['', '## 执行成本与原始记录', '',
        f"Agent 调用 {state.usage.get('agent_calls',0)} 次；控制器目标执行 {state.usage.get('experiments',0)} 次。",
        f"目标进程累计秒数：{cost['process_seconds']}；含准备的动作秒数：{cost['action_seconds']}；两者不相加。",
        f"请求模型：`{state.config.get('agent_model')}` / `{state.config.get('agent_reasoning_effort')}`；服务端模型版本仅以回执为准。",
        '[完整状态与历史](state.json)、[当前工作索引](research.json)、[实际配置](config.json)、[事件](events.jsonl)。',
        '源码身份、工具成功及模型解释各有边界；脚本化产品仅验证框架，不作为自主发现证据。', ''])
    path = root / 'report.md'
    path.write_text('\n'.join(rows))
    return path
