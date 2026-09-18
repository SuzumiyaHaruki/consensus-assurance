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
                for m in value['source_text_pool']:views[m.get('view_id',m.get('id'))]=m
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
        wanted.update(anchor.get('source_ids',[]))
        basis=obj.get('grounding') or {};wanted.update(basis.get('behavior_ids',[])+basis.get('expectation_ids',[]));todo.extend(basis.get('binding_ids',[]))
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


def validate_view_citations(response, context):
    """A text-view alias is not a source identity; require an explicit scoped correction."""
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    from .output_repair import pointer
    views={v.get('view_id',v.get('id')):v for v in context.get('source_text_pool',[])}
    materials=all_materials(context);diagnostics=[]
    def walk(node, route=()):
        if isinstance(node,dict):
            for key,value in node.items():
                citation=key in {'source_ids','expectation_ids','material_id'} or (key=='behavior_ids' and route and route[-1]=='grounding')
                if citation:
                    aliases=[v for v in (value if isinstance(value,list) else [value]) if isinstance(v,str) and v in views]
                    if aliases:
                        choices={a:[m['id'] for m in materials if m['file']==views[a]['file'] and m['content_digest']==views[a]['content_digest'] and views[a]['start_line']<=m['start_line']<=m['end_line']<=views[a]['end_line']] for a in aliases}
                        diagnostics.append(Diagnostic(code='source_view_citation',category='material',paths=[pointer(route+(key,))],
                            material_ids=list(dict.fromkeys(i for ids in choices.values() for i in ids)),allowed=['representation'],
                            message='Text view aliases are not source IDs; select actual contributing ranges without inventing or broadening evidence',details={'alias_candidates':choices}))
                walk(value,route+(key,))
        elif isinstance(node,list):
            for i,value in enumerate(node):walk(value,route+(i,))
    walk(response.model_dump(mode='json'))
    if diagnostics:raise DiagnosticError(diagnostics)


def citation_ranges(response, state):
    """Resolve only physical citations fully covered in the captured content version."""
    import re
    found={};known={m.id for m in state.materials}
    def walk(node):
        if isinstance(node,dict):
            for key,value in node.items():
                if key in {'source_ids','expectation_ids','material_id'}:
                    for id in value if isinstance(value,list) else [value]:
                        match=re.fullmatch(r'(.+):(\d+):(\d+)',id) if isinstance(id,str) else None
                        if match and id not in known:
                            file,start,end=match.groups();version=state.snapshot.files.get(file)
                            ref=dict(file=file,start_line=int(start),end_line=int(end),content_digest=version)
                            if version and 1<=ref['start_line']<=ref['end_line'] and covered(ref,state.materials):found[id]=ref
                else:walk(value)
        elif isinstance(node,list):
            for value in node:walk(value)
    walk(response.model_dump(mode='json'))
    return found
