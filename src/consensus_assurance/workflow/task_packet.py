"""Task-scoped context, explicit review contracts and actual transmission receipts."""
import json
from .materials import compact_index, material_usage, material_allowance
from .review_contract import target_contract
from consensus_assurance.core.types import uid


def prepare(engine,kind,context):
    state=engine.state
    packet=dict(context)
    task=next((t for t in state.inquiry_tasks if t.id==state.active_inquiry_id),None)
    if kind=='semantic_review':
        task=task or next((t for t in state.inquiry_tasks if t.id==context.get('task',{}).get('id')),None)
        if task:
            from .inquiry import objects
            packet['review_contract']=[target_contract(state,objects(state)[i]) for i in task.target_ids]
            for c in packet['review_contract']:
                if c['target_id'] in task.requested_aspects:c['required_aspects']=task.requested_aspects[c['target_id']]
            task.context_dependencies={c['target_id']:c for c in packet['review_contract']}
    # The global index is a lookup aid, not full catalogue or source text.
    index=compact_index(state,engine.root/'source') if state.snapshot else []
    if isinstance(index,dict):index=list(index.values())
    files={m['file'] for key in ('materials','new_materials','initial_materials') for m in packet.get(key,[])}
    packet['file_lookup']=[{'file':x['file'],'lines':x.get('lines'),'unavailable':x.get('unavailable')} for x in index if kind in {'read','discover','explore','targeted_read'} or x['file'] in files]
    packet['lookup_request']='Request a focused ReadingPlan for an unlisted path or symbol; omitted files are not absent from the repository'
    packet['file_metadata']=[{**x,'attached_ranges':[[m['start_line'],m['end_line']] for key in ('materials','new_materials','initial_materials') for m in packet.get(key,[]) if m['file']==x['file']]} for x in index if x['file'] in files]
    packet['material_budget']={'used':material_usage(state),'breadth':material_allowance(state,engine.config.budget,'breadth'),'depth':material_allowance(state,engine.config.budget,'depth')}
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
    from pathlib import Path
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
    groups={'sources':{'materials','new_materials','initial_materials','source_text_pool'},'current_graph':{'unit','claims','bindings','relations','modeling_brief','review_contract'},
        'semantic_view':{'semantic_view','open_issues','resolved_issues'},'catalogue':{'file_lookup','file_metadata','catalogue','responsibilities'}}
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
        pool.append({k:v for k,v in view.model_dump().items() if k!='kind'})
        for m in items:
            m['source_view_id']=view.id;m.pop('text',None)
    if pool:
        result['source_text_pool']=pool
        result['source_reference_rule']='Material descriptors retain original citation IDs. source_view_id locates the exact complete text; use file line ranges to select it. Missing text is not permission to infer code.'
    return result
