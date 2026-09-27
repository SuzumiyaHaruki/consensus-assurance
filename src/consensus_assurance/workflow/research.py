"""Derived research frontier and attributed decisions; no second scheduler or evidence state."""
from .audit_spec import load, audit_object_index, slice_for


def pending_work(state):
    work=[{'id':u.id,'kind':'unit','candidate_id':u.candidate_id,
        'remaining':u.remaining_obligation_ids or u.obligation_ids,'reasons':u.coverage_limitations}
        for u in state.units if u.status not in {'checked','revised'}]
    artifacts={a.id:a for a in state.models+state.direct_checks}
    work += [{'id':i.id,'kind':'review_issue','unit_id':getattr(artifacts.get(i.target_id),'unit_id',None),
        'reasons':[i.explanation]} for i in state.review_issues if not i.resolved_by]
    work += [{'id':c.id,'kind':'candidate','reasons':c.question.unknowns}
        for c in state.question_candidates if not c.obligation_id and c.status in {'active','blocked'}]
    return work


def feedback_due(state):
    acknowledged={ref for s in state.selections for ref in s.get('feedback',{}).get('ref_ids',[])}
    nodes=[s['operation_id'] for s in state.selections if s.get('action') in {'pause','explained'}]
    nodes += [r.id for r in state.semantic_reviews]
    # Acknowledging a saved artifact addresses its latest review only; later reviews remain due.
    return [id for id in nodes if id not in acknowledged and not any(
        s.get('feedback') and set(s['feedback']['ref_ids'])&feedback_aliases(state,id) and id in s.get('feedback_nodes',[])
        for s in state.selections)]


def feedback_aliases(state,node):
    review=next((r for r in state.semantic_reviews if r.id==node),None)
    selection=next((s for s in state.selections if s['operation_id']==node),{})
    refs={node,*(review.target_versions if review else selection.get('candidate_ids',[]))}
    if review:refs.update(c.id for c in state.checks if c.model_id in review.target_versions or c.direct_check_id in review.target_versions)
    return refs


def view(state):
    from .review_contract import target_contract
    spec=load(state)
    focus=state.config.get('activity_focus',[])
    covered={a for c in state.question_candidates for a in c.question.activity_classes}
    return {'audit_spec_path':state.audit_spec_path,'audit_spec_version':state.audit_spec_version,
        'target_profile':spec.target_profile.model_dump(mode='json') if spec else None,
        'activity_focus':focus,'understanding_status':'accepted_partial_map' if spec else 'unregistered',
        'units':[u.model_dump(mode='json') for u in state.units],
        'claims':[c.model_dump(mode='json') for c in state.claims],
        'bindings':[b.model_dump(mode='json',exclude={'excerpt'}) for b in state.bindings],
        'candidates':[c.model_dump(mode='json',exclude={'history'}) for c in state.question_candidates],
        'artifacts':[{'artifact':a.model_dump(mode='json'),'review_contract':target_contract(state,a)} for a in state.direct_checks+state.models],
        'recent_executions':[c.model_dump(mode='json') for c in state.checks[-12:]],
        'recent_reviews':[r.model_dump(mode='json') for r in state.semantic_reviews[-12:]],
        'current':state.native_current,
        'open_issues':[i.model_dump(mode='json') for i in state.review_issues if not i.resolved_by],
        'frontier':{'surfaces':[s.model_dump(mode='json') for s in spec.surfaces if s.disposition!='mapped'] if spec else [],
            'status':'registered_partial' if spec and spec.surfaces else 'unregistered',
            'uninvestigated_focus':[a for a in focus if a not in covered],
            'map_unknowns':{k:v['unknowns'] for k,v in audit_object_index(spec).items() if v.get('unknowns')}},
        'pending_work':pending_work(state),
        'paused_candidates':[c.model_dump(mode='json') for c in state.question_candidates if c.status=='paused'],
        'feedback_due':feedback_due(state),'decisions':state.selections,
        'deferred_understanding':[s for s in state.selections if s.get('feedback',{}).get('understanding')=='deferred'],
        'question_chain':[{'candidate_id':c.id,'basis':slice_for(state,c.question) if spec else None,
            'basis_version':c.question.audit_spec_version,'unit_ids':[u.id for u in state.units if u.candidate_id==c.id],
            'review_ids':[r.id for r in state.semantic_reviews if r.unit_id in {u.id for u in state.units if u.candidate_id==c.id}]
            } for c in state.question_candidates],
        'stop':state.run_stop or next((s for s in reversed(state.selections) if s.get('action')=='stop'),None),
        'stop_reason':state.stop_reason}


def record_decision(engine,submission,operation_id,map_changed=False):
    """Check explicit handoffs; resource/user exits never require another model call."""
    from consensus_assurance.core.submissions import CandidateSubmission, CheckSubmission, StopSubmission
    state=engine.state
    spec=load(state)
    known={x.id for name in ('question_candidates','units','claims','bindings','checks','semantic_reviews',
        'models','direct_checks','materials','review_issues') for x in getattr(state,name)}
    known.update(audit_object_index(spec))
    known.update(s['operation_id'] for s in state.selections)
    forced=isinstance(submission,StopSubmission) and submission.reason in {'resource_limit','user_stop','tool_gap'}
    feedback=submission.feedback
    due=feedback_due(state)
    if feedback:
        if not set(feedback.ref_ids)<=known:raise ValueError('Research feedback references an unaccepted result or object')
        if (feedback.understanding=='updated')!=map_changed:raise ValueError('Feedback understanding must match the actual accepted map change')
    if due and submission.action!='review' and not forced:
        addressed=set(feedback.ref_ids) if feedback else set()
        for node in due:
            if not addressed&feedback_aliases(state,node):raise ValueError('Record the result, remaining discriminator and map disposition before the next research decision: '+node)
    work=pending_work(state)
    dispositions={d.target_id:d for d in submission.deferred_work}
    if len(dispositions)!=len(submission.deferred_work) or not set(dispositions)<={w['id'] for w in work}:
        raise ValueError('Work disposition must identify current unfinished work')
    selected=getattr(submission,'unit_id',None)
    if submission.action=='review':
        artifact=next((a for a in state.models+state.direct_checks if a.id==submission.artifact_id),None)
        selected=artifact.unit_id if artifact else None
    cand=submission.candidate if isinstance(submission,CheckSubmission) else submission if isinstance(submission,CandidateSubmission) else None
    if cand and not selected:selected=cand.candidate_id or cand.parent_candidate_id
    switching=(bool(cand and (not cand.candidate_id or cand.action in {'pause','explained'}))
        or isinstance(submission,StopSubmission) or bool(selected and state.active_unit_id and selected!=state.active_unit_id))
    if switching and not forced:
        omitted=[w['id'] for w in work if w['id'] not in dispositions and not (selected and (w['id']==selected or w.get('unit_id')==selected))]
        if omitted:raise ValueError('Continue pending local work or record why and how to resume it: '+', '.join(omitted))
    record={'operation_id':operation_id,'action':submission.action,'rationale':submission.rationale,
        'feedback':feedback.model_dump(mode='json') if feedback else {},'feedback_nodes':due if feedback else [],
        'deferred_work':[d.model_dump(mode='json') for d in submission.deferred_work],
        'remaining_seconds':engine.budget.remaining(),
        'remaining_agent_calls':engine.config.budget.agent_calls-state.usage.get('agent_calls',0)}
    if isinstance(submission,StopSubmission):
        if not set(submission.ref_ids)<=known:raise ValueError('Stop basis references unknown research objects')
        if submission.scope in {'candidate','family'} and not set(submission.ref_ids)&{c.id for c in state.question_candidates}:
            raise ValueError('Local stop must identify its Candidate or family')
        if submission.scope=='focus' and not state.config.get('activity_focus'):raise ValueError('No Activity focus is configured')
        if not forced and (not submission.ref_ids or not any(m.id in submission.ref_ids for m in state.materials)):
            raise ValueError('Normal stop needs related research objects and acquired source reasoning')
        if submission.reason=='bounded_completed':
            if submission.scope=='focus':raise ValueError('Local checked units do not establish focus exhaustion')
            ids=set(submission.ref_ids)
            related={u.id for u in state.units if u.candidate_id in ids or u.id in ids}
            if any(w['id'] in related or w.get('unit_id') in related or submission.scope=='run' for w in work):
                raise ValueError('Selected scope still has unfinished work; use an explicit incomplete stop')
            if any(c.id in ids and c.status not in {'explained','escalated'} for c in state.question_candidates):
                raise ValueError('Candidate completion needs an explained hypothesis or reviewed bounded check')
            if submission.scope=='run' and (any(c.status=='paused' for c in state.question_candidates) or
                    not spec or any(s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'} for s in spec.surfaces)):
                raise ValueError('Run has paused or unexpanded understanding; state a bounded local scope or an incomplete run stop')
        if submission.scope=='focus' and submission.reason=='no_actionable_direction':
            if not spec or not spec.surfaces or not submission.frontier_comparison.strip():
                raise ValueError('Focus selection needs a registered frontier and bounded comparison; checked units are insufficient')
        record.update(scope=submission.scope,reason=submission.reason,ref_ids=submission.ref_ids,
            frontier_comparison=submission.frontier_comparison)
    state.selections.append(record)
    return record
