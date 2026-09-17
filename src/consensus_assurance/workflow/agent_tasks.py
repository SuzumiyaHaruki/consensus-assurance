"""Bounded recoverable repair sessions keep candidate and patch provenance separate."""
import json
from pathlib import Path
from consensus_assurance.core.types import CheckRun,uid
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from consensus_assurance.adapters.storage.files import write_json
from .prompts import render
from .errors import Blocked
from .output_repair import OutputRepair,repair_targets,apply_replacements,diagnostic_targets,diagnostic_context
from .materials import validate_read_requests, attachment_key


from .output_repair import save_session


def diagnostics_for(exc,candidate,kind,version,limit):
    if isinstance(exc,DiagnosticError):
        result=[d.model_copy(update={'task':kind,'candidate_version':version}) for d in exc.diagnostics]
        return result,diagnostic_targets(candidate,result,limit)
    errors=exc.errors(include_url=False,include_context=False) if hasattr(exc,'errors') else []
    try:targets=repair_targets(candidate,errors,str(exc),limit)
    except ValueError:targets=[]
    return [Diagnostic(code='schema_type' if errors else 'unclassified_validation',category='format' if errors else 'semantic',task=kind,candidate_version=version,paths=[t['path'] for t in targets],message=str(exc),allowed=['representation'] if targets else ['stop'])],targets


def ask(engine,kind,response_type,context,validator=None):
    state=engine.state
    if not engine.agent.mock and not engine.config.allow_agent_materials:raise Blocked('Agent material transmission disabled by configuration; no repository payload was sent')
    def register_citations(response):
        from .sources import citation_ranges
        refs=citation_ranges(response,state)
        if refs:
            engine.read([{k:v for k,v in ref.items() if k!='content_digest'} | {'reason':'Register an exact citation within already acquired source'} for ref in refs.values()],reason='Resolve covered citation ranges without new source acquisition')
    session=state.pending_output_repair
    if session and session.get('task')!=kind:raise Blocked('Another repair session is pending')
    if session and 'id' not in session:raise Blocked('Historical repair needs an explicit migrated child run; original artifacts preserved')
    logical_task={'unit_id':state.active_unit_id,'model_id':state.active_model_id,'finding_id':state.active_finding_id,'inquiry_id':state.active_inquiry_id}
    if session and session.get('logical_task',logical_task)!=logical_task:raise Blocked('The repair session belongs to another logical task')
    if session and session.get('read_plan_id') and session.get('read_requests'):
        obtained=engine.read(session['read_requests'],plan_id=session['read_plan_id'],related_ids=session.get('read_related_ids',[]),reason=session.get('read_rationale','Resume requested repair context'))
        if obtained['status']!='complete':save_session(engine,session);raise Blocked('Repair reading plan still has unmet ranges; no new agent call was sent')
        session['requested_material_ids']=[id for i in obtained['items'] for id in i['material_ids'] if i['status']!='deferred']
        session.pop('read_plan_id')
        try:
            candidate=json.loads(Path(session['current_path']).read_text());response=response_type.model_validate(candidate)
            register_citations(response)
            validate_read_requests(state,engine.root/'source',response)
            if validator:validator(response)
        except ValueError as exc:
            diags,targets=diagnostics_for(exc,candidate,kind,session['version'],engine.config.budget.error_context_chars)
            session.update(diagnostics=[d.model_dump(mode='json') for d in diags],targets=targets,error=str(exc))
        else:
            session['status']='accepted_after_read';session['accepted_check']=session['read_check']
        state.pending_action=None;save_session(engine,session)
    if session and session.get('status') in {'accepted','accepted_after_read'} and session.get('accepted_check'):
        response=response_type.model_validate_json(Path(session['current_path']).read_text())
        register_citations(response)
        validate_read_requests(state,engine.root/'source',response)
        if validator:validator(response)
        state.pending_output_repair=None
        return response,CheckRun.model_validate(session['accepted_check'])
    from .task_packet import prepare, receipt
    context,review_task=prepare(engine,kind,context)
    def validate(response):
        from .sources import validate_view_citations
        from .task_packet import pool_sources
        validate_view_citations(response,pool_sources(context))
        register_citations(response)
        validate_read_requests(state,engine.root/"source",response)
        if validator:validator(response)
    limit=engine.config.budget.error_context_chars
    while True:
        import time
        preparation_started=time.monotonic()
        if session:
            if session['attempt']>=engine.config.budget.repair_attempts or session.get('blocked'):
                save_session(engine,session)
                detail=(session.get('patch_error') or {}).get('message') or session['error']
                raise Blocked('Structured response repair stopped after '+str(session['attempt'])+' attempts: '+detail)
            candidate=json.loads(Path(session['current_path']).read_text())
            diags=[Diagnostic.model_validate(d) for d in session['diagnostics']]
            context,_=prepare(engine,kind,context)
            context={**context,'attached_materials':[m.model_dump(mode='json') for m in state.materials if m.id in state.task_attachments.get(attachment_key(state),[])]}
            active_diags=diags[:1]
            if diags[0].code=='audit_spec_reference':
                for d in diags[1:]:
                    if len(active_diags)>=24:break
                    if d.code!=diags[0].code or d.category!=diags[0].category:continue
                    try:diagnostic_targets(candidate,active_diags+[d],limit)
                    except ValueError:break
                    active_diags.append(d)
            active_targets=diagnostic_targets(candidate,active_diags,limit) if active_diags[0].code not in {'schema_type','unclassified_validation'} else session['targets']
            context['repair_requested_material_ids']=session.get('requested_material_ids',[])
            # Allocate requested source within the existing whole-packet ceiling;
            # error_context_chars bounds diagnostic fields, not repeated old closures.
            requested=[m for m in context['attached_materials'] if m['id'] in context['repair_requested_material_ids']]
            source_room=min(engine.config.budget.context_chars//2,max(limit,sum(len(json.dumps(m,ensure_ascii=False)) for m in requested)+limit))
            if active_diags[0].code=='schema_type' or active_diags[0].category in {'association','material'}:
                # Reference fields need the owning object, dependency claims and source,
                # while editable diagnostics remain bounded by error_context_chars.
                source_room=engine.config.budget.context_chars//2
            related=diagnostic_context(candidate,active_diags,context,source_room)
            if related['required_materials_missing'] or related['required_objects_missing']:
                session['error']='Required repair objects or requested source cannot fit this issue packet; a smaller repair scope is required'
                session['blocked']=True;save_session(engine,session);raise Blocked(session['error'])
            session['related_context']=related
            if not session['targets'] and not any('read' in d.allowed for d in diags):
                save_session(engine,session);raise Blocked('Cannot localize an authorized mechanical repair; explicit semantic plan required: '+session['error'])
            request={'original_task':kind,'response_type':response_type.__name__,'repair_session_id':session['id'],'candidate_version':session['version'],
                'repair_targets':active_targets,'residual_problems':[{'code':d['code'],'object_ids':d['object_ids']} for d in session['diagnostics']],'active_diagnostics':[d.model_dump(mode='json') for d in active_diags],'validation_error':session['error'],'patch_error':session.get('patch_error'),
                'related_context':related,'remaining_seconds':engine.budget.remaining()}
            schema=OutputRepair
        else:request=context;schema=response_type
        directory=engine.root/'agent'/(uid()+'-'+kind)
        from .task_packet import pool_sources
        request=pool_sources(request)
        prompt=render('retry' if session else kind,request,engine.inquiry)
        sent=receipt(engine,kind,request,prompt,schema,review_task,repair=bool(session))
        sent['preparation_seconds']=time.monotonic()-preparation_started
        if len(prompt)>engine.config.budget.context_chars:
            sent['status']='blocked_context_limit'
            state.usage['packet_preparation_failures']=state.usage.get('packet_preparation_failures',0)+1
            if review_task:
                review_task.preparation_failures+=1
                from .inquiry import split_context_task
                sent['child_task_ids']=split_context_task(engine,review_task)
            elif not session and kind in {'build','F3'}:
                from .inquiry import split_model_context
                sent['child_task_ids']=split_model_context(engine,kind)
            write_json(engine.root/'packets'/(sent['id']+'.json'),sent)
            engine.checkpoint('context_limit')
            raise Blocked('Required context exceeds context_chars; split the task or explicitly revise the limit; no payload sent')
        if review_task and not review_task.admitted:
            resource='exploration_rounds' if review_task.kind=='spec_refine' else 'semantic_reviews'
            if state.usage.get(resource,0)>=getattr(engine.config.budget,resource):raise Blocked('Actual inquiry admission budget exhausted: '+resource)
            if review_task.preparation_failures>=engine.config.budget.context_preparations:raise Blocked('Context preparation limit exhausted; no backend call sent')
        from .action_identity import stable_input
        pending=state.pending_action
        saved_scope_result=bool(pending and pending.kind=='agent:scope_review' and pending.status=='completed' and pending.logical_input.get('inputs')==stable_input({'prompt':prompt,'response_type':schema.__name__}))
        if kind=='scope_review' and not saved_scope_result and state.usage.get('semantic_reviews',0)>=engine.config.budget.semantic_reviews:raise Blocked('Scope interpretation review budget exhausted; the saved proposal remains pending')
        invoked=False
        def invoke():
            nonlocal invoked
            invoked=True
            if review_task and not review_task.admitted:
                engine.budget.take('exploration_rounds' if review_task.kind=='spec_refine' else 'semantic_reviews')
                review_task.admitted=True
                engine.checkpoint('inquiry_backend_admitted')
            elif kind=='scope_review':
                engine.budget.take('semantic_reviews')
            return engine.agent.analyze(engine.runner,prompt,directory,state.snapshot.id,engine.budget.timeout(),schema)
        payload=engine.action('agent:'+kind+(':repair' if session else ''),'agent_calls',invoke,{'prompt':prompt,'response_type':schema.__name__})
        sent['result_reused']=not invoked
        sent['status']='action_returned';sent['action_id']=state.pending_action.id if state.pending_action else None
        check=CheckRun.model_validate(payload[0]);sent['check_id']=check.id;sent['status']='reused_result' if any(p.get('check_id')==check.id for p in state.packet_receipts if p is not sent) else 'executed';write_json(engine.root/'packets'/(sent['id']+'.json'),sent);check.parameters['agent_task']=kind;engine.record(check);cwd=Path(check.cwd)
        raw=payload[1]
        if raw is None and check.reason!='Structured agent output is invalid':raise Blocked(f'Agent blocked: {check.status.value}; {check.reason}')
        if session:
            session['attempt']+=1
            try:
                if raw is None:
                    decoded=cwd/'decoded-response.json'
                    raw=json.loads(decoded.read_text()) if decoded.exists() else None
                write_json(engine.root/'repair-sessions'/session['id']/f"patch-{session['attempt']}.json",{'check_id':check.id,'raw':raw})
                patch=OutputRepair.model_validate(raw)
                if patch.change_request and not patch.draft_patch:
                    session['proposed_change']=patch.change_request
                    session['error']='Explicit semantic/scope plan requested: '+patch.change_request;session['blocked']=True
                    save_session(engine,session);raise Blocked(session['error'])
                if patch.requests:
                    if not any('read' in d.allowed for d in active_diags):raise ValueError('This diagnostic requires citation/metadata correction, not another source request')
                    if patch.replacements:raise ValueError('Read or attach material before returning replacements')
                    validate_read_requests(state,engine.root/'source',patch)
                    session.setdefault('read_plan_id',uid());session['read_requests']=[q.model_dump(mode='json') for q in patch.requests]
                    session['read_check']=check.model_dump(mode='json');session['read_related_ids']=[id for d in diags for id in d.object_ids];session['read_rationale']=patch.rationale
                    save_session(engine,session)
                    obtained=engine.read(patch.requests,plan_id=session['read_plan_id'],related_ids=[id for d in diags for id in d.object_ids],reason=patch.rationale)
                    if obtained['status']!='complete':save_session(engine,session);raise Blocked('Requested repair material is deferred; the original reading plan remains pending')
                    session['requested_material_ids']=[id for i in obtained['items'] for id in i['material_ids'] if i['status']!='deferred']
                    from .sources import ranges,all_materials
                    provided=[{'file':file,'content_digest':version,'ranges':spans} for (file,version),spans in sorted(ranges(all_materials(related)).items())]
                    progress={'candidate_version':session['version'],'diagnostics':session['diagnostics'],'actually_provided':provided}
                    if progress==session.get('last_read_progress'):
                        session['stagnation']=session.get('stagnation',0)+1
                        if session['stagnation']>=engine.config.budget.repair_stagnation:session['blocked']=True
                    session['last_read_progress']=progress
                    session.pop('read_plan_id',None)
                    session['read_requests']=[q.model_dump(mode='json') for q in patch.requests]
                    try:
                        response=response_type.model_validate(candidate)
                        validate(response)
                    except ValueError as exc:
                        diags,targets=diagnostics_for(exc,candidate,kind,session['version'],limit)
                        session.update(diagnostics=[d.model_dump(mode='json') for d in diags],targets=targets,error=str(exc))
                        state.pending_action=None;save_session(engine,session);continue
                    session['status']='accepted_after_read';session['accepted_check']=check.model_dump(mode='json');session['resolved_diagnostics']=session['diagnostics'];session['diagnostics']=[];session['error']='';save_session(engine,session);state.pending_output_repair=None
                    write_json(cwd/'accepted-response.json',response)
                    return response,check
                if patch.draft_patch:
                    if kind!='graph_patch' or patch.replacements or patch.binding_splits or patch.requests:raise ValueError('Explicit draft scope plan must be the sole graph_patch repair action')
                    from .repair_policy import validate_draft_plan
                    merged=patch.draft_patch.model_dump(mode='json')
                    validate_draft_plan(candidate,merged)
                    session.setdefault('draft_scope_plans',[]).append({'attempt':session['attempt'],'rationale':patch.rationale,'before':candidate,'after':merged,'review_required':'Regular scope and binding review before modeling; no normative change authorized'})
                else:
                    if not patch.replacements and not patch.binding_splits:raise ValueError('Repair needs replacements, source-backed draft splits, material requests, or a change request')
                    merged=apply_replacements(candidate,active_targets,patch)
                    from .repair_policy import validate_representation
                    validate_representation(candidate,merged,active_targets,related)
                    if patch.binding_splits:
                        from .repair_policy import split_draft_bindings
                        merged=split_draft_bindings(merged,patch,active_diags,related,{b.id for b in state.bindings})
                session['patch_error']=None
            except ValueError as exc:
                session['patch_error']={'message':str(exc),'raw_patch':raw,'diagnostics':[d.model_dump(mode='json') for d in getattr(exc,'diagnostics',[])]}
                session['patch_failures']=session.get('patch_failures',0)+1
                if session['patch_failures']>=max(1,engine.config.budget.repeated_error_revisions):session['blocked']=True
                state.pending_action=None;save_session(engine,session);continue
        else:
            if raw is None:
                decoded=cwd/'decoded-response.json';raw=json.loads(decoded.read_text()) if decoded.exists() else None
            if raw is None:raise Blocked('Unparseable original output; preserved logs cannot be repaired without a candidate')
            merged=raw
        try:
            response=response_type.model_validate(merged)
            validate(response)
            write_json(cwd/'accepted-response.json',response)
            sent['status']='accepted';write_json(engine.root/'packets'/(sent['id']+'.json'),sent)
            if getattr(response,'bundle',None) is not None:
                from consensus_assurance.core.types import now
                state.milestones.setdefault('bundle_accepted',now())
            engine.checkpoint('agent_response_accepted')
            if session:
                session['status']='accepted';session['accepted_check']=check.model_dump(mode='json');session['resolved_diagnostics']=session['diagnostics'];session['diagnostics']=[];session['error']='';session['version']+=1
                session['current_path']=str(engine.root/'repair-sessions'/session['id']/f"candidate-{session['version']}.json")
                write_json(Path(session['current_path']),merged)
                save_session(engine,session)
            state.pending_output_repair=None
            return response,check
        except ValueError as exc:
            if session is None:
                id=uid();folder=engine.root/'repair-sessions'/id
                decoded=cwd/'decoded-response.json'
                write_json(folder/'original.json',json.loads(decoded.read_text()) if decoded.exists() else merged);write_json(folder/'candidate-0.json',merged)
                session={'id':id,'logical_task':logical_task,'task':kind,'response_type':response_type.__name__,'original_path':str(folder/'original.json'),'current_path':str(folder/'candidate-0.json'),'version':0,'attempt':0,'problem_failures':{},'seen_candidates':[],'status':'repairing'}
            else:
                old_keys={d.problem_key() for d in active_diags}
                new_diags,_=diagnostics_for(exc,merged,kind,session['version']+1,limit)
                for d in new_diags:
                    key=d.problem_key()
                    if key in old_keys:session['problem_failures'][key]=session['problem_failures'].get(key,0)+1
                if any(v>=max(1,engine.config.budget.repeated_error_revisions) for v in session['problem_failures'].values()):session['blocked']=True
                if merged in session['seen_candidates'] or merged==candidate:session['stagnation']=session.get('stagnation',0)+1
                if session.get('stagnation',0)>=engine.config.budget.repair_stagnation:session['blocked']=True
                session['seen_candidates'].append(candidate)
                session['version']+=1;session['current_path']=str(engine.root/'repair-sessions'/session['id']/f"candidate-{session['version']}.json")
                write_json(Path(session['current_path']),merged)
            diags,targets=diagnostics_for(exc,merged,kind,session['version'],limit)
            session.update(diagnostics=[d.model_dump(mode='json') for d in diags],targets=targets,error=str(exc))
            write_json(cwd/'diagnostics.json',session['diagnostics']);(cwd/'graph-validation-error.txt').write_text(str(exc))
            if state.pending_action:state.action_history.append(state.pending_action.model_copy(deep=True));state.pending_action=None
            save_session(engine,session)
