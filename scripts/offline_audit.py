"""Export an explicitly authored offline spec against retained materials; no backend calls."""
import argparse,json
from pathlib import Path
from consensus_assurance.workflow.history import load_analysis
from consensus_assurance.workflow.audit_spec import validate,slice_for,accept,audit_progress
from consensus_assurance.core.types import ConsensusAuditSpec,Material
from consensus_assurance.adapters.storage.files import write_json
from types import SimpleNamespace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.run.resolve();out=args.output.resolve()
    if out.exists() or out.is_relative_to(root):raise ValueError('Use a new directory outside the retained run')
    state=load_analysis(root/'state.json');fixture=json.loads(args.fixture.read_text())
    for m in fixture.get('additional_materials',[]):
        actual=(root/'source'/m['file']).read_text().splitlines()
        if m['text']!='\n'.join(actual[m['start_line']-1:m['end_line']]):raise ValueError('Offline excerpt differs from retained source')
        state.materials.append(Material.model_validate(m))
    spec=ConsensusAuditSpec.model_validate(fixture['audit_spec']);validate(state,spec)
    accept(SimpleNamespace(root=out,state=state),spec)
    original=json.loads((root/'state.json').read_text())
    write_json(out/'audit-spec.json',spec);write_json(out/'audit-progress.json',audit_progress(state))
    write_json(out/'workset.json',slice_for(state,classes=['A6','A3','A5']))
    metrics={'origin':'offline_analyst_reconstruction','parent':str(root),'provenance':fixture['provenance'],
        'original_agent_calls':original['usage'].get('agent_calls',0),'original_largest_prompt':max((p.get('prompt_chars',0) for p in original.get('packet_receipts',[])),default=0),
        'original_question_calls':sum(p['kind']=='question' and p['status'] in {'executed','accepted'} for p in original['packet_receipts']),
        'original_semantic_review_calls':sum(p['kind']=='semantic_review' and p['status'] in {'executed','accepted'} for p in original['packet_receipts']),
        'offline_agent_calls':0,'offline_verification_actions':0,'limitation':'Authored reconstruction cannot predict autonomous calls, latency or discovery quality'}
    write_json(out/'metrics.json',metrics);print(json.dumps(metrics,ensure_ascii=False))

if __name__=='__main__':main()
