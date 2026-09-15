"""Read-only historical proposal replay into a new local scope stage; never call an agent."""
import argparse,json,copy,shutil
from pathlib import Path
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import GraphPatch,BuildReply
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import write_json,digest
from consensus_assurance.workflow.engine import Engine,FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update,ScopeAssessment,accept
from consensus_assurance.workflow.graph import validate_patch
from consensus_assurance.reporting.chinese import render_report


def replay(parent,out):
    if out.exists():raise ValueError('Output exists; use a new directory to preserve history')
    old=Analysis.model_validate_json((parent/'state.json').read_text());out.mkdir(parents=True)
    source=parent/'source';records=[]
    for patch_path in sorted(parent.glob('agent/*graph_patch/decoded-response.json')):
        patch=GraphPatch.model_validate_json(patch_path.read_text());unit_id=patch.units[0].id
        root=out/unit_id;root.mkdir();
        for original,name in [('response.json','recorded-response.json'),('decoded-response.json','recorded-decoded.json'),('prompt.txt','recorded-prompt.txt')]:
            source_path=patch_path.parent/original
            if source_path.is_file():shutil.copyfile(source_path,root/name)
        (root/'source').symlink_to(source.resolve(),target_is_directory=True)
        cfg=Config.model_validate(old.config);cfg.agent_backend='mock';cfg.allow_agent_materials=False;cfg.allow_experiments=False
        state=Analysis(mode='mock',analysis_mode='regression',framework_revision=FRAMEWORK_REVISION,framework_stage='offline_scope_reconnection',parent_run=str(parent.resolve()),config=cfg.model_dump(mode='json'),snapshot=old.snapshot,
            claims=copy.deepcopy(old.claims),bindings=copy.deepcopy(old.bindings),relations=copy.deepcopy(old.relations),units=copy.deepcopy(old.units),materials=copy.deepcopy(old.materials),review_issues=copy.deepcopy(old.review_issues),semantic_reviews=copy.deepcopy(old.semantic_reviews))
        unit=next(u for u in state.units if u.id==unit_id);state.active_unit_id=unit.id
        build_path=next(p for p in parent.glob('agent/*build/prompt.txt') if json.loads(p.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])['unit']['id']==unit_id)
        packet=json.loads(build_path.read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1]);provided={m['id'] for m in packet['materials']}
        # Reconstruct the actual pre-read material boundary; acquire omitted/new ranges from captured bytes.
        events=[json.loads(line) for line in (parent/'events.jsonl').read_text().splitlines()]
        before_read=None
        for event in events:
            if event['event']!='targeted_read_plan_saved':continue
            candidate=Analysis.model_validate_json((parent/'history'/(event['state_version']+'.json')).read_text())
            if candidate.active_unit_id==unit_id:
                before_read=candidate;break
        if before_read is None:raise ValueError('Actual pre-read checkpoint is missing; no reconstructed history is substituted')
        state.materials=copy.deepcopy(before_read.materials)
        e=Engine(cfg,root,*assemble(cfg),'');e.state=state;e.budget=BudgetTracker(cfg.budget,state)
        request=BuildReply.model_validate_json((build_path.parent/'decoded-response.json').read_text())
        obtained=e.read(request.requests,plan_id='recorded-build-dependencies',related_ids=unit.obligation_ids,reason=request.gap)
        obtained['scope_requested']=True
        if obtained['status']!='complete':raise ValueError('Historical dependency acquisition remained incomplete')
        try:validate_patch(state,patch);old_error=''
        except ValueError as exc:old_error=str(exc)
        write_json(root/'original-patch.json',json.loads(patch_path.read_text()))
        update=from_patch(state,unit,patch)
        correction=None
        try:needed=validate_scope_update(state,update)
        except ValueError as exc:
            write_json(root/'first-scope-rejection.json',{'error':str(exc),'diagnostics':[d.model_dump(mode='json') for d in getattr(exc,'diagnostics',[])]})
            # Explicit offline candidate correction, not a silent change to accepted code semantics.
            bad=next((b for b in patch.bindings if b.id=='B_future_response'),None)
            if bad is None:raise
            material=next(m for m in state.materials if m.id==bad.material_id)
            lines=material.text.splitlines()
            starts=[material.start_line+i for i,line in enumerate(lines) if line.strip()=='func (l *logFuture) Response() interface{} {']
            if len(starts)!=1:raise ValueError('Intended accessor identity cannot be located from actual source')
            line=starts[0];body=lines[line-material.start_line:line-material.start_line+3]
            if 'return l.response' not in body[1]:raise ValueError('Accessor body does not match the original candidate description')
            before=bad.model_dump(mode='json');bad.start_line=line;bad.end_line=line+2;bad.anchor.start_line=line;bad.anchor.end_line=line
            correction={'origin':'explicit_offline_candidate_location_correction','before':before,'after':bad.model_dump(mode='json'),'material_id':material.id,'content_digest':material.content_digest,
                'reason':'Original unaccepted candidate described logFuture.Response but pointed at another location; actual source identifies the accessor. This changes a proposed binding and is not a runtime mechanical repair claim.'}
            write_json(root/'location-correction.json',correction)
            update=from_patch(state,unit,patch);needed=validate_scope_update(state,update)
        if needed:
            # This is an explicit offline reviewer interpretation, not an autonomous backend answer.
            update.assessment=ScopeAssessment(decision='refinement',source_ids=update.source_ids,addressed_fields=needed,preserved_question=update.original_question,
                rationale='Offline source review: the exact original audit question, claims and fault scope are retained; the read Future methods refine response publication and observation events. This does not establish any upstream guarantee or withdraw the stored semantic issues.',
                remaining_unknowns=['Existing applicability and behavior conditions remain unresolved','This offline interpretation requires real agent assessment in any new autonomous run'])
        update.read_plan_id='recorded-build-dependencies'
        write_json(root/'original-patch.json',json.loads(patch_path.read_text()));write_json(root/'scope-proposal.json',update)
        new=accept(e,update)
        state.stop_reason='Historical scope reconnected; build is pending because the original run contains no Bundle. No new agent/model/check was fabricated.'
        e.checkpoint('offline_scope_reconnected');render_report(state,root)
        records.append({'unit_id':unit_id,'parent_patch':str(patch_path.resolve()),'parent_patch_digest':digest(patch_path.read_bytes()),'parent_build':str(build_path.parent.resolve()),'original_error':old_error,'actual_diff_fields':[c.field for c in update.changes],'location_correction':correction,'interpretation_origin':'offline_reviewer' if needed else 'validated_additive_scope','new_unit_id':new.id,'goal_ids_preserved':new.goal_ids==unit.goal_ids,'obligation_ids_preserved':new.obligation_ids==unit.obligation_ids,'models':len(state.models),'agent_calls':state.usage.get('agent_calls',0)})
    write_json(out/'parent-reference.json',{'parent_run':str(parent.resolve()),'snapshot':old.snapshot.model_dump(mode='json'),'records':records})
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(replay(args.parent,args.out),ensure_ascii=False,indent=2))
