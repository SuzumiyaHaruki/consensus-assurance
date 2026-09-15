"""Bounded recoverable repair sessions keep candidate and patch provenance separate."""
import json
from pathlib import Path
from consensus_assurance.core.types import CheckRun,uid
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from consensus_assurance.adapters.storage.files import write_json
from .prompts import render
from .errors import Blocked
from .output_repair import OutputRepair,repair_targets,apply_replacements,diagnostic_targets,diagnostic_context
from .materials import obtain_materials


def save_session(engine,session):
    engine.state.pending_output_repair=session
    engine.state.repair_sessions[session['id']]=session
    write_json(engine.root/'repair-sessions'/session['id']/'session.json',session)
    engine.checkpoint('output_repair_pending')


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
    session=state.pending_output_repair
    if session and session.get('task')!=kind:raise Blocked('Another repair session is pending')
    if session and 'id' not in session:raise Blocked('Historical repair needs an explicit migrated child run; original artifacts preserved')
    logical_task={'unit_id':state.active_unit_id,'model_id':state.active_model_id,'finding_id':state.active_finding_id,'inquiry_id':state.active_inquiry_id}
    if session and session.get('logical_task',logical_task)!=logical_task:raise Blocked('The repair session belongs to another logical task')
    if session and session.get('status') in {'accepted','accepted_after_read'} and session.get('accepted_check'):
        response=response_type.model_validate_json(Path(session['current_path']).read_text())
        if validator:validator(response)
        state.pending_output_repair=None
        return response,CheckRun.model_validate(session['accepted_check'])
    limit=engine.config.budget.error_context_chars
    while True:
        if session:
            if session['attempt']>=engine.config.budget.repair_attempts or session.get('blocked'):
                save_session(engine,session);raise Blocked('Structured response repair limit reached: '+session['error'])
            candidate=json.loads(Path(session['current_path']).read_text())
            diags=[Diagnostic.model_validate(d) for d in session['diagnostics']]
            context={**context,'attached_materials':[m.model_dump(mode='json') for m in state.materials if m.id in state.attached_material_ids]}
            active_diags=diags[:1]
            active_targets=diagnostic_targets(candidate,active_diags,limit) if active_diags[0].code not in {'schema_type','unclassified_validation'} else session['targets']
            related=diagnostic_context(candidate,active_diags,context,limit)
            session['related_context']=related
            if not session['targets'] and not any('read' in d.allowed for d in diags):
                save_session(engine,session);raise Blocked('Cannot localize an authorized mechanical repair; explicit semantic plan required: '+session['error'])
            request={'original_task':kind,'response_type':response_type.__name__,'repair_session_id':session['id'],'candidate_version':session['version'],
                'repair_targets':active_targets,'diagnostics':session['diagnostics'],'active_diagnostics':[d.model_dump(mode='json') for d in active_diags],'validation_error':session['error'],'patch_error':session.get('patch_error'),
                'related_context':related,'remaining_seconds':engine.budget.remaining()}
            schema=OutputRepair
        else:request=context;schema=response_type
        directory=engine.root/'agent'/(uid()+'-'+kind)
        prompt=render('retry' if session else kind,request,engine.inquiry if kind in {'read','discover','F3','targeted_read','graph_patch','explore','semantic_review'} else '')
        payload=engine.action('agent:'+kind+(':repair' if session else ''),'agent_calls',lambda:engine.agent.analyze(engine.runner,prompt,directory,state.snapshot.id,engine.budget.timeout(),schema),{'prompt':prompt,'response_type':schema.__name__})
        check=CheckRun.model_validate(payload[0]);check.parameters['agent_task']=kind;engine.record(check);cwd=Path(check.cwd)
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
                if patch.change_request:
                    session['proposed_change']=patch.change_request
                    session['error']='Explicit semantic/scope plan requested: '+patch.change_request;session['blocked']=True
                    save_session(engine,session);raise Blocked(session['error'])
                if patch.requests:
                    if patch.replacements:raise ValueError('Read or attach material before returning replacements')
                    engine.budget.take('targeted_reads')
                    obtained=obtain_materials(state,engine.root/'source',patch.requests,engine.config.budget,[id for d in diags for id in d.object_ids],patch.rationale)
                    if obtained['unavailable']:save_session(engine,session);raise Blocked('Requested repair material is unavailable within budget')
                    session['read_requests']=[q.model_dump(mode='json') for q in patch.requests]
                    try:
                        response=response_type.model_validate(candidate)
                        if validator:validator(response)
                    except ValueError as exc:
                        diags,targets=diagnostics_for(exc,candidate,kind,session['version'],limit)
                        session.update(diagnostics=[d.model_dump(mode='json') for d in diags],targets=targets,error=str(exc))
                        state.pending_action=None;save_session(engine,session);continue
                    session['status']='accepted_after_read';session['accepted_check']=check.model_dump(mode='json');session['resolved_diagnostics']=session['diagnostics'];session['diagnostics']=[];session['error']='';save_session(engine,session);state.pending_output_repair=None
                    write_json(cwd/'accepted-response.json',response)
                    return response,check
                if not patch.replacements:raise ValueError('Repair needs replacements, material requests, or a change request')
                merged=apply_replacements(candidate,active_targets,patch)
                from .repair_policy import validate_representation
                validate_representation(candidate,merged,active_targets,related)
                session['patch_error']=None
            except ValueError as exc:
                session['patch_error']={'message':str(exc),'raw_patch':raw}
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
            if validator:validator(response)
            write_json(cwd/'accepted-response.json',response)
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
