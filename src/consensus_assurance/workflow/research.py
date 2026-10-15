"""Read-only current-work projections over semantic owners and immutable receipts."""
import json
from consensus_assurance.core.types import FixedExperiment
from .knowledge import gap_answers, open_gaps, use_paths, receipt_references
from .experiments import assessment, fixed_experiment_locator


def execution_cost(check):
    """Process time and enclosing action cost are different, independently optional records."""
    from datetime import datetime
    from math import isfinite
    def valid(value):return value if type(value) in (int,float) and isfinite(value) and value>=0 else None
    try:process=valid((datetime.fromisoformat(check.ended_at)-datetime.fromisoformat(check.started_at)).total_seconds())
    except (TypeError,ValueError,OverflowError):process=None
    return {'process_seconds':process,'action_seconds':valid(check.parameters.get('action_seconds'))}


def costs(state):
    checks = {c.id:c for c in state.checks if c.action == 'experiment'}
    values = {id:execution_cost(c) for id,c in checks.items()}
    def total(key):
        known = [v[key] for v in values.values() if v[key] is not None]
        return sum(known) if known or not values else None
    return {'agent_calls':state.usage.get('agent_calls',0), 'target_executions':len(checks),
            'process_seconds':total('process_seconds'), 'action_seconds':total('action_seconds'),
            'unrecorded_action_ids':[id for id,v in values.items() if v['action_seconds'] is None],
            'elapsed_seconds':state.elapsed_seconds}


def available(state):
    budget = state.config['budget']
    return {'seconds':max(0, budget['total_seconds'] - state.elapsed_seconds),
            **{k:max(0, budget[k] - state.usage.get(k,0)) for k in ('agent_calls','experiments')}}


def excerpt(text, limit=400):
    return text if len(text) <= limit else text[:limit] + f' [preview: {len(text)-limit} characters omitted; see full record]'


def preview(value):
    """Shorten prose explicitly; identifiers and evidence references stay complete."""
    if isinstance(value, list):
        return [preview(item) for item in value]
    if not isinstance(value, dict) or value.get('view') == 'preview':
        return value
    result = {}
    for key, item in value.items():
        if key in {'counterevidence', 'limitations'}:
            result[key] = [excerpt(text) for text in item[:3]]
            if len(item) > 3:
                result[key + '_omitted_count'] = len(item)-3
        elif isinstance(item, str) and key in {'question', 'hypothesis', 'discriminator', 'rationale',
                'statement', 'conditions', 'assertion', 'correction', 'changed_premise', 'explanation', 'joint_history'}:
            result[key] = excerpt(item)
        else:
            result[key] = preview(item)
    return result


def record_preview(value, collection):
    return {**preview(value), 'view':'preview',
        'record':{'path':'state.json', 'collection':collection, 'id':value['id']}}


def interpretation_view(opinion, *, compact=False):
    fields = {'id','conclusion','defect_claim','rationale','counterevidence','limitations'} if compact else None
    return record_preview(opinion.model_dump(mode='json', include=fields), 'interpretations') if opinion else None


def knowledge_view(state, entry):
    paths = use_paths(state, entry.id)
    return record_preview({**entry.model_dump(exclude={'history'}), 'uses':list(paths),
        'use_paths':{id:path for id,path in paths.items() if len(path)>1},
        'last_correction':{k:entry.history[-1][k] for k in ('revision','correction','recorded_uses','affected_uses')}
            if entry.history else None}, 'knowledge')


def knowledge_revision_view(record):
    if record is None:
        return None
    value = record_preview({k:record[k] for k in
        ('id','revision','kind','statement','conditions','source_ids','executions','knowledge')}, 'knowledge')
    value['record']['revision'] = record['revision']
    return value


def open_gap_view(state, investigation_id):
    answers = gap_answers(state, investigation_id)
    owners = {gap:i.id for i in state.interpretations if i.investigation_id == investigation_id for gap in i.answers}
    return [{**g.model_dump(mode='json'),
        'response':answers[g.id].model_dump() if g.id in answers else None,
        'response_record':{'path':'state.json','collection':'interpretations','id':owners[g.id]} if g.id in owners else None}
        for g in open_gaps(state, investigation_id)]


def reselection_view(state):
    """Navigate all registered work without ranking topics or claiming source coverage."""
    allocation = available(state)
    latest = {i.investigation_id:i for i in state.interpretations}
    questions = []
    for q in state.investigations:
        opinion = latest.get(q.id)
        account = record_preview({**opinion.model_dump(include={'id','conclusion','defect_claim','rationale'}),
            'counterevidence_count':len(opinion.counterevidence), 'limitation_count':len(opinion.limitations)},
            'interpretations') if opinion else None
        questions.append(record_preview({'id':q.id, 'question':q.question, 'disposition':q.disposition,
            'parent_id':q.parent_id,
            'discriminator':q.discriminator, 'resume_conditions':q.resume_conditions,
            'open_gap_count':len(open_gaps(state,q.id)),
            'latest_interpretation':account}, 'investigations'))
    return {'investigation_axes':['Decision formation and progress',
                                'Context validity and authority transitions'],
        'target':{'repo':state.snapshot.repo, 'snapshot_id':state.snapshot.id},
        'directed_question':state.config.get('directed_question'),
        'questions':questions,
        'knowledge':[record_preview({'id':e.id, 'revision':e.revision, 'kind':e.kind,
            'statement':e.statement, 'conditions':e.conditions}, 'knowledge') for e in state.knowledge],
        'index':'research.json contains current previews; full records and history: state.json; captured tree: agent-source/',
        'scope':'All registered questions and knowledge, not an exhaustive source frontier or a priority order. '
            'Parent links are recorded relationships, not root-cause groups. Accounts are navigation previews; '
            'read their counterevidence and limits before reusing a conclusion. Choose from overall source understanding '
            'as well as these records; the last execution is not the default next task.',
        'execution_capacity':{'available':state.config['allow_experiments'] and state.config['execution_backend']!='none'
            and all(allocation[k]>0 for k in ('seconds','agent_calls','experiments')),
            'timeout_ceiling_seconds':min(allocation['seconds'],state.config['budget']['action_timeout']),
            'note':'Capacity is not a runtime estimate. Include construction/review time; source work remains useful if a test will not fit.'}}


def current_view(state, root, implementation=None):
    from consensus_assurance.adapters.validation import validation_tool
    from .audit import Inputs
    def read(path):
        try:
            return Inputs(root).json(path)
        except (OSError,ValueError):
            return {}
    questions = []
    for q in state.investigations:
        related = [a.id for a in state.experiments if a.investigation_id == q.id]
        check = next((c for c in reversed(state.checks) if c.experiment_id in related), None)
        opinions = [i for i in state.interpretations if i.investigation_id == q.id]
        questions.append(record_preview({'id':q.id, 'version':q.version, 'question':q.question, 'hypothesis':q.hypothesis,
            'discriminator':q.discriminator, 'disposition':q.disposition, 'parent_id':q.parent_id,
            'source_ids':q.source_ids, 'resume_conditions':q.resume_conditions,
            'knowledge':[u.model_dump(mode='json') for u in q.knowledge],
            'open_gaps':open_gap_view(state,q.id),
            'latest_execution':{'id':check.id, 'experiment_id':check.experiment_id, 'status':check.status.value,
                'exit_code':check.exit_code, 'record':f'logs/{check.id}/check.json',
                'observations':f'logs/{check.id}/observations.json'} if check else None,
            'latest_interpretation':interpretation_view(opinions[-1]) if opinions else None}, 'investigations'))
    knowledge = [knowledge_view(state,e) for e in state.knowledge]
    results = []
    for raw in state.experiments:
        a = FixedExperiment.model_validate(raw)
        checks = [c for c in state.checks if c.experiment_id == a.id]
        results.append({'id':a.id, **fixed_experiment_locator(a),
            'results':[{k:v for k,v in assessment(state,root,a,c).items() if k not in {'events','comparisons'}} for c in checks]})
    return {'run_id':state.id, 'method':state.framework_revision, 'allocation':available(state),
        'source_path':str(root/'agent-source'), 'draft_path':str(root/'draft'), 'state_path':str(root/'state.json'),
        'submission_schema':str(root/'submission.schema.json'), 'method_path':str(root/'audit-method.md'),
        'directed_question':state.config.get('directed_question'), 'investigation_focus':state.config.get('investigation_focus',[]),
        'investigations':questions, 'knowledge':knowledge, 'experiments':results, 'reselection':reselection_view(state),
        'citation_scope':'Result citations locate current and historical uses; an absent citation is not a task to clear. '
            'One applicable receipt can support multiple questions without a dedicated execution for each.',
        'current':state.current_submission, 'validation':validation_tool(root), 'tools':state.tools,
        'build_inputs':implementation.build_inputs(root,state,read) if hasattr(implementation,'build_inputs') else [],
        'implementation':{'name':implementation.name, 'harness_kind':implementation.harness_kind,
            'harness_filename':implementation.harness_filename,
            'default_execution_package':getattr(implementation,'package',None),
            'instructions':implementation.harness_instructions,
            'network':'Agent shell networking is disabled. Isolated target execution may communicate only inside its private network namespace.',
            'support_path':str(root/'target-support')} if implementation else None,
        'example':{'rationale':'Investigate a sourced local uncertainty',
            'sources':[{'id':'source','file':'REPLACE_WITH_CAPTURED_FILE','start_line':1,'end_line':1,'kind':'code_observation'}],
            'investigations':[{'ref':'@question','question':'Which applicable caller condition establishes this result?',
                'source_ids':['source'],'discriminator':'Trace the actual producer and the enclosing protection'}]},
        'optional_experiment':{'investigation_id':'@question',
            'harness_path':implementation.harness_filename if implementation else 'probe.py',
            'source_ids':['source'], 'scope':{'description':'Observe the sourced local behavior'},
            'prefix':'Describe actual initialization and producer calls in the draft harness, including supplied state'},
        'costs':costs(state)}


def execution_locator(check, fixed=None):
    value = {'id':check.id, 'status':check.status.value, 'exit_code':check.exit_code,
        'record':f'logs/{check.id}/check.json', 'observations':f'logs/{check.id}/observations.json',
        'stdout':check.stdout, 'stderr':check.stderr}
    if fixed:
        value.update(fixed_experiment_locator(fixed))
    return value


def source_locations(state, ids):
    return [{'id':m.id, 'record':{'path':'state.json', 'collection':'materials', 'id':m.id},
             **({'path':'agent-source/'+m.file, 'start_line':m.start_line, 'end_line':m.end_line}
                if m.file in state.snapshot.files else {})}
            for m in state.materials if m.id in ids]


def execution_feedback(state, root, fixed, check):
    """Place fixed predicates beside retained observations, without inferring their meaning."""
    from .audit import draft_bytes
    value = execution_locator(check, fixed)
    value.update(requirement=fixed.basis.requirement,
        comparisons=[{'comparison_index':i, 'definition':c.model_dump(mode='json')}
                     for i,c in enumerate(fixed.basis.comparisons)],
        sources=source_locations(state, fixed.basis.source_ids),
        anchors=[a.model_dump(mode='json') for a in fixed.basis.anchors])
    try:
        observed = json.loads(draft_bytes(root, value['observations']))
    except (OSError, ValueError) as exc:
        value['observation_error'] = str(exc)
        return value
    # Small receipts are shown whole; never select a favorable or "representative" event.
    events = observed['events']
    inline = len(events) <= 8 and len(json.dumps(events, ensure_ascii=False)) <= 6000
    value.update(event_count=len(events), events=events if inline else [],
        events_omitted_count=0 if inline else len(events),
        parsing_error_count=len(observed['parsing_errors']), prerequisites=observed['prerequisites'])
    for comparison, result in zip(value['comparisons'], observed['comparisons'], strict=True):
        omitted = {} if inline else {k:len(result[k]) for k in ('correlations','diagnostics','limitations')}
        comparison['result'] = {k:v for k,v in result.items() if k not in omitted}
        if omitted:
            comparison['omitted_detail_counts'] = omitted
    return value


def cited_execution_feedback(state, root, check, fixed, previous, current, owner_id, remaining, path):
    """Show explicit citations, never select observations by their apparent outcome."""
    from .audit import draft_bytes
    indices = sorted(set(previous + current))
    references = receipt_references(state, check.id)
    for collection in ('current','knowledge'):
        references[collection] = [r for r in references[collection] if r['id'] != owner_id]
    for r in [*references['current'], *references['knowledge']]:
        r['overlapping_event_indices'] = sorted(set(indices) & set(r['event_indices']))
    value = {**execution_locator(check, fixed), 'event_indices':indices,
        'previous_event_indices':previous, 'current_event_indices':current,
        'references':references,
        'selection':'Explicitly cited subset, not the complete receipt or an applicability judgment. '
            'Inline limits are shared across account changes. Shared event paths locate earlier content in this update. '
            'Changed receipts are listed first within each account; '
            'added or removed event indices are shown first within each receipt.'}
    try:
        raw = json.loads(draft_bytes(root, value['observations']))
    except (OSError, ValueError) as exc:
        return {**value, 'observation_error':str(exc)}
    shown, shared = [], []
    changed = set(previous) ^ set(current)
    for index in sorted(indices, key=lambda i: i not in changed):
        key = (check.id, index)
        if key in remaining['shown']:
            shared.append({'event_index':index, 'path':remaining['shown'][key]})
            continue
        event = {'event_index':index, 'observation':raw['events'][index]}
        size = len(json.dumps(event, ensure_ascii=False))
        if remaining['events'] == 0 or size > remaining['chars']:
            continue
        remaining['shown'][key] = f'{path}/cited_events/{len(shown)}'
        shown.append(event)
        remaining['events'] -= 1
        remaining['chars'] -= size
    return {**value, 'cited_events':shown, 'event_count':len(raw['events']),
        'shared_cited_events':shared,
        'omitted_cited_indices':sorted(set(indices) - {e['event_index'] for e in [*shown,*shared]}),
        'parsing_error_count':len(raw['parsing_errors']), 'prerequisites':raw['prerequisites'],
        'comparisons':[{'comparison_index':i, 'outcome':r['outcome'], 'comparison_complete':r['comparison_complete'],
            'missing_indices':r['missing_indices'], 'diagnostic_count':len(r['diagnostics']),
            'limitation_count':len(r['limitations'])} for i,r in enumerate(raw['comparisons'])]}


def cited_executions(state, root, previous, current, owner_id, remaining, path):
    fixed = {a.id:a for a in state.experiments}
    receipts = sorted((c for c in state.checks if c.id in previous or c.id in current),
        key=lambda c: previous.get(c.id) == current.get(c.id))
    return [cited_execution_feedback(state,root,c,fixed.get(c.experiment_id),
        previous.get(c.id,[]),current.get(c.id,[]),owner_id,remaining,f'{path}/{index}')
        for index,c in enumerate(receipts)]


def interpretation_knowledge(state, prior, opinion):
    """Old and new explicit reasons, including removed citations; association is not invalidation."""
    latest = {i.investigation_id:i.id for i in state.interpretations}
    locations = {item.id:{'path':'state.json','collection':collection,'id':item.id,
        **({'current':latest[item.investigation_id] == item.id} if collection == 'interpretations' else {})}
        for collection in ('investigations','experiments','interpretations') for item in getattr(state,collection)}
    references = {}
    for side, account in (('previous',prior), ('current',opinion)):
        for use in account.knowledge if account else []:
            key = (use.entry_id, use.revision)
            if key not in references:
                entry = next(e for e in state.knowledge if e.id == use.entry_id)
                basis = next(r for r in [*entry.history,entry.model_dump(exclude={'history'})]
                    if r['revision'] == use.revision)
                paths = use_paths(state,entry.id,use.revision)
                references[key] = {'entry_id':entry.id, 'revision':use.revision,
                    'statement':excerpt(basis['statement']), 'conditions':excerpt(basis['conditions']),
                    'source_ids':basis['source_ids'], 'executions':basis['executions'],
                    'record':{'path':'state.json','collection':'knowledge','id':entry.id,'revision':use.revision},
                    'previous_assertions':[], 'current_assertions':[],
                    'recorded_uses':[{'record':locations[id],
                        **({'knowledge_path':preview(path)} if len(path)>1 else {})}
                        for id,path in paths.items() if locations[id].get('current',True)],
                    'historical_interpretations':{'path':'state.json','collection':'interpretations',
                        'ids':[id for id in paths if not locations[id].get('current',True)]}}
            references[key][side + '_assertions'].append(excerpt(use.assertion))
    return list(references.values())


def operation_summary(state, root):
    current = state.current_submission
    executed = bool(current.get('experiment_id') and current.get('phase') == 'executed' and not current.get('execution_gap'))
    summary = {k:current[k] for k in ('phase','operation_id','experiment_id','no_change','references','effects','execution_gap') if k in current}
    summary['allocation'] = available(state)
    summary['open_work_index'] = 'research.json'
    summary['diagnostics'] = current.get('rejected',{})
    turn = next((c for c in reversed(state.checks) if c.action == 'agent_turn'), None)
    if not current and turn and turn.status.value == 'timeout':
        summary['interrupted_turn'] = {'id':turn.id, 'reason':turn.reason,
            'record':f'logs/{turn.id}/check.json', 'stdout':turn.stdout, 'stderr':turn.stderr,
            'model_turn_completed':bool(turn.parameters.get('agent_turn_completed')),
            'next':'The preceding process timed out; no submission was accepted from it. '
                'Continue this session using retained drafts, logs and the current allocation. '
                'If the model already finished, repair and deliver the existing update through the normal final-response format; '
                'otherwise continue the unfinished work. Do not reconstruct work merely because delivery was interrupted.'}
    check = next((c for c in reversed(state.checks) if c.action == 'experiment'),None)
    fixed = next((a for a in state.experiments if a.id == check.experiment_id), None) if check else None
    necessary_gaps = [{**preview({'investigation_id':q.id, 'id':g['id'],
        'question':g['question'], 'response':g['response'], 'response_record':g['response_record']}), 'view':'preview',
        'record':{'path':'state.json','collection':'investigations','id':q.id}}
        for q in state.investigations for g in open_gap_view(state,q.id)]
    owners = {i.investigation_id for i in state.interpretations if i.operation_id == current.get('operation_id')}
    owners.update(q.id for q in state.investigations if q.operation_id == current.get('operation_id'))
    if current.get('no_change'):
        owners.clear()
    if fixed and current.get('experiment_id') == fixed.id:
        owners.add(fixed.investigation_id)
    latest = {i.investigation_id:i for i in state.interpretations}
    use_owners = {q.id:q.id for q in state.investigations}
    use_owners.update((a.id,a.investigation_id) for a in state.experiments)
    use_owners.update((i.id,i.investigation_id) for i in state.interpretations)
    corrections = []
    for entry in state.knowledge:
        if entry.operation_id != current.get('operation_id') or not entry.history or current.get('no_change'):
            continue
        revisions = [*entry.history, {'operation_id':entry.operation_id}]
        for prior, successor in zip(revisions, revisions[1:]):
            if successor['operation_id'] != current.get('operation_id') or not prior['correction'].strip():
                continue
            affected = []
            paths = use_paths(state, entry.id)
            for use in prior['affected_uses']:
                owner_id = use_owners.get(use)
                if owner_id is None:
                    continue
                owners.add(owner_id)
                opinion = latest.get(owner_id)
                affected.append({'id':use, 'investigation_id':owner_id,
                    'latest_interpretation':{'path':'state.json','collection':'interpretations','id':opinion.id}
                        if opinion else None})
                if len(paths.get(use, []))>1:
                    affected[-1]['knowledge_path'] = paths[use]
            corrections.append(record_preview({'id':entry.id, 'revision':entry.revision,
                'changed_premise':prior['correction'], 'previous_revision':prior['revision'],
                'recorded_uses':prior['recorded_uses'], 'affected_uses':prior['affected_uses'],
                'affected_use_locations':affected}, 'knowledge'))
    if corrections:
        summary['knowledge_corrections'] = corrections
        summary['correction_guidance'] = (
            'Recorded premise corrections and explicit uses are above; full history is at each record. '
            'Review the identified uses under their original investigations; necessary gaps remain in research.json.')
    summary['questions'] = [record_preview({'id':q.id, 'version':q.version, 'question_state':'current',
        'question':q.question, 'hypothesis':q.hypothesis, 'disposition':q.disposition, 'parent_id':q.parent_id,
        'discriminator':q.discriminator, 'knowledge':[u.model_dump() for u in q.knowledge],
        'latest_interpretation':interpretation_view(latest.get(q.id))}, 'investigations')
        for q in state.investigations if q.id in owners]
    if fixed and current.get('experiment_id') == fixed.id and executed:
        question = next(q for q in summary['questions'] if q['id'] == fixed.investigation_id)
        question['execution'] = execution_feedback(state, root, fixed, check)
    previous, updates, changes = {}, {}, []
    remaining = {'events':8, 'chars':6000, 'shown':{}}  # Shared by interpretation and knowledge citations.
    for opinion in state.interpretations:
        prior = previous.get(opinion.investigation_id)
        if opinion.operation_id == current.get('operation_id') and not current.get('no_change'):
            batch = updates.setdefault(opinion.investigation_id, [])
            batch.append(opinion.id)
            if opinion.id != latest[opinion.investigation_id].id:
                continue
            changes.append({'investigation_id':opinion.investigation_id,
                'previous':interpretation_view(prior, compact=True),
                'current':{'id':opinion.id, 'conclusion':opinion.conclusion, 'defect_claim':opinion.defect_claim},
                'record':{'path':'state.json', 'collection':'interpretations'},
                'previous_source_ids':prior.source_ids if prior else [], 'current_source_ids':opinion.source_ids,
                'sources':source_locations(state, set(opinion.source_ids) | (set(prior.source_ids) if prior else set())),
                'intermediate_interpretation_ids':batch[:-1],
                'knowledge_references':interpretation_knowledge(state, prior, opinion),
                'executions':cited_executions(state,root,prior.executions if prior else {},opinion.executions,
                    opinion.id,remaining,f'/interpretation_changes/{len(changes)}/executions')})
        else:
            previous[opinion.investigation_id] = opinion
    if changes:
        summary['interpretation_changes'] = changes
    knowledge_changes = []
    for entry in state.knowledge:
        if entry.operation_id != current.get('operation_id') or current.get('no_change'):
            continue
        prior = next((r for r in reversed(entry.history) if r['operation_id'] != entry.operation_id), None)
        knowledge_changes.append({'id':entry.id, 'previous':knowledge_revision_view(prior),
            'current':knowledge_revision_view(entry.model_dump(exclude={'history'})),
            'intermediate_revisions':[r['revision'] for r in entry.history if r['operation_id'] == entry.operation_id],
            'sources':source_locations(state,set(entry.source_ids) | (set(prior['source_ids']) if prior else set())),
            'executions':cited_executions(state,root,prior['executions'] if prior else {},entry.executions,
                entry.id,remaining,f'/knowledge_changes/{len(knowledge_changes)}/executions')})
    if knowledge_changes:
        summary['knowledge_changes'] = knowledge_changes
    if changes or knowledge_changes:
        summary['account_guidance'] = (
            'Relate changed explanations and knowledge to their cited basis and conditions. '
            'Saving knowledge does not strengthen its evidence. '
            'Old and new reasons include removed citations. Other current citations and historical locators are '
            'review candidates, not automatically affected conclusions; event overlap alone does not establish impact. '
            'Correct identified premises and uses, preserving independent support. Withdrawing a witness does not '
            'refute the question. Unrecorded code reuse remains for investigation. No separate confirmation is required.')
    summary['necessary_gaps'] = necessary_gaps
    summary['reselection'] = reselection_view(state)
    action = ('Check the proposed inference against its cited basis and conditions. For execution-based claims, '
        'do fixed operations, actual operands and consumers, order and raw observations establish it, '
        'or also fit a concrete permitted explanation? Use available evidence or inspect the decisive location '
        'where needed; correct identified errors in explanations and knowledge, preserving independent support. '
        if executed or changes or knowledge_changes or corrections else '')
    summary['next'] = (
        'The unchanged submission is already retained; this call still consumed time and a model turn. '
        if current.get('no_change') else '') + action + (
        'Choose and undertake the next action that can change a judgment, using overall source understanding '
        'and the allocation: resolve a consequential premise or measurement, continue valuable construction, '
        'or pursue an independent sourced lead. Saved receipts can answer multiple applicable questions; '
        'missing citations are not a queue to clear. Research.json retains every execution and its citation index. '
        'After a local answer, reconsider the available directions rather than inherit the last experiment; '
        'a question may remain unresolved while attention moves elsewhere. No separate selection submission is needed.')
    return summary


def global_stop(raw):
    return raw.get('action') == 'stop' and raw.get('scope') == 'run'


def stop_record(engine, reason):
    engine.state.run_stop = {'reason':reason,'origin':'controller','rationale':engine.state.stop_reason,
                             'remaining':available(engine.state)}
