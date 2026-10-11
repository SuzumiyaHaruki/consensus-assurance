"""Physical source coverage for verified source anchors.

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
