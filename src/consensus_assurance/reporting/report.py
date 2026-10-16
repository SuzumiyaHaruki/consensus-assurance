"""Portable human report derived from saved inputs, raw receipts and attributed opinions."""
import json
from pathlib import Path
from consensus_assurance.core.types import FixedExperiment
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import gap_answers, open_gaps
from consensus_assurance.workflow.research import costs

COMPARISON_LABELS = {'holds':'declared predicate holds', 'violated':'declared predicate does not hold', 'unknown':'comparison undetermined'}
DEFECT_LABELS = {'asserted':'defect asserted (subject to independent verification)', 'refuted':'defect claim refuted within the stated scope',
                 'unresolved':'unresolved', None:'no explicit defect claim submitted'}


def comparison_summary(result):
    prefix = 'No fixed comparisons declared. ' if result.get('comparisons') == [] else ''
    return prefix + f"Mechanical comparison: {COMPARISON_LABELS[result['outcome']]} (`{result['outcome']}`)."


def execution_summary(check):
    from consensus_assurance.workflow.research import execution_cost
    return execution_cost(check)


def interpretation_rows(value):
    heading = f'Current model interpretation `{value.id}` · `{value.conclusion}`'
    sources = ', '.join(f'[{id}](state.json)' for id in value.source_ids)
    executions = '; '.join(f'[{id}](logs/{id}/check.json) ([observations](logs/{id}/observations.json), event indices {indices})'
        for id,indices in value.executions.items()) or 'No execution receipt explicitly cited by this interpretation'
    rows = ['', heading + ': ' + value.rationale, '',
        f'Sources: {sources}; execution evidence: {executions}.']
    if value.counterevidence:
        rows.append('Interpretation counterevidence: ' + '; '.join(value.counterevidence))
    if value.limitations:
        rows.append('Interpretation limitations: ' + '; '.join(value.limitations))
    if value.answers:
        rows.append('Gap responses: ' + '; '.join(k + ': ' +
            ('model declares resolved: ' if v.resolved else 'gap remains open: ') + v.explanation
            for k,v in value.answers.items()))
    if value.failure_attribution:
        failure = value.failure_attribution
        rows.append('Submitted model independent-failure attribution: '
            f"comparison / event indices {json.dumps(failure['witness_indices'])}; "
            f"[failure output](logs/{failure['check_id']}/{failure['failure_stream']}.log), lines {failure['failure_lines']}; "
            f"saved harness lines {failure['harness_lines']}. The semantic explanation is the rationale above.")
    return rows


def render_report(state, root):
    root = Path(root)
    labels = {'active':'active','paused':'paused','explained':'local question answered','closed':'local question disposed'}
    latest = {i.investigation_id:i for i in state.interpretations}
    claimed = {id for id,i in latest.items() if i.defect_claim == 'asserted'}
    rows = ['# Consensus audit research report', '',
        f"Method `{state.framework_revision}`; mode `{state.mode}/{state.analysis_mode}`; elapsed {state.elapsed_seconds / 60:.2f} minutes.",
        f"Stop reason: {state.stop_reason}", '',
        'Mechanical results evaluate declared predicates. Model defect claims address applicability, causes and counterevidence; independent verification is separate. Each question uses its latest interpretation; an explicit null claim does not inherit an earlier assertion. Historical interpretations and raw evidence remain available.',
        '', '## Explicit model defect claims (subject to independent verification)', '']
    if not claimed:
        rows.append('No current explicit defect assertion; this does not establish that the target has no defects.')
    if not state.investigations:
        rows.append('No accepted questions or conclusions; interruption does not establish absence of defects.')
    other_started = False
    for q in sorted(state.investigations, key=lambda q:q.id not in claimed):
        if q.id not in claimed and not other_started:
            rows.extend(['', '## Other research results', ''])
            other_started = True
        opinions = [i for i in state.interpretations if i.investigation_id == q.id]
        rows.extend([f'### {q.question}', '', f'Current disposition: {labels[q.disposition]}.',
                     f'Question `{q.id}` v{q.version}; sources: {", ".join(q.source_ids)} ([full references](state.json)).'])
        rows.append('Current model defect claim: ' + DEFECT_LABELS[opinions[-1].defect_claim if opinions else None] + '.')
        if opinions:
            rows.extend(interpretation_rows(opinions[-1]))
        if q.parent_id:
            rows.append(f'Parent question: `{q.parent_id}`; this result does not automatically close its parent.')
        if q.hypothesis:
            rows.append('Hypothesis: ' + q.hypothesis)
        if q.discriminator:
            rows.append('Registered discriminator: ' + q.discriminator)
        pending = open_gaps(state, q.id)
        if pending:
            answers = gap_answers(state, q.id)
            rows.extend(['', 'Unresolved necessary gaps:', ''])
            for g in pending:
                response = answers.get(g.id)
                detail = (' Latest response (gap remains open): ' + response.explanation
                    if response and (not opinions or g.id not in opinions[-1].answers) else '')
                rows.append(f'- `{g.id}`: {g.question}' + detail)
        if q.resume_conditions:
            rows.append('Resume conditions: ' + '; '.join(q.resume_conditions))
        for raw in state.experiments:
            a = FixedExperiment.model_validate(raw)
            if a.investigation_id != q.id:
                continue
            rows.extend(['', f"Fixed experiment `{a.id}` v{a.version}: [saved basis](fixed-experiments/{a.id}/basis.json).",
                         'Scope: ' + a.basis.scope.description, 'History / supplied conditions: ' + a.basis.prefix])
            if a.basis.scope.assumptions:
                rows.append('Assumptions: ' + '; '.join(a.basis.scope.assumptions))
            if a.basis.scope.excluded:
                rows.append('Excluded scope: ' + '; '.join(a.basis.scope.excluded))
            if a.previous_id:
                rows.append(f'Predecessor `{a.previous_id}`; revision reason: {a.revision_reason}; actual changes: ' + ', '.join(a.difference))
            rows.append('Declared requirement / prediction: ' + (a.basis.requirement or 'No fixed requirement; observations remain available for sourced interpretation.'))
            checks = [c for c in state.checks if c.experiment_id == a.id]
            if not checks:
                rows.append('Accepted; no execution recorded yet.')
            for c in checks:
                result = assessment(state, root, a, c)
                rows.append(f"Execution `{c.id}`: {c.status.value}, exit code {c.exit_code}; [receipt](logs/{c.id}/check.json), [full observations](logs/{c.id}/observations.json), [stdout](logs/{c.id}/stdout.log), [stderr](logs/{c.id}/stderr.log).")
                rows.append(comparison_summary(result))
                current = next((i for i in opinions if i.id == result['interpretation_id']), None)
                if current:
                    rows.append(f'Directly attributed interpretation for this execution: `{current.id}` ({current.conclusion}; {"current question interpretation" if current.id == latest[q.id].id else "historical interpretation; the question has a later account"}).')
                    if current.conclusion in {'holds','violated'}:
                        if result['outcome'] == 'unknown':
                            rows.append(f'Model interpretation: `{current.conclusion}`; the mechanical comparison is undetermined, not an opposing conclusion.')
                        elif current.conclusion != result['outcome']:
                            rows.append(f'Interpretation differs from the mechanical result: model `{current.conclusion}`, mechanical `{result["outcome"]}`.')
                citations = result['interpretation_citations']
                other_current = [i for i in citations['current'] if i['id'] != result['interpretation_id']]
                if other_current:
                    rows.append('Other current question interpretations explicitly citing this receipt: ' + '; '.join(
                        f"[{i['id']}]({citations['path']}) (question `{i['investigation_id']}`, "
                        f"fixed-experiment attribution: {i['experiment_id'] or 'none'}; event indices {i['event_indices']})"
                        for i in other_current) + '.')
                if citations['historical_count']:
                    rows.append(f"Historical interpretations explicitly citing this receipt: {citations['historical_count']} "
                                f"([full records]({citations['path']})); these are not current question accounts.")
                if result['blockers']:
                    rows.append('Evidence limitations: ' + '; '.join(result['blockers']))
                for comparison in result['comparisons']:
                    index = comparison['comparison_index']
                    spec = a.basis.comparisons[index]
                    predicate = spec.model_dump(include={'assertion','antecedent','applicability_conditions'}, exclude_none=True)
                    rows.extend(['', f'Comparison {index} · `{spec.event}`: {spec.description}',
                        'Declared predicate: `' + json.dumps(predicate, ensure_ascii=False) + '`', comparison_summary(comparison),
                        'Observation coverage: ' + ('complete' if comparison['comparison_complete'] else 'unresolved items remain') +
                        '; valid violating event indices: ' + str(comparison['valid_witness_indices']) +
                        ' (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).'])
                    if comparison['limitations']:
                        rows.append('Observation gaps: ' + '; '.join(comparison['limitations']))
        if len(opinions) > 1:
            rows.extend(['', 'Interpretation history:', ''])
            for prior, current in zip(opinions, opinions[1:]):
                current_fields = current.model_dump()
                changed = [key for key,value in prior.model_dump(exclude={'id','operation_id'}).items()
                    if value != current_fields[key]]
                rows.append(f'- [{prior.id}](state.json) → [{current.id}](state.json): '
                    f'{prior.conclusion} → {current.conclusion}; model claim '
                    f'{prior.defect_claim or "none"} → {current.defect_claim or "none"}; '
                    f'changed fields: {", ".join(changed)}. Full accounts, evidence and boundaries remain in state.json.')
    rows.extend(['', '## Shared understanding and revisions', ''])
    for e in state.knowledge:
        rows.append(f'- `{e.id}` r{e.revision} · {e.kind}: {e.statement}; conditions: {e.conditions}.')
        for h in e.history:
            rows.append(f"  Prior r{h['revision']}: {h['statement']}; correction: {h.get('correction') or 'no premise correction registered'}; affected uses: {', '.join(h.get('affected_uses',[])) or 'none registered'}.")
    cost = costs(state)
    rows.extend(['', '## Execution costs and raw records', '',
        f"Codex investigation turns: {state.usage.get('agent_calls',0)} (not provider request count); controller target executions: {state.usage.get('experiments',0)} (excludes Agent local exploratory checks).",
        f"Total target process seconds: {cost['process_seconds']}; action seconds including preparation: {cost['action_seconds']}; these overlap and must not be added together.",
        f"Requested model: `{state.config.get('agent_model')}` / `{state.config.get('agent_reasoning_effort')}`; server model identity is only established by receipts.",
        '[Full state and history](state.json), [current work index](research.json), [actual configuration](config.json), [events](events.jsonl).',
        'Scripted products demonstrate framework behavior, not autonomous discovery.', ''])
    path = root / 'report.md'
    path.write_text('\n'.join(rows))
    return path
