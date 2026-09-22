"""Bounded responsibility exploration and semantic review interleaved with local verification."""
from pathlib import Path
import json
from consensus_assurance.core.types import InquiryTask, SemanticReview
from consensus_assurance.core.proposals import SpecRefinement, ReviewReply, ReviewKnowledgeReply
from consensus_assurance.adapters.storage.files import write_json
from .feedback import apply_feedback
from .errors import Blocked
from .reviews import required_aspects, material_closure, readiness, validate_resolutions, record_dispositions, valid_supersession, review_objects as objects


def enabled(engine):
    return engine.config.budget.exploration_rounds > 0 or engine.config.budget.semantic_reviews > 0


def enqueue(state, kind, reason, trigger, activity_classes=(), target_ids=(), unit_id=None, model_id=None, requests=(), surface_entry_points=(), candidate_id=None, diagnostics=()):
    signature=(kind,trigger,tuple(activity_classes),tuple(target_ids),unit_id,model_id,tuple(surface_entry_points),candidate_id)
    def opinion(d): return {k:d[k] for k in ('object_ids','material_ids','message')}
    sources={m.file for m in state.materials if any(m.id in d['material_ids'] for d in diagnostics)}
    for task in state.inquiry_tasks:
        if kind==task.kind=='spec_refine' and diagnostics and task.candidate_id==candidate_id:
            if task.status=='completed' and all(opinion(d) in [opinion(old) for old in task.diagnostics] for d in diagnostics):
                from .audit_spec import load,audit_object_index
                current=audit_object_index(load(state))
                if task.context_dependencies=={id:current.get(id) for id in task.target_ids}:return task
            related=set(task.target_ids)&set(target_ids) or sources&{m.file for m in state.materials if any(m.id in d['material_ids'] for d in task.diagnostics)}
            if task.status=='pending' and (set(task.target_ids)==set(target_ids) or candidate_id is None and related):
                task.diagnostics.extend(d for d in diagnostics if opinion(d) not in [opinion(old) for old in task.diagnostics])
                task.target_ids=list(dict.fromkeys(task.target_ids+list(target_ids)))
                return task
            continue
        if signature==(task.kind,task.trigger,tuple(task.activity_classes),tuple(task.target_ids),task.unit_id,task.model_id,tuple(task.surface_entry_points),task.candidate_id):
            return task
    task=InquiryTask(surface_entry_points=list(surface_entry_points),kind=kind,reason=reason,trigger=trigger,
        activity_classes=list(activity_classes),target_ids=list(target_ids),unit_id=unit_id,model_id=model_id,
        requests=list(requests),stage='read' if requests else 'analyze',candidate_id=candidate_id,diagnostics=list(diagnostics))
    task.target_versions={i:getattr(objects(state)[i],"version",1) for i in task.target_ids if i in objects(state)}
    unit=next((u for u in state.units if u.id==unit_id),None)
    task.unit_version=unit.version if unit else None
    task.material_ids=sorted(material_closure(state,task.target_ids)[0])
    state.inquiry_tasks.append(task)
    return task


def review_unit(engine, unit, trigger, model=None):
    if not enabled(engine): return
    if model is None and unit.audit_question and unit.audit_question.preferred_check in {'direct_test','controlled_schedule'}:return
    available=objects(engine.state)
    if trigger=="before_model" and readiness(engine.state,unit)["status"]=="reviewed":return
    ids=[x for x in dict.fromkeys(unit.obligation_ids+[unit.id]+([model.id] if model else [])+[i.target_id for i in engine.state.review_issues if not i.resolved_by and i.target_id in unit.binding_ids+unit.relation_ids]) if x in available]
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


def choose_task(engine):
    state=engine.state
    if state.active_inquiry_id:
        return next(t for t in state.inquiry_tasks if t.id==state.active_inquiry_id)
    pending=[t for t in state.inquiry_tasks if t.status=='pending' and not t.superseded_by]
    for task in pending:
        resource=inquiry_resource(task)
        if resource and not task.admitted and state.usage.get(resource,0)>=getattr(engine.config.budget,resource):
            task.status='blocked';task.stop_reason='Budget exhausted or disabled: '+resource
    pending=[t for t in pending if t.status=='pending' and not t.superseded_by]
    if state.active_unit_id:
        if state.next_action in {'select','build','technical_repair','model_syntax','model_explore','harness','direct_check','direct_execute'}:return None
        local=[t for t in pending if t.unit_id==state.active_unit_id]
        # Executable checks precede generic inquiry; explicit selected reviews still run.
        return next((t for t in local if t.kind=='review'),None)
    focused=[t for t in pending if t.kind=='review' and t.unit_id in state.deferred_units]
    if focused:return focused[0]
    ready=any(u.status in {'pending','partial','selected'} and not (u.audit_question and u.audit_question.disposition=='explained_by_existing_mechanism') for u in state.units)
    if ready and engine.config.budget.audit_units>state.usage.get('audit_units',0):return None
    if any(c.status=='active' for c in state.question_candidates):return None
    feedback=[t for t in pending if t.kind=='review' or t.candidate_id]
    if feedback:return feedback[0]
    if state.last_work_kind in {'candidate','local','review'}:
        enrichment=next((t for t in pending if t.diagnostics and not t.candidate_id),None)
        if enrichment:return enrichment
    from .audit_spec import next_surface_refinement
    from .budget import can_start_episode
    if can_start_episode(state,'surface') and state.usage.get('exploration_rounds',0)<engine.config.budget.exploration_rounds:
        surface=next_surface_refinement(state)
        if surface:
            return enqueue(state,'spec_refine','Expand one source-grounded implementation surface','surface:'+surface.entry_point,surface_entry_points=[surface.entry_point])
    if pending and state.last_work_kind!='surface' and (pending[0].admitted or can_start_episode(state,'surface')):return pending[0]
    return None


def inquiry_resource(task):
    return 'semantic_reviews' if task.kind=='review' else 'exploration_rounds' if task.surface_entry_points and not task.candidate_id else None


def read_purpose(task):
    return 'depth' if task.candidate_id or task.unit_id or task.diagnostics or task.kind=='review' else 'breadth'


def task_context(engine,task):
    return {'task':{'id':task.id},'current_material_ids':list(dict.fromkeys(task.added_material_ids+task.material_ids+engine.state.task_attachments.get('inquiry:'+task.id,[])))}


def validate_spec_refinement(state,reply,task):
    if reply.requests:return
    from .audit_spec import merge_delta
    merge_delta(state,task,reply.delta)


def validate_review(state,task,reply):
    available=objects(state); material_ids=set(task.material_ids) or {m.id for m in state.materials}
    if any(i not in available or available[i].version!=v for i,v in task.target_versions.items()):raise ValueError("Review target version changed since task execution started")
    from .review_contract import validate_contract
    validate_contract(state,task,reply)
    validate_resolutions(state,task,reply)
    for item in reply.items:
        from .sources import includes
        if item.target_id not in available or not includes(state,item.source_ids,material_ids):
            raise ValueError('Semantic review cites an unavailable object or material')
        if not item.rationale.strip():raise ValueError('Semantic review needs sourced reasoning')
    if reply.revision:
        reviewed=set(task.target_ids)|{id for a in state.direct_checks if a.id in task.target_ids for id in a.graph_versions}
        if reply.revision.kind!='F2' or not set(reply.revision.target_ids)<=reviewed:
            raise ValueError('Review revisions must be F2 and target the reviewed semantic objects')
        from .mutations import validate_changes
        validate_changes(state,reply.revision,reviewed)
        trial=state.model_copy(deep=True)
        unit=next((u for u in trial.units if u.id==task.unit_id),None)
        apply_feedback(trial,unit,None,reply.revision)
    if getattr(reply,'descriptive_delta',None):
        from .audit_spec import merge_delta
        merge_delta(state,descriptive_task(state,task),reply.descriptive_delta)


def descriptive_task(state,task):
    unit=next((u for u in state.units if u.id==task.unit_id),None)
    question=unit.audit_question if unit else None
    return task.model_copy(update={'target_ids':list(dict.fromkeys(task.target_ids+(question.behavior_ids+question.fact_ids if question else []))),
        'activity_classes':list(dict.fromkeys(task.activity_classes+(question.activity_classes if question else [])))})


def release_action(engine):
    if engine.state.pending_action:
        engine.state.action_history.append(engine.state.pending_action.model_copy(deep=True))
        engine.state.pending_action=None


def process_task(engine, task):
    state=engine.state
    if task.kind=='spec_refine' and task.diagnostics and not (task.target_ids or task.surface_entry_points or task.activity_classes):
        task.target_ids=list(dict.fromkeys(id for d in task.diagnostics for id in d['object_ids']))
    if task.status=='pending':
        planned_versions=dict(task.target_versions)
        task.target_versions={i:objects(state)[i].version for i in task.target_ids if i in objects(state)}
        task.status='running';state.active_inquiry_id=task.id
        state.inquiry_selections.append({'task_id':task.id,'kind':task.kind,'reason':task.reason,'trigger':task.trigger,'planned_target_versions':planned_versions,'execution_target_versions':task.target_versions})

    if task.stage=='read':
        from .materials import uncovered_requests,request_material_ids
        requested=list(task.requests);remaining=uncovered_requests(state,requested)
        task.added_material_ids=list(dict.fromkeys(task.added_material_ids+request_material_ids(state,requested)))
        if remaining:
            from consensus_assurance.core.types import uid
            if not task.read_plan_id or task.read_plan_id in state.read_plans:task.read_plan_id=uid()
            receipt=engine.read(remaining,purpose=read_purpose(task),partial=read_purpose(task)=='breadth',plan_id=task.read_plan_id,related_ids=task.target_ids+task.activity_classes+([task.unit_id] if task.unit_id else []),reason=task.reason)
            task=next(t for t in state.inquiry_tasks if t.id==task.id)
            task.added_material_ids=list(dict.fromkeys(task.added_material_ids+[id for item in receipt['items'] if item['status']!='deferred' for id in item['material_ids']]))
            if receipt['status']!='complete' and not task.candidate_id:
                raise Blocked('Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt')
        task.stage='analyze';release_action(engine)
    if task.repair_session and not state.pending_output_repair:state.pending_output_repair=task.repair_session
    context=task_context(engine,task)
    if task.kind=='spec_refine':
        from .audit_spec import SpecIssue
        try:reply,check=engine.ask('spec_refine',SpecRefinement,context,lambda p:validate_spec_refinement(state,p,task),purpose=read_purpose(task))
        except SpecIssue as exc:
            if state.audit_spec_path or not task.draft_path:task.draft_path=exc.draft_path
            diagnostics=[d.model_dump(mode='json') for d in exc.diagnostics]
            task.semantic_failures=task.semantic_failures+1 if task.diagnostics==diagnostics else 0
            task.diagnostics=diagnostics;state.active_inquiry_id=None
            task.status='blocked' if task.semantic_failures>=max(1,engine.config.budget.repair_stagnation) else 'pending'
            if task.status=='blocked':task.stop_reason='Descriptive semantic refinement made no progress; diagnostics and attempted delta retained'
            release_action(engine);engine.checkpoint('descriptive_refinement_remains_open');return
        if reply.requests:
            old=set(task.material_ids)
            if all(q.file+':'+str(q.start_line)+':'+str(q.end_line) in old for q in reply.requests):
                raise Blocked('Exploration repeated already available ranges without producing a new interpretation')
            task.requests=reply.requests;task.read_plan_id=None;task.stage='read';release_action(engine);engine.checkpoint('inquiry_reading_requested');return
    else:
        schema=ReviewKnowledgeReply if task.unit_id and state.audit_spec_path else ReviewReply
        reply,check=engine.ask('semantic_review',schema,context,lambda p:validate_review(state,task,p))
    from .transactions import commit_graph
    commit_graph(engine,'inquiry-'+check.id,{'task_id':task.id,'reply':reply.model_dump(mode='json')},lambda proxy:apply_task_response(proxy,task.id,reply,check))
    release_action(engine);engine.checkpoint('inquiry_task_completed')



def pause_unit(engine, reason):
    state=engine.state
    if state.active_unit_id:
        unit=next(u for u in state.units if u.id==state.active_unit_id)
        from .task_view import local_basis
        state.deferred_units[unit.id]={'basis':local_basis(state,unit),'next_action':state.next_action,'model_id':state.active_model_id,'finding_id':state.active_finding_id,'direct_check_id':state.active_direct_check_id,'reason':reason,
            'pending_feedback':state.pending_feedback,'pending_output_repair':state.pending_output_repair,'targeted_gap':state.targeted_gap}
        unit.status='blocked'
        from .modeling import obligation_progress
        unit.obligation_checks,unit.remaining_obligation_ids=obligation_progress(state,unit)
    state.gaps.append(reason)
    state.active_unit_id=None;state.active_model_id=None;state.active_finding_id=None;state.active_direct_check_id=None
    state.pending_output_repair=None;state.pending_feedback=None;state.targeted_gap=None
    release_action(engine);state.next_action='select';state.last_work_kind='local'
    engine.checkpoint('local_work_deferred_for_other_tasks')


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
        if item.status!='no_issue_found':
            result.append('Unresolved semantic review for '+item.target_id+': '+item.rationale)
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
        state.active_model_id=saved['model_id'];state.active_finding_id=saved['finding_id'];state.active_direct_check_id=saved.get('direct_check_id')
        state.next_action=saved['next_action']
        state.pending_feedback=saved.get('pending_feedback')
        state.pending_output_repair=saved.get('pending_output_repair')
        state.targeted_gap=saved.get('targeted_gap')
        if unit.recheck_reasons:
            state.active_model_id=None;state.active_direct_check_id=None;state.active_finding_id=None;state.next_action='select'
            state.pending_feedback=None;state.pending_output_repair=None;state.targeted_gap=None
        engine.checkpoint('explicit_resume_of_deferred_local_work')
        return


def apply_task_response(engine,task_id,reply,check):
    state=engine.state;task=next(t for t in state.inquiry_tasks if t.id==task_id)
    versions={i:getattr(objects(state)[i],'version',1) for i in task.target_ids if i in objects(state)}
    if task.kind=='spec_refine':
        from .audit_spec import accept,merge_delta,load,audit_object_index
        revised=merge_delta(state,task,reply.delta)
        if revised!=load(state):accept(engine,revised)
        current=audit_object_index(load(state))
        task.context_dependencies={id:current.get(id) for id in task.target_ids}
        material_reviews(engine,None,task.added_material_ids)
        for unit in state.units:
            if set(task.added_material_ids)&{source for c in state.claims if c.id in unit.obligation_ids for source in c.source_ids}:
                review_unit(engine,unit,'spec_materials:'+task.id)
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
                if set(reply.revision.target_ids)&set(active.obligation_ids+active.relation_ids+active.binding_ids+[active.id]):
                    state.active_model_id=None;state.active_direct_check_id=None;state.active_finding_id=None;state.next_action='select'
            for candidate in state.units:
                if set(reply.revision.target_ids)&set(candidate.obligation_ids+candidate.relation_ids+candidate.binding_ids+[candidate.id]):
                    review_unit(engine,candidate,'semantic_revision:'+review.revision_id)
        if getattr(reply,'descriptive_delta',None):
            from .audit_spec import accept,merge_delta,load
            revised=merge_delta(state,descriptive_task(state,task),reply.descriptive_delta)
            if revised!=load(state):accept(engine,revised)
        state.semantic_reviews.append(review)
        from .review_contract import missing_pairs
        missing={} if any(a.id in task.target_ids for a in state.direct_checks) else missing_pairs(state,task,reply.items)
        if missing and not task.trigger.endswith(':missing_aspects'):
            follow=enqueue(state,'review','Supply only the missing target/aspect judgments',task.id+':missing_aspects',target_ids=list(missing),unit_id=task.unit_id,model_id=task.model_id)
            follow.requested_aspects=missing
            follow.context_dependencies=task.context_dependencies
        elif missing:
            task.status='blocked';task.stop_reason='Focused review still omitted required aspects'

        for item in reply.items:
            if item.aspect=='checker_correspondence' and item.status in {'disputed','revision_needed'} and task.model_id:
                state.affect([task.model_id],'Semantic review questions checker correspondence: '+item.rationale)
                if state.active_model_id==task.model_id:
                    state.active_model_id=None;state.active_direct_check_id=None;state.active_finding_id=None;state.next_action='select'
        followup_before={t.id for t in state.inquiry_tasks}
        focus=[i for i in reply.items if i.status!='no_issue_found']
        if reply.requests and focus:
            targets=list(dict.fromkeys(i.target_id for i in focus)) or task.target_ids
            follow=enqueue(state,'review','Follow up only the unresolved aspects using the requested source',task.id+':followup',target_ids=targets,unit_id=task.unit_id,model_id=task.model_id,requests=reply.requests)
            follow.requested_aspects={id:list(dict.fromkeys(i.aspect for i in focus if i.target_id==id)) or task.requested_aspects.get(id,list(required_aspects(objects(state)[id]))) for id in targets}
            follow.resolution_issue_ids=[i.id for i in state.review_issues if not i.resolved_by and i.target_id in targets and i.aspect in follow.requested_aspects[i.target_id]]
        record_dispositions(state,review,reply,[t.id for t in state.inquiry_tasks if t.id not in followup_before])
        if reply.requests and focus:
            follow.resolution_issue_ids=[i.id for i in state.review_issues if not i.resolved_by and i.target_id in targets and i.aspect in follow.requested_aspects[i.target_id]]
    task.repair_session=None;task.check_id=check.id;task.status='blocked' if task.stop_reason=='Focused review still omitted required aspects' else 'completed';task.stage='done';state.active_inquiry_id=None
    settle_parents(state)
    state.last_work_kind='surface' if task.surface_entry_points else task.kind;release_action(engine)


def split_context_task(engine,task):
    if task.child_task_ids or task.preparation_failures>engine.config.budget.context_preparations:return []
    if task.kind=='review' and len(task.target_ids)>1:
        fields=task.target_ids;key='target_ids'
    else:return []
    middle=(len(fields)+1)//2;children=[]
    for index,part in enumerate((fields[:middle],fields[middle:])):
        child=enqueue(engine.state,task.kind,task.reason+'; bounded subtask '+str(index+1),task.id+':context_part:'+str(index),unit_id=task.unit_id,model_id=task.model_id,**{key:part})
        child.requested_aspects={id:aspects for id,aspects in task.requested_aspects.items() if id in child.target_ids}
        child.resolution_issue_ids=[id for id in task.resolution_issue_ids if any(i.id==id and i.target_id in child.target_ids for i in engine.state.review_issues)]
        child.added_material_ids=list(task.added_material_ids)
        engine.state.task_attachments['inquiry:'+child.id]=list(engine.state.task_attachments.get('inquiry:'+task.id,[]))
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


def wake_changed(engine):
    """Retry a paused stage only after a relevant dependency changed; budgets remain spent."""
    from .task_view import local_basis
    state=engine.state
    if state.active_unit_id or state.active_inquiry_id or state.pending_action or state.pending_output_repair:return
    for unit in state.units:
        saved=state.deferred_units.get(unit.id)
        if unit.status!='blocked' or not saved or not saved.get('basis'):continue
        if (saved.get('pending_output_repair') or {}).get('mode')=='check_generation':continue
        if saved['basis']==local_basis(state,unit):continue
        if saved.get('pending_output_repair',{} ) and saved['pending_output_repair'].get('blocked'):continue
        unit.status='selected';state.active_unit_id=unit.id;state.active_model_id=saved['model_id'];state.active_finding_id=saved['finding_id'];state.active_direct_check_id=saved.get('direct_check_id')
        state.next_action=saved['next_action'];state.pending_feedback=saved.get('pending_feedback');state.targeted_gap=saved.get('targeted_gap')
        state.pending_output_repair=saved.get('pending_output_repair')
        engine.checkpoint('relevant_dependency_woke_local_stage');return True


def split_model_context(engine, kind):
    """A real oversized build can first resolve one independently reviewable dispute."""
    state=engine.state
    unit=next((u for u in state.units if u.id==state.active_unit_id),None)
    if unit is None:return []
    _,closure=material_closure(state,[unit.id])
    disputed={i.target_id for i in state.review_issues if not i.resolved_by and i.target_id in closure}
    priority=list(dict.fromkeys(unit.obligation_ids+unit.binding_ids+unit.relation_ids+[unit.id]))
    from .task_packet import prepare,pool_sources
    from .prompts import render
    children=[]
    for id in [id for id in priority if id in disputed][:engine.config.budget.context_preparations]:
        trigger='packet_dependency:'+kind+':'+unit.id+':'+str(unit.version)+':'+id
        if any(t.trigger==trigger for t in state.inquiry_tasks):continue
        task=enqueue(state,'review','Resolve the named current dispute before rebuilding an oversized verification workset',trigger,target_ids=[id],unit_id=unit.id)
        task.resolution_issue_ids=[i.id for i in state.review_issues if i.target_id==id and not i.resolved_by]
        task.requested_aspects={id:sorted({i.aspect for i in state.review_issues if i.id in task.resolution_issue_ids})}
        packet,_=prepare(engine,'semantic_review',task_context(engine,task))
        children.append(task.id)
        if len(render('semantic_review',pool_sources(packet),engine.inquiry))<=engine.config.budget.context_chars:
            task.expected_contribution='Address these exact issues with actual supplied sources; all other disputes remain pending'
            break
        task.status='blocked';task.stop_reason='Independent dispute packet still exceeds context_chars; no backend call sent'
        task.preparation_failures+=1
    return children
