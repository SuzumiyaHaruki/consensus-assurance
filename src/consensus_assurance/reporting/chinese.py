"""Portable human report derived from saved inputs, raw receipts and attributed opinions."""
import json
from pathlib import Path
from consensus_assurance.core.types import FixedExperiment
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import open_gaps
from consensus_assurance.workflow.research import costs

COMPARISON_LABELS = {'holds':'所声明比较条件成立', 'violated':'所声明比较条件不成立', 'unknown':'比较未判定'}


def comparison_summary(result):
    witness = ('固定比较的完整反例见证已确认' if result['confirmed'] else
               '未产生反例见证' if result['outcome'] == 'holds' else '反例见证未确认')
    return (f"机械比较：{COMPARISON_LABELS[result['outcome']]}（{result['outcome']}）；"
            f"{witness}（confirmed={json.dumps(result['confirmed'])}）。")


def execution_summary(check):
    from consensus_assurance.workflow.research import execution_cost
    return execution_cost(check)


def render_report(state, root):
    root = Path(root)
    labels = {'active':'调查中','paused':'暂停','explained':'局部问题已回答','closed':'局部问题已处置'}
    conclusions = {**COMPARISON_LABELS, 'explained':'源码解释','conditional':'条件性解释','unresolved':'未解决'}
    rows = ['# 共识审计研究报告', '',
        f"方法 `{state.framework_revision}`；模式 `{state.mode}/{state.analysis_mode}`；持续 {state.elapsed_seconds / 60:.2f} 分钟。",
        f"停止原因：{state.stop_reason}", '',
        '机械结果仅评价所声明谓词；confirmed 仅表示固定比较的完整反例见证得到确认，不是规范适用性或共识缺陷的独立裁决。模型解释保留其归属，异常预测成立也可能支持缺陷解释。',
        '', '## 问题与证据', '']
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
            rows.append('声明的要求／预测：' + (a.basis.requirement or '探索尚未固定要求，不产生反例见证确认。'))
            checks = [c for c in state.checks if c.experiment_id == a.id]
            if not checks:
                rows.append('已受理，尚无实际执行记录。')
            for c in checks:
                result = assessment(state, root, a, c)
                rows.append(f"执行 `{c.id}`：{c.status.value}，退出码 {c.exit_code}；[回执](logs/{c.id}/check.json)、[完整观察](logs/{c.id}/observations.json)、[stdout](logs/{c.id}/stdout.log)、[stderr](logs/{c.id}/stderr.log)。")
                rows.append(comparison_summary(result))
                current = next((i for i in opinions if i.id == result['interpretation_id']), None)
                if current:
                    rows.append(f'当前模型归属解释 `{current.id}`（{current.conclusion}）：{conclusions[current.conclusion]}；' + (current.report_answer or current.rationale))
                    if current.conclusion in {'holds','violated'} and current.conclusion != result['outcome']:
                        rows.append(f'归属判断与机械结果不一致：模型 `{current.conclusion}`，机械 `{result["outcome"]}`；保留原解释，不改写比较结果或确认值。')
                if result['blockers']:
                    rows.append('待解决：' + '；'.join(result['blockers']))
                for comparison in result['comparisons']:
                    index = comparison['comparison_index']
                    spec = a.basis.comparisons[index]
                    predicate = spec.model_dump(include={'assertion','antecedent','applicability_conditions'}, exclude_none=True)
                    rows.extend(['', f'比较 {index} · `{spec.event}`：{spec.description}',
                        '声明谓词：`' + json.dumps(predicate, ensure_ascii=False) + '`', comparison_summary(comparison),
                        '观察范围：' + ('完整' if comparison['comparison_complete'] else '仍有未决项') +
                        '；有效反例事件索引：' + str(comparison['valid_witness_indices']) + '（零起始，见完整观察）。'])
                    if comparison['limitations']:
                        rows.append('观测缺口：' + '；'.join(comparison['limitations']))
        if opinions:
            rows.extend(['', '模型归属解释历史（非独立框架裁决）：', ''])
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
            rows.append(f"  原 r{h['revision']}：{h['statement']}；修订说明：{h.get('correction') or '未登记前提更正'}；受影响引用：{', '.join(h.get('affected_uses',[])) or '无登记'}。")
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
