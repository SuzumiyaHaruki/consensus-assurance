import json
s=json.load(open('submission.json')); m=json.load(open('map.json'))
for x in s['sources']:
 n=len(open('../agent-source/'+x['file']).read().splitlines())
 x['end_line']=min(x['end_line'],n)
f=dict(id='F_vote_record',meaning='The stable store contains the last vote term key and candidate-address bytes key written by persistVote; a completed successful persistVote writes both.',identity={'server':'local Raft server','slot':'keyLastVoteTerm and keyLastVoteCand'},validity_context='requestVote reads both keys and recognizes a repeated vote if the requested term equals the stored vote term and candidate bytes are non-nil. The two writes are independent; atomic cross-key crash behavior is not established.',representation=['StableStore keyLastVoteTerm','StableStore keyLastVoteCand'],durability='Stored through the injected StableStore; individual write failures are returned.',recovery='Subsequent requestVote calls read these keys, including after initialization from durable state.',source_ids=['s_persist','s_vote','s_elect_send','s_stable'],unknowns=['Failure/crash between the two key writes remains an unresolved fault-contract and history question.'])
m['facts'].append(f)
b=next(b for b in m['behaviors'] if b['id']=='B_election'); b['produces_fact_ids']=['F_vote_record']; b['consumes_fact_ids']=['F_vote_record']
m['core_overview']['context']['fact_ids']=['F_vote_record']
for k in ['formation','context','connection']:
 p=m['core_overview'][k]
 ids=list(p['source_ids'])
 for b in m['behaviors']:
  if b['id'] in p['behavior_ids']: ids.extend(b['source_ids'])
 for f in m['facts']:
  if f['id'] in p['fact_ids']: ids.extend(f['source_ids'])
 p['source_ids']=list(dict.fromkeys(ids))
json.dump(s,open('submission.json','w'),indent=2)
json.dump(m,open('map.json','w'),indent=2)
