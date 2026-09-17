"""Read-only archived packet comparison; never invokes an analysis backend."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.config import Config
from consensus_assurance.plugins.implementations.hashicorp_raft.adapter import HashicorpRaft
from consensus_assurance.workflow.inquiry import task_context
from consensus_assurance.workflow.discovery import context
from consensus_assurance.workflow.task_packet import prepare,pool_sources
from consensus_assurance.workflow.prompts import render


def inspect(root):
    from consensus_assurance.workflow.inquiry import split_model_context
    records=[]
    events=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
    for event in events:
        if event.get('event')!='context_limit':continue
        version=event['state_version']
        state=Analysis.model_validate_json((root/'history'/(version+'.json')).read_text())
        old=state.packet_receipts[-1]
        engine=SimpleNamespace(state=state,root=root,config=Config.model_validate(state.config),implementation=HashicorpRaft(),inquiry='',
            budget=SimpleNamespace(remaining=lambda:0),error_context=lambda c:c.model_dump(mode='json'))
        unit=next(u for u in state.units if u.id==old['unit_id'])
        task=next((t for t in state.inquiry_tasks if t.id==old['task_id']),None)
        packet=task_context(engine,task) if task else context(engine,unit)
        ready,_=prepare(engine,old['kind'],packet)
        chars=len(render(old['kind'],pool_sources(ready)))
        item={'kind':old['kind'],'state_version':version,'original_chars':old['prompt_chars'],'current_chars':chars,
            'ceiling':engine.config.budget.context_chars,'fits':chars<=engine.config.budget.context_chars,
            'selected_unit_version':unit.version,'counterevidence_preserved':len(packet.get('open_issues',packet.get('semantic_view',{}).get('open_issues',[]))),
            'basis':'Same context_limit checkpoint; time field fixed for offline rendering. No backend execution or issue resolution.', 'children':[]}
        if not item['fits'] and old['kind']=='F3':
            usage=dict(state.usage);state.active_inquiry_id=None
            for id in split_model_context(engine,'F3'):
                child=next(t for t in state.inquiry_tasks if t.id==id)
                data,_=prepare(engine,'semantic_review',task_context(engine,child))
                size=len(render('semantic_review',pool_sources(data)))
                item['children'].append({'targets':child.target_ids,'chars':size,'fits':size<=engine.config.budget.context_chars,'issue_ids':child.resolution_issue_ids})
            assert usage==state.usage
        records.append(item)
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve().is_relative_to(args.run.resolve()):raise ValueError('Offline output must remain outside the retained run')
    data=inspect(args.run)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(data,ensure_ascii=False,indent=2))
