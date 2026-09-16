"""Replay the explicitly archived candidate; never invoke a backend or modify its parent."""
import argparse,json,shutil
from pathlib import Path
from consensus_assurance.core.types import Analysis,InquiryTask
from consensus_assurance.core.proposals import ReviewReply,GraphPatch
from consensus_assurance.workflow.inquiry import validate_review
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update,apply_scope_update
from consensus_assurance.workflow.output_repair import OutputRepair
from consensus_assurance.workflow.repair_policy import split_draft_bindings
from consensus_assurance.workflow.sources import all_materials


def replay(parent,out,corrections):
    if out.exists():raise ValueError('Use a new output directory; history is read-only')
    out.mkdir(parents=True);state=Analysis.model_validate_json((parent/'state.json').read_text())
    record={'parent':str(parent.resolve()),'origin':'offline_recorded_response_with_explicit_supplements','models':0,'agent_calls':0,'records':[]}
    def save(name,data): (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    for folder,kind in [('8a7fe58d21194075bf8d501221a837f8-semantic_review','review'),('f6577be6da9a47f68581404d750a55d6-graph_patch','graph')]:
        root=parent/'agent'/folder
        for name in ['response.json','decoded-response.json','prompt.txt']:
            if (root/name).exists():shutil.copyfile(root/name,out/(kind+'-'+name))
        raw=json.loads((root/'decoded-response.json').read_text());packet=json.loads((root/'prompt.txt').read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        if kind=='review':
            task=InquiryTask.model_validate(packet['task']);task.material_ids=[m['id'] for m in all_materials(packet)]
            parsed=ReviewReply.model_validate(raw)
            validate=lambda:validate_review(state,task,parsed)
        else:
            parsed=GraphPatch.model_validate(raw);unit=next(u for u in state.units if u.id==parsed.units[0].id)
            validate=lambda:validate_scope_update(state,from_patch(state,unit,parsed))
        try:validate();diagnostics=[]
        except ValueError as exc:diagnostics=[d.model_dump(mode='json') for d in getattr(exc,'diagnostics',[])];save(kind+'-rejection.json',{'error':str(exc),'diagnostics':diagnostics})
        if kind=='review':
            for r in parsed.resolutions:
                r.condition_dispositions=ReviewReply.model_validate({**raw,'resolutions':[{**x,'condition_dispositions':corrections['conditions']} for x in raw['resolutions']]}).resolutions[0].condition_dispositions
            validate_review(state,task,parsed)
        else:
            from consensus_assurance.core.diagnostics import Diagnostic
            raw=split_draft_bindings(raw,OutputRepair.model_validate(corrections['split']),[Diagnostic.model_validate(d) for d in diagnostics],{'materials':[m.model_dump(mode='json') for m in state.materials]},{b.id for b in state.bindings})
            parsed=GraphPatch.model_validate(raw);update=from_patch(state,unit,parsed);validate_scope_update(state,update)
            new=apply_scope_update(state,update)
            record['preserved']={'goals':unit.goal_ids==new.goal_ids,'obligations':unit.obligation_ids==new.obligation_ids,'question':unit.audit_question==new.audit_question,'fault_scope':unit.scope==new.scope}
            save('scope-update.json',update.model_dump(mode='json'))
        save(kind+'-accepted-offline.json',parsed.model_dump(mode='json'));record['records'].append({'kind':kind,'original':folder,'correction_origin':'explicit_offline_review','accepted':True})
    save('supplements.json',corrections);save('parent-reference.json',record)
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--supplements',type=Path,required=True);a=p.parse_args()
    print(json.dumps(replay(a.parent,a.out,json.loads(a.supplements.read_text())),ensure_ascii=False,indent=2))
