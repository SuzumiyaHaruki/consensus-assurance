"""Read-only current-work projections over semantic owners and immutable receipts."""
from consensus_assurance.core.types import FixedExperiment
from .knowledge import open_gaps, uses_of
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


def knowledge_view(state, entry):
    return {**entry.model_dump(exclude={'history'}), 'uses':uses_of(state,entry.id,entry.revision),
        'last_correction':{k:entry.history[-1][k] for k in ('revision','correction','recorded_uses','affected_uses')}
            if entry.history else None}


def reselection_view(state):
    """Bounded navigation from retained records, with no topic ranking or inferred coverage."""
    allocation = available(state)
    operations = {id:n for n,id in enumerate(state.applied_operations)}
    recent = sorted(state.knowledge, key=lambda e:operations.get('submission-'+e.operation_id,-1))[-3:]
    knowledge = []
    for entry in recent:
        value = knowledge_view(state,entry)
        value['statement'], value['conditions'] = entry.statement[:600], entry.conditions[:300]
        value['source_ids'], value['uses'] = entry.source_ids[:4], value['uses'][:6]
        value['source_locations'] = {m.id:f'agent-source/{m.file}:{m.start_line}-{m.end_line}'
            for m in state.materials if m.id in value['source_ids']}
        value['executions'] = {id:{'indices':indices[:6], 'record':f'logs/{id}/observations.json'}
            for id,indices in list(entry.executions.items())[-3:]}
        if value['last_correction']:
            value['last_correction'] = {k:(v[:600] if isinstance(v,str) else v[:6] if isinstance(v,list) else v)
                for k,v in value['last_correction'].items()}
        knowledge.append(value)
    questions = []
    for q in state.investigations[-8:]:
        opinion = next((i for i in reversed(state.interpretations) if i.investigation_id == q.id),None)
        questions.append({'id':q.id, 'question':q.question[:240], 'disposition':q.disposition,
            'source_ids':q.source_ids[:4], 'open_gap_count':len(open_gaps(state,q.id)),
            'latest_interpretation':{'id':opinion.id, 'conclusion':opinion.conclusion,
                'rationale':opinion.rationale[:400]} if opinion else None})
    return {'task':['A1: CFT decision formation and progress.',
                    'A2: Context and authority acquisition, transition and loss.'],
        'target':{'repo':state.snapshot.repo, 'snapshot_id':state.snapshot.id},
        'directed_question':state.config.get('directed_question'),
        'questions':questions, 'recent_knowledge':knowledge,
        'index':'research.json; full statements, sources, uses and history: state.json; captured tree: agent-source/',
        'scope':'Recent records only, not a coverage map; omitted or unread areas are not established as examined.',
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
        questions.append({'id':q.id, 'version':q.version, 'question':q.question, 'hypothesis':q.hypothesis,
            'discriminator':q.discriminator, 'disposition':q.disposition, 'parent_id':q.parent_id,
            'source_ids':q.source_ids, 'counterevidence':q.counterevidence,
            'limitations':q.limitations, 'resume_conditions':q.resume_conditions,
            'knowledge':[u.model_dump(mode='json') for u in q.knowledge],
            'open_gaps':[g.model_dump(mode='json') for g in open_gaps(state,q.id)],
            'latest_execution':{'id':check.id, 'experiment_id':check.experiment_id, 'status':check.status.value,
                'exit_code':check.exit_code, 'record':f'logs/{check.id}/check.json',
                'observations':f'logs/{check.id}/observations.json'} if check else None,
            'latest_interpretation':opinions[-1].model_dump(mode='json') if opinions else None,
            'record':{'path':'state.json', 'collection':'investigations','id':q.id}})
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
        'directed_question':state.config.get('directed_question'), 'activity_focus':state.config.get('activity_focus',[]),
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


def operation_summary(state, root):
    current = state.current_submission
    summary = {k:current[k] for k in ('phase','operation_id','experiment_id','no_change','references','execution_gap') if k in current}
    summary['allocation'] = available(state)
    summary['open_work_index'] = 'research.json'
    summary['diagnostics'] = current.get('rejected',{})
    check = next((c for c in reversed(state.checks) if c.action == 'experiment'),None)
    if check:
        summary['latest_actual_execution'] = {'id':check.id,'status':check.status.value,'exit_code':check.exit_code,
            'record':f'logs/{check.id}/check.json','observations':f'logs/{check.id}/observations.json'}
    gaps = [{'investigation_id':q.id,'id':g.id,'question':g.question[:400]}
        for q in state.investigations for g in open_gaps(state,q.id)]
    summary['necessary_gaps'], summary['other_gap_count'] = gaps[-8:], max(0,len(gaps)-8)
    owners = {i.investigation_id for i in state.interpretations if i.operation_id == current.get('operation_id')}
    owners.update(q.id for q in state.investigations if q.operation_id == current.get('operation_id'))
    if not owners and check:
        owners.update(a.investigation_id for a in state.experiments if a.id == check.experiment_id)
    local = [q for q in state.investigations if q.id in owners]
    summary['questions'] = [{'id':q.id, 'question':q.question[:240], 'disposition':q.disposition,
        'discriminator':q.discriminator[:400], 'knowledge':[
            {**u.model_dump(), 'assertion':u.assertion[:300]} for u in q.knowledge[:6]]}
        for q in local][-3:]
    answered = any(q.disposition != 'active' or (not open_gaps(state,q.id) and
        next((i.conclusion for i in reversed(state.interpretations) if i.investigation_id==q.id),None)
        in {'explained','holds','violated'}) for q in local)
    if current.get('no_change') or answered:
        summary['reselection'] = reselection_view(state)
        summary['next'] = ('No semantic change. ' if current.get('no_change') else '') + (
            'Local dispositions do not complete the global task. Select any valuable A1/A2 direction independently '
            'of the last question, or follow a newly grounded local lead; inspect sources and make a real next step. '
            'Necessary gaps remain with their owners; no experiment or parent link is mandatory.')
    return summary


def global_stop(raw):
    return raw.get('action') == 'stop' and raw.get('scope') == 'run'


def stop_record(engine, reason):
    engine.state.run_stop = {'reason':reason,'origin':'controller','rationale':engine.state.stop_reason,
                             'remaining':available(engine.state)}
