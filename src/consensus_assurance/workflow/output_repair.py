"""Bounded field replacement preserves the complete local object outside reported failures."""
import copy
import json
import re
from pydantic import Field
from consensus_assurance.core.types import Record


class Replacement(Record):
    path: str = Field(description='One exact JSON pointer from repair_targets')
    value_json: str = Field(description='JSON encoding of the replacement value, not a whole new response')


class OutputRepair(Record):
    replacements: list[Replacement] = Field(min_length=1, max_length=24)
    rationale: str


def pointer(parts):
    return '/' + '/'.join(str(p).replace('~','~0').replace('/','~1') for p in parts)


def parts(path):
    if not path.startswith('/') or path == '/': raise ValueError('Repair cannot replace the response root')
    return [x.replace('~1','/').replace('~0','~') for x in path[1:].split('/')]


def repair_targets(value, errors, reason, limit):
    paths = []
    for error in errors:
        current, route = value, []
        for key in error.get('loc',[]):
            if isinstance(current,dict) and key in current:
                route.append(key); current=current[key]
            elif isinstance(current,list) and isinstance(key,int) and 0 <= key < len(current):
                route.append(key); current=current[key]
            elif isinstance(current,dict) and error.get('type')=='missing':
                route.append(key); break
            else: break
        if route: paths.append(route)
    match = re.search(r'Binding ([\w-]+): literal symbol',reason)
    if match and isinstance(value,dict):
        for i,b in enumerate(value.get('bindings',[])):
            if b.get('id')==match[1]: paths.append(['bindings',i,'symbol'])
    if not paths and isinstance(value,dict):
        prefix=['bundle'] if isinstance(value.get('bundle'),dict) else []
        model=value.get('bundle',value)
        if isinstance(model,dict):
            if any(x in reason for x in ['Behavior module','TLA module','module feature','module dependency']): paths.append(prefix+['behavior'])
            elif 'Checker declaration missing' in reason: paths.append(prefix+['properties'])
            elif 'Harness kind' in reason: paths.append(prefix+['harness','kind'])
            elif any(x in reason for x in ['Checker claims','Model must check','invariant-to-claim','Duplicate invariant']): paths.append(prefix+['checkers'])
            elif 'constraint cites' in reason or 'transition constraint' in reason: paths.append(prefix+['constraints'])
            elif 'Only constant assignments' in reason: paths.append(prefix+['constants'])
            elif 'Feedback target' in reason: paths.append(['target_ids'])
            elif 'Semantic feedback requires' in reason: paths.append(['evidence_ids'])
    targets=[]
    for route in paths:
        path=pointer(route)
        if any(t['path']==path for t in targets): continue
        current=value; exists=True
        for key in route:
            try: current=current[key]
            except (KeyError,IndexError,TypeError): exists=False;current=None;break
        targets.append({'path':path,'exists':exists,'current_value':current})
    if not targets:
        raise ValueError('Cannot localize the invalid fields for bounded repair; original output preserved: '+reason)
    if len(json.dumps(targets,ensure_ascii=False)) > limit:
        raise ValueError('Invalid field exceeds repair context budget; no truncated object or invented continuation was sent')
    return targets


def apply_replacements(value, targets, repair):
    allowed={t['path'] for t in targets}
    paths=[r.path for r in repair.replacements]
    if len(set(paths))!=len(paths) or not set(paths)<=allowed:
        raise ValueError('Repair touches duplicate or unreported fields')
    result=copy.deepcopy(value)
    for replacement in repair.replacements:
        route=parts(replacement.path); parent=result
        for key in route[:-1]: parent=parent[int(key)] if isinstance(parent,list) else parent[key]
        key=int(route[-1]) if isinstance(parent,list) else route[-1]
        parent[key]=json.loads(replacement.value_json)
    return result


def repair_context(original, targets, context, limit):
    """Include located object context and complete relevant snippets, never a cut JSON prefix."""
    objects=[]; wanted=set()
    for target in targets:
        route=parts(target['path'])
        if len(route)>=2 and route[0] in {'claims','bindings','relations','units'}:
            obj=original[route[0]][int(route[1])]
            if obj not in objects: objects.append(obj)
            if obj.get('material_id'):wanted.add(obj['material_id'])
            wanted.update(obj.get('source_ids',[]))
    available=context.get('materials',[])
    selected=[]; omitted=[]
    for material in available:
        if wanted and material['id'] not in wanted: continue
        if len(json.dumps({'objects':objects,'materials':selected+[material]},ensure_ascii=False))<=limit:
            selected.append(material)
        else: omitted.append(material['id'])
    result={'objects':objects,'materials':selected,'omitted_material_ids':omitted,
        'source_limit':'Omitted snippets are not available; do not infer their contents'}
    if len(json.dumps(result,ensure_ascii=False))>limit:
        result={'objects':[], 'materials':[], 'omitted_material_ids':list(wanted),
            'source_limit':'Related objects exceed the context budget; only the reported fields are supplied'}
    return result
