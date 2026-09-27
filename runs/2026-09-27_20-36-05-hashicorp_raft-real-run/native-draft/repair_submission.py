import json
from pathlib import Path
s=json.loads(Path('submission.json').read_text())
m=json.loads(Path('audit-map.json').read_text())
for f in m['facts']:
 if f['id']=='F-application':
  f['unknowns']=['The library exposes completion through Future.Error and ApplyFuture.Response, but the downstream application caller consuming this completed result is not mapped in the captured library. No client read, retry, or durable application consequence is established here.']
q=s['question']
q['behavior_ids']=['B-repl','B-snapshot','B-heartbeat','B-verify-notify']
q['supporting_behavior_ids']['B-verify-register']='Establishes the pending-future registration and voter-derived threshold before principal positive notifications are consumed; it does not itself establish or consume F-peer-positive.'
q['supporting_behavior_ids']['B-verify-finish']='Consumes the downstream F-verify-threshold and exposes public success or failure; this is a consequence of the principal notification consumption, not a direct F-peer-positive edge.'
selected=set(q['behavior_ids'])|set(q['supporting_behavior_ids'])
required=set(q['source_ids'])
for b in m['behaviors']:
 if b['id'] in selected: required.update(b['source_ids'])
for f in m['facts']:
 if f['id'] in q['fact_ids']: required.update(f['source_ids'])
q['source_ids']=sorted(required)
s['repair_of']='537efb12020a4874b873c733c11811ee'
s['map_path']='audit-map-repair.json'
s['rationale']='Repair the rejected initial map and unchanged verification-eligibility question. F-application now explicitly identifies the unmapped downstream application consumer. The question lists only actual producers and consumers of F-peer-positive as direct behaviors; registration and public completion remain separately attributed support. Citations include every selected behavior and principal Fact source. The next discriminator remains applicability and actual fixed-membership nonvoter contributions to VerifyLeader; no obligation, execution evidence, or broader safety conclusion is asserted.'
Path('audit-map-repair.json').write_text(json.dumps(m,indent=2)+'\n')
Path('submission-repair.json').write_text(json.dumps(s,indent=2)+'\n')
