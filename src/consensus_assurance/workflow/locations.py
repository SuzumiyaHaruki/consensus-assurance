"""Limited source-backed Python/Go declaration index, never protocol-driven correction."""
import ast
import re


def code_mask(text):
    pattern=r'//[^\n]*|/\*[\s\S]*?(?:\*/|$)|\#[^\n]*|"(?:\\.|[^"\\])*(?:"|$)|\x27(?:\\.|[^\x27\\])*(?:\x27|$)|`[^`]*(?:`|$)'
    return re.sub(pattern,lambda m:''.join('\n' if c=='\n' else ' ' for c in m[0]),text)


def closing(text,start,left,right):
    depth=1;cursor=start+1
    while cursor<len(text) and depth:
        depth+=(text[cursor]==left)-(text[cursor]==right);cursor+=1
    return cursor if depth==0 else None


def extent(declaration):
    return declaration["end"] if declaration["end"] is not None else declaration["known_end"]


def declarations(material, include_calls=True):
    text=material.text;offset=material.start_line-1;result=[]
    if material.file.endswith('.py'):
        try:tree=ast.parse(text)
        except SyntaxError:return []
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                result.append({'symbol':node.name,'start':offset+node.lineno,'signature_end':max(offset+node.lineno,offset+(node.body[0].lineno-1 if node.body else node.lineno)),'end':offset+node.end_lineno,'kind':'declaration'})
    elif material.file.endswith('.go'):
        masked=code_mask(text)
        line=lambda pos:masked.count('\n',0,pos)+offset+1
        patterns=[r'(?m)^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(',r'(?m)^\s*(\w+)\s*:=\s*func\s*\(']
        for pattern in patterns:
            for match in re.finditer(pattern,masked):
                end_args=closing(masked,match.end()-1,'(',')')
                if end_args is None:continue
                opening=masked.find('{',end_args)
                # Anonymous return types contain braces before the function body.
                cursor=end_args
                while opening>=0 and re.search(r'\b(?:interface|struct)\s*$',masked[cursor:opening]):
                    cursor=closing(masked,opening,'{','}')
                    if cursor is None:opening=-1;break
                    opening=masked.find('{',cursor)
                if opening<0:continue
                end=closing(masked,opening,'{','}')
                receiver=re.match(r'\s*func\s+\(\s*(?:\w+\s+)?\*?(\w+)(?:\[[^]]+\])?\s*\)',match[0])
                result.append({'owner':receiver[1] if receiver else None,'symbol':match[1],'start':line(match.start()+len(match[0])-len(match[0].lstrip())),'signature_end':line(opening),'end':line(end) if end is not None else None,'known_end':material.end_line,'closed':end is not None,'kind':'declaration'})
        for match in re.finditer(r'(?m)^\s*type\s+(\w+)\s+(interface|struct)\s*\{',masked):
            opening=match.end()-1;end=closing(masked,opening,'{','}');start=line(match.start()+len(match[0])-len(match[0].lstrip()))
            result.append({'symbol':match[1],'start':start,'signature_end':line(opening),'end':line(end) if end is not None else None,'known_end':material.end_line,'closed':end is not None,'kind':'declaration'})
            if match[2]=='interface':
                for method in re.finditer(r'(?m)^\s*(\w+)\s*\(',masked[opening+1:(end-1 if end else len(masked))]):
                    pos=opening+1+method.start()+len(method[0])-len(method[0].lstrip())
                    result.append({'symbol':method[1],'start':line(pos),'signature_end':line(pos),'end':line(end) if end else None,'known_end':material.end_line,'closed':end is not None,'owner_start':start,'owner':match[1],'kind':'interface_member'})
        # A named non-struct type may be followed by contiguous methods on that exact receiver.
        for match in re.finditer(r'(?m)^[ \t]*type[ \t]+(\w+)[ \t]+([^\n]+)',masked):
            if re.match(r'(?:struct|interface)\b',match[2]):continue
            name=match[1];start=line(match.start());end_line=line(match.end())
            cursor=match.end()
            while cursor<len(masked):
                following=re.match(r'\s*func\s*\(\s*\w+\s+\*?'+re.escape(name)+r'\s*\)\s*(\w+)\s*\(',masked[cursor:])
                if not following:break
                method_start=line(cursor+following.start()+len(following[0])-len(following[0].lstrip()))
                method=next((d for d in result if d['symbol']==following[1] and d['start']==method_start and d['kind']=='declaration'),None)
                if not method:break
                if method['end'] is None:break
                end_line=method['end']
                cursor=sum(len(x)+1 for x in masked.split('\n')[:end_line-offset])
            result.append({'symbol':name,'start':start,'signature_end':line(match.end()),'end':end_line,'kind':'declaration'})
        # Constants are source identities too; a named member anchors its whole
        # declaration group, not neighboring type declarations.
        for match in re.finditer(r'(?m)^[ \t]*const[ \t]*\(',masked):
            end=closing(masked,match.end()-1,'(',')')
            for member in re.finditer(r'(?m)^[ \t]*(\w+)[ \t]*(?:\w+[ \t]*)?(?:=|$)',masked[match.end():(end-1 if end else len(masked))]):
                pos=match.end()+member.start()+len(member[0])-len(member[0].lstrip())
                result.append({'symbol':member[1],'start':line(pos),'signature_end':line(pos),'end':line(end) if end else None,'known_end':material.end_line,'closed':end is not None,'owner_start':line(match.start()),'kind':'declaration'})
        # Call-site anchors record syntax only, not resolved callee behavior.
        if include_calls:
            for match in re.finditer(r'\b(\w+)\s*\(',masked):
                if any(d['start']==line(match.start()) and d['symbol']==match[1] for d in result):continue
                end=closing(masked,match.end()-1,'(',')')
                if end is not None:result.append({'symbol':match[1],'start':line(match.start()),'signature_end':line(match.start()),'end':line(end),'closed':True,'kind':'callsite'})
    return result


def matches_symbol(declaration, symbol):
    return symbol == declaration["symbol"] or (declaration.get("owner") is not None
        and symbol == declaration["owner"] + "." + declaration["symbol"])


def contains(binding,material,declaration):
    start=declaration.get('owner_start',declaration['start']);end=extent(declaration)
    lines=code_mask(material.text).splitlines()
    def empty(a,b):return not ''.join(lines[max(0,a-material.start_line):max(0,b-material.start_line+1)]).strip()
    if binding.start_line<start and not empty(binding.start_line,start-1):return False
    if binding.end_line>end and not empty(end+1,binding.end_line):return False
    return binding.end_line>=start and binding.start_line<=end


def location_evidence(binding,materials):
    from .sources import source_views
    material=materials.get(binding.material_id)
    if material is None:return None,'The behavior material has not been read'
    candidates=[]
    anchor_material=materials.get(binding.anchor.material_id) if binding.anchor else None
    if binding.anchor and (anchor_material is None or anchor_material.file!=material.file or anchor_material.content_digest!=material.content_digest):
        return None,'Anchor source is missing or belongs to a different file/version'
    for view,contributors in source_views(materials.values()):
        if view.file!=material.file or view.content_digest!=material.content_digest:continue
        if not view.start_line<=binding.start_line<=binding.end_line<=view.end_line:continue
        declarations_here=declarations(view)
        for d in declarations_here:
            if not matches_symbol(d,binding.symbol):continue
            if d['kind']=='callsite' and (not binding.anchor or binding.anchor.kind!='callsite'):continue
            if not contains(binding,view,d):continue
            if d['kind']=='callsite' and not any(o['kind']=='declaration' and o['symbol']!=d['symbol'] and contains(binding,view,o) for o in declarations_here):continue
            if binding.anchor:
                a=binding.anchor
                if not (a.start_line==d['start'] and d['signature_end']<=a.end_line<=extent(d) and a.symbol==binding.symbol and a.kind==d['kind']):continue
                if not anchor_material.start_line<=d['start']<=anchor_material.end_line:continue
            declaration_source=anchor_material or next((m for m in contributors if m.start_line<=d['start']<=m.end_line),None)
            if declaration_source is None:continue
            used=[m.id for m in contributors if m.start_line<=max(binding.end_line,d['signature_end']) and m.end_line>=min(d['start'],binding.start_line)]
            anchor={'material_id':declaration_source.id,'start_line':d['start'],'end_line':d['signature_end'],'symbol':binding.symbol,'kind':d['kind'],
                    'source_ids':sorted(used),'boundary_complete':d.get('closed',True)}
            candidates.append({'anchor':anchor,'declaration':d,'view':view})
    identities={(x['declaration']['start'],x['declaration']['kind'],x['anchor']['material_id']):x for x in candidates}
    if len(identities)!=1:return None,'Declaration identity is missing, ambiguous, or not proven by contiguous acquired source; verify the anchor line or read the missing interval'
    return next(iter(identities.values())),''


def locate(binding,materials):
    evidence,error=location_evidence(binding,materials)
    return (evidence['anchor'] if evidence else None),error


def location_context(binding, materials):
    """Explain candidates from the same contiguous source views used for acceptance."""
    from .sources import source_views
    m=materials.get(binding.material_id)
    if m is None:return {'candidates':[], 'read_ranges':[]}
    views=[(v,refs) for v,refs in source_views(materials.values()) if v.file==m.file and v.content_digest==m.content_digest]
    candidates=[];sources=[]
    for view,refs in views:
        matches=[d for d in declarations(view) if matches_symbol(d,binding.symbol) and d['kind']!='callsite']
        for d in matches:
            candidates.append({**d,'contains_behavior':contains(binding,view,d)})
            sources.extend(r.id for r in refs if r.start_line<=max(d['signature_end'],binding.end_line) and r.end_line>=min(d['start'],binding.start_line))
    return {'candidates':candidates, 'read_ranges':[[v.start_line,v.end_line] for v,_ in views],
            'material_ids':sorted(set(sources+[m.id])), 'file':m.file,'content_digest':m.content_digest,
            'requested_anchor':binding.anchor.model_dump(mode='json') if binding.anchor else None,
            'behavior_range':[binding.start_line,binding.end_line],
            'next_action':'Correct an anchored offset only with supplied declaration evidence; request any missing contiguous interval. Open prefix does not establish a complete function end.'}


def declaration_index(materials):
    """Index only supplied contiguous source; offsets are navigation, not semantics."""
    from .sources import source_views
    result=[]
    for view,refs in source_views(materials):
        entries=[{'symbol':(d['owner']+'.' if d.get('owner') else '')+d['symbol'],
                  'kind':d['kind'],'start_line':d['start'],'signature_end':d['signature_end'],
                  'end_line':d['end'],'known_end':extent(d),'boundary_complete':d.get('closed',True)}
                 for d in declarations(view) if d['kind']!='callsite']
        if entries:result.append({'file':view.file,'material_ids':[m.id for m in refs],'declarations':entries})
    return result
