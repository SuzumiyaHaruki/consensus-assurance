"""Bounded responsibility exploration and semantic review interleaved with local verification."""
from pathlib import Path
import json
from consensus_assurance.core.types import InquiryTask, SemanticReview
from consensus_assurance.core.proposals import ExplorationReply, ReviewReply, Feedback
from consensus_assurance.adapters.storage.files import write_json
from .materials import catalogue, add_reads, ReadingPlan
from .graph import apply_patch
from .feedback import apply_feedback
from .errors import Blocked
from .budget import BudgetExhausted
from .reviews import material_closure, readiness, validate_resolutions, record_dispositions, valid_supersession


def enabled(engine):
    return engine.config.budget.exploration_rounds > 0 or engine.config.budget.semantic_reviews > 0


def objects(state):
    return {o.id:o for o in [*state.claims,*state.bindings,*state.relations,*state.units,*state.models]}


def enqueue(state, kind, reason, trigger, responsibility_ids=(), target_ids=(), unit_id=None, model_id=None, requests=()):
    signature=(kind,trigger,tuple(responsibility_ids),tuple(target_ids),unit_id,model_id)
    for task in state.inquiry_tasks:
        if signature==(task.kind,task.trigger,tuple(task.responsibility_ids),tuple(task.target_ids),task.unit_id,task.model_id):
            return task
    task=InquiryTask(kind=kind,reason=reason,trigger=trigger,responsibility_ids=list(responsibility_ids),target_ids=list(target_ids),unit_id=unit_id,model_id=model_id,requests=list(requests),stage='read' if requests else 'analyze')
    task.target_versions={i:getattr(objects(state)[i],"version",1) for i in task.target_ids if i in objects(state)}
    unit=next((u for u in state.units if u.id==unit_id),None)
    task.unit_version=unit.version if unit else None
    task.material_ids=sorted(material_closure(state,task.target_ids)[0])
    state.inquiry_tasks.append(task)
    return task


def register_responsibilities(state, candidates):
    materials={m.id for m in state.materials}; claims={c.id for c in state.claims}
    available={r.id for r in state.responsibilities}|{r.id for r in candidates}
    if len({r.id for r in candidates})!=len(candidates): raise ValueError('Duplicate responsibility identifiers')
    for r in candidates:
        if r.id in objects(state):raise ValueError('Responsibility ID collides with a graph object')
        if not r.description.strip() or not r.applicability.strip() or not set(r.source_ids)<=materials:
            raise ValueError('Responsibility needs actual read sources and an applicability explanation')
        if not set(r.claim_ids)<=claims: raise ValueError('Responsibility references unavailable claims')
        for edge in r.handoffs:
            if edge.target_id not in available or not set(edge.source_ids)<=materials or not edge.description.strip() or not set(edge.covered_by_unit_ids)<={u.id for u in state.units}:
                raise ValueError('Responsibility handoff lacks a located target or source')
    for candidate in candidates:
        old=next((r for r in state.responsibilities if r.id==candidate.id),None)
        new=candidate.model_copy(deep=True)
        if old:
            if candidate.version!=old.version: raise ValueError('Responsibility version differs from the current overview')
            if old==candidate: continue
            state.responsibility_history.append(old.model_dump(mode='json'))
            new.version=old.version+1
            state.responsibilities[state.responsibilities.index(old)]=new
        else: state.responsibilities.append(new)


def register_requests(state, requests, trigger):
    known={r.id for r in state.responsibilities}
    for i,request in enumerate(requests):
        if not set(request.responsibility_ids)<=known or not request.reason.strip():
            raise ValueError('Exploration request needs known responsibilities or a concrete system-wide gap')
        enqueue(state,'explore',request.reason,trigger+':'+str(i),request.responsibility_ids,requests=request.requests)


def initial_agenda(engine, proposal):
    state=engine.state
    register_responsibilities(state,proposal.responsibilities)
    register_requests(state,proposal.exploration_requests,'initial_request')
    if proposal.reading_requests:
        enqueue(state,'explore','Initial discovery requested additional material; existing units do not suppress it','initial_reading',requests=proposal.reading_requests)
    if not enabled(engine): return
    queue_handoffs(engine)
    if engine.config.budget.audit_units == 0:
        for unit in state.units: review_unit(engine,unit,'candidate_semantics')
    for r in state.responsibilities:
        if not r.claim_ids or r.questions:
            enqueue(state,'explore','Investigate an identified responsibility and its unexplained handoffs','responsibility:'+r.id+':'+str(r.version),[r.id])
    enqueue(state,'explore','Survey responsibilities and interfaces outside the first selected direction; the overview is not an exhaustive specification','initial_breadth')


def review_unit(engine, unit, trigger, model=None):
    if not enabled(engine): return
    available=objects(engine.state)
    if trigger=="before_model" and readiness(engine.state,unit)["status"]=="reviewed":return
    ids=[x for x in dict.fromkeys(unit.goal_ids+unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id]+([model.id] if model else [])) if x in available]
    from .review_contract import target_contract,same_basis
    needed={};basis={}
    for id in ids:
        contract=target_contract(engine.state,available[id]);basis[id]=contract
        for aspect in contract['required_aspects']:
            previous=next((r for r in reversed(engine.state.semantic_reviews) if same_basis(r.context_dependencies.get(id,{}),contract) and any(i.target_id==id and i.aspect==aspect for i in r.items)),None)
            if previous:
                reuse={'unit_id':unit.id,'target_id':id,'aspect':aspect,'review_id':previous.id,'basis':contract,'reason':'Same scoped semantics and source ranges; old issues remain open'}
                if reuse not in engine.state.review_reuses:engine.state.review_reuses.append(reuse)
                continue
            pending=next((t for t in engine.state.inquiry_tasks if t.kind=='review' and t.status in {'pending','running','blocked'} and id in t.target_ids and aspect in t.requested_aspects.get(id,contract['required_aspects']) and same_basis(t.context_dependencies.get(id,{}),contract)),None)
            if pending:continue
            needed.setdefault(id,[]).append(aspect)
    ids=list(needed)
    for start in range(0,len(ids),12):
        part=ids[start:start+12]
        versions=':'.join(x+'@'+str(getattr(available[x],'version',1)) for x in part)
        task=enqueue(engine.state,'review','Review new semantic inputs, dependency evidence or checker correspondence',trigger+':'+versions,target_ids=part,unit_id=unit.id,model_id=model.id if model else None)
        task.requested_aspects={id:needed[id] for id in part};task.context_dependencies={id:basis[id] for id in part}
        task.expected_contribution='Resolve changed target/aspect inputs before continuing the selected audit problem'
        if model:
            from .encoding import issue_models
            task.resolution_issue_ids=[i.id for i in engine.state.review_issues if not i.resolved_by and i.aspect=='checker_correspondence' and issue_models(engine.state,i,model)]


def material_reviews(engine, unit, added):
    if not enabled(engine) or not added:return
    files={m.file for m in engine.state.materials if m.id in added}
    for candidate in engine.state.units:
        relevant=candidate.id==(unit.id if unit else None) or any(b.id in candidate.binding_ids and b.file in files for b in engine.state.bindings)
        if relevant: review_unit(engine,candidate,'new_materials:'+','.join(added))


def after_search(engine, unit, model, check):
    if not enabled(engine):return
    review_unit(engine,unit,'after_search:'+check.id,model)
    enqueue(engine.state,'explore','Revisit unrepresented responsibilities and interactions after a local search, including when no counterexample was found','after_local:'+check.id)


def choose_task(engine):
    state=engine.state
    if state.active_inquiry_id:
        return next(t for t in state.inquiry_tasks if t.id==state.active_inquiry_id)
    pending=[t for t in state.inquiry_tasks if t.status=='pending' and not t.superseded_by]
    for task in pending:
        resource='exploration_rounds' if task.kind=='explore' else 'semantic_reviews'
        if state.usage.get(resource,0)>=getattr(engine.config.budget,resource):
            task.status='blocked';task.stop_reason='Budget exhausted or disabled: '+resource
    pending=[t for t in pending if t.status=='pending' and not t.superseded_by]
    if not pending:return None
    needed=[t for t in pending if t.kind=='review' and t.unit_id==state.active_unit_id and t.trigger.startswith('before_model')]
    if needed:return needed[0]
    reviews=[t for t in pending if t.kind=='review']
    if reviews and engine.config.budget.audit_units==0:return reviews[0]
    if state.active_unit_id and state.next_action in {'build','experiment','calibrate','search'}:
        local=[t for t in reviews if t.unit_id==state.active_unit_id]
        if local:return local[0]
        return None
    exploration=[t for t in pending if t.kind=='explore']
    exploration.sort(key=lambda t:(not t.trigger.startswith('handoff:'), any(r.claim_ids for r in state.responsibilities if r.id in t.responsibility_ids), bool(t.requests), len(t.requests)))
    # Alternate breadth and review, allowing one local segment between completed inquiries.
    if state.last_work_kind=='explore' and reviews:return reviews[0]
    if state.last_work_kind=='local' and exploration:return exploration[0]
    if state.last_work_kind=='review' and (state.active_unit_id or any(u.status in {'pending','partial'} for u in state.units)):return None
    if reviews:return reviews[0]
    if state.last_work_kind=='explore' and any(u.status in {'pending','partial','selected'} for u in state.units):return None
    return exploration[0] if exploration else None


def task_context(engine,task):
    state=engine.state; available=objects(state)
    seeds=set(task.target_ids)
    if task.kind=='explore' and task.unit_id:seeds.add(task.unit_id)
    for r in state.responsibilities:
        if r.id in task.responsibility_ids:seeds.update(r.claim_ids)
    wanted,closure=material_closure(state,seeds)
    wanted.update(task.added_material_ids)
    wanted.update(state.task_attachments.get('inquiry:'+task.id,[]))
    wanted.update(task.material_ids)
    for issue in state.review_issues:
        if (issue.target_id in closure or issue.id in task.resolution_issue_ids) and not issue.resolved_by:wanted.update(issue.source_ids)
    if task.kind=='explore':
        for role in state.responsibilities:
            if role.id in task.responsibility_ids:wanted.update(role.source_ids)
        wanted.update(m.id for m in state.materials if m.file.lower().endswith('readme.md'))
    pending_scope=[u for u in state.scope_updates.values() if u['status']=='needs_F2_or_investigation' and u['proposal']['unit_id']==task.unit_id]
    for p in pending_scope:wanted.update(p['proposal']['source_ids'])
    selected=[m for m in state.materials if m.id in wanted]
    task.material_ids=[m.id for m in selected]
    task.unit_version=next((u.version for u in state.units if u.id==task.unit_id),None)
    result={'pending_scope_updates':pending_scope,'task':task.model_dump(mode='json',exclude={'context_receipt_id','context_dependencies','admitted','preparation_failures','child_task_ids'}),'responsibilities':[r.model_dump(mode='json') if r.id in task.responsibility_ids else {'id':r.id,'description':r.description,'claim_ids':r.claim_ids} for r in state.responsibilities],
        'materials':[m.model_dump(mode='json') for m in selected],
        'omitted_material_ids':[m.id for m in state.materials if m.id not in wanted],
        'catalogue':[],
        'unread_ranges':{f:r for f,r in state.unread_ranges.items() if f in {m.file for m in selected}},'remaining_seconds':engine.budget.remaining(),
        'target_objects':[available[i].model_dump(mode='json') for i in task.target_ids if i in available],
        'claims':[c.model_dump(mode='json') if c.id in closure else {'id':c.id,'kind':c.kind,'description':c.description,'version':c.version} for c in state.claims if c.id not in task.target_ids],
        'bindings':[b.model_dump(mode='json') for b in state.bindings if b.id in closure and b.id not in task.target_ids],
        'relations':[r.model_dump(mode='json') for r in state.relations if r.id in closure and r.id not in task.target_ids],
        'units':[u.model_dump(mode='json') for u in state.units if u.id in closure and u.id not in task.target_ids],
        'open_issues':[i.model_dump(mode='json') for i in state.review_issues if (i.target_id in closure or i.id in task.resolution_issue_ids) and not i.resolved_by],
        'blocked_review_tasks':[t.model_dump(mode='json') for t in state.inquiry_tasks if t.kind=='review' and t.status=='blocked' and not t.superseded_by and set(t.target_ids)<=set(task.target_ids)],
        'cost_estimate':cost_estimate(engine),'overview_limit':'This compact index is not complete implementation coverage; request specific actual ranges before deriving new claims'}
    if task.model_id:
        model=next((m for m in state.models if m.id==task.model_id),None)
        if model:
            result['bundle']=json.loads(Path(model.bundle_path).read_text())
            result['prior_issue_models']=[{'issue_id':i.id,'model_id':old.id,'bundle':json.loads(Path(old.bundle_path).read_text()),'current_model_id':model.id} for i in state.review_issues if i.id in task.resolution_issue_ids for old in state.models if old.id==i.model_id]
            result['checker_executions']=[engine.error_context(c) for c in state.checks if c.model_id==model.id and c.action=='model_check']
            result['reachability']=[r.model_dump(mode='json') for r in state.reachability_results if r.model_id==model.id]
    return result


def validate_exploration(state,reply):
    if reply.requests:
        if reply.patch.claims or reply.patch.bindings or reply.patch.units or reply.patch.relations:
            raise ValueError('Read missing material before claiming a graph patch based on it')
        return
    trial=state.model_copy(deep=True)
    apply_patch(trial,reply.patch)
    register_responsibilities(trial,reply.responsibilities)
    register_requests(trial,reply.exploration_requests,'validation')


def validate_review(state,task,reply):
    available=objects(state); material_ids=set(task.material_ids) or {m.id for m in state.materials}
    if any(i not in available or available[i].version!=v for i,v in task.target_versions.items()):raise ValueError("Review target version changed since task execution started")
    from .review_contract import validate_contract
    validate_contract(state,task,reply)
    validate_resolutions(state,task,reply)
    for item in reply.items:
        if item.target_id not in available or not set(item.source_ids)<=material_ids:
            raise ValueError('Semantic review cites an unavailable object or material')
        if not all(x.strip() for x in [item.explanation,item.alternatives,item.counterexample_reasoning]):
            raise ValueError('Semantic review needs material reasoning, alternatives and a reverse sufficiency check')
    if reply.revision:
        if reply.revision.kind!='F2' or not set(reply.revision.target_ids)<=set(task.target_ids):
            raise ValueError('Review revisions must be F2 and target the reviewed semantic objects')
        from .mutations import validate_changes
        validate_changes(state,reply.revision,task.target_ids)
        trial=state.model_copy(deep=True)
        unit=next((u for u in trial.units if u.id==task.unit_id),None)
        apply_feedback(trial,unit,None,reply.revision)
    register_requests(state.model_copy(deep=True),reply.exploration_requests,'validation')


def release_action(engine):
    if engine.state.pending_action:
        engine.state.action_history.append(engine.state.pending_action.model_copy(deep=True))
        engine.state.pending_action=None


def process_task(engine, task):
    state=engine.state
    if task.status=='pending':
        planned_versions=dict(task.target_versions)
        task.target_versions={i:objects(state)[i].version for i in task.target_ids if i in objects(state)}
        task.status='running';state.active_inquiry_id=task.id
        state.inquiry_selections.append({'task_id':task.id,'kind':task.kind,'reason':task.reason,'trigger':task.trigger,'planned_target_versions':planned_versions,'execution_target_versions':task.target_versions})
        engine.checkpoint('inquiry_task_started')
    if task.stage=='read':
        if not task.read_plan_id:
            from consensus_assurance.core.types import uid
            task.read_plan_id=uid();engine.checkpoint('inquiry_read_plan_saved')
        receipt=engine.read(task.requests,purpose='breadth' if task.kind=='explore' else 'depth',partial=task.kind=='explore',plan_id=task.read_plan_id,related_ids=task.target_ids+task.responsibility_ids,reason=task.reason)
        task=next(t for t in state.inquiry_tasks if t.id==task.id)
        task.added_material_ids=list(dict.fromkeys(task.added_material_ids+[id for item in receipt['items'] if item['status']!='deferred' for id in item['material_ids']]))
        if receipt['status']!='complete':
            raise Blocked('Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt')
        task.stage='analyze';release_action(engine)
        write_json(engine.root/'materials.json',[m.model_dump(mode='json') for m in state.materials]);engine.checkpoint('inquiry_materials_read')
    if task.repair_session and not state.pending_output_repair:state.pending_output_repair=task.repair_session
    context=task_context(engine,task)
    if task.kind=='explore':
        reply,check=engine.ask('explore',ExplorationReply,context,lambda p:validate_exploration(state,p))
        if reply.requests:
            old={m['id'] for m in context['materials']}
            if all(q.file+':'+str(q.start_line)+':'+str(q.end_line) in old for q in reply.requests):
                raise Blocked('Exploration repeated already available ranges without producing a new interpretation')
            task.requests=reply.requests;task.read_plan_id=None;task.stage='read';release_action(engine);engine.checkpoint('inquiry_reading_requested');return
    else:
        reply,check=engine.ask('semantic_review',ReviewReply,context,lambda p:validate_review(state,task,p))
    from .transactions import commit_graph
    commit_graph(engine,'inquiry-'+check.id,{'task_id':task.id,'reply':reply.model_dump(mode='json')},lambda proxy:apply_task_response(proxy,task.id,reply,check))
    release_action(engine);engine.checkpoint('inquiry_task_completed')



def pause_unit(engine, reason):
    state=engine.state
    if state.active_unit_id:
        unit=next(u for u in state.units if u.id==state.active_unit_id)
        state.deferred_units[unit.id]={'next_action':state.next_action,'model_id':state.active_model_id,'finding_id':state.active_finding_id,'reason':reason,
            'pending_feedback':state.pending_feedback,'pending_output_repair':state.pending_output_repair,'targeted_gap':state.targeted_gap}
        unit.status='blocked'
        from .modeling import obligation_progress
        unit.obligation_checks,unit.remaining_obligation_ids=obligation_progress(state,unit)
    state.gaps.append(reason)
    state.active_unit_id=None;state.active_model_id=None;state.active_finding_id=None
    state.pending_output_repair=None;state.pending_feedback=None;state.targeted_gap=None
    release_action(engine);state.next_action='select';state.last_work_kind='local'
    engine.checkpoint('local_work_deferred_for_other_tasks')


def reserve_for_inquiry(engine):
    pending=[t for t in engine.state.inquiry_tasks if t.status=='pending' and engine.state.usage.get('exploration_rounds' if t.kind=='explore' else 'semantic_reviews',0)<getattr(engine.config.budget,'exploration_rounds' if t.kind=='explore' else 'semantic_reviews')]
    engine.budget.reserved_agent_calls=min(2,len(pending))
    engine.budget.reserved_seconds=engine.config.budget.outer_reserve_seconds if pending else 0


def clear_reserve(engine):
    engine.budget.reserved_agent_calls=0
    engine.budget.reserved_seconds=0


def semantic_limitations(state, model):
    available=objects(state)
    lineage={model.id}
    previous=model.previous_id
    models={m.id:m for m in state.models}
    while previous and previous in models and previous not in lineage:
        lineage.add(previous);previous=models[previous].previous_id
    relevant=set(model.graph_versions)|lineage|{s.claim_id for s in model.checkers}
    latest={}
    for review in state.semantic_reviews:
        for item in review.items:
            linked=[i for i in state.review_issues if i.review_id==review.id and i.target_id==item.target_id and i.aspect==item.aspect]
            if linked and all(i.resolved_by for i in linked):continue
            if item.aspect=='checker_correspondence' and review.model_id and review.model_id not in lineage:continue
            if item.target_id not in relevant or item.target_id not in available:continue
            if review.target_versions.get(item.target_id)!=getattr(available[item.target_id],'version',1):continue
            key=(model.id if item.aspect=="checker_correspondence" else item.target_id,item.aspect)
            latest[key]=item
    result=[]
    for item in latest.values():
        if item.status!='no_issue_found' or item.limitations:
            result.append('Unresolved semantic review for '+item.target_id+': '+item.explanation)
    for task in state.inquiry_tasks:
        if task.kind=='review' and task.status in {'pending','running','blocked'} and not task.superseded_by and not any(valid_supersession(state,r,task) for r in state.semantic_reviews) and any(i in relevant and i in available and task.target_versions.get(i)==getattr(available[i],'version',1) for i in task.target_ids):
            result.append('Relevant semantic review is unfinished: '+task.id)
    result.extend("Open review issue: "+i.id+": "+i.explanation for i in state.review_issues if not i.resolved_by and i.target_id in relevant)
    unit=next((u for u in state.units if u.id==model.unit_id),None)
    if unit and unit.semantic_readiness and readiness(state,unit)["status"]!="reviewed":result.append("Selected unit was explicitly exploratory: "+unit.semantic_readiness.get("limitation",""))
    return result


def resume_deferred(engine):
    """An explicit resume may retry a deferred action; automatic scheduling never spins on it."""
    state=engine.state
    if state.active_inquiry_id or state.active_unit_id:return
    if engine.budget.remaining()<=0 or state.usage.get('agent_calls',0)>=engine.config.budget.agent_calls:return
    for task in state.inquiry_tasks:
        if task.child_task_ids:continue
        if task.status=='blocked' and not task.superseded_by and task.stop_reason and not task.stop_reason.startswith('Budget exhausted or disabled'):
            task.status='running';state.active_inquiry_id=task.id
            engine.checkpoint('explicit_resume_of_blocked_inquiry')
            return
    for unit in state.units:
        saved=state.deferred_units.get(unit.id)
        if unit.status!='blocked' or not saved:continue
        unit.status='selected';state.active_unit_id=unit.id
        state.active_model_id=saved['model_id'];state.active_finding_id=saved['finding_id']
        state.next_action=saved['next_action']
        state.pending_feedback=saved.get('pending_feedback')
        state.pending_output_repair=saved.get('pending_output_repair')
        state.targeted_gap=saved.get('targeted_gap')
        if unit.recheck_reasons:
            state.active_model_id=None;state.active_finding_id=None;state.next_action='build'
            state.pending_feedback=None;state.pending_output_repair=None;state.targeted_gap=None
        engine.checkpoint('explicit_resume_of_deferred_local_work')
        return


def prepare_selected(engine,unit):
    review_unit(engine,unit,'before_model')
    pending=[t for t in engine.state.inquiry_tasks if t.kind=='review' and t.unit_id==unit.id and t.unit_version==unit.version and t.trigger.startswith('before_model') and t.status=='pending' and not t.superseded_by]
    if pending and engine.state.usage.get('semantic_reviews',0)<engine.config.budget.semantic_reviews:return False
    unit.semantic_readiness=readiness(engine.state,unit)
    engine.checkpoint('selected_unit_semantic_readiness')
    return True


def apply_task_response(engine,task_id,reply,check):
    state=engine.state;task=next(t for t in state.inquiry_tasks if t.id==task_id)
    versions={i:getattr(objects(state)[i],'version',1) for i in task.target_ids if i in objects(state)}
    if task.kind=='explore':
        changed=apply_patch(state,reply.patch)
        register_responsibilities(state,reply.responsibilities)
        register_requests(state,reply.exploration_requests,task.id)
        state.gaps.extend(reply.limitations)
        queue_handoffs(engine)
        for r in reply.responsibilities:
            if not r.claim_ids or r.questions:
                stored=next(x for x in state.responsibilities if x.id==r.id)
                enqueue(state,'explore','Continue unexplained responsibility or handoff','responsibility:'+r.id+':'+str(stored.version),[r.id])
        material_reviews(engine,None,task.added_material_ids)
        for unit in state.units:
            if changed & set(unit.goal_ids+unit.obligation_ids+unit.relation_ids):
                review_unit(engine,unit,"graph_growth:"+task.id)
            if set(task.added_material_ids)&{source for c in state.claims if c.id in unit.goal_ids+unit.obligation_ids for source in c.source_ids}:
                review_unit(engine,unit,'exploration_materials:'+task.id)
    else:
        review=SemanticReview(context_receipt_id=task.context_receipt_id,context_dependencies=task.context_dependencies,task_id=task.id,check_id=check.id,unit_id=task.unit_id,unit_version=task.unit_version,model_id=task.model_id,target_versions=versions,material_ids=task.material_ids if task.context_receipt_id else task.material_ids or [m.id for m in state.materials],items=reply.items,origin='mock' if engine.agent.mock else 'agent',supersedes_task_ids=reply.supersedes_task_ids,resolves_issue_ids=reply.resolves_issue_ids,resolution_rationale=reply.resolution_rationale)
        if reply.revision:
            ids_before=set(objects(state))
            engine.budget.take("revisions")
            unit=next((u for u in state.units if u.id==task.unit_id),None)
            apply_feedback(state,unit,None,reply.revision)
            added=sorted(set(objects(state))-ids_before)
            for start in range(0,len(added),12):
                enqueue(state,'review','New candidates require their own semantic review',task.id+':new_candidates:'+str(start),target_ids=added[start:start+12])
            review.revision_id=state.revisions[-1].id
            if state.revisions[-1].status=='applied' and state.active_unit_id:
                active=next(u for u in state.units if u.id==state.active_unit_id)
                if set(task.target_ids)&set(active.goal_ids+active.obligation_ids+active.relation_ids+active.binding_ids+[active.id]):
                    state.active_model_id=None;state.active_finding_id=None;state.next_action='build'
            for candidate in state.units:
                if set(task.target_ids)&set(candidate.goal_ids+candidate.obligation_ids+candidate.relation_ids+candidate.binding_ids+[candidate.id]):
                    review_unit(engine,candidate,'semantic_revision:'+review.revision_id)
        state.semantic_reviews.append(review)
        for item in reply.items:
            if item.aspect=='checker_correspondence' and item.status in {'disputed','revision_needed'} and task.model_id:
                state.affect([task.model_id],'Semantic review questions checker correspondence: '+item.explanation)
                if state.active_model_id==task.model_id:
                    state.active_model_id=None;state.active_finding_id=None;state.next_action='build'
        followup_before={t.id for t in state.inquiry_tasks}
        if reply.requests:
            enqueue(state,'review','Follow up semantic interpretation with requested source material',task.id+':followup',target_ids=task.target_ids,unit_id=task.unit_id,model_id=task.model_id,requests=reply.requests)
        register_requests(state,reply.exploration_requests,task.id)
        record_dispositions(state,review,reply,[t.id for t in state.inquiry_tasks if t.id not in followup_before])
        state.gaps.extend(reply.limitations)
    task.repair_session=None;task.check_id=check.id;task.status='completed';task.stage='done';state.active_inquiry_id=None
    settle_parents(state)
    state.last_work_kind=task.kind;release_action(engine)


def queue_handoffs(engine):
    state=engine.state
    for role in state.responsibilities:
        for edge in role.handoffs:
            from .handoffs import handoff_status
            disposition=handoff_status(state,role,edge)
            if disposition['assignments']:continue
            enqueue(state,'explore','Investigate the unassigned handoff: '+edge.description,
                'handoff:'+role.id+'->'+edge.target_id+'@'+str(role.version),[role.id,edge.target_id])


def cost_estimate(engine):
    tasks=[t for t in engine.state.inquiry_tasks if t.status=='pending' and not t.superseded_by]
    units=[u for u in engine.state.units if u.status in {'pending','partial','selected'}]
    available=max(0,engine.config.budget.agent_calls-engine.state.usage.get('agent_calls',0))
    lower=len(tasks)+len(units)
    from .materials import material_allowance
    return {'material_allocation':{p:material_allowance(engine.state,engine.config.budget,p) for p in ('breadth','depth')},'pending_inquiries':len(tasks),'pending_units':len(units),'minimum_agent_calls':lower,
        'remaining_agent_calls':available,'fits_minimum':lower<=available,
        'limitations':['Lower bound only: excludes retries, additional reading, model repair, replay and tool latency; not a price or token bill']}


def split_context_task(engine,task):
    if task.child_task_ids or task.preparation_failures>engine.config.budget.context_preparations:return []
    if task.kind=='review' and len(task.target_ids)>1:
        fields=task.target_ids;key='target_ids'
    elif task.kind=='explore' and not task.responsibility_ids and len(engine.state.responsibilities)>1:
        fields=[r.id for r in engine.state.responsibilities];key='responsibility_ids'
    else:return []
    middle=(len(fields)+1)//2;children=[]
    for index,part in enumerate((fields[:middle],fields[middle:])):
        child=enqueue(engine.state,task.kind,task.reason+'; bounded subtask '+str(index+1),task.id+':context_part:'+str(index),unit_id=task.unit_id,model_id=task.model_id,**{key:part})
        child.parent_task_id=task.id;child.expected_contribution='Resolve this explicit part of the oversized parent; other parts remain pending'
        children.append(child.id)
    task.child_task_ids=children
    return children


def settle_parents(state):
    tasks={t.id:t for t in state.inquiry_tasks}
    for parent in state.inquiry_tasks:
        if parent.child_task_ids and all(id in tasks and tasks[id].status=='completed' for id in parent.child_task_ids):
            parent.status='completed';parent.stage='done'
            parent.stop_reason='All explicit child tasks executed; semantic issues and scope limits remain in their individual records'
