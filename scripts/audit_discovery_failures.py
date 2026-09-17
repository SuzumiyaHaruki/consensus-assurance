"""Read-only cross-run discovery diagnostics; no backend or graph mutation."""
import argparse
import json
from pathlib import Path
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import Discovery
from consensus_assurance.workflow.graph_diagnostics import diagnose_graph
from consensus_assurance.workflow.associations import GOAL_KINDS


def audit(root):
    state=Analysis.model_validate_json((root/'state.json').read_text())
    session=state.pending_output_repair
    if not session:return {'run':str(root),'repair_session':False}
    path=root/'repair-sessions'/session['id']/Path(session['current_path']).name
    raw=json.loads(path.read_text());materials={m.id for m in state.materials}
    unknown={obj['id']:sorted(set(obj.get('grounding',{}).get('behavior_ids',[])+obj.get('grounding',{}).get('expectation_ids',[]))-materials)
             for kind in ('claims','relations') for obj in raw.get(kind,[])}
    links={u['id']:[r['id'] for r in raw.get('relations',[]) if r['id'] in u['relation_ids'] and r['source'] in u['goal_ids'] and r['target'] in u['obligation_ids'] and r['kind'] in GOAL_KINDS] for u in raw.get('units',[])}
    try:
        proposal=Discovery.model_validate(raw)
        current=[d.model_dump(mode='json') for d in diagnose_graph(state,proposal)]
    except ValueError as exc:current=[{'schema_error':str(exc)}]
    return {'run':str(root),'agent_calls':state.usage.get('agent_calls',0),'accepted_claims':len(state.claims),
        'accepted_units':len(state.units),'models':len(state.models),'repair_attempts':session['attempt'],
        'recorded_stop':state.stop_reason,'recorded_diagnostics':session['diagnostics'],
        'unacquired_grounding_ids':{k:v for k,v in unknown.items() if v},'goal_links':links,
        'current_diagnostics':current,'attribution':'Offline inspection of the saved candidate; no correction, execution or success claim'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if any(args.output.resolve().is_relative_to(r.resolve()) for r in args.run):raise ValueError('Keep output outside retained runs')
    records=[audit(r) for r in args.run]
    args.output.write_text(json.dumps(records,ensure_ascii=False,indent=2))
    for r in records:
        print(Path(r['run']).name, 'calls='+str(r['agent_calls']), 'accepted='+str(r['accepted_units']),
              'grounding_objects='+str(len(r['unacquired_grounding_ids'])),
              'units_missing_goal_link='+str(sum(not links for links in r['goal_links'].values())))
