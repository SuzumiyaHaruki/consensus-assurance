"""Current research projection and attributed decisions; history stays in state."""
from .audit_spec import load, audit_object_index
from consensus_assurance.core.types import ACTIVITY_ROLES


def pending_work(state):
    return ([{'id':u.id, 'candidate_id':u.candidate_id, 'kind':'unit',
        'remaining':u.remaining_obligation_ids or u.obligation_ids, 'reasons':u.coverage_limitations}
        for u in state.units if u.status not in {'checked','revised'}]
        + [{'id':i.id, 'kind':'review_issue', 'reasons':[i.explanation], 'source_ids':i.source_ids}
            for i in state.review_issues if not i.resolved_by]
        + [{'id':c.id, 'kind':'candidate', 'reasons':c.question.unknowns}
            for c in state.question_candidates if not c.obligation_id and c.status in {'active','blocked'}])


def source_refs(state, refs):
    """Resolve accepted identifiers, not prose, to their retained source ownership."""
    links = {m.id:{m.id} for m in state.materials}
    links.update({c.id:set(c.question.source_ids) for c in state.question_candidates})
    links.update({u.id:set(u.binding_ids+[u.candidate_id]) for u in state.units})
    links.update({b.id:{b.material_id} for b in state.bindings})
    links.update({c.id:set(c.source_ids) for c in state.claims})
    links.update({a.id:{a.unit_id,getattr(a,'research_ref',None)}-{None,''} for a in state.models+state.direct_checks})
    links.update({m.id:links[m.id]|{ref for basis in m.constraints for ref in basis.source_ids} for m in state.models})
    links.update({e.id:{e.check_id} for e in state.evidence+state.findings})
    links.update({c.id:{c.model_id,c.direct_check_id} - {None} for c in state.checks})
    links.update({r.id:{ref for item in r.items for ref in item.source_ids} for r in state.semantic_reviews})
    links.update({key:set(obj.get('source_ids',[])) for key,obj in audit_object_index(load(state)).items()})
    links.update({s['operation_id']:set(s.get('candidate_ids',[])+s.get('feedback',{}).get('ref_ids',[]))
        for s in state.selections})
    found, seen, todo = set(), set(), list(refs)
    materials = {m.id for m in state.materials}
    while todo:
        ref = todo.pop()
        if ref in seen:continue
        seen.add(ref)
        if ref in materials:found.add(ref)
        else:todo.extend(links.get(ref,()))
    return found


def capacity(state):
    limits = state.config.get('budget',{})
    names = ('agent_calls','experiments','model_checks','audit_units','semantic_reviews','revisions','reachability_checks')
    remaining = {name:max(0,limits.get(name,0)-state.usage.get(name,0)) for name in names}
    seconds=max(0,limits.get('total_seconds',0)-state.elapsed_seconds)
    execution = state.config.get('allow_experiments',False) and state.config.get('execution_backend','none')!='none' and remaining['experiments'] > 0
    model = state.config.get('verifier_backend','none') != 'none' and remaining['model_checks'] >= 2
    return {'remaining':remaining, 'remaining_seconds':seconds,
        'new_obligation':bool(seconds and remaining['audit_units'] and (execution or model)),
        'direct_execution':bool(seconds and execution), 'model_execution':bool(seconds and model),
        'source_investigation':bool(seconds and remaining['agent_calls']),
        'exhausted':[name for name,value in remaining.items() if not value]}


def frontier(state, spec):
    """Project sourced unknowns and actual edges, never synthesize lifecycle products."""
    candidates = state.question_candidates
    relationships = []
    for fact in spec.facts if spec else []:
        investigations = [c for c in candidates if fact.id in c.question.fact_ids]
        referenced = {b for c in investigations for b in c.question.behavior_ids}
        edges = set(fact.established_by+fact.consumed_by+fact.invalidators+fact.reinterpreters)
        relationships.append({'fact_id':fact.id, 'source_ids':fact.source_ids,
            'unknowns':fact.unknowns, 'producers':fact.established_by, 'consumers':fact.consumed_by,
            'invalidators':fact.invalidators, 'reinterpreters':fact.reinterpreters,
            'unselected_behavior_ids':sorted(edges-referenced),
            'investigations':[{'candidate_id':c.id,'status':c.status,'lifecycle':c.question.obligation_relation_kind,
                'question':c.question.question,'remaining':c.question.unknowns,'resume_conditions':c.resume_conditions}
                for c in investigations], 'coverage':'Described relationships; selected checks settle only their explicit scope'})
    return {'relationships':relationships,
        'behavior_unknowns':[{'behavior_id':b.id,'activity':b.primary_activity,'unknowns':b.unknowns,
            'source_ids':b.source_ids,'protections':b.existing_protections} for b in spec.behaviors if b.unknowns] if spec else [],
        'surfaces':[s.model_dump(mode='json') for s in spec.surfaces] if spec else [],
        'core_regions':[{'activity':a,'entries':[x.model_dump(mode='json') for x in spec.activities if x.class_id==a] if spec else [],
            'coverage':'Partial understanding; neither candidate labels nor object counts establish exhaustion'}
            for a,role in ACTIVITY_ROLES.items() if role['role']=='core']}


def conclusions(state, records):
    """One result per logical obligation, with artifact versions retained as evidence."""
    result=[]
    for claim in state.claims:
        observed=[r for r in records if r.get('claim_id')==claim.id]
        if not observed:continue
        confirmed=any(r.get('confirmed') and r.get('outcome')=='violated' for r in observed)
        checked=all(r.get('reviewed_complete') for r in observed)
        result.append({'claim_id':claim.id,'concern':claim.concern,'description':claim.description,
            'disposition':'confirmed_in_scope' if confirmed else 'bounded_no_violation' if checked and all(r.get('outcome')=='holds' for r in observed) else 'investigation_lead',
            'scope':claim.scope.model_dump(mode='json'),'check_ids':[r['experiment_check_id'] for r in observed],
            'blockers':list(dict.fromkeys(b for r in observed for b in r['blockers'])),
            'unestablished_consequences':list(dict.fromkeys(b for r in observed for b in r['boundaries']))})
    return result


def costs(state):
    from datetime import datetime
    def seconds(check):
        return max(0,(datetime.fromisoformat(check.ended_at)-datetime.fromisoformat(check.started_at)).total_seconds()) if check.ended_at and check.started_at else 0
    rejected={s['operation_id'] for s in state.selections if s['action']=='rejected'}
    calls=[c for c in state.checks if c.action=='native_agent']
    formal=[c for c in state.checks if c.action in {'direct_check','exploration','model_syntax','model_check','reachability'}]
    return {'agent_calls':state.usage.get('agent_calls',0),'agent_seconds':sum(map(seconds,calls)),
        'rejected_calls':len(rejected),'rejected_call_seconds':sum(seconds(c) for c in calls if c.id in rejected),
        'formal_executions':len(formal),'formal_execution_seconds':sum(map(seconds,formal)),
        'elapsed_seconds':state.elapsed_seconds,
        'interpretation':'Rejected calls may contain useful investigation; wall time is not token cost or pure waste'}


def view(state, compact=False):
    spec = load(state)
    current = [u for u in state.units if u.status != 'revised']
    superseded = {a.previous_id for a in state.direct_checks+state.models}
    artifacts = [a for a in state.direct_checks+state.models if a.id not in superseded and
        (a.unit_id in {u.id for u in current} or getattr(a,'research_ref',None))]
    records = [r for r in state.monitor_results if (r.get('direct_check_id') or r.get('model_id')) in {a.id for a in artifacts}]
    result = {'audit_spec_path':state.audit_spec_path, 'audit_spec_version':state.audit_spec_version,
        'activity_roles':ACTIVITY_ROLES, 'activity_focus':state.config.get('activity_focus',[]),
        'understanding_status':'accepted_partial_map' if spec else 'unregistered',
        'candidates':[c.model_dump(mode='json',exclude={'history','check_ids'}) for c in state.question_candidates],
        'units':[u.model_dump(mode='json',exclude={'audit_question'}) for u in current],
        'claims':[c.model_dump(mode='json') for c in state.claims if any(c.id in u.obligation_ids for u in current)],
        'artifacts':[a.model_dump(mode='json') for a in artifacts], 'assessments':records,
        'frontier':frontier(state,spec), 'capacity':capacity(state), 'conclusions':conclusions(state,records), 'costs':costs(state),
        'handoffs':[s for s in state.selections if s.get('released_candidate_ids') or s['action'] in {'pause','explained'} or s['action']=='stop' and s.get('scope')!='run'],
        'pending_work':pending_work(state), 'current':{k:v for k,v in state.native_current.items() if k!='harness'},
        'latest_decision':state.selections[-1] if state.selections else None,
        'stop':state.run_stop, 'stop_reason':state.stop_reason}
    if compact:
        for candidate in result['candidates']:
            if candidate['status']!='active' and not any(u.id==state.active_unit_id and u.candidate_id==candidate['id'] for u in current):
                candidate['question']={key:value for key,value in candidate['question'].items()
                    if key in {'question','source_ids','fact_ids','obligation_relation_kind','unknowns','activity_classes'}}
        result['claims']=[{k:v for k,v in claim.items() if k in {'id','version','concern','description','source_ids'}} for claim in result['claims']]
        result['assessments']=[{k:v for k,v in record.items() if k in {'claim_id','direct_check_id','experiment_check_id','confirmed','outcome','blockers','raw_log','bounded_complete'}} for record in records]
        result['handoffs']=[{k:v for k,v in s.items() if k in {'operation_id','action','scope','reason','candidate_ids','rationale'}} for s in result['handoffs']]
    return result


def global_stop(raw):
    return raw.get('action')=='stop' and (raw.get('scope')=='run' or raw.get('reason')=='user_stop' or
        raw.get('reason') in {'resource_limit','tool_gap'} and raw.get('scope') not in {'candidate','family','focus'})


def family(state, candidate_ids):
    """Retain family identity through explicit forks and equivalent semantic anchors."""
    selected=set(candidate_ids)
    while True:
        roots=[c for c in state.question_candidates if c.id in selected]
        anchors={(tuple(sorted(c.question.fact_ids)),c.question.obligation_relation_kind,
            tuple(sorted(c.question.contexts))) for c in roots}
        linked={c.id for c in state.question_candidates if c.parent_candidate_id in selected or
            any(r.parent_candidate_id==c.id for r in roots) or
            (tuple(sorted(c.question.fact_ids)),c.question.obligation_relation_kind,tuple(sorted(c.question.contexts))) in anchors}
        if linked<=selected:return selected
        selected.update(linked)


def release(state, ids, reason, resume_conditions, closed=False):
    for c in state.question_candidates:
        if c.id in ids:
            c.status='closed' if closed else 'paused'
            c.stop_reason=reason
            c.resume_conditions=[] if closed else resume_conditions
    if any(u.id==state.active_unit_id and u.candidate_id in ids for u in state.units):
        state.active_unit_id=state.active_direct_check_id=state.active_model_id=None


def reject_local(state, operation_id, errors):
    current=next((u.candidate_id for u in state.units if u.id==state.active_unit_id),None)
    selected={current} if current else {c.id for c in state.question_candidates if c.status=='active'}
    ids=family(state,selected)
    record={'operation_id':operation_id,'action':'rejected','rationale':'; '.join(errors),
        'candidate_ids':sorted(ids)}
    if not any(s['operation_id']==operation_id for s in state.selections):
        state.selections.append(record)
        for c in state.question_candidates:
            if c.id in ids:c.stagnation+=1
    if ids and max(c.stagnation for c in state.question_candidates if c.id in ids)>=max(1,state.config.get('budget',{}).get('repair_attempts',4)):
        release(state,ids,'Local submission repair limit reached; compare other sourced directions',
            ['Supply a substantive answer or changed execution evidence before resuming this family'])
        return True
    return False


def stop_record(engine, raw, operation_id, controller=False):
    """Exit without accepting any attached semantic edits or requiring another turn."""
    state = engine.state
    record = {'operation_id':operation_id, 'action':'stop', 'scope':'run', 'reason':raw['reason'],
        'rationale':str(raw.get('rationale','Execution interrupted')), 'origin':'controller' if controller else 'agent',
        'pending_work':pending_work(state), 'remaining_seconds':engine.budget.remaining(),
        'remaining_agent_calls':engine.config.budget.agent_calls-state.usage.get('agent_calls',0)}
    if not controller:
        ignored = sorted(set(raw)-{'action','scope','reason','rationale','ref_ids'})
        refs = raw.get('ref_ids',[])
        known = {x.id for name in ('units','question_candidates','checks','materials','models','direct_checks') for x in getattr(state,name)}
        record['notes'] = {'ref_ids':refs, 'unapplied_fields':ignored,
            'diagnostics':['Stop metadata is explanatory only; semantic changes were not applied']+
                (['Unknown or stale references: '+str([r for r in refs if not isinstance(r,str) or r not in known])] if isinstance(refs,list) else ['ref_ids is not a list'])}
        if not any(s['operation_id']==operation_id for s in state.selections):state.selections.append(record)
        state.native_current = {'phase':'executed','action':'stop','scope':'run','reason':raw['reason'],'operation_id':operation_id}
        state.stop_reason = 'Scoped stop (run/'+raw['reason']+'): '+record['rationale']
    state.run_stop = record
    return record


def record_decision(engine, submission, operation_id, map_changed=False):
    from consensus_assurance.core.submissions import StopSubmission
    state, spec = engine.state, load(engine.state)
    if isinstance(submission,StopSubmission) and global_stop(submission.model_dump()) and submission.reason in {'resource_limit','user_stop','tool_gap'}:
        return stop_record(engine,submission.model_dump(mode='json'),operation_id)
    known = {x.id for name in ('question_candidates','units','claims','bindings','checks','semantic_reviews',
        'models','direct_checks','materials','review_issues','evidence','findings') for x in getattr(state,name)}
    known.update(audit_object_index(spec))
    known.update(s['operation_id'] for s in state.selections)
    feedback = submission.feedback
    if feedback:
        if not set(feedback.ref_ids)<=known:raise ValueError('Research feedback references unknown objects: '+', '.join(set(feedback.ref_ids)-known))
    record = {'operation_id':operation_id,'action':submission.action,'rationale':submission.rationale,
        'feedback':feedback.model_dump(mode='json') if feedback else {}, 'map_updated':map_changed}
    if isinstance(submission,StopSubmission):
        if not set(submission.ref_ids)<=known or not source_refs(state,submission.ref_ids):
            raise ValueError('Normal stop needs known research references with acquired source ownership')
        related = set(submission.ref_ids)|{u.id for u in state.units if u.id in submission.ref_ids or u.candidate_id in submission.ref_ids}
        if submission.scope in {'candidate','family'} and not any(c.id in submission.ref_ids for c in state.question_candidates):
            raise ValueError('Local stop must identify its Candidate or family')
        ids={c.id for c in state.question_candidates if c.id in submission.ref_ids}
        if submission.scope=='family':ids=family(state,ids)
        if submission.scope=='focus':
            focus=state.config.get('activity_focus',[]) or ['A1','A2']
            ids={c.id for c in state.question_candidates if set(c.question.activity_classes)&set(focus)}
        related.update(u.id for u in state.units if u.candidate_id in ids)
        related.update(i.id for i in state.review_issues if any(a.id==i.target_id and
            a.unit_id in related for a in state.direct_checks+state.models))
        if submission.reason=='bounded_completed':
            if submission.scope=='focus' or any(w['id'] in related or submission.scope=='run' for w in pending_work(state)):
                raise ValueError('Selected scope still has unfinished work; local checks do not establish focus exhaustion')
            if submission.scope=='run' and (not spec or any(c.status=='paused' for c in state.question_candidates)
                    or any(s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'} for s in spec.surfaces)):
                raise ValueError('Run has paused or unexpanded understanding')
        if submission.scope in {'run','focus'} and not submission.frontier_comparison.strip():
            raise ValueError('Normal run/focus stop needs a comparison of known directions, permissions and remaining capacity; checked Units do not exhaust the map')
        if submission.scope!='run':
            if submission.reason!='bounded_completed' and not submission.resume_conditions:
                raise ValueError('Local pause needs concrete resume_conditions; pending Units and issues remain visible')
            release(state,ids,submission.rationale,submission.resume_conditions,submission.reason=='bounded_completed')
        record.update(scope=submission.scope,reason=submission.reason,ref_ids=submission.ref_ids,
            frontier_comparison=submission.frontier_comparison,pending_work=pending_work(state),candidate_ids=sorted(ids),resume_conditions=submission.resume_conditions)
    state.selections.append(record)
    if isinstance(submission,StopSubmission) and global_stop(record):state.run_stop=record
    return record
