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


def source_refs(state, refs, include_executions=False):
    """Resolve retained ownership; execution observations need not have a graph yet."""
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
    if include_executions:
        materials.update(c.id for c in state.checks if c.action in
            {'exploration','direct_check','model_check','reachability','trace_calibration'})
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


def frontier(state, spec, results=()):
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
            'unreferenced_behavior_ids':sorted(edges-referenced),
            'investigations':[{'candidate_id':c.id,'status':c.status,'lifecycle':c.question.obligation_relation_kind,
                'question':c.question.question,'remaining':c.question.unknowns,'resume_conditions':c.resume_conditions,
                'results':[{'claim_id':r['claim_id'],'disposition':r['disposition']} for r in results if r['candidate_id']==c.id]}
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
        unit=next((u for u in state.units if u.status!='revised' and claim.id in u.obligation_ids),None)
        result.append({'claim_id':claim.id,'candidate_id':unit.candidate_id if unit else None,
            'question':unit.audit_question.question if unit and unit.audit_question else None,
            'concern':claim.concern,'description':claim.description,
            'disposition':'confirmed_in_scope' if confirmed else 'bounded_no_violation' if checked and all(r.get('outcome')=='holds' for r in observed) else 'investigation_lead',
            'scope':claim.scope.model_dump(mode='json'),'check_ids':[r['experiment_check_id'] for r in observed],
            'blockers':list(dict.fromkeys(b for r in observed for b in r['blockers'])),
            'conditions':[{'check_id':r['experiment_check_id'],'scope':r.get('scope',{}),
                'adaptations':r.get('adaptations',[]),
                'notes':r.get('conditions',{'supplementary':r.get('boundaries',[])})} for r in observed]})
    return result


def costs(state):
    from datetime import datetime
    def seconds(check):
        return max(0,(datetime.fromisoformat(check.ended_at)-datetime.fromisoformat(check.started_at)).total_seconds()) if check.ended_at and check.started_at else 0
    rejected={s['operation_id'] for s in state.selections if s['action']=='rejected'}
    calls=[c for c in state.checks if c.action=='agent_turn']
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
    results=conclusions(state,records)
    overview=spec.core_overview if spec else None
    ready=bool(overview and overview.status=='usable')
    directed=bool((state.config.get('directed_question') or '').strip())
    drafts={s['draft_id']:s for s in state.selections if s.get('draft_id')}
    result = {'audit_spec_path':state.audit_spec_path, 'audit_spec_version':state.audit_spec_version,
        'activity_roles':ACTIVITY_ROLES, 'activity_focus':state.config.get('activity_focus',[]),
        'understanding_status':overview.status if overview else 'incomplete' if spec else 'unregistered',
        'core_overview':overview.model_dump(mode='json') if overview else None,
        'understanding_changes':[{'operation_id':s['operation_id'],'version':s['accepted_versions']['audit_spec'],
            'delta':s.get('map_delta',{}),'explanations':s.get('map_changes',{}),'effects':s.get('map_effects',{})}
            for s in state.selections if s.get('map_updated')],
        'next_objective':{'action':'investigate_and_refocus' if ready or directed else 'recover_core_understanding',
            'boundary':'user_directed' if directed else 'both_core_paths',
            'reason':'Use results to update understanding and compare the remaining frontier' if ready or directed else
                'Save partial maps and leads; explain formation, context transitions and their connection before focused investigation',
            'core_gaps':overview.core_gaps if overview else ['Initial two-line explanation is not yet recorded']},
        'drafts':[s for s in drafts.values() if s['draft_status']!='accepted'],
        'candidates':[c.model_dump(mode='json',exclude={'history','check_ids'}) for c in state.question_candidates],
        'units':[u.model_dump(mode='json',exclude={'audit_question'}) for u in current],
        'claims':[c.model_dump(mode='json') for c in state.claims if any(c.id in u.obligation_ids for u in current)],
        'artifacts':[a.model_dump(mode='json') for a in artifacts], 'assessments':records,
        'frontier':frontier(state,spec,results), 'capacity':capacity(state), 'conclusions':results, 'costs':costs(state),
        'handoffs':[s for s in state.selections if s.get('feedback') or s.get('released_candidate_ids') or s['action'] in {'pause','explained'} or s['action']=='stop' and s.get('scope')!='run'],
        'pending_work':pending_work(state), 'current':{k:v for k,v in state.current_submission.items() if k!='harness'},
        'latest_decision':state.selections[-1] if state.selections else None,
        'stop':state.run_stop, 'stop_reason':state.stop_reason}
    for candidate in result['candidates']:
        candidate['results']=[{k:r[k] for k in ('claim_id','description','disposition')} for r in results if r['candidate_id']==candidate['id']]
        candidate['open_issue_ids']=[i.id for i in state.review_issues if i.target_id==candidate['id'] and not i.resolved_by]
        candidate['current_applicability']='pending_review' if candidate['open_issue_ids'] else 'within_recorded_scope'
        units={u.id for u in state.units if u.candidate_id==candidate['id']}
        owned={a.id for a in state.models+state.direct_checks if a.unit_id in units}
        candidate['executions']=[{'check_id':c.id,'artifact_id':c.direct_check_id or c.model_id,
            'action':c.action,'status':c.status.value,'outcome':c.outcome}
            for c in state.checks if c.direct_check_id in owned or c.model_id in owned]
    if compact:
        result['understanding_changes']=[{'operation_id':c['operation_id'],'version':c['version'],
            'changed_object_ids':list(c['delta']),'effects':c['effects']} for c in result['understanding_changes'][-1:]]
        if result['latest_decision']:result['latest_decision']={k:v for k,v in result['latest_decision'].items() if k!='map_delta'}
        for candidate in result['candidates']:
            if candidate['status']!='active' and not any(u.id==state.active_unit_id and u.candidate_id==candidate['id'] for u in current):
                candidate['question']={key:value for key,value in candidate['question'].items()
                    if key in {'question','source_ids','fact_ids','obligation_relation_kind','unknowns','activity_classes'}}
        result['claims']=[{k:v for k,v in claim.items() if k in {'id','version','concern','description','source_ids'}} for claim in result['claims']]
        result['assessments']=[{k:v for k,v in record.items() if k in {'claim_id','direct_check_id','experiment_check_id','confirmed','outcome','blockers','raw_log','bounded_complete'}} for record in records]
        substantive=[s for s in result['handoffs'] if s.get('feedback')]
        result['handoffs']=[{k:v for k,v in s.items() if k in {'operation_id','action','scope','reason','candidate_ids','rationale','feedback'}}
            for s in (substantive or result['handoffs'])[-1:]]
    return result


def current_view(state, root, implementation=None, compact=False):
    """Rebuild a snapshot from state and trusted runtime context, never an old projection."""
    from consensus_assurance.adapters.validation import validation_tool
    from .review_contract import target_contract
    result = view(state,compact=compact)
    targets=[a for a in state.direct_checks+state.models if a.id in {x['id'] for x in result['artifacts']}]
    targets.extend(c for c in state.question_candidates if any(i.target_id==c.id and not i.resolved_by for i in state.review_issues))
    contracts=[target_contract(state,a) for a in targets]
    result.update(run_id=state.id,snapshot_id=state.snapshot.id,elapsed_seconds=state.elapsed_seconds,
        source_path=str(root/'agent-source'),draft_path=str(root/'draft'),state_path=str(root/'state.json'),
        product_schemas=str(root/'product-schemas.json'),submission_schema=str(root/'submission.schema.json'),
        method_path=str(root/'audit-method.md'),
        optional_model_method=str(root/'model-method.md') if state.config.get('verifier_backend','none')!='none' else None,
        directed_question=state.config.get('directed_question'),tools=state.tools,
        implementation={'name':implementation.name,'harness_kind':implementation.harness_kind,
            'harness_filename':implementation.harness_filename,'instructions':implementation.harness_instructions,
            'support_path':str(root/'target-support')} if implementation else None,
        validation=validation_tool(root),
        rejected_drafts=[str(p) for p in sorted((root/'submissions').glob('*/diagnostics.json'))],
        review_contracts=[{k:c[k] for k in ('target_id','object_type','version','required_aspects','questions','optional_questions')}
            for c in contracts])
    return result


def global_stop(raw):
    return raw.get('action')=='stop' and (raw.get('scope')=='run' or raw.get('reason')=='user_stop' or
        raw.get('reason') in {'resource_limit','tool_gap'} and raw.get('scope') not in {'candidate','family','focus'})


def release(state, ids, reason, resume_conditions, closed=False):
    for c in state.question_candidates:
        if c.id in ids:
            c.status='closed' if closed else 'paused'
            c.stop_reason=reason
            c.resume_conditions=[] if closed else resume_conditions
    if any(u.id==state.active_unit_id and u.candidate_id in ids for u in state.units):
        state.active_unit_id=state.active_direct_check_id=state.active_model_id=None


def reject_local(state, operation_id, errors, raw):
    """Track one draft through existing operations, including before acceptance."""
    if any(s['operation_id']==operation_id for s in state.selections):
        return next(s.get('draft_status')=='paused' for s in state.selections if s['operation_id']==operation_id)
    target=raw.get('candidate') if isinstance(raw.get('candidate'),dict) else raw
    repair_of=raw.get('repair_of') or target.get('repair_of')
    previous=next((s for s in state.selections if s['operation_id']==repair_of and s['action']=='rejected'),None)
    if previous is None and not raw and state.selections:
        last=state.selections[-1]
        if last['action']=='rejected' and last.get('submitted_path')==errors.get('submitted_path'):previous=last
    ids={c.id for c in state.question_candidates if c.id==target.get('candidate_id')}
    ids.update(u.candidate_id for u in state.units if raw.get('unit_id') in {u.id,u.candidate_id})
    diagnostics=sorted(errors['errors'])
    repeats=previous.get('repeats',1)+1 if previous and previous.get('diagnostics')==diagnostics else 1
    paused=repeats>=max(1,state.config.get('budget',{}).get('repair_attempts',4))
    state.selections.append({'operation_id':operation_id,'action':'rejected','rationale':'; '.join(diagnostics),
        'candidate_ids':sorted(ids),'draft_id':previous['draft_id'] if previous else operation_id,
        'repair_of':previous['operation_id'] if previous else None,'diagnostics':diagnostics,'repeats':repeats,
        'draft_status':'paused' if paused else 'active','raw_path':errors['raw_path'],
        'submitted_path':errors.get('submitted_path')})
    for c in state.question_candidates:
        if c.id in ids:c.stagnation=repeats
    if paused:
        release(state,ids,'Repeated identical draft diagnostics; compare other sourced directions',
            ['Repair the archived draft diagnostics with new information before resuming'])
    return paused


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
        state.current_submission = {'phase':'executed','action':'stop','scope':'run','reason':raw['reason'],'operation_id':operation_id}
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
        if not source_refs(state,feedback.ref_ids,include_executions=True):
            raise ValueError('Research feedback needs acquired sources or a retained research execution')
        candidates={c.id:c for c in state.question_candidates}
        if not set(feedback.question_updates)<=candidates.keys():raise ValueError('Feedback question_updates must name saved Candidates')
        if feedback.question_updates and not source_refs(state,feedback.ref_ids):raise ValueError('Question updates need sourced answers through retained references')
    record = {'operation_id':operation_id,'action':submission.action,'rationale':submission.rationale,
        'feedback':feedback.model_dump(mode='json') if feedback else {}, 'map_updated':map_changed}
    if submission.repair_of:
        prior=next((s for s in state.selections if s['operation_id']==submission.repair_of and s['action']=='rejected'),None)
        if prior is None:raise ValueError('repair_of must name a retained rejected operation')
        record.update(repair_of=submission.repair_of,draft_id=prior['draft_id'],draft_status='accepted')
    if isinstance(submission,StopSubmission):
        if not set(submission.ref_ids)<=known or not source_refs(state,submission.ref_ids):
            raise ValueError('Normal stop needs known research references with acquired source ownership')
        related = set(submission.ref_ids)|{u.id for u in state.units if u.id in submission.ref_ids or u.candidate_id in submission.ref_ids}
        if submission.scope in {'candidate','family'} and not any(c.id in submission.ref_ids for c in state.question_candidates):
            raise ValueError('Local stop must identify its Candidate or family')
        ids={c.id for c in state.question_candidates if c.id in submission.ref_ids}
        if submission.scope=='focus':
            focus=state.config.get('activity_focus',[]) or ['A1','A2']
            ids={c.id for c in state.question_candidates if set(c.question.activity_classes)&set(focus)}
        related.update(u.id for u in state.units if u.candidate_id in ids)
        related.update(i.id for i in state.review_issues if any(a.id==i.target_id and
            a.unit_id in related for a in state.direct_checks+state.models))
        if submission.reason=='bounded_completed':
            if submission.scope=='focus' or any(w['id'] in related or submission.scope=='run' for w in pending_work(state)):
                raise ValueError('Selected scope still has unfinished work; local checks do not establish focus exhaustion')
            if submission.scope=='run' and (not spec or not (state.config.get('directed_question') or '').strip() and (not spec.core_overview or spec.core_overview.status!='usable') or any(c.status=='paused' for c in state.question_candidates)
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
