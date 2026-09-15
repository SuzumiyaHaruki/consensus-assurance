"""Replay existing reviews locally; synthetic supplements are never semantic evidence."""
import argparse
import json
import sys
from pathlib import Path
from consensus_assurance.adapters.agents.backend import MockAgent
from consensus_assurance.adapters.storage.files import Store,write_json,digest
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Analysis,InquiryTask
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine,FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.inquiry import task_context,validate_review,apply_task_response
from consensus_assurance.workflow.transactions import commit_graph
from consensus_assurance.workflow.review_contract import target_contract
from consensus_assurance.reporting.chinese import render_report


def replay(parent,out):
    if out.exists():raise ValueError('Use a new output directory; historical artifacts are read-only')
    out.mkdir(parents=True)
    old=Store(parent).load()
    cfg=Config.model_validate(old.config);cfg.agent_backend='mock';cfg.allow_agent_materials=False;cfg.allow_experiments=False
    state=Analysis(mode='mock',framework_revision=FRAMEWORK_REVISION,framework_stage='offline_recorded_review_replay',config=cfg.model_dump(mode='json'),snapshot=old.snapshot,
        claims=old.claims,bindings=old.bindings,relations=old.relations,units=old.units,materials=old.materials,responsibilities=old.responsibilities,completed_steps=['materials','discovery'])
    # Reference the authorized immutable captured source; never use a live target to patch evidence.
    (out/'source').symlink_to((parent/'source').resolve(),target_is_directory=True)
    e=Engine(cfg,out,*assemble(cfg),'');e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    records=[];objects={o.id:o for o in [*state.claims,*state.bindings,*state.relations,*state.units]}
    for p in sorted(parent.glob('agent/*semantic_review/response.json')):
        raw=json.loads(p.read_text());wire=json.loads((p.parent/'prompt.txt').read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        task=InquiryTask.model_validate(wire['task']);task.status='running';task.repair_session=None
        task.context_receipt_id=None;task.context_dependencies={};state.inquiry_tasks.append(task);state.active_inquiry_id=task.id
        # Restore only actually cited prior material for this specific recorded task.
        state.task_attachments['inquiry:'+task.id]=sorted({id for item in raw['items'] for id in item['source_ids']})
        original_digest=digest(p.read_bytes())
        try:validate_review(state,task,ReviewReply.model_validate(raw));rejection=[]
        except ValueError as exc:rejection=[d.model_dump(mode='json') for d in getattr(exc,'diagnostics',[])]
        responses=[raw]
        for id in task.target_ids:
            contract=target_contract(state,objects[id]);have={i['aspect'] for i in raw['items'] if i['target_id']==id}
            for aspect in contract['required_aspects']:
                if aspect in have:continue
                supplement={'target_id':id,'aspect':aspect,'status':'needs_reading','source_ids':contract['required_material_ids'],
                    'explanation':'Synthetic interface-only supplement: the historical applicability item did not explicitly complete the requested decomposition analysis',
                    'alternatives':'Actual responsibility and code-use alternatives remain for a future substantive review',
                    'counterexample_reasoning':'No synthetic supplement establishes the absence or presence of a violation',
                    'limitations':['Offline framework replay only; no new autonomous semantic analysis was performed']}
                responses.append({'replacements':[{'path':'/items/-','value_json':json.dumps(supplement)}],'rationale':'Append an explicitly unresolved synthetic interface supplement; preserve the entire original review'})
        fixture=out/'fixtures'/(task.id+'.json');write_json(fixture,responses);e.agent=MockAgent(str(fixture))
        reply,check=e.ask('semantic_review',ReviewReply,task_context(e,task),lambda r:validate_review(state,task,r))
        commit_graph(e,'offline-review-'+check.id,{'task_id':task.id,'reply':reply.model_dump(mode='json')},lambda proxy:apply_task_response(proxy,task.id,reply,check))
        e.advance('select')
        assert digest(p.read_bytes())==original_digest
        records.append({'parent_response':str(p.resolve()),'parent_digest':original_digest,'initial_diagnostics':rejection,'synthetic_supplements':len(responses)-1,'accepted_check':check.id,'original_items_preserved':all(i in reply.model_dump(mode='json')['items'] for i in raw['items'])})
    state.stop_reason='Offline interface replay completed; substantive review gaps remain unresolved; no model generated or TLC executed'
    write_json(out/'parent-reference.json',{'parent_run':str(parent.resolve()),'parent_framework':old.framework_revision,'origin':'recorded_response_plus_synthetic_interface_supplements','records':records})
    write_json(out/'materials.json',[m.model_dump(mode='json') for m in state.materials]);write_json(out/'snapshot.json',state.snapshot)
    e.checkpoint('offline_review_replay_completed');render_report(state,out)
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(replay(args.parent,args.out),ensure_ascii=False,indent=2))
