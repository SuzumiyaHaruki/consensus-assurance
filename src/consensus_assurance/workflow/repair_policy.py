"""Mechanical fixes cannot change selected questions or silently redirect code."""
from .output_repair import all_materials,parts
from .locations import declarations,contains,code_mask,locate
from consensus_assurance.core.proposals import BindingDraft
from consensus_assurance.core.types import Material


def validate_representation(before,after,targets,context):
    # Interface repairs may add an aspect but cannot erase a substantive opinion.
    if any(t['path']=='/items' or t['path'].startswith('/items/') for t in targets):
        for item in before.get('items',[]):
            if item.get('status')!='no_issue_found' or item.get('limitations'):
                semantic=lambda x:{k:v for k,v in x.items() if k not in {'target_id','aspect','source_ids'}}
                matches=[x for x in after.get('items',[]) if semantic(x)==semantic(item)]
                if not matches:raise ValueError('Interface repair must retain prior negative analysis and limitations; only diagnosed metadata may change')
        if before.get('revision')!=after.get('revision'):raise ValueError('Interface repair cannot change a semantic revision')
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
        old_decls=[d for m in materials if m.file==old_material.file for d in declarations(m) if d['symbol']==left.get('symbol')]
        verified,_=locate(BindingDraft.model_validate(right),{m.id:m for m in materials})
        new_decls=[d for m in materials if verified and m.id==verified['material_id'] for d in declarations(m) if d['symbol']==right.get('symbol') and d['start']==verified['start_line'] and d['kind']==verified['kind']]
        if not new_decls:raise ValueError('Replacement lacks a verified source declaration')
        d=new_decls[0]
        if old_decls and not any(o['start']==d['start'] for o in old_decls):raise ValueError('Location repair redirects to another function; explicit scope revision required')
        if d['kind']!='callsite' and not contains(type('Range',(),left)(),new_material,d):raise ValueError('Original behavior does not belong to the corrected identity; scope plan required')
        changed=set(range(left['start_line'],left['end_line']+1))^set(range(right['start_line'],right['end_line']+1))
        lines=code_mask(new_material.text).splitlines()
        for line in changed:
            if d['start']<=line<=d['signature_end']:continue
            pos=line-new_material.start_line
            if not 0<=pos<len(lines) or lines[pos].strip().strip('{}(),;'):
                raise ValueError('Behavior range changed beyond declaration or punctuation correction; explicit scope plan required')


def classify_conditions(state,conditions,dispositions,provided):
    """One policy for old counterevidence versus still-relevant current conditions."""
    from .sources import includes
    if len(dispositions)!=len({d.condition for d in dispositions}) or set(conditions)!={d.condition for d in dispositions}:
        raise ValueError('Each exact condition needs its own attributed disposition; unspecified conditions remain unresolved')
    for d in dispositions:
        if not d.rationale.strip() or not includes(state,d.source_ids,provided):raise ValueError('Condition disposition lacks supplied source evidence')
    return dispositions


def split_draft_bindings(candidate,patch,diagnostics,context,accepted_ids):
    """Split an unaccepted representation, preserving all meaningful lines and roles.

    Existing semantic objects, normative judgments and checked obligations are never
    rewritten here. Full graph/scope validation follows this pure transformation.
    """
    import copy
    from .output_repair import parts
    from .associations import claim_ids
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
            if collection=='units' and (a.get('audit_question') or {}).get('question')!=(b.get('audit_question') or {}).get('question'):
                raise ValueError('Draft plan changes the audit question')
