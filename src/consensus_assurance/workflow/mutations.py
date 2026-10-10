"""Actual semantic write sets and atomic in-memory adoption."""
import json
from consensus_assurance.core.types import Record

COLLECTIONS=('claims','bindings','relations','units')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def adopt(state, trial):
    for name in type(state).model_fields:
        old,new=getattr(state,name),getattr(trial,name)
        if isinstance(old,list) and isinstance(new,list):
            by_id={getattr(x,'id',None):x for x in old if isinstance(x,Record) and hasattr(x,'id')}
            new=[by_id[x.id] if isinstance(x,Record) and hasattr(x,'id') and x.id in by_id and by_id[x.id]==x else x for x in new]
        state.__dict__[name]=new


def write_set(state,patch):
    current={obj.id:(name,obj) for name in COLLECTIONS for obj in getattr(state,name)}
    writes={}; seen=set()
    for name in COLLECTIONS:
        for new in getattr(patch,name):
            if new.id in seen:raise ValueError('Duplicate or cross-type patch ID')
            seen.add(new.id)
            if any(new.id==x.id for x in [*state.evidence,*state.semantic_reviews]):raise ValueError('ID cannot be reused across object types: '+new.id)
            if new.id not in current:continue
            collection,old=current[new.id]
            if collection!=name:raise ValueError('ID cannot be reused across object types: '+new.id)
            old_data=old.model_dump(mode='json')
            new_data=new.model_dump(mode='json')
            if name=='bindings':
                material=next((m for m in state.materials if m.file==old.file and m.start_line<=old.start_line<=old.end_line<=m.end_line),None)
                old_data['material_id']=old_data.get('material_id') or (material.id if material else None)
            for field,value in new_data.items():
                if field=='id':continue
                if canonical(old_data.get(field))!=canonical(value):
                    writes[(new.id,field)]=(old_data.get(field),value)
    return writes
