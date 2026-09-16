"""Bounded field replacement preserves the complete local object outside reported failures."""
import copy
import json
import re
from pydantic import Field
from consensus_assurance.core.types import ReadRequest
from consensus_assurance.core.types import Record
from consensus_assurance.core.proposals import BindingDraft,GraphPatch


class Replacement(Record):
    path: str = Field(description='One exact JSON pointer from repair_targets')
    value_json: str = Field(description='JSON encoding of the replacement value, not a whole new response')


class BindingSplit(Record):
    path: str = Field(description="JSON pointer to one diagnosed, unaccepted binding")
    bindings: list[BindingDraft] = Field(min_length=2,max_length=8,description="Complete replacement BindingDraft objects, each anchored in supplied code; preserve the entire original behavior range and associations")
    rationale: str = Field(min_length=1)


class OutputRepair(Record):
    draft_patch: GraphPatch | None = Field(default=None, description="Explicit alternative scope/location proposal for a graph_patch draft; preserve existing claims, relations, checked obligations and fault scope. This is not a mechanical field replacement and is fully revalidated.")
    binding_splits: list[BindingSplit] = Field(default_factory=list,max_length=4)
    replacements: list[Replacement] = Field(default_factory=list, max_length=24)
    requests: list[ReadRequest] = Field(default_factory=list,max_length=12)
    change_request: str = ""
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
        if isinstance(parent,list) and route[-1]=='-':
            parent.append(json.loads(replacement.value_json))
        else:
            key=int(route[-1]) if isinstance(parent,list) else route[-1]
            parent[key]=json.loads(replacement.value_json)
    return result


def diagnostic_targets(value,diagnostics,limit):
    """Resolve typed paths, including graph drafts nested in feedback and build replies."""
    def prefix_for(node,d):
        if isinstance(node,dict):
            for name in ('bindings','units','claims','relations'):
                if any(isinstance(x,dict) and x.get('id') in d.object_ids for x in node.get(name,[]) if isinstance(node.get(name),list)):
                    return []
            for key,child in node.items():
                found=prefix_for(child,d)
                if found is not None:return [key]+found
        return None
    result=[]
    for diagnostic in diagnostics:
        prefix=prefix_for(value,diagnostic) or []
        for path in diagnostic.paths:
            relative=parts(path)
            if len(relative)>=2 and relative[0] in {'bindings','units','claims','relations'}:
                node=value
                for key in prefix:node=node[key]
                matches=[i for i,obj in enumerate(node.get(relative[0],[])) if obj.get('id') in diagnostic.object_ids]
                if not matches:continue
                relative[1]=str(matches[0])
            route=prefix+relative;current=value;exists=True
            for key in route:
                try:current=current[int(key)] if isinstance(current,list) else current[key]
                except (ValueError,KeyError,IndexError,TypeError):exists=False;current=None;break
            item={'path':pointer(route),'exists':exists,'current_value':current}
            if item not in result:result.append(item)
    if len(json.dumps(result,ensure_ascii=False))>limit:raise ValueError('Repair target set exceeds bounded context; preserve candidate and request smaller scope')
    return result


from .sources import all_materials


def diagnostic_context(candidate,diagnostics,context,limit):
    """Follow explicit referenced objects; never arbitrary graph connectedness."""
    ids={id for d in diagnostics for id in d.object_ids};wanted={id for d in diagnostics for id in d.material_ids};objects=[];index={}
    def collect(node):
        if isinstance(node,dict):
            if isinstance(node.get('id'),str):index[node['id']]=node
            for value in node.values():collect(value)
        elif isinstance(node,list):
            for value in node:collect(value)
    collect(context)
    collect(candidate)
    from .sources import dependency_closure
    sources,visited=dependency_closure(index,ids);wanted.update(sources)
    objects=[index[id] for id in sorted(visited)]
    # Current explicit requests take precedence over a large historical object closure.
    explicit=list(dict.fromkeys(context.get('repair_requested_material_ids',[])))
    available={m['id']:m for m in all_materials(context)}
    wanted.update(explicit)
    direct=[o for o in objects if o.get('id') in ids]
    objects=direct
    selected=[];omitted=[]
    priority=list(dict.fromkeys(explicit+[id for d in diagnostics for id in d.material_ids]+sorted(wanted)))
    for id in priority:
        material=available.get(id)
        if material is None:omitted.append(id);continue
        if len(json.dumps({'objects':objects,'materials':selected+[material]},ensure_ascii=False))<=limit:selected.append(material)
        else:omitted.append(id)
    if len(json.dumps(objects,ensure_ascii=False))>limit:objects=[]
    return {'objects':objects,'materials':selected,'omitted_material_ids':sorted(set(omitted)),
        'required_material_ids':explicit,'required_materials_missing':[id for id in explicit if id not in {m['id'] for m in selected}],
        'source_limit':'Omitted material is not available. Previously recorded analysis is evidence history, not a substitute for newly requested source.'}


def save_session(engine,session):
    from consensus_assurance.adapters.storage.files import write_json
    engine.state.pending_output_repair=session
    engine.state.repair_sessions[session['id']]=session
    write_json(engine.root/'repair-sessions'/session['id']/'session.json',session)
    engine.checkpoint('output_repair_pending')
