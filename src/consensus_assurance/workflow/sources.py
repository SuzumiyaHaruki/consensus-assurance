"""Physical source coverage shared by acquisition, packets, citations and review reuse.

Material is the source reference: file, content version and inclusive line range.
Citation identity is retained; coverage never follows filenames alone.
"""

def value(m,key):return m.get(key) if isinstance(m,dict) else getattr(m,key)

def ranges(materials):
    groups={}
    for m in materials:
        key=(value(m,'file'),value(m,'content_digest'))
        groups.setdefault(key,[]).append((value(m,'start_line'),value(m,'end_line')))
    result={}
    for key,spans in groups.items():
        merged=[]
        for start,end in sorted(spans):
            if merged and start<=merged[-1][1]+1:merged[-1][1]=max(end,merged[-1][1])
            else:merged.append([start,end])
        result[key]=merged
    return result

def covered(reference,provided):
    key=(value(reference,'file'),value(reference,'content_digest'))
    return any(a<=value(reference,'start_line')<=value(reference,'end_line')<=b for a,b in ranges(provided).get(key,[]))

def citation_status(state,ids,provided_ids):
    known={m.id:m for m in state.materials};provided=[known[i] for i in provided_ids if i in known]
    return {id:'unknown' if id not in known else 'provided' if covered(known[id],provided) else 'cached_not_provided' for id in ids}

def includes(state,needed,provided):return all(v=='provided' for v in citation_status(state,needed,provided).values())


def all_materials(context):
    found={};views={};descriptors=[]
    def walk(value):
        if isinstance(value,dict):
            if 'source_text_pool' in value:
                for m in value['source_text_pool']:views[m['id']]=m
            if {'id','file','start_line','end_line'}<=set(value):
                if 'source_view_id' in value:descriptors.append(value)
                elif 'text' in value and not value['id'].startswith('source-view-'):found[value['id']]=value
            for k,v in value.items():
                if k not in {'raw_output','prompt','text','source_text_pool'}:walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    walk(context)
    for m in descriptors:
        view=views.get(m['source_view_id'])
        if view and view['file']==m['file'] and view['start_line']<=m['start_line']<=m['end_line']<=view['end_line']:
            material={k:v for k,v in m.items() if k!='source_view_id'}
            material['text']='\n'.join(view['text'].split('\n')[m['start_line']-view['start_line']:m['end_line']-view['start_line']+1]);found[m['id']]=material
    return list(found.values())



def dependency_closure(objects,seeds):
    """Follow only explicit semantic/mapping references, never arbitrary graph edges."""
    wanted=set();visited=set();todo=list(seeds)
    while todo:
        id=todo.pop()
        if id in visited or id not in objects:continue
        visited.add(id);obj=objects[id]
        if hasattr(obj,'model_dump'):obj=obj.model_dump(mode='json')
        wanted.update(obj.get('source_ids',[]))
        if obj.get('material_id'):wanted.add(obj['material_id'])
        anchor=obj.get('anchor') or {}
        if anchor.get('material_id'):wanted.add(anchor['material_id'])
        basis=obj.get('grounding') or {};wanted.update(basis.get('behavior_ids',[])+basis.get('expectation_ids',[]));todo.extend(basis.get('binding_ids',[]))
        for key in ['goal_ids','obligation_ids','binding_ids','relation_ids']:todo.extend(obj.get(key,[]))
        for key in ['source','target','claim_id']:
            if obj.get(key) in objects:todo.append(obj[key])
        for association in obj.get('associations',[]):todo.append(association['claim_id']);wanted.update(association.get('source_ids',[]))
        for use in obj.get('code_uses',[]):todo.extend(use.get('claim_ids',[])+use.get('relation_ids',[]));wanted.update(use.get('source_ids',[]))
        question=obj.get('audit_question') or {};wanted.update(question.get('source_ids',[]))
        for point in obj.get('coverage_intent',[])+question.get('points',[]):wanted.update(point.get('source_ids',[]))
    return wanted,visited
