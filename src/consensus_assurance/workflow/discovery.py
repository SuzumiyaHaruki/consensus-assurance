"""Repository reading, candidate discovery and incremental dependency expansion."""
from pathlib import Path
from consensus_assurance.core.proposals import Discovery, Derivation, GraphPatch
from consensus_assurance.adapters.storage.files import write_json
from .materials import initial_materials, ReadingPlan, uid, material_allowance
from .graph import apply_patch, validate_patch
from .errors import Blocked
from . import inquiry


def context(engine, unit=None):
    result = {"capabilities": [c.model_dump(mode="json") for c in engine.state.capabilities],
        "parameters": engine.config.parameters, "remaining_seconds": engine.budget.remaining(),
        "activity_focus": engine.config.activity_focus,
        "directed_question": engine.config.directed_question,
        "snapshot_id": engine.state.snapshot.id,
        "harness_kind": engine.implementation.harness_kind if engine.implementation else None,
        "harness_instructions": engine.implementation.harness_instructions if engine.implementation else "No execution backend configured; source review and local ModelDraft/TLC remain available",
        "target":engine.config.target.model_dump(mode="json")}
    if unit:
        from .task_view import local_workset
        result.update(local_workset(engine,unit))
    else:
        result["materials"]=[item.model_dump(mode="json") for item in engine.state.materials]
    from .audit_spec import load
    spec=load(engine.state)
    result["audit_spec"]=({'version':spec.version,'facts':[f.model_dump(mode='json') for f in spec.facts if unit.audit_question and f.id in unit.audit_question.fact_ids]} if unit else spec.model_dump(mode='json')) if spec else None
    return result

def discover(engine):
    source = engine.root / "source"
    if "materials" not in engine.state.completed_steps:
        if not engine.state.materials and 'automatic-survey' not in engine.state.read_plans:
            sample=initial_materials(source, engine.state.snapshot, engine.config.budget, engine.knowledge)
            engine.read([{'file':m.file,'start_line':m.start_line,'end_line':m.end_line,'reason':'Automatic bounded survey'} for m in sample if m.kind!='protocol_candidate'],purpose='breadth',partial=True,plan_id='automatic-survey')
            for m in sample:
                if m.kind=='protocol_candidate':engine.state.materials.append(m)

        if not engine.state.materials and material_allowance(engine.state,engine.config.budget,"breadth")["available_chars"]==0:raise Blocked("No material capacity for a grounded initial plan; no agent request sent")
        plan, _ = engine.ask("read", ReadingPlan, {"initial_materials": [m.model_dump(mode="json") for m in engine.state.materials],
            "activity_focus":engine.config.activity_focus,"reading_goal":"Recover one sourced responsibility relation and its decisive dependencies; the material allowance is a ceiling, not a target"},purpose="breadth")
        engine.read(plan.requests,purpose="breadth",partial=True,plan_id="initial-reading",related_ids=plan.related_ids,reason=plan.rationale)
        engine.state.completed_steps.append("materials"); engine.advance("discover")
    if "understanding" not in engine.state.completed_steps:
        from .audit_spec import validate, accept, SpecIssue
        pending=next((t for t in engine.state.inquiry_tasks if t.kind=='spec_refine' and t.draft_path and t.status!='completed'),None)
        if not pending and not engine.state.audit_spec_path:
            try:
                proposal,check=engine.ask('discover',Discovery,engine.context(),lambda p:validate(engine.state,p.audit_spec),purpose='breadth')
                accept(engine,proposal.audit_spec)
                if proposal.reading_requests:inquiry.enqueue(engine.state,'spec_refine','Resolve decisive understanding gaps','initial-reads',requests=proposal.reading_requests)
            except SpecIssue as exc:
                pending=inquiry.enqueue(engine.state,'spec_refine','Revise the unaccepted descriptive subgraph from actual source','initial-draft')
                pending.draft_path=exc.draft_path;pending.diagnostics=[d.model_dump(mode='json') for d in exc.diagnostics]
                engine.checkpoint('initial_descriptive_refinement_queued')
        while pending and pending.status!='completed':
            if pending.status=='blocked':raise Blocked(pending.stop_reason)
            inquiry.process_task(engine,pending)
            pending=next(t for t in engine.state.inquiry_tasks if t.id==pending.id)
        engine.state.completed_steps.append('understanding');engine.checkpoint('implementation_understanding_accepted')
    if "discovery" not in engine.state.completed_steps:
        engine.state.completed_steps.append('discovery');engine.advance('select')


def active_candidate(state):
    return next((c for c in state.question_candidates if c.status=='active'),None)


def candidate_blockage(state,candidate):
    if candidate.status not in {'blocked','active'}:return None
    tasks=[t for t in state.inquiry_tasks if t.id in candidate.spec_task_ids and t.status=='blocked']
    if any(t.preparation_failures or t.semantic_failures or any(d['category']=='semantic' for d in t.diagnostics+(t.repair_session or {}).get('diagnostics',[])) for t in tasks):return 'workflow_blocked'
    deferred=any(i['status']=='deferred' for id in [candidate.read_plan_id]+[t.read_plan_id for t in tasks] for i in state.read_plans.get(id,{}).get('items',[]))
    if candidate.status=='blocked' and not deferred and not tasks and not candidate.question.requests and not candidate.stagnation:return 'evidence_blocked'
    if deferred or any(state.usage.get(k,0)>=v for k,v in state.config.get('budget',{}).items() if k in {'agent_calls','total_seconds'} and v>0):return 'resource_blocked'
    if candidate.status=='blocked':return 'workflow_blocked'
    return None


def derive_context(engine):
    state=engine.state;candidate=active_candidate(state)
    return {'candidate_id':candidate.id if candidate else None,'remaining_seconds':engine.budget.remaining()}


def derivation_graph(reply):
    from consensus_assurance.core.proposals import UnitDraft
    units=[]
    if reply.obligation:
        units=[UnitDraft(id='unit-'+reply.obligation.id,obligation_ids=[reply.obligation.id],binding_ids=[b.id for b in reply.bindings],
            relation_ids=[r.id for r in reply.dependencies],scope=reply.obligation.scope,audit_question=reply.audit_question,rationale=reply.selection_rationale)]
    return GraphPatch(claims=([reply.obligation] if reply.obligation else [])+reply.context_claims,bindings=reply.bindings,
        relations=reply.dependencies,units=units,rationale=reply.selection_rationale)


def classify_derivation_outcome(state,reply):
    """Classify the candidate decision independently of descriptive feedback; no mutation."""
    from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
    def invalid_reference(path,message):
        raise DiagnosticError([Diagnostic(code='candidate_reference',category='association',paths=[path],message=message,allowed=['representation'])])
    q=reply.audit_question;current=active_candidate(state)
    selected=next((c for c in state.question_candidates if c.id==reply.candidate_id),None)
    parent=next((c for c in state.question_candidates if c.id==reply.fork_from_candidate_id),None)
    pausing=reply.candidate_action=='pause'
    if reply.candidate_id:
        if selected is None or selected.status not in {'active','paused','blocked'}:
            invalid_reference('/candidate_id','Select an existing active, paused or blocked candidate ID')
        if reply.fork_from_candidate_id:invalid_reference('/fork_from_candidate_id','Choose an existing candidate or fork a new one')
        if current and current.id!=selected.id:invalid_reference('/candidate_id','Pause the current question before resuming another ID')
    elif current and not reply.fork_from_candidate_id:
        invalid_reference('/candidate_id','Continue the selected question by its candidate_id')
    if pausing:
        if not current or selected is None or selected.id!=current.id:invalid_reference('/candidate_action','Pause requires the current active candidate ID')
        if not reply.resume_conditions:invalid_reference('/resume_conditions','Pause needs concrete discriminators that justify resuming the same candidate')
    elif reply.resume_conditions:invalid_reference('/resume_conditions','Resume conditions belong only to a pause decision')
    if reply.fork_from_candidate_id and parent is None:invalid_reference('/fork_from_candidate_id','Fork requires an existing parent ID')
    if parent and not reply.fork_reason.strip():invalid_reference('/fork_reason','Explain why the question needs a separate candidate')
    if reply.fork_reason and not parent:invalid_reference('/fork_from_candidate_id','Fork reason requires its parent candidate ID')
    if current and parent and parent.id!=current.id:invalid_reference('/fork_from_candidate_id','Fork must pause the active candidate')
    graph=reply.obligation or reply.bindings or reply.dependencies or reply.context_claims
    if not reply.selection_rationale.strip():raise ValueError('Explain the bounded analysis outcome')
    if q is None:
        if reply.frontier_entry_point:
            if selected or current or graph or reply.descriptive_issues or pausing:
                raise ValueError('A frontier read is a separate selection without candidate or graph edits')
            from .audit_spec import load
            spec=load(state)
            if not spec or not any(s.entry_point==reply.frontier_entry_point and s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'} for s in spec.surfaces):
                invalid_reference('/frontier_entry_point','Select an existing unresolved surface')
            return 'frontier'
        if pausing:
            if graph or reply.reading_requests or reply.descriptive_issues:raise ValueError('A pause without a replacement question cannot add semantic work')
            return 'pause'
        if selected and not (graph or reply.reading_requests or reply.descriptive_issues):return 'resume'
        if not current and not (graph or reply.reading_requests or reply.descriptive_issues):return 'selection_exhausted'
        raise ValueError('Selection can stop only after candidates were considered, with no active question or proposed work')
    if reply.frontier_entry_point:invalid_reference('/frontier_entry_point','Frontier reading cannot replace the selected candidate')
    reads=reply.reading_requests+q.requests
    if not reply.obligation and graph:raise ValueError('A pre-obligation candidate cannot create graph objects')
    if q.disposition=='explained_by_existing_mechanism' and (graph or reads or not q.counterevidence):
        raise ValueError('Explained candidates need sourced protections, no graph objects and no pending reads')
    if not reply.obligation and (q.disposition=='ready_for_check' or reads and q.preferred_check!='source_review'):
        raise ValueError('Pre-obligation candidates use source_review for acquisition; a ready check requires its obligation')
    prefix='pause_and_' if pausing else ''
    if reply.obligation:return prefix+'escalate'
    if q.disposition=='explained_by_existing_mechanism':return prefix+'explained'
    if reads:return prefix+'continue_read'
    reviewed=not pausing and selected and (selected.material_ids or selected.history or len(selected.check_ids)>1)
    if reviewed and q.disposition=='needs_specific_evidence' and q.preferred_check=='source_review' and q.unknowns:
        return prefix+'blocked_evidence'
    raise ValueError('An initial question needs actionable source or a grounded result; evidence-blocked requires a reviewed candidate and explicit unknowns')


def validate_derivation(state,reply):
    from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
    from .audit_spec import load,audit_object_index,validate_question
    spec=load(state);known={m.id for m in state.materials}
    objects=set(audit_object_index(spec))
    issues=[]
    for i,issue in enumerate(reply.descriptive_issues):
        if not set(issue.object_ids)<=objects or not set(issue.source_ids)<=known or not issue.reason.strip():
            issues.append(Diagnostic(code='descriptive_issue',category='material',object_ids=issue.object_ids,paths=[f'/descriptive_issues/{i}'],material_ids=sorted(known&set(issue.source_ids)),message='Describe an existing inventory object issue with acquired source and reason',allowed=['representation','read']))
    q=reply.audit_question;current=active_candidate(state)
    receipts=[r for r in state.packet_receipts if r['kind']=='derive' and (not current or r.get('candidate_id')==current.id)]
    attached=set(next((r['material_ids'] for r in reversed(receipts) if r['status'] not in {'blocked_context_limit','prepared'}),[])) if receipts else set(current.material_ids if current else [])|set(next((r['material_ids'] for r in reversed(state.packet_receipts) if r['kind']=='derive' and r['status'] not in {'blocked_context_limit','prepared'}),[]))
    try:
        if spec is None:raise ValueError('An accepted inventory is required')
        outcome=classify_derivation_outcome(state,reply)
        if q:
            validate_question(spec,q)
            if not q.question.strip() or not q.trigger_rationale.strip():raise ValueError('State the discriminator and selection reason')
    except DiagnosticError as exc:
        issues.extend(exc.diagnostics)
    except ValueError as exc:
        questions=[x for x in (q,current.question if current else None) if x]
        refs={id for x in questions for id in x.fact_ids+x.behavior_ids}
        sources={id for x in questions for id in x.source_ids}|attached
        issues.append(Diagnostic(code='question_identity',category='semantic',object_ids=sorted(refs),material_ids=sorted(sources&known),paths=['/audit_question'],message=str(exc),allowed=['read','semantic_revision']))
    if q:
        invalid=set(q.source_ids)-known
        from .sources import includes
        missing=not attached or not any(includes(state,[id],attached) for id in q.source_ids)
        terminal=reply.obligation or not (reply.reading_requests+q.requests)
        if invalid or terminal and missing:
            issues.append(Diagnostic(code='question_source_reference' if invalid else 'question_source_missing',category='material',
                object_ids=q.fact_ids+q.behavior_ids,paths=['/audit_question/source_ids'],material_ids=sorted(set(attached)&known),
                message='Use actual material IDs; terminal reasoning requires nonempty currently attached/read sources',allowed=['representation','read']))
    if reply.obligation and (reply.obligation.kind!='obligation' or not reply.bindings):
        issues.append(Diagnostic(code='derivation_primary',category='association',object_ids=[reply.obligation.id],paths=['/obligation','/bindings'],message='A primary obligation requires its actual code bindings',allowed=['association','read']))
    existing={o.id for name in ('claims','bindings','relations','units') for o in getattr(state,name)}
    candidates=[('/obligation',reply.obligation)]+[(f'/{name}/{i}',o) for name in ('bindings','dependencies','context_claims') for i,o in enumerate(getattr(reply,name))]
    for path,obj in candidates:
        if obj and obj.id in existing:
            issues.append(Diagnostic(code='existing_graph_identity',category='semantic',object_ids=[obj.id],paths=[path],material_ids=sorted(known&set(getattr(obj,'source_ids',[]))),message='Derivation adds candidates; existing semantic objects require attributed F2 rather than replacement',allowed=['read','semantic_revision']))
    if reply.obligation:
        from .sources import dependency_closure,includes
        graph=derivation_graph(reply);objects={o.id:o for name in ('claims','bindings','relations','units') for o in getattr(graph,name)}
        required,_=dependency_closure(objects,objects)
        missing=[id for id in required&known if not includes(state,[id],attached)]
        if missing:issues.append(Diagnostic(code='derivation_source_missing',category='material',object_ids=[reply.obligation.id],material_ids=sorted(missing),message='Read and attach the actual obligation/code dependency source before escalation',allowed=['read']))
    if issues:raise DiagnosticError(issues)
    if outcome not in {'escalate','pause_and_escalate'}:return outcome
    try:validate_patch(state,derivation_graph(reply))
    except DiagnosticError as exc:
        patch=derivation_graph(reply)
        merged={name:list(dict.fromkeys([o.id for o in getattr(state,name)]+[o.id for o in getattr(patch,name)])) for name in ('claims','bindings','relations','units')}
        locations={o.id:path for path,o in candidates if o}
        locations.update({u.id:'/audit_question' for u in patch.units})
        for d in exc.diagnostics:
            d.object_ids=list(dict.fromkeys(reply.obligation.id if id in {u.id for u in patch.units} else id for id in d.object_ids))
            def wire(path):
                if path in {'/claims','/units','/relations'}:return {'/claims':'/obligation','/units':'/audit_question','/relations':'/dependencies'}[path]
                parts=path.split('/')
                if len(parts)>2 and parts[1] in merged and parts[2].isdigit():
                    owner=merged[parts[1]][int(parts[2])]
                    if owner in locations and parts[1]!='units':return locations[owner]+('/'+'/'.join(parts[3:]) if parts[3:] else '')
                if path.startswith('/claims/0'):return path.replace('/claims/0','/obligation',1)
                if path.startswith('/claims/'):
                    parts=path.split('/');parts[1]='context_claims';parts[2]=str(int(parts[2])-1);return '/'.join(parts)
                if path.startswith('/units/'):
                    return '/audit_question' if '/audit_question' in path else '/dependencies' if '/relation_ids' in path else '/bindings'
                return path.replace('/relations','/dependencies',1)
            d.paths=list(dict.fromkeys(wire(path) for path in d.paths))
        raise
    return outcome


def accept_derivation(engine,reply,check_id):
    from .transactions import commit_graph
    from consensus_assurance.core.types import QuestionCandidate
    def commit(proxy):
        state=proxy.state
        outcome=validate_derivation(state,reply)
        if outcome=='selection_exhausted':
            state.gaps.append('No additional tractable candidate selected: '+reply.selection_rationale)
            state.completed_steps.append('derived-spec:'+str(state.audit_spec_version))
            return
        if outcome=='frontier':
            from .audit_spec import load
            surface=next(s for s in load(state).surfaces if s.entry_point==reply.frontier_entry_point)
            inquiry.enqueue(state,'spec_refine',reply.selection_rationale,check_id+':frontier',
                target_ids=['surface:'+surface.entry_point],surface_entry_points=[surface.entry_point],requests=reply.reading_requests)
            return
        candidate=next((c for c in state.question_candidates if c.id==reply.candidate_id),None)
        if reply.candidate_action=='pause':
            candidate.status='paused';candidate.stop_reason=reply.selection_rationale
            candidate.resume_conditions=list(reply.resume_conditions)
            if outcome=='pause':
                candidate.check_ids.append(check_id)
                return
            candidate=None;outcome=outcome.removeprefix('pause_and_')
        if outcome=='resume':
            candidate.status='active';candidate.stop_reason=''
            candidate.resume_conditions=[]
            candidate.check_ids.append(check_id)
            return
        q=reply.audit_question.model_copy(deep=True)
        if candidate:
            candidate.history.append(candidate.question.model_copy(deep=True))
            candidate.question=q;candidate.status='active';candidate.stop_reason=''
        else:
            parent=next((c for c in state.question_candidates if c.id==reply.fork_from_candidate_id),None)
            if parent and parent.status=='active':parent.status='paused';parent.stop_reason=reply.fork_reason
            candidate=QuestionCandidate(question=q,parent_candidate_id=reply.fork_from_candidate_id,fork_reason=reply.fork_reason)
            state.question_candidates.append(candidate)
        candidate.check_ids.append(check_id)
        candidate.spec_task_ids=[]
        for issue in reply.descriptive_issues:
            task=inquiry.enqueue(state,'spec_refine',issue.reason,check_id,target_ids=issue.object_ids,
                candidate_id=candidate.id if issue.candidate_effect=='requires_recheck' else None,
                diagnostics=[{'code':'audit_spec_semantics','category':'semantic','object_ids':issue.object_ids,'material_ids':issue.source_ids,'message':issue.reason,'allowed':['read','semantic_revision'],'details':{'check_id':check_id}}])
            if issue.candidate_effect=='requires_recheck':candidate.spec_task_ids.append(task.id)
        requests=list({(r.file,r.start_line,r.end_line,r.symbol,r.literal):r for r in reply.reading_requests+q.requests}.values())
        q.requests=requests
        if candidate.spec_task_ids:
            candidate.stage='read' if requests else 'analyze'
            if requests:candidate.read_plan_id=uid()
            return
        if outcome in {'explained','blocked_evidence'}:
            candidate.status='explained' if outcome=='explained' else 'blocked'
            candidate.stage='analyze';candidate.stop_reason=reply.selection_rationale
            return
        if outcome=='continue_read':
            candidate.stage='read';candidate.read_plan_id=uid()
            return
        patch=derivation_graph(reply);patch.units[0].audit_question=q
        apply_patch(state,patch)
        unit=next(u for u in state.units if u.id==patch.units[0].id)
        candidate.status='escalated';candidate.obligation_id=reply.obligation.id
        inquiry.review_unit(proxy,unit,'derived:'+check_id)
    path=engine.root/f'derivation-{check_id}.json';write_json(path,reply);engine.state.derivation_path=str(path)
    commit_graph(engine,'derive-'+check_id,reply.model_dump(mode='json'),commit)
    return active_candidate(engine.state) is None and bool(reply.obligation or reply.audit_question is None)


def continue_candidate(engine,candidate):
    """Resume only this question's source work and selected inventory corrections."""
    state=engine.state
    for id in candidate.spec_task_ids:
        task=next(t for t in state.inquiry_tasks if t.id==id)
        while task.status not in {'completed','blocked'}:
            try:inquiry.process_task(engine,task)
            except Blocked as exc:
                task=next(t for t in state.inquiry_tasks if t.id==id)
                task.status='blocked';task.stop_reason=str(exc);task.repair_session=state.pending_output_repair
                state.pending_output_repair=None;state.active_inquiry_id=None
                inquiry.release_action(engine);engine.checkpoint('selected_inventory_correction_blocked')
            task=next(t for t in state.inquiry_tasks if t.id==id)
        candidate=active_candidate(state)
        if task.status=='blocked':
            candidate.status='blocked';candidate.stop_reason=task.stop_reason;return
    if candidate.spec_task_ids:
        from .audit_spec import load,validate_question
        try:validate_question(load(state),candidate.question)
        except ValueError as exc:
            candidate.status='blocked';candidate.stop_reason='Inventory correction requires explicit question reconnection: '+str(exc)
            engine.checkpoint('candidate_reconnection_required');return
    if candidate.stage!='read':return
    receipt=engine.read(candidate.question.requests,purpose='depth',partial=True,plan_id=candidate.read_plan_id,
        related_ids=[candidate.id]+candidate.question.fact_ids+candidate.question.behavior_ids,reason=candidate.question.question)
    candidate=active_candidate(state)
    from .sources import includes
    attached=[id for i in receipt['items'] if i['status']!='deferred' for id in i['material_ids']]
    progress=any(i['status']=='acquired' for i in receipt['items']) or not includes(state,attached,candidate.material_ids)
    candidate.material_ids=list(dict.fromkeys(candidate.material_ids+attached))
    candidate.stagnation=0 if progress else candidate.stagnation+1
    candidate.stage='analyze'
    if candidate.stagnation>=max(1,engine.config.budget.repair_stagnation):
        candidate.status='blocked';candidate.stop_reason='Repeated source requests provided no new source to this question; receipts retain deferred ranges'
    inquiry.release_action(engine);engine.checkpoint('candidate_source_receipt_saved')


def ask_derivation(engine,packet):
    return engine.ask('derive',Derivation,packet,lambda p:validate_derivation(engine.state,p),purpose='depth')


def derive(engine):
    if 'derived-spec:'+str(engine.state.audit_spec_version) in engine.state.completed_steps:return
    if 'derive-context-deferred:'+str(engine.state.audit_spec_version) in engine.state.completed_steps:return
    if engine.state.derivation_path:
        path=Path(engine.state.derivation_path);check_id=path.stem.removeprefix('derivation-')
        if 'derive-'+check_id not in engine.state.applied_operations:
            if accept_derivation(engine,Derivation.model_validate_json(path.read_text()),check_id):
                inquiry.release_action(engine);engine.checkpoint('derivation_episode_committed');return
            if active_candidate(engine.state) is None:
                return
    while True:
        candidate=active_candidate(engine.state)
        if candidate:
            continue_candidate(engine,candidate)
            if active_candidate(engine.state) is None:break
        packet=derive_context(engine)
        try:proposal,check=ask_derivation(engine,packet)
        except Blocked as exc:
            if not str(exc).startswith('Required context exceeds context_chars (derive:'):raise
            marker='derive-context-deferred:'+str(engine.state.audit_spec_version)
            if marker not in engine.state.completed_steps:engine.state.completed_steps.append(marker)
            if candidate:
                candidate.status='blocked';candidate.stop_reason=str(exc)
                candidate.resume_conditions=['Reprepare this discriminator with required exact source after the packet workset changes']
            engine.state.gaps.append(str(exc));inquiry.release_action(engine)
            engine.checkpoint('selected_derivation_context_deferred');return
        if accept_derivation(engine,proposal,check.id):
            inquiry.release_action(engine);engine.checkpoint('derivation_episode_committed');return
        inquiry.release_action(engine);engine.checkpoint('candidate_continuation_saved')
        if active_candidate(engine.state) is None:break
    inquiry.release_action(engine);engine.checkpoint('candidate_episode_finished')


def targeted_read(engine, unit, gap, relation_ids=None, requests=None, update_required=True):
    if engine.state.targeted_gap is None:
        engine.state.targeted_gap={"plan_id":uid(),"requests":[q.model_dump(mode="json") if hasattr(q,"model_dump") else q for q in (requests or [])],"gap":gap,"related_ids":unit.obligation_ids if unit else [],
            "update_required":update_required,"relation_ids":relation_ids or [],"stage":"read","new_material_ids":[]}

    task=engine.state.targeted_gap
    if task["stage"] == "read":
        if task["requests"]:
            reading=ReadingPlan.model_validate({"requests":task["requests"],"rationale":gap,"related_ids":task["related_ids"],"gap":gap})
        else:
            reading,_=engine.ask("targeted_read",ReadingPlan,{"gap":task,
                "already_read":[{"id":m.id,"file":m.file,"start":m.start_line,"end":m.end_line} for m in engine.state.materials],
                "relevant_bindings":[b.model_dump() for b in engine.state.bindings if unit and b.id in unit.binding_ids]})
        reading.related_ids=task["related_ids"]; reading.gap=gap
        task['requests']=[q.model_dump(mode='json') for q in reading.requests]

        receipt=engine.read(reading.requests,plan_id=task['plan_id'],related_ids=task['related_ids'],reason=gap)
        task=engine.state.targeted_gap
        receipt['scope_requested']=task.get('update_required',True)
        task['receipt_id']=receipt['id'];task['unfulfilled']=[item for item in receipt['items'] if item['status']=='deferred']
        task['new_material_ids']=list(dict.fromkeys(task.get('new_material_ids',[])+[id for item in receipt['items'] if item['status']=='acquired' for id in item['material_ids']]))
        task['reattached_material_ids']=[id for item in receipt['items'] if item['status']=='cached' for id in item['material_ids']]
        if task['unfulfilled']:
            engine.checkpoint('targeted_read_deferred');raise Blocked('Required material remains deferred; resume the same reading plan before graph patch')
        task['stage']='patch';inquiry.release_action(engine)

    if not task["new_material_ids"]:
        if task.get('reattached_material_ids'):
            engine.state.targeted_gap=None;return None
        raise Blocked("Targeted reading found no usable range; dependency remains unexplained: "+gap)
    if not task.get("update_required",update_required):
        engine.state.targeted_gap=None;return None
    from .scope_updates import from_patch,validate_scope_update,ScopeUpdate,ScopeAssessment,accept
    def validate_proposal(p):
        from .mutations import write_set,classify_writes
        if unit and classify_writes(write_set(engine.state,p),unit.id)!='candidate_additions':validate_scope_update(engine.state,from_patch(engine.state,unit,p))
        else:validate_patch(engine.state,p)
    if task.get('scope_update'):
        update=ScopeUpdate.model_validate(task['scope_update'])
        patch=update.patch
    else:
        try:
            patch,check=engine.ask("graph_patch",GraphPatch,{"gap":task,
            "new_materials":[m.model_dump(mode="json") for m in engine.state.materials if m.id in task["new_material_ids"]],
            "claims":[c.model_dump(mode="json") for c in engine.state.claims],"bindings":[b.model_dump(mode="json") for b in engine.state.bindings],
            "relations":[e.model_dump(mode="json") for e in engine.state.relations if e.source in {c.id for c in engine.state.claims}],
            "units":[u.model_dump(mode="json") for u in engine.state.units]},validate_proposal)
        except Blocked:
            session=engine.state.pending_output_repair
            if session and any(d['code'].startswith('scope_') for d in session.get('diagnostics',[])):
                raw=GraphPatch.model_validate_json(Path(session['current_path']).read_text())
                pending=from_patch(engine.state,unit,raw)
                pending.read_plan_id=task['plan_id']
                task['scope_update']=pending.model_dump(mode='json')
                engine.state.scope_updates[pending.id]={'status':'needs_F2_or_investigation','proposal':pending.model_dump(mode='json'),'repair_session_id':session['id']}
                inquiry.enqueue(engine.state,'review','Resolve the proposed semantic/scope difference before applying any part', 'scope_dispute:'+pending.id,target_ids=sorted({c.target_id for c in pending.changes}),unit_id=unit.id)
                engine.checkpoint('scope_dispute_queued')
            raise
        from .mutations import write_set,classify_writes
        if unit and classify_writes(write_set(engine.state,patch),unit.id)!='candidate_additions':
            update=from_patch(engine.state,unit,patch)
            update.read_plan_id=task['plan_id']
            task['scope_update']=update.model_dump(mode='json')
            engine.state.scope_updates[update.id]={'status':'proposed','proposal':update.model_dump(mode='json'),'check_id':check.id}
            engine.checkpoint('scope_proposal_saved')
        else:update=None
    if update:
        needed=validate_scope_update(engine.state,update)
        if needed:
            assessment,_=engine.ask('scope_review',ScopeAssessment,{'scope_update':update.model_dump(mode='json'),'required_fields':needed,**engine.context(unit)})
            update.assessment=assessment
            task['scope_update']=update.model_dump(mode='json')
            engine.state.scope_updates[update.id]={'status':'reviewed' if assessment.decision=='refinement' else 'needs_F2_or_investigation','proposal':update.model_dump(mode='json')}
            engine.checkpoint('scope_interpretation_saved')
        if update.assessment and update.assessment.decision!='refinement':
            inquiry.enqueue(engine.state,'review','Investigate whether the proposed scope changes the original obligation','scope_dispute:'+update.id,target_ids=[unit.id],unit_id=unit.id)
            engine.checkpoint('scope_dispute_queued')
            raise Blocked('Scope interpretation remains unresolved; a scoped review/F2 task is pending')
        validate_scope_update(engine.state,update)
        return accept(engine,update)
    from .transactions import commit_graph
    def commit(proxy):
        apply_patch(proxy.state,patch)
        target=next((u for u in proxy.state.units if unit and u.id==unit.id),None)
        inquiry.material_reviews(proxy,target,proxy.state.targeted_gap["new_material_ids"])
        proxy.state.targeted_gap=None
        inquiry.release_action(proxy)
    commit_graph(engine,"targeted-"+engine.state.pending_action.id,patch.model_dump(mode="json"),commit)
    engine.checkpoint("targeted_graph_patch_applied")
    return patch
