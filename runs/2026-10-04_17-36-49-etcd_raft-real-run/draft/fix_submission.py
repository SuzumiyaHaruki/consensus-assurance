import json
from pathlib import Path
p=json.load(open('submission.json'));m=json.load(open('initial-map.json'))
for s in p['sources']:
 s['end_line']=min(s['end_line'],len(Path('../agent-source',s['file']).read_text().splitlines()))
lookup={x['id']:x for x in m['behaviors']+m['facts']}
for k in ['formation','context','connection']:
 c=m['core_overview'][k]
 c['source_ids']=list(dict.fromkeys(c['source_ids']+[s for id in c['behavior_ids']+c['fact_ids'] for s in lookup[id]['source_ids']]))
q=p['question'];q['source_ids']=list(dict.fromkeys(q['source_ids']+[s for id in q['behavior_ids']+q['fact_ids']+list(q['supporting_behavior_ids']) for s in lookup[id]['source_ids']]))
json.dump(p,open('submission.json','w'),indent=2);json.dump(m,open('initial-map.json','w'),indent=2)
