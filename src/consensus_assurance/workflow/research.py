"""Read-only current-work projections over semantic owners and immutable receipts."""
import json
from consensus_assurance.core.types import FixedExperiment
from .knowledge import gap_answers, open_gaps, use_paths
from .experiments import assessment


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


def interpretation_view(opinion):
    return record_preview(opinion.model_dump(mode='json'), 'interpretations') if opinion else None


def knowledge_view(state, entry):
    paths = use_paths(state, entry.id)
    return record_preview({**entry.model_dump(exclude={'history'}), 'uses':list(paths),
        'use_paths':{id:path for id,path in paths.items() if len(path)>1},
        'last_correction':{k:entry.history[-1][k] for k in ('revision','correction','recorded_uses','affected_uses')}
            if entry.history else None}, 'knowledge')


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
        questions.append(record_preview({'id':q.id, 'question':q.question, 'disposition':q.disposition,
            'open_gap_count':len(open_gaps(state,q.id)),
            'latest_interpretation':{'id':opinion.id, 'conclusion':opinion.conclusion,
                'defect_claim':opinion.defect_claim} if opinion else None}, 'investigations'))
    return {'investigation_axes':['Decision formation and progress',
                                'Context validity and authority transitions'],
        'target':{'repo':state.snapshot.repo, 'snapshot_id':state.snapshot.id},
        'directed_question':state.config.get('directed_question'),
        'questions':questions,
        'knowledge':[record_preview({'id':e.id, 'revision':e.revision, 'kind':e.kind,
            'statement':e.statement}, 'knowledge') for e in state.knowledge],
        'index':'research.json contains current previews; full records and history: state.json; captured tree: agent-source/',
        'scope':'All registered questions and knowledge, not an exhaustive source frontier or a priority order. '
            'Choose from overall source understanding as well as these records; the last execution is not the default next task.',
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
        results.append({'id':a.id, 'investigation_id':a.investigation_id, 'previous_id':a.previous_id,
            'basis':f'fixed-experiments/{a.id}/basis.json',
            'results':[{k:v for k,v in assessment(state,root,a,c).items() if k not in {'events','comparisons'}} for c in checks]})
    return {'run_id':state.id, 'method':state.framework_revision, 'allocation':available(state),
        'source_path':str(root/'agent-source'), 'draft_path':str(root/'draft'), 'state_path':str(root/'state.json'),
        'submission_schema':str(root/'submission.schema.json'), 'method_path':str(root/'audit-method.md'),
        'directed_question':state.config.get('directed_question'), 'investigation_focus':state.config.get('investigation_focus',[]),
        'investigations':questions, 'knowledge':knowledge, 'experiments':results, 'reselection':reselection_view(state),
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
        value.update(experiment_id=fixed.id, investigation_id=fixed.investigation_id,
            basis=f'fixed-experiments/{fixed.id}/basis.json',
            harness=f'fixed-experiments/{fixed.id}/{fixed.harness_filename}')
    return value


def execution_feedback(state, root, fixed, check):
    """Place fixed predicates beside retained observations, without inferring their meaning."""
    from .audit import draft_bytes
    value = execution_locator(check, fixed)
    value.update(requirement=fixed.basis.requirement,
        comparisons=[{'comparison_index':i, 'definition':c.model_dump(mode='json')}
                     for i,c in enumerate(fixed.basis.comparisons)],
        sources=[{'id':m.id, 'record':{'path':'state.json', 'collection':'materials', 'id':m.id},
                  **({'path':'agent-source/'+m.file, 'start_line':m.start_line, 'end_line':m.end_line}
                     if m.file in state.snapshot.files else {})}
                 for m in state.materials if m.id in fixed.basis.source_ids],
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


def operation_summary(state, root):
    current = state.current_submission
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
    summary['necessary_gaps'] = [{**preview({'investigation_id':q.id, 'id':g['id'],
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
        if entry.operation_id != current.get('operation_id') or not entry.history:
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
    if (fixed and current.get('experiment_id') == fixed.id and current.get('phase') == 'executed'
            and not current.get('execution_gap')):
        question = next(q for q in summary['questions'] if q['id'] == fixed.investigation_id)
        question['execution'] = execution_feedback(state, root, fixed, check)
    previous, changes = {}, []
    fixed_by_id = {a.id:a for a in state.experiments}
    for opinion in state.interpretations:
        prior = previous.get(opinion.investigation_id)
        if opinion.operation_id == current.get('operation_id') and not current.get('no_change'):
            changes.append({'investigation_id':opinion.investigation_id,
                'previous':{'id':prior.id, 'conclusion':prior.conclusion, 'defect_claim':prior.defect_claim} if prior else None,
                'current':{'id':opinion.id, 'conclusion':opinion.conclusion, 'defect_claim':opinion.defect_claim},
                'record':{'path':'state.json', 'collection':'interpretations'},
                'executions':[{**execution_locator(c, fixed_by_id.get(c.experiment_id)),
                               'event_indices':opinion.executions[c.id]}
                              for c in state.checks if c.id in opinion.executions]})
        previous[opinion.investigation_id] = opinion
    if changes:
        summary['interpretation_changes'] = changes
    cited = {id for i in state.interpretations for id in i.executions}
    summary['uncited_executions'] = [{'id':c.id, 'experiment_id':c.experiment_id, 'status':c.status.value,
        'record':f'logs/{c.id}/check.json', 'observations':f'logs/{c.id}/observations.json'}
        for c in state.checks if c.action == 'experiment' and c.id not in cited]
    summary['reselection'] = reselection_view(state)
    summary['next'] = (
        'The unchanged submission is already retained; this call still consumed time and a model turn. '
        if current.get('no_change') else '') + (
        'Choose and undertake the next action that can change a judgment, using overall source understanding '
        'and the allocation: inspect an uncited result, resolve a relevant premise or measurement, continue '
        'valuable construction, or pursue an independent sourced lead. A previous answer does not interpret a new receipt; '
        'an explicit citation alone does not resolve its applicability or gaps. After a local answer, reconsider '
        'the available directions rather than inherit the last experiment. No separate selection submission is needed; '
        'do not repeat closing submissions.')
    if check:
        summary['latest_actual_execution'] = execution_locator(check, fixed)
    return summary


def global_stop(raw):
    return raw.get('action') == 'stop' and raw.get('scope') == 'run'


def stop_record(engine, reason):
    engine.state.run_stop = {'reason':reason,'origin':'controller','rationale':engine.state.stop_reason,
                             'remaining':available(engine.state)}
