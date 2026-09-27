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


def view(state):
    spec = load(state)
    current = [u for u in state.units if u.status != 'revised']
    superseded = {a.previous_id for a in state.direct_checks+state.models}
    artifacts = [a for a in state.direct_checks+state.models if a.id not in superseded and
        (a.unit_id in {u.id for u in current} or getattr(a,'research_ref',None))]
    records = [r for r in state.monitor_results if (r.get('direct_check_id') or r.get('model_id')) in {a.id for a in artifacts}]
    return {'audit_spec_path':state.audit_spec_path, 'audit_spec_version':state.audit_spec_version,
        'activity_roles':ACTIVITY_ROLES, 'activity_focus':state.config.get('activity_focus',[]),
        'understanding_status':'accepted_partial_map' if spec else 'unregistered',
        'candidates':[c.model_dump(mode='json',exclude={'history','check_ids'}) for c in state.question_candidates],
        'units':[u.model_dump(mode='json',exclude={'audit_question'}) for u in current],
        'claims':[c.model_dump(mode='json') for c in state.claims if any(c.id in u.obligation_ids for u in current)],
        'artifacts':[a.model_dump(mode='json') for a in artifacts], 'assessments':records,
        'frontier':{'surfaces':[s.model_dump(mode='json') for s in spec.surfaces if s.disposition!='mapped'] if spec else [],
            'uninvestigated_core':[a for a,role in ACTIVITY_ROLES.items() if role['role']=='core'
                and not any(a in c.question.activity_classes for c in state.question_candidates)]},
        'pending_work':pending_work(state), 'current':{k:v for k,v in state.native_current.items() if k!='harness'},
        'latest_decision':state.selections[-1] if state.selections else None,
        'stop':state.run_stop, 'stop_reason':state.stop_reason}


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
        state.native_current = {'phase':'executed','action':'stop','operation_id':operation_id}
        state.stop_reason = 'Scoped stop (run/'+raw['reason']+'): '+record['rationale']
    state.run_stop = record
    return record


def record_decision(engine, submission, operation_id, map_changed=False):
    from consensus_assurance.core.submissions import StopSubmission
    state, spec = engine.state, load(engine.state)
    if isinstance(submission,StopSubmission) and submission.reason in {'resource_limit','user_stop','tool_gap'}:
        return stop_record(engine,submission.model_dump(mode='json'),operation_id)
    known = {x.id for name in ('question_candidates','units','claims','bindings','checks','semantic_reviews',
        'models','direct_checks','materials','review_issues','evidence','findings') for x in getattr(state,name)}
    known.update(audit_object_index(spec))
    known.update(s['operation_id'] for s in state.selections)
    feedback = submission.feedback
    if feedback:
        if not set(feedback.ref_ids)<=known:raise ValueError('Research feedback references unknown objects: '+', '.join(set(feedback.ref_ids)-known))
        if (feedback.understanding=='updated')!=map_changed:raise ValueError('Feedback understanding must match the accepted map change')
    record = {'operation_id':operation_id,'action':submission.action,'rationale':submission.rationale,
        'feedback':feedback.model_dump(mode='json') if feedback else {}}
    if isinstance(submission,StopSubmission):
        if not set(submission.ref_ids)<=known or not source_refs(state,submission.ref_ids):
            raise ValueError('Normal stop needs known research references with acquired source ownership')
        related = set(submission.ref_ids)|{u.id for u in state.units if u.id in submission.ref_ids or u.candidate_id in submission.ref_ids}
        if submission.scope in {'candidate','family'} and not any(c.id in submission.ref_ids for c in state.question_candidates):
            raise ValueError('Local stop must identify its Candidate or family')
        if submission.reason=='bounded_completed':
            if submission.scope=='focus' or any(w['id'] in related or submission.scope=='run' for w in pending_work(state)):
                raise ValueError('Selected scope still has unfinished work; local checks do not establish focus exhaustion')
            if submission.scope=='run' and (not spec or any(c.status=='paused' for c in state.question_candidates)
                    or any(s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'} for s in spec.surfaces)):
                raise ValueError('Run has paused or unexpanded understanding')
        if submission.scope=='focus' and submission.reason=='no_actionable_direction' and (not spec or not spec.surfaces or not submission.frontier_comparison.strip()):
            raise ValueError('Focus selection needs a registered frontier and bounded comparison')
        record.update(scope=submission.scope,reason=submission.reason,ref_ids=submission.ref_ids,
            frontier_comparison=submission.frontier_comparison,pending_work=pending_work(state))
    state.selections.append(record)
    if isinstance(submission,StopSubmission):state.run_stop=record
    return record
