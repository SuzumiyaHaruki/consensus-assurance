import json
m=json.load(open('map.json'));s=json.load(open('submission.json'));objs={o['id']:o for o in m['behaviors']+m['facts']}
for p in m['core_overview'].values():
 if isinstance(p,dict):
  p['source_ids']=list(dict.fromkeys(p.get('source_ids',[])+[sid for oid in p.get('behavior_ids',[])+p.get('fact_ids',[]) for sid in objs[oid]['source_ids']]))
q=s['question'];q['source_ids']=list(dict.fromkeys(q['source_ids']+[sid for oid in q['behavior_ids']+q['fact_ids']+list(q['supporting_behavior_ids']) for sid in objs[oid]['source_ids']]))
for n,o in [('map.json',m),('submission.json',s)]:json.dump(o,open(n,'w'),indent=2)
