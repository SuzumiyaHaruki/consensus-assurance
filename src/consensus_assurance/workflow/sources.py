"""Physical source coverage shared by bindings, citations and review.

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
        wanted.update(anchor.get('source_ids',[]))
        basis=obj.get('grounding') or {};wanted.update(basis.get('source_ids',[])+basis.get('expectation_ids',[]));todo.extend(basis.get('binding_ids',[]))
        for key in ['obligation_ids','binding_ids','relation_ids','behavior_ids','fact_ids','produces_fact_ids','consumes_fact_ids','producer_behavior_ids','consumer_behavior_ids']:todo.extend(obj.get(key,[]))
        for key in ['source','target','claim_id','fact_id']:
            if obj.get(key) in objects:todo.append(obj[key])
        for association in obj.get('associations',[]):todo.append(association['claim_id']);wanted.update(association.get('source_ids',[]))
        question=obj.get('audit_question') or {};wanted.update(question.get('source_ids',[]))
    return wanted,visited


def source_views(materials):
    """Merge only contiguous acquired lines of one file/version; retain original references."""
    from consensus_assurance.core.types import Material
    groups={}
    for raw in materials:
        m=Material.model_validate(raw) if isinstance(raw,dict) else raw
        groups.setdefault((m.file,m.content_digest),[]).append(m)
    result=[]
    for (file,version),items in sorted(groups.items()):
        lines={}
        for m in items:
            for n,text in enumerate(m.text.split('\n')[:m.end_line-m.start_line+1],m.start_line):
                if n in lines and lines[n]!=text:raise ValueError('Conflicting source text at the same file/version/range')
                lines[n]=text
        for start,end in ranges(items)[(file,version)]:
            contributors=[m for m in items if m.start_line<=end and m.end_line>=start]
            view=Material(id='source-view-'+str(len(result)+1),file=file,content_digest=version,start_line=start,end_line=end,
                text='\n'.join(lines[n] for n in range(start,end+1)),kind=contributors[0].kind)
            result.append((view,contributors))
    return result
