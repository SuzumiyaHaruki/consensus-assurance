import re
from pathlib import Path
from pydantic import Field
from typing import Literal
from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
from consensus_assurance.core.types import uid
from consensus_assurance.core.types import Material, Record
from consensus_assurance.adapters.storage.files import digest


from consensus_assurance.core.proposals import ReadRequest


class ReadingPlan(Record):
    requests: list[ReadRequest] = Field(max_length=12)
    rationale: str
    related_ids: list[str] = []
    gap: str = ""


def request_identity(request):
    """The source selector, independent of prose explaining the read."""
    q=ReadRequest.model_validate(request)
    return (q.file,q.start_line,q.end_line,q.symbol,q.literal)


def request_label(request):
    q=ReadRequest.model_validate(request)
    scope=q.file or '<authorized snapshot>'
    if q.symbol:return scope+' symbol='+q.symbol
    if q.literal:return scope+' literal='+repr(q.literal)
    return f'{scope}:{q.start_line}–{q.end_line}'


def read_complete(receipt):
    return receipt['status']=='complete' and all(item['status'] not in {'deferred','unresolved'} for item in receipt['items'])


def material_kind(path, text):
    if path.endswith((".md", ".rst")):
        return "document_statement"
    if "_test" in path or path.startswith("test"):
        return "test_expectation"
    if "interface {" in text:
        return "interface_statement"
    return "code_observation"


def source_root(repo,snapshot):
    repo=Path(repo)
    return repo if repo.is_dir() else Path(snapshot.repo)


def metadata(repo,snapshot,file):
    if Path(file).is_absolute() or '..' in Path(file).parts:raise PermissionError('Path is outside the authorized relative namespace')
    if file not in snapshot.files:raise FileNotFoundError('Path is absent from the captured file index')
    if snapshot.readable_files is not None and file not in snapshot.readable_files:raise PermissionError('Path is excluded from agent-readable materials')
    path=source_root(repo,snapshot)/file
    if not path.resolve().is_relative_to(source_root(repo,snapshot).resolve()):raise PermissionError("Path escapes the source snapshot")
    data=path.read_bytes()
    if digest(data)!=snapshot.files[file]:raise ValueError("Current source content differs from the captured snapshot")
    text=data.decode('utf-8');lines=text.splitlines()
    return {'file':file,'lines':len(lines),'content_digest':snapshot.files[file],'snapshot_id':snapshot.id,'encoding':'utf-8'},lines


def locate(repo,snapshot,request):
    """Find exact declarations or literal lines in authorized snapshot files."""
    from .locations import declarations,matches_symbol
    files=[request.file] if request.file else sorted(snapshot.readable_files if snapshot.readable_files is not None else snapshot.files)
    matches=[]
    for file in files:
        info,lines=metadata(repo,snapshot,file)
        if request.symbol:
            if not file.endswith(('.go','.py')):continue
            if not lines:continue
            source=Material(id='',file=file,start_line=1,end_line=len(lines),kind='code_observation',text='\n'.join(lines),content_digest=info['content_digest'])
            matches.extend({'file':file,'start_line':d.get('owner_start',d['start']),'end_line':d['end'],'kind':d['kind']} for d in declarations(source,include_calls=False)
                if d['kind'] in {'declaration','interface_member'} and matches_symbol(d,request.symbol))
        else:
            matches.extend({'file':file,'start_line':i,'end_line':i,'kind':'literal_line'} for i,line in enumerate(lines,1) if request.literal in line)
    return {'kind':'symbol' if request.symbol else 'literal','query':request.symbol or request.literal,
        'match_count':len(matches),'matches':matches[:24],'truncated':len(matches)>24,
        'scope':'Complete declaration' if request.symbol else 'Matching line only; request more context if needed'}


def preflight(state,repo,requests,path='/requests'):
    rows=[];errors=[]
    for i,raw in enumerate(requests):
        req=ReadRequest.model_validate(raw);info={'file':req.file,'snapshot_id':state.snapshot.id}
        try:
            lookup=locate(repo,state.snapshot,req) if req.symbol or req.literal else None
            match=lookup['matches'][0] if lookup and lookup['match_count']==1 and lookup['matches'][0]['end_line'] is not None else None
            resolved=req.model_copy(update={k:match[k] for k in ('file','start_line','end_line')} | {'symbol':None,'literal':None}) if match else req
            if lookup and not match:
                rows.append((req,None,{'file':req.file,'snapshot_id':state.snapshot.id,'lookup':lookup},None));continue
            info,lines=metadata(repo,state.snapshot,resolved.file)
            if lookup:
                info['lookup']=lookup
                info['resolved_range']={'file':resolved.file,'start_line':resolved.start_line,'end_line':resolved.end_line}
            if resolved.start_line>resolved.end_line or resolved.end_line>len(lines):
                raise IndexError('Requested source range does not exist; actual file has '+str(len(lines))+' lines')
            rows.append((req,resolved,info,lines))
        except (ValueError,OSError,IndexError) as exc:
            code='read_range' if isinstance(exc,IndexError) else 'read_encoding' if isinstance(exc,UnicodeError) else 'read_permission' if isinstance(exc,PermissionError) else 'read_path' if isinstance(exc,FileNotFoundError) else 'read_snapshot'
            fields=['start_line','end_line'] if code=='read_range' else ['file' if req.file else 'symbol' if req.symbol else 'literal']
            errors.append(Diagnostic(code=code,category='material',object_ids=[req.file] if req.file else [],paths=[path+'/'+str(i)+'/'+f for f in fields],message=str(exc),allowed=['representation','read'],
                details={'original_request':req.model_dump(mode='json'),'file_metadata':info,'legal_range':[1,info.get('lines',0)],'no_clamping':True}))
    if errors:raise DiagnosticError(errors)
    return rows


def read_material(repo,snapshot,request):
    class Input:pass
    state=Input();state.snapshot=snapshot
    _,req,info,lines=preflight(state,repo,[request])[0]
    if req is None:raise ValueError('Source lookup did not identify one complete range')
    text='\n'.join(lines[req.start_line-1:req.end_line])
    return Material(id=f"{req.file}:{req.start_line}:{req.end_line}",file=req.file,start_line=req.start_line,end_line=req.end_line,
        kind=material_kind(req.file,text),text=text,content_digest=info['content_digest'])


def initial_materials(repo, snapshot, budget, knowledge):
    result, count = [], 0
    available = sorted(snapshot.readable_files if snapshot.readable_files is not None else snapshot.files)
    documents = [f for f in available if f.endswith((".md", ".rst"))]
    documents.sort(key=lambda f: (Path(f).stem.lower() != "readme", len(Path(f).parts), f))
    selected = documents[:2]
    code=[f for f in available if f.endswith(('.go','.py','.rs','.java','.cc','.cpp','.h')) and 'test' not in Path(f).name.lower()]
    hints=('api|client|future|service','rpc|transport|message','protocol|consensus|replica|participant|coordinator|node|server','storage|snapshot|log|history','recovery|restore|startup','config|member','fsm|apply|state')
    for pattern in hints:
        matches=[f for f in code if f not in selected and re.search(pattern,Path(f).stem,re.I)]
        match=min(matches,key=lambda f:(len(Path(f).parts),not bool(re.fullmatch(pattern,Path(f).stem,re.I)),f)) if matches else None
        if match:selected.append(match)
    selected.extend(f for f in code if f not in selected)
    selected.extend(f for f in available if f not in selected)
    for rel in selected:
        if len(result) >= min(8, budget.material_chunks):
            break
        lines = (repo / rel).read_text().splitlines()
        if not lines:
            continue
        end = min(len(lines), 80)
        item = read_material(repo, snapshot, ReadRequest(file=rel, start_line=1, end_line=end, reason="Initial repository survey"))
        if count + len(item.text) > min(40000,budget.material_chars//3):
            continue
        result.append(item); count += len(item.text)
    if knowledge and len(result) < budget.material_chunks and count + len(knowledge) <= budget.material_chars:
        result.append(Material(id="protocol-knowledge", file="protocol-knowledge", start_line=1, end_line=len(knowledge.splitlines()),
            kind="protocol_candidate", text=knowledge, content_digest=digest(knowledge.encode())))
    return result


class ReadItem(Record):
    request: ReadRequest
    status: Literal['acquired','cached','deferred','unresolved']
    material_ids: list[str] = []
    new_chars: int = 0
    new_chunks: int = 0
    reason: str = ''
    file_metadata: dict = {}


class ReadReceipt(Record):
    id: str
    snapshot_id: str
    purpose: Literal['breadth','depth']
    status: Literal['complete','partial','deferred']
    items: list[ReadItem]
    partial_policy: str
    related_ids: list[str] = []
    reason: str
    original_requests: list[ReadRequest]
    allowance: dict
    attempt: int = 1


def material_lines(state):
    lines={}
    for m in state.materials:
        for offset,text in enumerate(m.text.split('\n')[:m.end_line-m.start_line+1]):
            key=(m.content_digest,m.file,m.start_line+offset)
            if key in lines and lines[key]!=text:raise ValueError('Cached source ranges disagree for the same snapshot')
            lines[key]=text
    return lines


def usage_of(lines):
    chunks=0;previous=None
    for version,file,line in sorted(lines):
        if previous!=(version,file,line-1):chunks+=1
        previous=(version,file,line)
    return {'unique_chars':sum(len(t)+1 for t in lines.values()),'unique_chunks':chunks}


def material_usage(state):return usage_of(material_lines(state))


def material_allowance(state,budget,purpose):
    used=material_usage(state)
    depth=sum(a.get('new_chars',0) for a in state.material_allocations if a['purpose']=='depth')
    breadth=max(0,used['unique_chars']-depth)
    ratio=budget.depth_material_reserve if purpose=='breadth' else budget.breadth_material_reserve
    consumed=depth if purpose=='breadth' else breadth
    reserve=max(0,int(budget.material_chars*ratio)-consumed)
    reason='Protect finite '+('local dependency/review' if purpose=='breadth' else 'breadth exploration')+' capacity'
    if purpose=='breadth' and 'discovery' in state.completed_steps and not any(u.status in {'pending','partial','selected'} for u in state.units) and not state.deferred_units and not any(p['purpose']=='depth' and p['status']!='complete' for p in state.read_plans.values()):
        reserve=0;reason='No currently executable local unit; unused depth reserve may be borrowed'
    chunk_reserve=max(0,int(budget.material_chunks*ratio)-(sum(a.get('new_chunks',0) for a in state.material_allocations if a['purpose']=='depth') if purpose=='breadth' else max(0,used['unique_chunks']-sum(a.get('new_chunks',0) for a in state.material_allocations if a['purpose']=='depth'))))
    if reserve==0:chunk_reserve=0
    return {**used,'total_chars':budget.material_chars,'total_chunks':budget.material_chunks,'reserved_for_other_chars':reserve,
        'available_chars':max(0,budget.material_chars-used['unique_chars']-reserve),
        'available_chunks':max(0,budget.material_chunks-used['unique_chunks']-chunk_reserve),'purpose':purpose,'allocation_reason':reason,
        'accounting':'Unique normalized source lines including one logical separator per line; not prompt tokens or a bill'}


def attachment_key(state):
    candidate=next((c for c in state.question_candidates if c.status=='active'),None)
    return 'inquiry:'+state.active_inquiry_id if state.active_inquiry_id else 'unit:'+state.active_unit_id if state.active_unit_id else 'candidate:'+candidate.id if candidate else 'discovery'


def plan_read(state,repo,requests,budget,*,purpose='depth',partial=False,plan_id=None,related_ids=(),reason='Read requested material'):
    rows=preflight(state,repo,requests)
    cached=material_lines(state);allowance=material_allowance(state,budget,purpose);available=allowance['available_chars'];chunk_room=allowance['available_chunks']
    outcomes=[];new_materials=[]
    # Preserve authored priority, including when a prefix must be deferred.
    ordered=list(enumerate(rows));deferred=False
    for index,(original,req,info,lines) in ordered:
        if req is None:
            lookup=info['lookup']
            reason='No matching source' if lookup['match_count']==0 else 'Ambiguous source lookup' if lookup['match_count']>1 else 'Matched declaration has no complete boundary'
            outcomes.append((index,ReadItem(request=original,status='unresolved',reason=reason,file_metadata=info)));continue
        additions={(info['content_digest'],req.file,i):lines[i-1] for i in range(req.start_line,req.end_line+1) if (info['content_digest'],req.file,i) not in cached}
        cost=sum(len(t)+1 for t in additions.values());chunks=usage_of({**cached,**additions})['unique_chunks']-usage_of(cached)['unique_chunks']
        mid=f'{req.file}:{req.start_line}:{req.end_line}'
        if (deferred or cost>available or chunks>chunk_room) and cost:
            deferred=True
            outcome=ReadItem(request=original,status='deferred',new_chars=cost,new_chunks=max(0,chunks),reason='Unique material allowance or protected reserve is insufficient; the entire request remains pending',file_metadata=info)
        else:
            text='\n'.join(lines[req.start_line-1:req.end_line])
            if mid not in {m.id for m in state.materials}:new_materials.append(Material(id=mid,file=req.file,start_line=req.start_line,end_line=req.end_line,kind=material_kind(req.file,text),text=text,content_digest=info['content_digest']))
            outcome=ReadItem(request=original,status='acquired' if cost else 'cached',material_ids=[mid],new_chars=cost,new_chunks=max(0,chunks),file_metadata=info)
            cached.update(additions);available-=cost;chunk_room-=chunks
        outcomes.append((index,outcome))
    items=[x for _,x in sorted(outcomes)]
    status='complete' if all(x.status!='deferred' for x in items) else 'partial' if any(x.status!='deferred' for x in items) else 'deferred'
    receipt=ReadReceipt(id=plan_id or uid(),snapshot_id=state.snapshot.id,purpose=purpose,status=status,items=items,partial_policy='independent_ranges_with_explicit_defer' if partial else 'all_required_before_next_stage',related_ids=list(related_ids),reason=reason,original_requests=[q for q,_,_,_ in rows],allowance=allowance)
    return receipt,new_materials


def apply_read(state,receipt,new_materials):
    prior=state.read_plans.get(receipt.id)
    if prior:receipt.attempt=prior.get('attempt',1)+1
    old={m.id for m in state.materials}
    state.materials.extend(m for m in new_materials if m.id not in old)
    for item in receipt.items:
        if item.status=='acquired':state.material_allocations.append({'plan_id':receipt.id,'purpose':receipt.purpose,'new_chars':item.new_chars,'new_chunks':item.new_chunks,'reason':receipt.allowance['allocation_reason']})
    encoded=receipt.model_dump(mode='json');state.read_plans[receipt.id]=encoded
    attached=[id for item in receipt.items if item.status!='deferred' for id in item.material_ids]
    key=attachment_key(state);state.task_attachments[key]=list(dict.fromkeys(state.task_attachments.get(key,[])+attached))
    task=next((t for t in state.inquiry_tasks if t.id==state.active_inquiry_id),None)
    if task and task.unit_id:
        unit=next((u for u in state.units if u.id==task.unit_id),None)
        if unit and (task.unit_version is None or task.unit_version==unit.version):
            owner='unit:'+unit.id
            state.task_attachments[owner]=list(dict.fromkeys(state.task_attachments.get(owner,[])+attached))
    state.reading_history.append({'plan_id':receipt.id,'attempt':receipt.attempt,'related_ids':receipt.related_ids,'gap':receipt.reason,'rationale':receipt.reason,
        'requests':[q.model_dump(mode='json') for q in receipt.original_requests],'added_material_ids':[id for item in receipt.items if item.status=='acquired' for id in item.material_ids],
        'reattached_material_ids':[id for item in receipt.items if item.status=='cached' for id in item.material_ids],'unavailable':[item.model_dump(mode='json') for item in receipt.items if item.status in {'deferred','unresolved'}]})
    for item in receipt.items:
        if item.status in {'deferred','unresolved'}:state.gaps.append(item.status.title()+' read '+request_label(item.request)+': '+item.reason)
    return encoded


def execute_read(engine,requests,*,purpose='depth',partial=False,plan_id=None,related_ids=(),reason='Read material'):
    state=engine.state
    receipt,materials=plan_read(state,engine.root/'source',requests,engine.config.budget,
        purpose=purpose,partial=partial,plan_id=plan_id,related_ids=related_ids,reason=reason)
    apply_read(state,receipt,materials)
    refresh_unread(state,engine.root/'source')
    engine.checkpoint('material_receipt_saved')
    return state.read_plans[receipt.id]


def request_groups(value,path=''):
    if isinstance(value,Record):value=value.model_dump(mode='json')
    if isinstance(value,dict):
        for key,child in value.items():
            route=path+'/'+key
            if key in {'requests','reading_requests'} and isinstance(child,list) and all(isinstance(q,dict) and ({'file','start_line','end_line'}<=set(q) or 'symbol' in q or 'literal' in q) for q in child):yield route,child
            else:yield from request_groups(child,route)
    elif isinstance(value,list):
        for i,child in enumerate(value):yield from request_groups(child,path+'/'+str(i))


def validate_read_requests(state,repo,response):
    errors=[]
    for path,requests in request_groups(response):
        try:preflight(state,repo,requests,path)
        except DiagnosticError as exc:errors.extend(exc.diagnostics)
    if errors:raise DiagnosticError(errors)


def uncovered_requests(state, requests):
    """Subtract source already acquired for the current snapshot from requests."""
    current={file:digest for file,digest in state.snapshot.files.items()}
    acquired={}
    for material in state.materials:
        if current.get(material.file)==material.content_digest:
            acquired.setdefault(material.file,[]).append((material.start_line,material.end_line))
    result=[]
    for request in requests:
        if request.symbol or request.literal:
            if not any(plan['snapshot_id']==state.snapshot.id and any(item['status'] in {'acquired','cached'} and
                request_identity(item['request'])==request_identity(request) for item in plan['items'])
                for plan in state.read_plans.values()):result.append(request)
            continue
        cursor=request.start_line
        for start,end in sorted(acquired.get(request.file,[])):
            if end<cursor or start>request.end_line:continue
            if cursor<start:
                result.append(request.model_copy(update={'start_line':cursor,'end_line':min(request.end_line,start-1)}))
            cursor=max(cursor,end+1)
            if cursor>request.end_line:break
        if cursor<=request.end_line:result.append(request.model_copy(update={'start_line':cursor}))
    return result


def request_material_ids(state, requests):
    """Return current-version material identities contributing to requested ranges."""
    current=state.snapshot.files
    ids=[id for plan in state.read_plans.values() if plan['snapshot_id']==state.snapshot.id for item in plan['items']
        if item['status'] in {'acquired','cached'} and any(request_identity(item['request'])==request_identity(r) for r in requests if r.symbol or r.literal)
        for id in item['material_ids']]
    return list(dict.fromkeys(ids+[m.id for request in requests if request.start_line is not None for m in state.materials
        if m.file==request.file and m.content_digest==current.get(m.file)
        and m.start_line<=request.end_line and request.start_line<=m.end_line]))


def requests_provided(state,requests,material_ids):
    """Check actual current source coverage, not global cache availability."""
    from .sources import covered,includes
    provided=[m for m in state.materials if m.id in material_ids]
    for request in requests:
        if request.symbol or request.literal:
            ids=request_material_ids(state,[request])
            if not ids or not includes(state,ids,material_ids):return False
        elif not covered({'file':request.file,'content_digest':state.snapshot.files.get(request.file),
            'start_line':request.start_line,'end_line':request.end_line},provided):return False
    return True


def compact_index(state,repo,files=None):
    visible=state.snapshot.readable_files if state.snapshot.readable_files is not None else state.snapshot.files
    for file in visible:
        if file not in state.file_index:
            try:state.file_index[file]=metadata(repo,state.snapshot,file)[0]
            except (ValueError,OSError) as exc:state.file_index[file]={'file':file,'lines':None,'snapshot_id':state.snapshot.id,'unavailable':str(exc)}
    wanted=set(visible if files is None else files)
    return [{**info,'read_ranges':[[m.start_line,m.end_line] for m in state.materials if m.file==file]} for file,info in sorted(state.file_index.items()) if file in wanted]


def refresh_unread(state,repo):
    state.unread_ranges={}
    for info in compact_index(state,repo):
        if info['lines'] is None:continue
        covered=sorted(info['read_ranges']);cursor=1;missing=[]
        for a,b in covered:
            if cursor<a:missing.append([cursor,a-1])
            cursor=max(cursor,b+1)
        if cursor<=info['lines']:missing.append([cursor,info['lines']])
        if missing:state.unread_ranges[info['file']]=missing
    state.unexplored=list(state.unread_ranges)
