"""Limited source-backed Python/Go declaration index, never protocol-driven correction."""
import ast
import re


def code_mask(text):
    pattern=r'//[^\n]*|/\*[\s\S]*?\*/|\#[^\n]*|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|`[^`]*`'
    return re.sub(pattern,lambda m:''.join('\n' if c=='\n' else ' ' for c in m[0]),text)


def closing(text,start,left,right):
    depth=1;cursor=start+1
    while cursor<len(text) and depth:
        depth+=(text[cursor]==left)-(text[cursor]==right);cursor+=1
    return cursor


def declarations(material):
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
                end_args=closing(masked,match.end()-1,'(',')');opening=masked.find('{',end_args)
                # Anonymous return types contain braces before the function body.
                cursor=end_args
                while opening>=0 and re.search(r'\b(?:interface|struct)\s*$',masked[cursor:opening]):
                    cursor=closing(masked,opening,'{','}');opening=masked.find('{',cursor)
                if opening<0:continue
                end=closing(masked,opening,'{','}')
                result.append({'symbol':match[1],'start':line(match.start()+len(match[0])-len(match[0].lstrip())),'signature_end':line(opening),'end':line(end),'kind':'declaration'})
        for match in re.finditer(r'(?m)^\s*type\s+(\w+)\s+(interface|struct)\s*\{',masked):
            opening=match.end()-1;end=closing(masked,opening,'{','}');start=line(match.start()+len(match[0])-len(match[0].lstrip()))
            result.append({'symbol':match[1],'start':start,'signature_end':line(opening),'end':line(end),'kind':'declaration'})
            if match[2]=='interface':
                for method in re.finditer(r'(?m)^\s*(\w+)\s*\(',masked[opening+1:end-1]):
                    pos=opening+1+method.start()+len(method[0])-len(method[0].lstrip())
                    result.append({'symbol':method[1],'start':line(pos),'signature_end':line(pos),'end':line(end),'owner_start':start,'kind':'interface_member'})
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
                end_line=method['end']
                cursor=sum(len(x)+1 for x in masked.split('\n')[:end_line-offset])
            result.append({'symbol':name,'start':start,'signature_end':line(match.end()),'end':end_line,'kind':'declaration'})
        # Call-site anchors record syntax only, not resolved callee behavior.
        for match in re.finditer(r'\b(\w+)\s*\(',masked):
            if any(d['start']==line(match.start()) and d['symbol']==match[1] for d in result):continue
            end=closing(masked,match.end()-1,'(',')')
            result.append({'symbol':match[1],'start':line(match.start()),'signature_end':line(match.start()),'end':line(end),'kind':'callsite'})
    return result


def contains(binding,material,declaration):
    start=declaration.get('owner_start',declaration['start']);end=declaration['end']
    lines=code_mask(material.text).splitlines()
    def empty(a,b):return not ''.join(lines[max(0,a-material.start_line):max(0,b-material.start_line+1)]).strip()
    if binding.start_line<start and not empty(binding.start_line,start-1):return False
    if binding.end_line>end and not empty(end+1,binding.end_line):return False
    return binding.end_line>=start and binding.start_line<=end


def locate(binding,materials):
    material=materials.get(binding.material_id)
    if material is None:return None,'The behavior material has not been read'
    candidates=[]
    for m in materials.values():
        if m.file!=material.file or m.content_digest!=material.content_digest:continue
        if m.start_line>binding.start_line or m.end_line<binding.end_line:continue
        for d in declarations(m):
            if d['symbol']!=binding.symbol:continue
            if d['kind']=='callsite' and (not binding.anchor or binding.anchor.kind!='callsite'):continue
            contained=contains(binding,m,d)
            if d['kind']=='callsite':
                contained=binding.start_line<=d['start']<=d['end']<=binding.end_line and any(owner['kind']=='declaration' and owner['symbol']!=d['symbol'] and contains(binding,m,owner) for owner in declarations(m))
            if contained:candidates.append((m,d))
    if binding.anchor:
        a=binding.anchor
        candidates=[(m,d) for m,d in candidates if m.id==a.material_id and d['start']==a.start_line and d['signature_end']<=a.end_line<=d['end'] and a.symbol==binding.symbol and a.kind==d['kind']]
    unique={(d['symbol'],d['start'],d['end'],d['kind']):(m,d) for m,d in candidates}
    if len(unique)!=1:return None,'Declaration identity is missing, ambiguous, or does not contain the behavior range; read the declaration or propose an explicit location correction'
    m,d=next(iter(unique.values()))
    return {'material_id':m.id,'start_line':d['start'],'end_line':d['signature_end'],'symbol':d['symbol'],'kind':d['kind']},''
