"""Task-scoped context, explicit review contracts and actual transmission receipts."""
import json
from .materials import compact_index, material_usage, material_allowance, attachment_key
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
    packet['file_lookup']=[{'file':x['file'],'lines':x.get('lines'),'unavailable':x.get('unavailable')} for x in index]
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
    from .output_repair import all_materials
    materials=all_materials(packet)
    def source_size(value):
        if isinstance(value,dict):
            if {'file','start_line','end_line','text'}<=set(value):return len(value['text'])
            return sum(source_size(v) for v in value.values())
        if isinstance(value,list):return sum(source_size(v) for v in value)
        return 0
    ids=[m['id'] for m in materials if 'id' in m]
    item={'id':uid(),'kind':kind,'task_id':task.id if task else engine.state.active_inquiry_id,'unit_id':engine.state.active_unit_id,
        'material_ids':list(dict.fromkeys(ids)),'materials':[{k:m.get(k) for k in ('id','file','start_line','end_line','content_digest')} for m in materials],
        'review_contract':packet.get('review_contract',[]),'omitted_material_ids':packet.get('omitted_material_ids',[]),
        'source_chars_sent':source_size(packet),'prompt_chars':len(prompt),'prompt_bytes':len(prompt.encode()),'wire_schema_bytes':len(json.dumps(wire,ensure_ascii=False,indent=2).encode()),'wire_schema_chars':len(json.dumps(wire,ensure_ascii=False,indent=2)),'schema_size_basis':'Exact prepared JSON file serialization; not backend token consumption',
        'duplicate_material_occurrences':len(ids)-len(set(ids)),'status':'prepared'}
    engine.state.packet_receipts.append(item)
    if task:
        task.context_receipt_id=item['id'];task.material_ids=list(dict.fromkeys((task.material_ids if repair else [])+item['material_ids']))
        item['review_material_ids']=task.material_ids
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
    groups={}
    for m in found:groups.setdefault((m['file'],m['content_digest']),[]).append(m)
    pool=[]
    for (file,version),items in sorted(groups.items()):
        if len(items)<2:continue
        lines={}
        for m in items:
            for i,line in enumerate(m['text'].split('\n')[:m['end_line']-m['start_line']+1],m['start_line']):
                if i in lines and lines[i]!=line:raise ValueError('Overlapping material text disagrees')
                lines[i]=line
        ranges=[]
        for i in sorted(lines):
            if not ranges or i!=ranges[-1][-1]+1:ranges.append([i])
            else:ranges[-1].append(i)
        for seq in ranges:
            id='source-view-'+str(len(pool)+1)
            pool.append({'id':id,'file':file,'content_digest':version,'start_line':seq[0],'end_line':seq[-1],'text':'\n'.join(lines[i] for i in seq)})
            for m in items:
                if seq[0]<=m['start_line']<=m['end_line']<=seq[-1]:m['source_view_id']=id;m.pop('text',None)
    if pool:
        result['source_text_pool']=pool
        result['source_reference_rule']='Material descriptors retain original citation IDs. source_view_id locates the exact complete text; use file line ranges to select it. Missing text is not permission to infer code.'
    return result
