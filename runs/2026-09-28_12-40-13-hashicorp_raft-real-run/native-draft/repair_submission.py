import json
from pathlib import Path
s=json.loads(Path('submission.json').read_text())
m=json.loads(Path('audit-map.json').read_text())
s['repair_of']='f3582dadec184744ba19676e3f99be08'
s['sources'] += [dict(id='i_forced_recovery',file='api.go',start_line=284,end_line=312,kind='interface_statement'),dict(id='s_forced_recovery',file='api.go',start_line=313,end_line=440,kind='code_observation')]
b=dict(id='b_forced_recovery',primary_activity='A3',execution_owner='Explicit offline RecoverCluster caller and supplied temporary FSM',protocol_context='Existing local snapshot/log state and operator-supplied replacement configuration',trigger='RecoverCluster invocation after exceptional loss of quorum',source_ids=['i_forced_recovery','s_forced_recovery'],legal_preconditions=['Documented manual recovery scope; typical procedure shuts down all servers and uses identical replacement membership. Discard the supplied FSM afterward.'],implementation_guards=['Validates configuration and requires existing state; rejects failure to restore any available snapshot.'],reads=['Newest usable snapshot then every subsequent local log entry, without a known commit boundary.'],writes=['Applies all subsequent LogCommand entries to the temporary FSM; records replacement configuration at configuration index 1 in a new snapshot.'],durable_effects=['Persists and closes replacement snapshot before deleting the existing log range.'],important_branches=['Snapshot open/restore failures try older snapshots; store, snapshot or compaction errors return failure.'],cross_activity_effects={'A1':'Explicitly treats remaining local history as committed rather than reconstructing quorum support; ordinary consensus guarantees cannot be assumed for this exceptional operation.','A2':'Replacement snapshot membership is consumed on subsequent NewRaft startup and determines eligible participants.'},existing_protections=['Public contract warns of implicit commitment of previously uncommitted entries and requires a fresh application FSM on restart.'],unknowns=['Partial failures and concrete storage crash behavior remain unexamined.'])
m['behaviors'].append(b)
for a in m['activities']:
 if a['class_id']=='A3':
  a['source_ids']=sorted(set(a['source_ids']+b['source_ids']))
  a['entry_points'].append('RecoverCluster')
  a['realization_summary']+='; offline RecoverCluster reconstructs local state and writes operator-selected replacement membership under an explicitly exceptional contract.'
x=m['surfaces'][3]
x.update(disposition='mapped',behavior_ids=['b_forced_recovery'],source_ids=b['source_ids'],reason='Read the public exceptional-recovery contract and implementation: replay local suffix into a temporary FSM, snapshot with replacement membership, then truncate logs. This is an explicit authority reset, not evidence that ordinary quorum decisions can be reconstructed from this local state.')
o=m['core_overview']
o['open_details']=[x.replace('Forced RecoverCluster implementation, detailed snapshot compaction and legacy protocol combinations.','Partial failures during forced RecoverCluster, detailed snapshot compaction and legacy protocol combinations.') for x in o['open_details']]
o['connection']['explanation']+=' Offline RecoverCluster is a separate documented exceptional reset: it applies the local suffix without a known commit boundary, snapshots the supplied replacement configuration, and deletes old logs. Its warning about implicit commitment bounds the ordinary consensus interpretation above.'
o['connection']['behavior_ids'].append('b_forced_recovery')
bs={b['id']:b for b in m['behaviors']};fs={f['id']:f for f in m['facts']}
for name in ['formation','context','connection']:
 p=o[name];refs=set(p['source_ids'])
 for bid in p['behavior_ids']: refs.update(bs[bid]['source_ids'])
 for fid in p['fact_ids']: refs.update(fs[fid]['source_ids'])
 p['source_ids']=sorted(refs)
q=s['question'];refs=set(q['source_ids'])
for bid in q['behavior_ids']+list(q['supporting_behavior_ids']): refs.update(bs[bid]['source_ids'])
for fid in q['fact_ids']: refs.update(fs[fid]['source_ids'])
q['source_ids']=sorted(refs)
s['map_path']='audit-map-repair.json'
s['rationale']='Repair of rejected initial product: read and map RecoverCluster under its explicit exceptional-recovery contract, replace its unsourced surface, and include source dependencies of every referenced Behavior and Fact in the overview and question. The verification-eligibility proposition and its unknowns are unchanged. '+s['rationale']
import jsonschema
jsonschema.validate(s,json.load(open('../native-submission.schema.json')))
jsonschema.validate(m,json.load(open('../product-schemas.json'))['ConsensusAuditSpec'])
source_ids={x['id'] for x in s['sources']}
for x in s['sources']:
 assert 1<=x['start_line']<=x['end_line']<=len(Path('../native-source',x['file']).read_text().splitlines())
for p in [o[n] for n in ['formation','context','connection']]+[q]:
 assert set(p['source_ids'])<=source_ids
 for bid in p['behavior_ids']: assert set(bs[bid]['source_ids'])<=set(p['source_ids'])
 for fid in p['fact_ids']: assert set(fs[fid]['source_ids'])<=set(p['source_ids'])
for x in m['surfaces']:
 assert x['source_ids'] and set(x['source_ids'])<=source_ids
 assert set(x.get('behavior_ids',[]))<=set(bs)
Path('audit-map-repair.json').write_text(json.dumps(m,indent=2)+'\n')
Path('submission-repair.json').write_text(json.dumps(s,indent=2)+'\n')
print('Repair products validated against schemas, source bounds, and referenced source coverage; original drafts preserved.')
