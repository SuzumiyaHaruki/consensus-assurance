import json

def source(id,file,start,end,kind='code_observation'):
    return dict(id=id,file=file,start_line=start,end_line=end,kind=kind)
sources=[
 source('S-snapshot-contract','docs/omnipaxos/compaction.md',29,63,'document_statement'),
 source('S-snapshot-interface','omnipaxos/src/storage/mod.rs',76,104,'interface_statement'),
 source('S-storage-read-contract','omnipaxos/src/storage/mod.rs',159,178,'interface_statement'),
 source('S-sync-mutation','omnipaxos/src/storage/internal_storage.rs',313,383),
 source('S-delta-producer','omnipaxos/src/storage/internal_storage.rs',385,412),
 source('S-memory-read','omnipaxos_storage/src/memory_storage.rs',34,106),
 source('S-logsync-producer','omnipaxos/src/sequence_paxos/mod.rs',402,437),
 source('S-reconnect','omnipaxos/src/sequence_paxos/mod.rs',341,357),
 source('S-follower-sync','omnipaxos/src/sequence_paxos/follower.rs',13,78),
 source('S-leader-sync','omnipaxos/src/sequence_paxos/leader.rs',150,191),
 source('S-leader-reprepare','omnipaxos/src/sequence_paxos/leader.rs',66,74),
 source('S-decisions','omnipaxos/src/sequence_paxos/leader.rs',287,345),
 source('S-quorum','omnipaxos/src/util.rs',229,259),
 source('S-api','omnipaxos/src/omni_paxos.rs',344,423,'interface_statement'),
 source('S-read-view','omnipaxos/src/storage/internal_storage.rs',77,213),
 source('S-communication','docs/omnipaxos/communication.md',1,27,'document_statement'),
 source('S-leadership','omnipaxos/src/sequence_paxos/leader.rs',14,60),
 source('S-linearizable','omnipaxos/src/sequence_paxos/mod.rs',23,25,'interface_statement'),
]
ids=[s['id'] for s in sources]
bindings=[
 dict(id='B-sync-log',material_id='S-sync-mutation',symbol='sync_log',start_line=313,end_line=359,description='Consumes leader-selected log synchronization and merges delta with a locally reconstructed snapshot.',pending=[]),
 dict(id='B-follower-sync',material_id='S-follower-sync',symbol='handle_acceptsync',start_line=53,end_line=78,description='Ballot- and phase-qualified synchronous consumer; returns after storage synchronization and queues Accepted.',pending=[]),
 dict(id='B-delta-producer',material_id='S-delta-producer',symbol='create_diff_snapshot',start_line=389,end_line=412,description='Produces a delta after the follower-reported decided prefix when the leader has not compacted that prefix.',pending=[]),
]
bids=[b['id'] for b in bindings]
grounding=dict(source_ids=['S-sync-mutation','S-delta-producer','S-logsync-producer','S-follower-sync','S-memory-read','S-read-view'],expectation_ids=['S-snapshot-contract','S-snapshot-interface','S-linearizable'],binding_ids=bids,
 derivation='The documented key-value snapshot preserves the latest value of every decided key and merges later changes. create_log_sync creates a delta beginning at the recipient\'s reported decided index; handle_acceptsync must preserve that base when applying it. sync_log updates cached decided_idx before create_decided_snapshot, which uses that newer boundary against the old local log. MemoryStorage returns an empty vector for an unavailable complete range, potentially discarding the old decided keys before merging the delta. The observer materializes the actual read_decided_suffix result, including snapshot contents, not just accepted/decided counters.',
 applicability='A valid fixed configuration, fault-free MemoryStorage, key-value Snapshot with overwrite merge, real quorum-decided prefixes, and a follower reconnecting after missing additional decided entries. No crash, invalid messages, configuration change, or concurrent API access.',unresolved=[],conflicts=[],alternatives=['Complete snapshots replace the base directly and do not traverse the suspected delta merge path.','A follower with all newly decided entries locally can mask loss with idempotent key-value merge; this check records the shorter accepted log before synchronization.'])
claim=dict(id='O-reconnect-snapshot-state',kind='obligation',concern='consensus_safety',description='When a follower completes an admitted log synchronization carrying a delta snapshot of a leader\'s decided prefix, its exposed decided state must represent that entire prefix, preserving previously decided application keys not superseded by the delta.',source_ids=['S-snapshot-contract','S-snapshot-interface','S-linearizable','S-logsync-producer','S-follower-sync'],scope=dict(description='Preservation of decided key-value state across follower Recover/Prepare/Accept synchronization within one configuration.',assumptions=['Snapshot create folds the supplied entries in order; merge applies the later delta with overwrite semantics.','The storage implementation satisfies the complete-interval read contract and no storage failure occurs.','Messages are produced by actual configured nodes and delivered in per-sender order except losses during an explicit disconnection.'],excluded=['Cross-configuration fencing','Permanent liveness claims','Crash recovery and failed storage transactions']),pending=[],grounding=grounding)
question=dict(question='Does reconnect synchronization preserve an existing decided key when a real leader sends a delta beyond a follower\'s shorter accepted log, given that sync_log updates decided_idx before reconstructing the delta base?',source_ids=ids,disposition='ready_for_check',preferred_check='controlled_schedule',importance='Losing an already decided key from a returned decided snapshot would break the replicated-state safety contract during recovery.',participants=['leader 3','follower 2','quorum peer 1'],contexts=['One configuration; follower Accept to Recover to Prepare to Accept'],activity_classes=['A1','A2','A3','A5','A6'],counterevidence=grounding['alternatives'],unknowns=['The actual retained execution must establish that the naturally produced message is Delta, the follower has the shorter accepted log, and the same handler returns a readable divergent decided state.'])
candidate=dict(action='obligation',rationale='Follow the snapshot-base ownership boundary exposed by real reconnect handling. Preserve the complete-snapshot branch as counterevidence rather than generalizing to all synchronization.',question=question,obligation=claim,bindings=bindings)

def val(field,value): return dict(field=field,op='eq',value=value)
def ref(field,reference): return dict(field=field,op='eq',reference=reference)
prereqs=[
 dict(alias='prefix',event='prefix_decided',conditions=[val('follower_decided',1)]),
 dict(alias='reconnect',event='reconnect_requested',conditions=[ref('operation','prefix.operation'),ref('follower_decided','prefix.follower_decided'),val('leader_decided',2)]),
 dict(alias='admission',event='sync_admitted',conditions=[ref('operation','reconnect.operation'),ref('before_view','prefix.follower_view'),ref('leader_view','reconnect.expected_view'),ref('incoming_decided','reconnect.leader_decided'),val('snapshot_kind','delta'),val('ballot_matches',True),val('from',3),val('to',2),val('follower_accepted',1),val('follower_decided',1),val('follower_compacted',0),val('sync_idx',2),val('suffix_len',0)]),
]
legality=dict(source_ids=['S-api','S-leadership','S-reconnect','S-leader-reprepare','S-follower-sync','S-decisions','S-quorum','S-leader-sync','S-logsync-producer','S-memory-read'],expectation_ids=['S-communication','S-storage-read-contract','S-snapshot-contract'],binding_ids=bids,derivation='The harness constructs three public OmniPaxos instances with default MemoryStorage. try_become_leader produces the Prepare/Promise/AcceptSync prefix; append produces both key proposals and real Accepted quorums. A single-threaded FIFO queue delivers unmodified messages and drops only traffic incident to node 2 during the declared disconnection. After quiescence the transport reconnects and calls node 2 reconnected(3), the documented caller duty. No protocol fields are fabricated. The real AcceptSync is sampled immediately before delivery; read_decided_suffix is sampled immediately after that same synchronous handler returns. All messages and pre/post states are printed. BTreeMap substitutes deterministic iteration for the documented HashMap without changing key overwrite or delta-merge semantics.',applicability='Three configured crash-fault participants, no actual crashes or storage faults; bounded deterministic public-API schedule; no timer deadline or permanent-stall assertion.',unresolved=[],conflicts=[],alternatives=[])
plan=dict(description='Decide key 11 on all nodes; isolate follower 2; decide distinct key 22 on nodes 3 and 1; reconnect follower 2 and inspect the actual delta-bearing AcceptSync and same-handler decided read. Compare application state with the leader\'s independently observed full prefix. A second predicate checks the exposed decided boundary against the admitted message.',claim_id=claim['id'],binding_ids=bids,harness=dict(kind='rust_test',source='',files={},description='Public-API, FIFO, real-prefix three-node reconnect experiment.',semantic_changes=['No target code changes. The harness supplies a documented-style key-value application Snapshot, deterministic transport and observation output.'],prerequisites=prereqs,legality=legality),monitors=[],observable_properties=[],uncertainties=['This check does not establish cross-configuration behavior, permanent data loss across every future recovery, or liveness. Actual retained execution and correspondence review remain required.'])
for checker,field,reference,description in [
 ('C-decided-state','follower_view','admission.leader_view','The follower decided read after synchronization must materialize the same key-value state as the admitted leader decided prefix.'),
 ('C-decided-boundary','follower_decided','admission.incoming_decided','The completed admitted synchronization must expose the decided boundary provided by the leader.')]:
 plan['monitors'].append(dict(id='M-'+checker,checker_id=checker,event='sync_returned',binding_ids=bids,grounding=grounding,admission_alias='admission'))
 plan['observable_properties'].append(dict(checker_id=checker,kind='event_assertion',trigger=val('handler_returned',True),assertion=ref(field,reference),identity_fields=['operation','follower'],description=description))
submission=dict(action='check',rationale='A sourced safety suspicion has a concrete public producer and reconnect prefix. Request retained execution to distinguish correct prefix-preserving synchronization from delta-base loss; no runtime result or formal validity is asserted yet.',sources=sources,candidate=candidate,plan_path='snapshot_reconnect.plan.json',harness_path='snapshot_reconnect.rs',files={})
for path,data in [('snapshot_reconnect.plan.json',plan),('snapshot_reconnect.submission.json',submission)]:
 with open(path,'w') as f: json.dump(data,f,indent=2);f.write('\n')
