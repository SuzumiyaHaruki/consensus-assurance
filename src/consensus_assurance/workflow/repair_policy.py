"""Mechanical fixes cannot change selected questions or silently redirect code."""
from .output_repair import all_materials,parts
from .locations import declarations,contains,code_mask,locate,location_evidence,matches_symbol
from consensus_assurance.core.proposals import BindingDraft
from consensus_assurance.core.types import Material


def validate_representation(before,after,targets,context):
    # Interface repairs may add an aspect but cannot erase a substantive opinion.
    if any(t['path']=='/items' or t['path'].startswith('/items/') for t in targets):
        for item in before.get('items',[]):
            if item.get('status')!='no_issue_found' or item.get('limitations') or item.get('counterevidence'):
                semantic=lambda x:{k:x.get(k) for k in ('status','rationale','counterevidence','limitations')}
                matches=[x for x in after.get('items',[]) if semantic(x)==semantic(item)]
                if not matches:raise ValueError('Interface repair must retain prior negative analysis and limitations; only diagnosed metadata may change')
        if before.get('revision')!=after.get('revision'):raise ValueError('Interface repair cannot change a semantic revision')
    # Citation repair cannot silently discard an asserted evidence dependency.
    for target in targets:
        route=parts(target['path'])
        if route[-1] not in {'source_ids','expectation_ids'} and route[-2:]!=['grounding','behavior_ids']:continue
        left=before;right=after
        for key in route:
            left=left[int(key)] if isinstance(left,list) else left[key]
            right=right[int(key)] if isinstance(right,list) else right[key]
        from .sources import covered
        available={m['id']:m for m in all_materials(context)}
        supplied=[available[id] for id in right if id in available]
        for id in set(left)-set(right):
            import re
            if target.get('grounding_reference_repair') and id not in available and not re.fullmatch(r'.+:\d+:\d+',id) and supplied:continue
            if id in target.get('citation_aliases',{}) and set(right)&set(target['citation_aliases'][id]):continue
            if id not in available or not covered(available[id],supplied):
                raise ValueError('Citation repair cannot discard evidence; acquire the missing range or request an explicit semantic decision')
    roots={}
    for target in targets:
        route=parts(target['path'])
        if 'bindings' in route:
            i=route.index('bindings');roots[tuple(route[:i+2])]=True
    materials=[Material.model_validate(m) for m in all_materials(context)]
    for route in roots:
        left=before;right=after
        for key in route:
            left=left[int(key)] if isinstance(left,list) else left[key]
            right=right[int(key)] if isinstance(right,list) else right[key]
        if all(left.get(key)==right.get(key) for key in ['symbol','start_line','end_line','material_id','anchor']):continue
        old_material=next((m for m in materials if m.id==left.get('material_id')),None)
        new_material=next((m for m in materials if m.id==right.get('material_id')),None)
        if not old_material or not new_material or old_material.file!=new_material.file:raise ValueError('Location repair needs actually supplied material from the same intended file')
        from .sources import source_views
        old_decls=[d for m,_ in source_views(materials) if m.file==old_material.file and m.content_digest==old_material.content_digest for d in declarations(m) if matches_symbol(d,left.get('symbol'))]
        evidence,_=location_evidence(BindingDraft.model_validate(right),{m.id:m for m in materials})
        if not evidence:raise ValueError('Replacement does not establish both declaration identity and behavior containment; an anchor-only edit cannot repair a cross-declaration behavior range')
        d=evidence['declaration'];new_material=evidence['view']
        if old_decls and not any(o['start']==d['start'] for o in old_decls):raise ValueError('Location repair redirects to another function; explicit scope revision required')
        if d['kind']!='callsite' and not contains(type('Range',(),left)(),new_material,d):raise ValueError('Original behavior does not belong to the corrected identity; scope plan required')
        changed=set(range(left['start_line'],left['end_line']+1))^set(range(right['start_line'],right['end_line']+1))
        lines=code_mask(new_material.text).splitlines()
        for line in changed:
            if d['start']<=line<=d['signature_end']:continue
            pos=line-new_material.start_line
            if not 0<=pos<len(lines) or lines[pos].strip().strip('{}(),;'):
                raise ValueError('Behavior range changed beyond declaration or punctuation correction; explicit scope plan required')


def condition_records(conditions,owner,source_ids=(),target_id=None,version=None):
    return [{'id':owner+'/condition/'+str(n+1),'text':text,'target_id':target_id,'version':version,'source_ids':list(source_ids)} for n,text in enumerate(dict.fromkeys(conditions))]


def classify_conditions(state,conditions,dispositions,provided,*,records=None,paths=None,object_ids=()):
    """One exact condition policy; IDs identify opinions, never make them true."""
    from .sources import includes
    from consensus_assurance.core.diagnostics import Diagnostic,DiagnosticError
    records=records or condition_records(conditions,'legacy',provided)
    expected={r['id']:r for r in records};by_text={r['text']:r['id'] for r in records}
    actual=[d.condition_id if d.condition_id else by_text.get(d.condition,'unknown:'+d.condition) for d in dispositions]
    missing=sorted(set(expected)-set(actual));extra=sorted(set(actual)-set(expected));duplicates=sorted({id for id in actual if actual.count(id)>1})
    if missing or extra or duplicates:
        code='condition_duplicate' if duplicates else 'condition_extra' if extra else 'condition_missing'
        raise DiagnosticError([Diagnostic(code=code,category='format',object_ids=list(object_ids),paths=paths or ['/condition_dispositions'],
            material_ids=list(provided),message='Condition dispositions do not match the current candidate conditions',allowed=['representation'],
            details={'expected_conditions':records,'current_dispositions':[d.model_dump(mode='json') for d in dispositions],
                'missing':missing,'extra':extra,'duplicate':duplicates,'required_action':'Correct only these condition references and supply attributed dispositions. Do not erase negative analysis or read source merely to copy an ID.'})])
    for d,id in zip(dispositions,actual):
        if d.condition and d.condition!=expected[id]['text']:raise ValueError('Condition ID and text disagree')
        if not d.rationale.strip() or not includes(state,d.source_ids,provided):raise ValueError('Condition disposition lacks supplied source evidence')
    return dispositions


def split_draft_bindings(candidate,patch,diagnostics,context,accepted_ids):
    """Split an unaccepted representation, preserving all meaningful lines and roles.

    Existing semantic objects, normative judgments and checked obligations are never
    rewritten here. Full graph/scope validation follows this pure transformation.
    """
    import copy
    from .output_repair import parts
    result=copy.deepcopy(candidate)
    materials={m['id']:Material.model_validate(m) for m in all_materials(context)}
    diagnosed={id for d in diagnostics if d.code=='declaration_identity' for id in d.object_ids}
    if len({s.path for s in patch.binding_splits})!=len(patch.binding_splits):raise ValueError('Duplicate split target')
    for split in patch.binding_splits:
        route=parts(split.path)
        if len(route)<2 or route[-2]!='bindings':raise ValueError('Split must address a diagnosed binding draft')
        parent=result;original_parent=candidate
        try:
            for key in route[:-2]:parent=parent[key];original_parent=original_parent[key]
            position=int(route[-1])
            if position<0 or position>=len(original_parent['bindings']):raise ValueError('Split pointer is outside the candidate')
            old=original_parent['bindings'][position]
            index=next(i for i,b in enumerate(parent['bindings']) if b['id']==old['id'])
        except (KeyError,TypeError,IndexError,StopIteration) as exc:
            raise ValueError('Split pointer does not identify a current binding draft') from exc
        if old['id'] not in diagnosed or old['id'] in accepted_ids:raise ValueError('Only diagnosed unaccepted bindings may be split')
        drafts=[BindingDraft.model_validate(b) for b in split.bindings]
        if len({b.id for b in drafts})!=len(drafts):raise ValueError('Split identities must be distinct')
        old_draft=BindingDraft.model_validate(old);m=materials.get(old_draft.material_id)
        if m is None:raise ValueError('Split requires the original supplied range')
        def significant(a,b):
            return {i for i,line in enumerate(code_mask(m.text).splitlines(),m.start_line) if a<=i<=b and line.strip()}
        original=significant(old_draft.start_line,old_draft.end_line);covered=set()
        for b in drafts:
            source=materials.get(b.material_id)
            if source is None or source.file!=m.file or source.content_digest!=m.content_digest:raise ValueError('Split source identity changed')
            if b.associations!=old_draft.associations or b.description!=old_draft.description or b.pending!=old_draft.pending:raise ValueError('Split cannot reinterpret responsibility, behavior or pending conditions')
            anchor,reason=locate(b,materials)
            if not anchor:raise ValueError('Split declaration is not verified: '+reason)
            covered.update(significant(b.start_line,b.end_line))
            if b.start_line<m.start_line or b.end_line>m.end_line:raise ValueError('Split cannot add unread behavior')
        if covered!=original:raise ValueError('Split lost or added meaningful behavior; explicit scope change required')
        if any(r.get('source')==old['id'] or r.get('target')==old['id'] for r in parent.get('relations',[])):raise ValueError('Physical relation endpoints need an explicit joint scope plan')
        parent['bindings'][index:index+1]=[b.model_dump(mode='json') for b in drafts]
        for unit in parent.get('units',[]):
            unit['binding_ids']=[id for x in unit['binding_ids'] for id in ([b.id for b in drafts] if x==old['id'] else [x])]
            unit['code_uses']=[{**use,'binding_id':b.id} for use in unit.get('code_uses',[]) for b in (drafts if use['binding_id']==old['id'] else [type('Identity',(),{'id':use['binding_id']})()])]
    return result


def validate_draft_plan(before,after):
    """Permit explicit unaccepted code/scope proposals, never normative weakening."""
    if before.get('claims',[])!=after.get('claims',[]) or before.get('relations',[])!=after.get('relations',[]):
        raise ValueError('Draft plan cannot reinterpret claims or dependency meaning; use semantic investigation')
    for collection in ('bindings','units'):
        old={x['id']:x for x in before.get(collection,[])};new={x['id']:x for x in after.get(collection,[])}
        if not set(old)<=set(new):raise ValueError('Draft plan cannot drop paths; use a source-preserving split or explicit investigation')
        for id,a in old.items():
            b=new[id]
            fields=('associations','pending') if collection=='bindings' else ('goal_ids','obligation_ids','scope')
            if any(a.get(k)!=b.get(k) for k in fields):raise ValueError('Draft plan changes responsibility or fault scope')
            from .audit_spec import IDENTITY
            if collection=='units' and any((a.get('audit_question') or {}).get(k)!=(b.get('audit_question') or {}).get(k) for k in IDENTITY):
                raise ValueError('Draft plan changes the audit question')
