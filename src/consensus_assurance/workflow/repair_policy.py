"""Mechanical fixes cannot change selected questions or silently redirect code."""
from .output_repair import all_materials,parts
from .locations import declarations,contains,code_mask,locate
from consensus_assurance.core.proposals import BindingDraft
from consensus_assurance.core.types import Material


def validate_representation(before,after,targets,context):
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
