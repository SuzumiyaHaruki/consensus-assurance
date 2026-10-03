import json
p='submission2.json';s=json.load(open(p));m=json.load(open('map2.json'));B={b['id']:b for b in m['behaviors']}
for x in s['sources']:
 x['end_line']=min(x['end_line'],sum(1 for _ in open('../agent-source/'+x['file'])))
pro=['b_ack_commit','b_append_accept','b_snapshot','b_config','b_reconstruct'];con=['b_application','b_reads']
for i in pro+con:
 b=B[i];field='produces_fact_ids' if i in pro else 'consumes_fact_ids';b.setdefault(field,[]).append('f_local_commit')
 s['map_changes'][i]=dict(impact='dependency',source_ids=b['source_ids'],rationale='Record the local committed-prefix producer/consumer edge already established by the traced source, with path-specific qualification retained.',preserves='No accepted Candidate or obligation exists; the new Fact does not equate local commitment with application completion.')
f=dict(id='f_local_commit',meaning='The local raft log records a committed prefix through committed; this is a decision boundary, not completed application or a guarantee that this node has already persisted the prefix.',identity={'owner':'raft.id','prefix_end':'raftLog.committed'},validity_context='Local log history: leader acknowledgment/configuration paths require current-term quorum candidate; follower appends use leader commitment bounded by matching appended range; snapshot and startup restore recorded committed history.',representation=['raftLog.committed'],durability='HardState.Commit and snapshot metadata persist the boundary through the caller storage contract; an in-memory update precedes completion of that work.',recovery='newRaft loads HardState after initializing compacted prefix and restores membership from Storage.',source_ids=list(dict.fromkeys(x for i in pro for x in B[i]['source_ids'])),unknowns=['Detailed out-of-band snapshot/storage caller policies remain external interface assumptions.'])
m['facts'].append(f);F={x['id']:x for x in m['facts']}
m['core_overview']['formation']['fact_ids']=['f_local_commit'];m['core_overview']['connection']['fact_ids'].append('f_local_commit')
for k in ['formation','context','connection']:
 c=m['core_overview'][k];c['source_ids']=list(dict.fromkeys(c['source_ids']+[x for i in c['behavior_ids'] for x in B[i]['source_ids']]+[x for i in c['fact_ids'] for x in F[i]['source_ids']]))
q=s['question'];q['source_ids']=list(dict.fromkeys(q['source_ids']+[x for i in q['behavior_ids'] for x in B[i]['source_ids']]+[x for i in q['fact_ids'] for x in F[i]['source_ids']]))
json.dump(m,open('map2.json','w'),indent=2);json.dump(s,open(p,'w'),indent=2)
