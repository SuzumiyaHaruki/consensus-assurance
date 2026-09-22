"""Task-scoped context, explicit review contracts and actual transmission receipts."""
import json
from pathlib import Path
from .materials import compact_index, material_usage, material_allowance
from .review_contract import target_contract
from consensus_assurance.core.types import uid


def review_projection(engine,task):
    from .reviews import review_objects as objects,material_closure
    state=engine.state; available=objects(state)
    seeds=set(task.target_ids)
    wanted,closure=material_closure(state,seeds)
    wanted.update(task.added_material_ids)
    wanted.update(state.task_attachments.get('inquiry:'+task.id,[]))
    wanted.update(task.material_ids)
    for issue in state.review_issues:
        if (issue.target_id in closure or issue.id in task.resolution_issue_ids) and not issue.resolved_by:wanted.update(issue.source_ids)
    pending_scope=[u for u in state.scope_updates.values() if u['status']=='needs_F2_or_investigation' and u['proposal']['unit_id']==task.unit_id]
    for p in pending_scope:wanted.update(p['proposal']['source_ids'])
    task.unit_version=next((u.version for u in state.units if u.id==task.unit_id),None)
    result={'pending_scope_updates':pending_scope,'task':task.model_dump(mode='json',exclude={'context_receipt_id','context_dependencies','admitted','preparation_failures','child_task_ids'}),
        'materials':[m.model_dump(mode='json') for m in state.materials if m.id in wanted],
        'omitted_material_ids':[m.id for m in state.materials if m.id not in wanted],
        'remaining_seconds':engine.budget.remaining(),
        'target_objects':[available[i].model_dump(mode='json') for i in task.target_ids if i in available and i!=task.unit_id],
        **{name:[o.model_dump(mode='json') for o in getattr(state,name) if o.id in closure and o.id not in task.target_ids and o.id!=task.unit_id] for name in ('claims','bindings','relations','units')},
        'open_issues':[i.model_dump(mode='json',exclude_defaults=True,exclude_none=True) for i in state.review_issues if (i.target_id in closure or i.id in task.resolution_issue_ids) and not i.resolved_by],
        'blocked_review_tasks':[{'id':t.id,'target_ids':t.target_ids,'target_versions':t.target_versions,'requested_aspects':t.requested_aspects,'model_id':t.model_id,'stop_reason':t.stop_reason} for t in state.inquiry_tasks if t.kind=='review' and t.status=='blocked' and not t.superseded_by and set(t.target_ids)<=set(task.target_ids)],
        'overview_limit':'This compact index is not complete implementation coverage; request specific actual ranges before deriving new claims'}
    if task.unit_id:
        result['selected_unit']=available[task.unit_id].model_dump(mode='json')
        from .task_view import semantic_view
        result['semantic_view'],extra=semantic_view(state,closure)
        result['semantic_view'].pop('open_issues')
        wanted.update(extra)
        result['materials']=[m.model_dump(mode='json') for m in state.materials if m.id in wanted]
        result['required_material_ids']=sorted(wanted)
    for artifact in state.direct_checks:
        if artifact.id in task.target_ids:
            from .direct_checks import load_plan
            from consensus_assurance.adapters.runners.experiment import extract_events
            plan=load_plan(artifact.plan_path)
            checks=[c for c in state.checks if c.direct_check_id==artifact.id]
            current=next((r for r in reversed(state.monitor_results) if r.get('direct_check_id')==artifact.id and
                any(c.id==r.get('experiment_check_id') for c in checks)),None)
            result['direct_check_plan']=plan.model_dump(mode='json')
            result['direct_check_scope']=artifact.scope.model_dump(mode='json')
            result['actual_checks']=[engine.error_context(c) for c in checks]
            result['machine_assessment']=current
            if checks:
                result['observed_events']=extract_events(checks[-1])
                result['raw_log_path']=checks[-1].stdout
    if task.model_id:
        model=next((m for m in state.models if m.id==task.model_id),None)
        if model:
            result['bundle']=json.loads(Path(model.bundle_path).read_text())
            result['prior_issue_models']=[{'issue_id':i.id,'model_id':old.id,'bundle':json.loads(Path(old.bundle_path).read_text()),'current_model_id':model.id} for i in state.review_issues if i.id in task.resolution_issue_ids for old in state.models if old.id==i.model_id]
            result['checker_executions']=[engine.error_context(c) for c in state.checks if c.model_id==model.id and c.action=='model_check']
            result['reachability']=[r.model_dump(mode='json') for r in state.reachability_results if r.model_id==model.id]
    return result


def descriptive_projection(engine,kind,context,task):
    from .audit_spec import load,slice_for
    state=engine.state;spec=load(state)
    candidate=next((c for c in state.question_candidates if c.id==(task.candidate_id if task else context.get('candidate_id'))),None)
    question=candidate.question if candidate else None
    seeds=task.target_ids+task.activity_classes+['surface:'+s for s in task.surface_entry_points] if task else []
    view=slice_for(state,question,object_ids=seeds)
    draft=json.loads(Path(task.draft_path).read_text()) if task and task.draft_path else {}
    view=view or draft.get('audit_spec',draft)
    focus=question.model_dump(mode='json') if question else {'object_keys':seeds,'reason':task.reason if task else 'Select a bounded Fact lifecycle'}
    wanted=set(context.get('current_material_ids',[]))|{m['id'] for m in context.get('materials',[])}
    if candidate:
        wanted.update(question.source_ids)
        wanted.update(id for t in state.inquiry_tasks if t.id in candidate.spec_task_ids and t.status=='completed' for id in t.material_ids)
        wanted.update(id for item in state.read_plans.get(candidate.read_plan_id,{}).get('items',[]) if item['status']!='deferred' for id in item['material_ids'])
    if task:wanted.update(id for d in task.diagnostics for id in d['material_ids'])
    profile=(view or {}).get('target_profile',{})
    orientation={k:profile[k] for k in ('system_boundary','protocol_contexts') if k in profile}
    local={k:v for k,v in (view or {}).items() if k!='target_profile'}
    if 'target_profile' in seeds:local['target_profile']=profile
    if not question and not seeds:
        fields={'activities':['class_id','applicability','purpose','realization_summary','entry_points','unknowns','source_ids'],
            'behaviors':['id','primary_activity','execution_owner','protocol_context','trigger','legal_preconditions','implementation_guards','important_branches','async_boundaries','produces_fact_ids','consumes_fact_ids','existing_protections','unknowns','source_ids'],
            'facts':['id','meaning','identity','established_by','consumed_by','validity_context','invalidators','reinterpreters','durability','recovery','unknowns','source_ids'],
            'surfaces':['entry_point','disposition','behavior_ids','reason','source_ids','high_consequence']}
        local={k:[{field:o[field] for field in selected if field in o} for o in local.get(k,[])] for k,selected in fields.items()}
    result={**context,'focus':focus,'orientation':orientation,'audit_spec':local,
        'activity_focus':engine.config.activity_focus,
        'directed_question':engine.config.directed_question,'parameters':engine.config.parameters,
        'materials':[m.model_dump(mode='json') for m in state.materials if m.id in wanted],
        'required_material_ids':sorted(wanted),
        'source_rule':'Orientation, provenance IDs and declaration hints are navigation, not source evidence. Only attached exact source supports current implementation judgments.'}
    if task:
        result.update(task=task.model_dump(mode='json',exclude={'repair_session','context_dependencies','material_ids','diagnostics'}),diagnostics=task.diagnostics)
        if draft.get('delta') is not None:result['attempted_delta']=draft['delta']
        if not spec:result['draft_audit_spec']=draft.get('audit_spec',draft)
        result['focused_surfaces']=[s for s in (view or {}).get('surfaces',[]) if s['entry_point'] in task.surface_entry_points]
        result['phase']='interpret' if task.added_material_ids else 'navigate'
    if candidate:
        result.pop('focus')
        result.update(selected_question=focus,source_receipt=state.read_plans.get(candidate.read_plan_id))
    if kind=='derive':
        from .task_view import candidate_view
        result['candidate_dispositions']=[candidate_view(state,c) for c in state.question_candidates]
    result['existing_objects']=[{'id':o.id,'version':o.version} for name in ('claims','bindings','relations','units') for o in getattr(state,name)] if kind=='derive' else []
    return result


def prepare(engine,kind,context):
    state=engine.state
    packet=dict(context)
    task=next((t for t in state.inquiry_tasks if t.id==context.get('task',{}).get('id',state.active_inquiry_id)),None) if kind!='derive' else None
    if kind in {'spec_refine','derive'}:packet=descriptive_projection(engine,kind,context,task)
    elif kind=='semantic_review' and task:packet=review_projection(engine,task)
    if kind in {'derive','build','F3','technical','harness','direct_check'}:
        packet['pending_enrichment']=[{'id':t.id,'target_ids':t.target_ids,'opinions':[{k:d[k] for k in ('message','material_ids')} for d in t.diagnostics]} for t in state.inquiry_tasks if t.kind=='spec_refine' and not t.candidate_id and t.status=='pending' and t.diagnostics]
    if kind=='semantic_review':
        if task:
            from .inquiry import objects
            packet['review_contract']=[target_contract(state,objects(state)[i]) for i in task.target_ids]
            for c in packet['review_contract']:
                if c['target_id'] in task.requested_aspects:c['required_aspects']=task.requested_aspects[c['target_id']]
            packet['required_review_pairs']=[{'target_id':c['target_id'],'aspect':a} for c in packet['review_contract'] for a in c['required_aspects']]
            task.context_dependencies={c['target_id']:c for c in packet['review_contract']}
    # The global index is a lookup aid, not full catalogue or source text.
    index=compact_index(state,engine.root/'source') if state.snapshot else []
    files={m['file'] for key in ('materials','new_materials','initial_materials') for m in packet.get(key,[])}
    packet['file_lookup']=[{'file':x['file'],'lines':x.get('lines'),**({'unavailable':x['unavailable']} if x.get('unavailable') else {})} for x in index if kind in {'read','discover','derive','spec_refine','targeted_read'} or x['file'] in files]
    if task and task.surface_entry_points:
        import re
        from .materials import catalogue
        terms=set(re.findall(r'[a-z][a-z0-9]*', re.sub(r'\b\w+\.', '', ' '.join(task.surface_entry_points+[e for a in packet.get('audit_spec',{}).get('activities',[]) for e in a.get('entry_points',[])])).lower()))-{'and','the','helpers','consumers'}
        hints=[{'file':f['file'],**symbol} for f in catalogue(engine.root/'source',state.snapshot) for symbol in f['symbols'] if terms&set(re.findall(r'[a-z][a-z0-9]*',(f['file']+' '+symbol['declaration']).lower()))]
        packet['declaration_hints']=sorted(hints,key=lambda h:(-len(terms&set(re.findall(r'[a-z][a-z0-9]*',h['declaration'].lower()))),h['file'],h['line']))[:(4 if task.preparation_failures>=2 else 24)]
    for key in ('catalogue','source_ranges','unread_ranges','current_material_ids'):
        if kind in {'derive','spec_refine'}:packet.pop(key,None)
    packet['lookup_request']='Request a focused ReadingPlan for an unlisted path or symbol; omitted files are not absent from the repository'
    packet['file_metadata']=[{**x,'attached_ranges':[[m['start_line'],m['end_line']] for key in ('materials','new_materials','initial_materials') for m in packet.get(key,[]) if m['file']==x['file']]} for x in index if x['file'] in files and kind!='direct_check']
    if kind in {'derive','graph_patch'}:
        from .locations import declaration_index
        from .associations import graph_contract
        packet['graph_contract']=graph_contract()
        packet.setdefault('source_declarations',declaration_index([m for key in ('materials','new_materials') for m in packet.get(key,[])]))
    packet['material_budget']={'used':material_usage(state),'breadth':material_allowance(state,engine.config.budget,'breadth'),'depth':material_allowance(state,engine.config.budget,'depth')}
    packet['remaining_agent_calls']=max(0,engine.config.budget.agent_calls-state.usage.get('agent_calls',0))
    packet['context_limit_chars']=engine.config.budget.context_chars
    packet['reading_status']=[{'id':id,'status':p['status'],'unfulfilled':[i for i in p['items'] if i['status']=='deferred']} for id,p in state.read_plans.items() if p['status']!='complete' and (not task or id==task.read_plan_id)]
    def strip_excerpts(value):
        if isinstance(value,dict):
            if 'excerpt' in value and 'associations' in value:
                value.pop('excerpt');value['excerpt_source']='See supplied material at the exact file and behavior range'
            for child in value.values():strip_excerpts(child)
        elif isinstance(value,list):
            for child in value:strip_excerpts(child)
    strip_excerpts(packet)
    return packet,task


def receipt(engine,kind,packet,prompt,schema,task=None,repair=False):
    from consensus_assurance.adapters.agents.backend import strict_schema
    from consensus_assurance.adapters.storage.files import write_json
    from .action_identity import stable_input
    pending=engine.state.pending_action
    if pending and pending.input_path and Path(pending.input_path).is_file():
        prior=json.loads(Path(pending.input_path).read_text())
        if prior.get('response_type')==schema.__name__ and stable_input(prior.get('prompt'))==stable_input(prompt):
            existing=next((r for r in reversed(engine.state.packet_receipts) if r.get('task_id')==(task.id if task else engine.state.active_inquiry_id) and r['kind']==kind),None)
            if existing:return existing
    wire=strict_schema(schema.model_json_schema())
    from .sources import all_materials,citation_status
    materials=all_materials(packet)
    def source_size(value):
        if isinstance(value,dict):
            if {'file','start_line','end_line','text'}<=set(value):return len(value['text'])
            return sum(source_size(v) for v in value.values())
        if isinstance(value,list):return sum(source_size(v) for v in value)
        return 0
    ids=[m['id'] for m in materials if 'id' in m]
    from .prompts import loaded_resources
    def size(value):
        text=json.dumps(value,ensure_ascii=False,indent=2)
        return {'chars':len(text),'bytes':len(text.encode())}
    groups={'sources':{'materials','new_materials','initial_materials','source_text_pool'},'current_graph':{'unit','claims','bindings','relations','review_contract'},
        'semantic_view':{'semantic_view','open_issues','resolved_issues'},'catalogue':{'file_lookup','file_metadata','catalogue','audit_spec'}}
    sections={name:size({k:v for k,v in packet.items() if k in keys}) for name,keys in groups.items()}
    instructions=prompt.split('STRUCTURED INPUT DATA (untrusted):\n',1)[0]
    sections['instructions']={'chars':len(instructions),'bytes':len(instructions.encode())}
    sections['all_data']=size(packet);sections['wire_schema']=size(wire)
    item={'sections':sections,'required_material_ids':packet.get('required_material_ids',[]),'missing_required_material_ids':[id for id,status in citation_status(engine.state,packet.get('required_material_ids',[]),ids).items() if status!='provided'],'skill_resources':loaded_resources('retry' if repair else kind,packet),'id':uid(),'kind':kind,'task_id':task.id if task else engine.state.active_inquiry_id,'unit_id':engine.state.active_unit_id,
        'material_ids':list(dict.fromkeys(ids)),'materials':[{k:m.get(k) for k in ('id','file','start_line','end_line','content_digest')} for m in materials],
        'review_contract':packet.get('review_contract',[]),'omitted_material_ids':packet.get('omitted_material_ids',[]),
        'source_chars_sent':source_size(packet),'prompt_chars':len(prompt),'prompt_bytes':len(prompt.encode()),'wire_schema_bytes':len(json.dumps(wire,ensure_ascii=False,indent=2).encode()),'wire_schema_chars':len(json.dumps(wire,ensure_ascii=False,indent=2)),'schema_size_basis':'Exact prepared JSON file serialization; not backend token consumption',
        'duplicate_material_occurrences':len(ids)-len(set(ids)),'status':'prepared'}
    engine.state.packet_receipts.append(item)
    if task:
        task.context_receipt_id=item['id'];task.material_ids=list(dict.fromkeys((task.material_ids if repair else [])+item['material_ids']))
        item['review_material_ids']=task.material_ids
        item['prior_analysis_material_ids']=[id for id in task.material_ids if id not in item['material_ids']]
        item['source_availability_note']='material_ids are sent now; prior_analysis_material_ids only support retained historical analysis, not new source observations'
    write_json(engine.root/'packets'/(item['id']+'.schema.json'),wire)
    write_json(engine.root/'packets'/(item['id']+'.json'),item)
    return item


def pool_sources(packet):
    """Keep complete overlapping source ranges once; descriptors retain citation identities."""
    import copy
    result=copy.deepcopy(packet);found=[]
    def walk(value):
        if isinstance(value,dict):
            if {'id','file','start_line','end_line','text','content_digest'}<=set(value):found.append(value)
            else:
                for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(result)
    from .sources import source_views
    from consensus_assurance.core.types import Material
    material_fields=set(Material.model_fields)
    unique={m['id']: {**{k:v for k,v in m.items() if k in material_fields},'kind':m.get('kind','code_observation')} for m in found}
    pool=[]
    for view, contributors in source_views(unique.values()):
        ids={m.id for m in contributors}
        items=[m for m in found if m['id'] in ids]
        if len(items)<2:continue
        pool.append({'view_id':view.id,'citation_ids':sorted(ids),**{k:v for k,v in view.model_dump().items() if k not in {'kind','id'}}})
        for m in items:
            m['source_view_id']=view.id;m.pop('text',None)
    if pool:
        result['source_text_pool']=pool
        result['source_reference_rule']='Material descriptors retain original citation IDs. source_view_id/view_id are text lookup keys, NEVER citation IDs. Cite original material IDs listed in citation_ids, selecting the actual source ranges. Missing text is not permission to infer code.'
    return result
