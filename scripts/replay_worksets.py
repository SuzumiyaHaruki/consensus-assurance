"""Offline projection of a recorded run. No agent calls, target writes or historical mutation."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from consensus_assurance.core.types import Analysis,InquiryTask
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import BuildReply,BindingDraft,ReviewReply
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.plugins.implementations.hashicorp_raft.adapter import HashicorpRaft
from consensus_assurance.consensus.inquiry import INQUIRY
from consensus_assurance.workflow.discovery import context
from consensus_assurance.workflow.task_packet import prepare,pool_sources,receipt
from consensus_assurance.workflow.prompts import render
from consensus_assurance.workflow.locations import locate,location_context
from consensus_assurance.workflow.reviews import validate_resolutions
from consensus_assurance.workflow.sources import all_materials
from consensus_assurance.core.diagnostics import DiagnosticError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.run.resolve();dest=args.output.resolve()
    if dest.is_relative_to(root) or root.is_relative_to(dest):raise ValueError('Replay output must be separate from the read-only archive')
    dest.mkdir(parents=True,exist_ok=False)
    final=Analysis.model_validate_json((root/'state.json').read_text())
    if final.id!='4ea880ec5eef41b185b599d8e333282f':raise ValueError('This replay documents the explicitly identified historical run only')
    packet_versions={'d6856d494a2741a68cce902d8ae58581':'862b1f3d9ffe43b9a1a61e23f1f19b3e',
                     '2708bec735794c9d865d806dc55ff0c2':'b69d50c2a0ac4e20897e36c355f034ef',
                     '7f8061900e784175bed46341523a042e':'e3c2f8f689474bae860507deb0985012'}
    comparisons=[]
    for packet_id,version in packet_versions.items():
        old=json.loads((root/'packets'/(packet_id+'.json')).read_text())
        s=Analysis.model_validate_json((root/'history'/(version+'.json')).read_text())
        e=SimpleNamespace(state=s,root=root,config=Config.model_validate(s.config),implementation=HashicorpRaft(),budget=SimpleNamespace(remaining=lambda:1))
        unit=next(u for u in s.units if u.id==s.active_unit_id)
        packet,_=prepare(e,'build',context(e,unit));packet=pool_sources(packet);prompt=render('build',packet,INQUIRY)
        e.root=dest/packet_id;s.pending_action=None
        new=receipt(e,'build',packet,prompt,BuildReply)
        write_json(e.root/'rebuilt-packet.json',packet)
        write_json(e.root/'parent.json',{'original_packet':str(root/'packets'/(packet_id+'.json')),'history_version':packet_versions.get(packet_id),'basis':'Exact saved state' if packet_id in packet_versions else 'Original prompt review records and sent-material attachment; current graph from unchanged accepted graph in final state'})
        comparisons.append({'packet_id':packet_id,'old_prompt_chars':old['prompt_chars'],'new_prompt_chars':new['prompt_chars'],
            'old_schema_chars':old['wire_schema_chars'],'new_schema_chars':new['wire_schema_chars'],
            'old_source_chars':old['source_chars_sent'],'new_source_chars':new['source_chars_sent'],
            'sections':new['sections'],'omitted_material_ids':new['omitted_material_ids'],
            'required_missing':new['missing_required_material_ids'],'within_original_limit':new['prompt_chars']<=e.config.budget.context_chars})
    folder=root/'agent/5fb1d7bd68bc4097b644cbaa916722e3-explore'
    raw=json.loads((folder/'decoded-response.json').read_text());shutil.copyfile(folder/'decoded-response.json',dest/'original-exploration.json')
    materials={m.id:m for m in final.materials};locations=[]
    for row in raw['patch']['bindings']:
        binding=BindingDraft.model_validate(row);anchor,error=locate(binding,materials)
        locations.append({'binding_id':binding.id,'accepted_location':anchor,'diagnostic':None if anchor else location_context(binding,materials),'error':error})
    folder=root/'agent/68dd6b52f1bb4ec18cae6428a2ef75f0-semantic_review'
    raw=json.loads((folder/'decoded-response.json').read_text());shutil.copyfile(folder/'decoded-response.json',dest/'original-review.json')
    data=json.loads((folder/'prompt.txt').read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])
    task=InquiryTask.model_validate(data['task']);task.material_ids=[m['id'] for m in all_materials(data)]
    try:validate_resolutions(final,task,ReviewReply.model_validate(raw));diagnostics=[]
    except DiagnosticError as exc:diagnostics=[d.model_dump(mode='json') for d in exc.diagnostics]
    write_json(dest/'location-results.json',locations);write_json(dest/'review-diagnostics.json',diagnostics)
    provenance={'origin':'offline_recorded_response_replay','parent_run':str(root),'parent_run_id':final.id,
        'parent_framework_revision':final.framework_revision,'target_snapshot':final.snapshot.model_dump(mode='json'),
        'controller_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'controller_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
        'limitation':'Current controller projections and diagnostics only; no new autonomous analysis, model or target execution. Historical framework bytes are not reconstructed from HEAD alone.'}
    write_json(dest/'provenance.json',provenance);write_json(dest/'packet-comparison.json',comparisons)
    print(json.dumps(comparisons,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
