import json
from pathlib import Path
import jsonschema
s=json.load(open('submission-backbone-repair.json'))
m=json.load(open(s['map_path']))
s['sources'].append(dict(id='S-run-owner',file='raft.go',start_line=135,end_line=155,kind='code_observation'))
m['facts'].append(dict(id='F-elected-role',meaning='Within one runCandidate invocation, the granted response count reached the previously computed voter quorum threshold, and the owner set local state to Leader and recorded its own leader identity.',identity={'owner':'local Raft instance','campaign':'runCandidate invocation and its voteCh','term':'current term at transition'},validity_context='Candidate loop after higher-response-term rejection; describes the local transition, not independently proven global authority',representation=['Raft state Leader','local leader address and ID'],durability='Leader role and campaign tally are volatile; term and self-vote use stable writes',recovery='NewRaft starts as Follower; role is not restored from a durable leader marker',source_ids=['S-election','S-elect','S-startup','S-persist'],unknowns=['No execution has established uniqueness of authority or a legal full election history.']))
for b in m['behaviors']:
 if b['id']=='B-election':b.setdefault('produces_fact_ids',[]).append('F-elected-role')
 if b['id']=='B-generation':
  b.setdefault('consumes_fact_ids',[]).append('F-elected-role')
  b['source_ids'].append('S-run-owner')
  b.setdefault('implementation_guards',[]).append('The main run dispatcher invokes runLeader when local state is Leader; shutdown can exit before dispatch.')
for i in ['B-election','B-generation']:
 s['map_changes'][i]['impact']='dependency'
 s['map_changes'][i]['source_ids']=list(dict.fromkeys(s['map_changes'][i]['source_ids']+['S-election','S-run-owner']))
 s['map_changes'][i]['rationale']+=' Record the local election-role fact and its actual run-dispatch consumption without assuming valid global authority.'
m['core_overview']['context']['fact_ids']=['F-elected-role']
m['core_overview']['context']['explanation']+=' F-elected-role records only the local quorum-tally transition; the main dispatcher subsequently consumes local Leader state to enter runLeader, subject to shutdown.'
m['core_overview']['context']['behavior_ids'].append('B-generation')
m['core_overview']['connection']['fact_ids'].append('F-elected-role')
m['core_overview']['connection']['explanation']+=' The local role transition is the explicit connection from the election owner to fresh leader-generation initialization, not an assumed global leadership guarantee.'
bs={b['id']:b for b in m['behaviors']};fs={f['id']:f for f in m['facts']}
for name in ['formation','context','connection']:
 p=m['core_overview'][name]
 for i in p['behavior_ids']:p['source_ids']+=bs[i]['source_ids']
 for i in p['fact_ids']:p['source_ids']+=fs[i]['source_ids']
 p['source_ids']=list(dict.fromkeys(p['source_ids']))
s['map_changes']['core_overview']['source_ids']=list(dict.fromkeys(s['map_changes']['core_overview']['source_ids']+['S-run-owner','S-election','S-elect','S-commit','S-fsm']))
s['map_changes']['core_overview']['rationale']+=' Repair explicit authority Fact references and include the sources of every referenced Behavior and Fact in each path.'
s['repair_of']='488ddccd063e4c30bc77612680855562'
s['map_path']='map-backbone-links.json'
s['rationale']='Repair rejected overview links by adding the weakest sourced local election-role fact and its actual dispatcher consumer, and completing each path source list from its referenced objects. Preserve conditional meaning and the existing frontier comparison. '+s['rationale']
jsonschema.validate(m,json.load(open('../product-schemas.json'))['ConsensusAuditSpec'])
jsonschema.validate(s,json.load(open('../submission.schema.json')))
for x in s['sources']:
 assert 1<=x['start_line']<=x['end_line']<=len((Path('../agent-source')/x['file']).read_text().splitlines())
Path(s['map_path']).write_text(json.dumps(m,indent=2)+'\n')
Path('submission-backbone-links.json').write_text(json.dumps(s,indent=2)+'\n')
print('Schema, citation bounds and overview reference closure checked locally.')
