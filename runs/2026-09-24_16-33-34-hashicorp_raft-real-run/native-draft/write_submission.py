import json
from pathlib import Path
sources=[]
def src(id,file,start,end,kind='code_observation'):
    sources.append(dict(id=id,file=file,start_line=start,end_line=end,kind=kind))
src('leader-dispatch','raft.go',134,155)
src('leader-object-allocation','raft.go',455,464)
src('leader-lifetime','raft.go',493,575)
src('replicator-capture','raft.go',578,645)
src('commit-consumer','raft.go',785,825)
src('replication-object','replication.go',31,95)
src('replication-loop','replication.go',135,197)
src('append-result','replication.go',202,280)
src('snapshot-result','replication.go',299,383)
src('heartbeat-result','replication.go',388,440)
src('pipeline-lifetime','replication.go',446,508)
src('pipeline-result','replication.go',534,566)
src('replication-update','replication.go',646,665)
src('commitment-contract','commitment.go',11,34,'interface_statement')
src('commitment-construction','commitment.go',35,47)
src('commitment-update','commitment.go',66,104)
src('node-construction','api.go',496,560)
src('node-startup','api.go',570,625)
src('transport-interface','transport.go',29,67,'interface_statement')
src('pipeline-interface','transport.go',109,140,'interface_statement')
src('fsm-interface','fsm.go',15,48,'interface_statement')
q={
 'disposition':'explained_by_existing_mechanism',
 'preferred_check':'source_review',
 'question': 'Can a delayed successful AppendEntries or InstallSnapshot response handled by a replication worker from an earlier leader incarnation contribute match evidence or a commit notification to a later leader incarnation on the same Raft instance? The decisive discriminator is whether the delayed completion dereferences the current r.leaderState.commitment/commitCh or the objects captured by its original followerReplication.',
 'importance':'The commitment consumer copies its aggregate index into Raft state and schedules inflight logs for processing (commit-consumer). Cross-incarnation support contamination could therefore undermine the context of a decision. This is motivation for the local ownership question, not a claim that an unsafe decision or application is reachable.',
 'source_ids':[s['id'] for s in sources],
 'participants':['One Raft instance entering leadership twice','A remote follower with a delayed replication response','The main run/leaderLoop goroutine','Old and new followerReplication workers and pipeline decoders'],
 'objects':['Old and new commitment objects','Old and new commitCh channels','Old and new followerReplication objects','AppendEntries request and response pair','InstallSnapshot metadata and response'],
 'contexts':['A1 decision support consumption across A2 leader-incarnation replacement','Same local server identity, fixed participant configuration for the selected scenario','Delay in a crash-fault setting with no Byzantine response fabrication','No process restart, client snapshot restore, or peer removal/re-addition in the selected scenario'],
 'event_paths':[
  'run invokes runLeader serially; setupLeaderState creates a new commitment, commitCh, replState map and stepDown channel on every leader entry (leader-dispatch, leader-object-allocation).',
  'startStopReplication creates a followerReplication that captures the current commitment and stepDown objects; currentTerm is also copied (replicator-capture).',
  'An append RPC may remain blocked while the main owner exits leaderLoop. Cleanup closes worker stop channels and clears leaderState fields, but does not synchronously join every worker (leader-lifetime, append-result). Closing stopCh alone is not treated as cancellation of an in-progress RPC.',
  'A subsequent leader entry allocates new objects. A delayed ordinary append completion checks response term and success, then updateLastAppended calls s.commitment.match; it does not reload r.leaderState.commitment (append-result, replication-update).',
  'The pipeline decoder similarly receives its original s argument and calls updateLastAppended. The snapshot-success branch calls s.commitment.match directly. Neither path redirects the old worker to the new commitment (pipeline-lifetime, pipeline-result, snapshot-result).',
  'match/recalculate lock and mutate that commitment object, then notify the commitCh stored inside it. The current leaderLoop listens on the current leaderState.commitCh and reads the current leaderState.commitment (commitment-construction, commitment-update, commit-consumer).',
  'The independent heartbeat path updates contact and verify futures but does not call commitment.match; its weaker contact observation is not used as replicated-log support on this path (heartbeat-result).'
 ],
 'activity_classes':['A1','A2'],
 'behavior_ids':[], 'fact_ids':[],
 'obligation_relation_kind':'consumption',
 'counterevidence':[
  'Object and channel replacement, coupled with capture by each worker, is an alternative to checking the current numeric term again at completion. Old-object updates can continue without becoming support in the new object.',
  'Ordinary append, pipeline and snapshot result paths also reject a response term greater than their request term before calling match. These guards alone would not answer the delayed old-success scenario, but remain relevant protections.',
  'Each new commitment starts with zero match indexes for voters and requires a quorum match at least startIndex before advancing. This is an additional local guard, not evidence that upstream reported support is valid.'
 ],
 'unknowns':[
  'No controlled same-history execution of delayed completion across re-election was performed; this is a source-grounded ownership explanation and creates no formal Evidence.',
  'The actual deployment-selected transport and stores are unknown. In-repository implementations remain inside the available source boundary; their response association, error semantics and crash durability have not been established by this question.',
  'The response-validity contract for pipeline futures and actual follower durability are separate upstream relations, not resolved by object isolation.',
  'Same-leader membership removal/re-addition and snapshot restore can involve different identity or history changes; they are excluded from this cross-leader-incarnation explanation.',
  'Other effects of old workers, including contact/verification behavior, request construction from shared state, termination progress and resource lifetime, are not classified as safe by this disposition.',
  'The source call from commitment to log processing does not establish end-to-end application correctness or a legal history causing an unsafe commit.'
 ],
 'priority':2,
 'trigger_rationale':'The result paths compare a reply term with the original request term and may update support before noticing a closed stop channel. This motivates a consumption question for retained support across A2 object replacement. Exact reading identifies captured object/channel ownership as the relevant protection, so a missing extra global term comparison is not itself a defect.'
}
submission={
 'action':'explained',
 'rationale':'Scoped disposition: explained by existing object isolation for direct propagation of an old replication completion into a later leader incarnation on the same instance. The selected fact is a voter match report attached to one commitment object, not merely a success signal or last-contact timestamp. Allocation, capture, each relevant update path, aggregate notification and the current consumer were read. Old workers retain the old commitment and its old notification channel after stepdown; a new leader allocates fresh objects. Source search found no production reassignment of followerReplication.commitment after construction. This explains the selected hypothesis without requiring synchronous RPC cancellation and without assuming the checked isolation. No obligation or executable Evidence is created. The remaining upstream and broader-history gaps are preserved in the question.',
 'sources':sources,
 'question':q,
 'resume_conditions':[],
 'counterevidence_resolution':'No previous counterevidence was removed. Captured ownership, term/success guards, quorum/startIndex checks, and the possibility of in-flight completion after stop notification are retained and distinguished.',
 'obligation':None,
 'bindings':[]
}
Path('submission.json').write_text(json.dumps(submission,indent=2)+'\n')
try:
 import jsonschema
 jsonschema.validate(submission,json.load(open('../native-submission.schema.json')))
 print('Submission schema validation passed.')
except ImportError:
 print('jsonschema unavailable; JSON serialization completed.')
for s in sources:
 lines=Path('../native-source',s['file']).read_text().splitlines()
 assert 1 <= s['start_line'] <= s['end_line'] <= len(lines), s
print('All source ranges are within the authorized snapshot files.')
