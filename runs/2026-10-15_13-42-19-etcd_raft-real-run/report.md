# Consensus audit research report

Method `audit-products-v80`; mode `real/autonomous`; elapsed 80.01 minutes.
Stop reason: Agent stopped: Total runtime budget exhausted before execution

Mechanical results evaluate declared predicates. Model defect claims address applicability, causes and counterevidence; independent verification is separate. Each question uses its latest interpretation; an explicit null claim does not inherit an earlier assertion. Historical interpretations and raw evidence remain available.

## Explicit model defect claims (subject to independent verification)

### Does a ReadIndex request that the leader postponed (because it had not committed an entry in its term) get answered when the leader's first commit of the term is performed inside switchToConfig while the application applies an already-committed configuration change?

Current disposition: active.
Question `8769550822c045a18219e24795b9bdc0-question-0` v3; sources: readindex-stash, msgappresp-release, switchtoconfig-commit, release-helper, heartbeatresp-readonly, readonly-maybeadvance, node-advance-contract, test-release-after-term-commit ([full references](state.json)).
Current model defect claim: defect asserted (subject to independent verification).

Current interpretation `63c5875253ff45f0b609b3c0ee4c71d7-interpretation-0` · declared predicate does not hold: The account now rests on a public-contract receipt for the premise and on the earlier fully-resolved receipt for the two completion paths. Source side: a leader postpones MsgReadIndex exactly when its configuration is not a singleton and no entry of its term is committed (raft.go:1354-1372); the only code that discharges the duty is releasePendingReadIndexMessages, called from the MsgAppResp commit path alone (raft.go:1550-1554), although switchToConfig also performs the term's first commit (raft.go:2013-2028) and the helper is guarded only by committedEntryInCurrentTerm() (raft.go:2127-2145); a postponed request is absent from readOnly.unconfirmedReads, so no heartbeat carries its context (read_only.go:93-101, raft.go:1600-1602). Receipt c86ee7b6e6604a269dc8aff31adce625 drives the decisive state through the Node interface: the application consumes the wrapped leader's Readys, writes entries and hard state, calls Advance while it is still applying the committed configuration change (permitted by node.go:166-187) so that applied progress through index 10 is reported with the tracker still holding voters=(1 2 3 4), campaigns through the Node interface and reaches StateLeader at term 2 with its term entry acknowledged only by voter 2 (parsed index 1 holds: state StateLeader, and the raw event carries last_index 11 with Match {1:11, 2:11, 3:0, 4:0}), then issues ReadIndex with context A through the Node interface and sees the request postponed (parsed index 2 holds: pending_reads 1, no ReadState delivered), and finally calls ApplyConfChange for the change it had already observed: the leader's commit advances 10 -> 11 with committed_entry_term 2, i.e. the release condition the helper is guarded by, while the postponed request stays held and no Ready delivers a ReadState for context A (parsed index 3: both witness assertions violated with a complete witness). What the earlier receipt a1859bb05261498c820729722eef035f adds is coverage of the two completion paths and the second configuration-change variant: the same omission for a local ReadState and for a forwarded request whose answer must be a MsgReadIndexResp, in both the removal and the leave-joint shapes, with the release controls holding when an unrelated entry is committed through the MsgAppResp path. The defect statement is unchanged and now rests on the documented client sequence rather than a supplied applied index: a request the leader accepted by postponing can remain unanswered across a commit of an entry of its own term when switchToConfig performs that commit, no periodic or acknowledgement path inside raft repairs it, and the answer that eventually arrives after an unrelated commit or a client retry carries a safe index taken at release time.

Sources: [readindex-stash](state.json), [msgappresp-release](state.json), [switchtoconfig-commit](state.json), [release-helper](state.json), [heartbeatresp-readonly](state.json), [readonly-maybeadvance](state.json), [node-advance-contract](state.json), [test-release-after-term-commit](state.json); execution evidence: [c86ee7b6e6604a269dc8aff31adce625](logs/c86ee7b6e6604a269dc8aff31adce625/check.json) ([observations](logs/c86ee7b6e6604a269dc8aff31adce625/observations.json), event indices [1, 2, 3]); [a1859bb05261498c820729722eef035f](logs/a1859bb05261498c820729722eef035f/check.json) ([observations](logs/a1859bb05261498c820729722eef035f/observations.json), event indices [2, 3, 5, 6, 11, 14, 18, 19, 20, 23]).
Interpretation counterevidence: The controls hold in the earlier receipt (parsed indices 6, 14 and 23): an unrelated proposal committed through the MsgAppResp path releases the postponed request and the answer is delivered, so the release mechanism is intact and the omission is specific to the switchToConfig commit path.; The Node.ReadIndex contract tells callers that read index requests can be lost without notice and that retries are their duty (node.go:218-224), so a retrying client is not blocked; the observation is an unanswered admissible request rather than a permanent client-visible outage.; The reachable prefix relies on documented application latitude - reporting applied progress before finishing the entries of a previous Ready (node.go:166-178) and calling ApplyConfChange later than that report (node.go:179-187) - and this receipt shows that sequence is reachable through the public interface, so the premise no longer depends on a supplied fixture; the unanswered request is not caused by that latitude, only the reachability of the state is.; The postponed form exists only for ReadOnlySafe: the lease-based branch answers from the leader's own commit index without postponing (raft.go:2146-2166), so that option cannot exhibit this omission.
Interpretation limitations: The comparison holds the applied configuration change to be the one that first makes a current-term entry committable; a leader that had already committed any entry of its term answers later requests normally (committedEntryInCurrentTerm() is true, so nothing is postponed).; The public-contract harness drives the wrapped leader against bare raft followers, so the followers' Ready/Advance duties are exercised only implicitly (their acknowledgements are delivered or held by the harness) and both run in one process.; No state machine was run, so the consequence measured is the unanswered request itself (no ReadState, no MsgReadIndexResp). The safe-but-late index of the eventual answer follows from the contract, not from a served value in the receipt.; The reachability without the documented latitude is not measured: this basis demonstrates one documented sequence, not that no other (or no simpler) sequence reaches the state.
Hypothesis: The postponed request is released only on the MsgAppResp commit path (raft.go:1550-1554), so a commit performed inside switchToConfig (raft.go:2013-2028) satisfies the release condition (newApplied >= pendingConfIndex is not involved; committedEntryInCurrentTerm() becomes true) without releasing it, leaving the received request unanswered until an unrelated commit or a client retry.
Registered discriminator: Whether the omission has consequences beyond the unanswered caller - for example an application that ties its own deadline to the read and re-issues it, or a caller that reuses one request context for several reads - and whether the postponed form exists for any read-only option other than ReadOnlySafe.

Fixed experiment `8769550822c045a18219e24795b9bdc0-experiment` v1: [saved basis](fixed-experiments/8769550822c045a18219e24795b9bdc0-experiment/basis.json).
Scope: Observe the whole interval of one postponed ReadIndex request on a real 4-node group: the leader postpones it, the application then applies an already-committed configuration change whose resulting configuration commits the leader's first entry of the term, the acknowledgement of the previous configuration arrives late, a heartbeat round runs, and finally an unrelated proposal is committed.
History / supplied conditions: For each case: build four nodes whose storage is bootstrapped with the case ConfState (voters {1,2,3,4}, or the joint configuration voters {1,2,3} + voters_outgoing {1,2,3,4}), append ten term-1 entries with entry 10 the case configuration change, persist HardState{Term:1,Commit:10} and set Applied=10; then elect node 1 with a real MsgHup/MsgVote/MsgVoteResp round (voter 4 unreachable, voter 3's MsgAppResp delayed), deliver the client's MsgReadIndex, apply the committed change at index 10 via applyConfChange, deliver the delayed acknowledgement, run one heartbeat round (tick), and finally propose one unrelated entry.
Assumptions: Four voters {1,2,3,4} bootstrapped from a ConfState-only snapshot, with log entries 1..9 ordinary and entry 10 the configuration change, HardState{Term:1, Commit:10}, applied index 10 (the application has reported applied progress but has not yet called ApplyConfChange for entry 10, which node.go:166-187 permits).; Transport preserves raft's per-message semantics (each message is Stepped by its target and resulting messages are delivered in order); voters are reachable for votes; voter 4 is unreachable and voter 3's append acknowledgements are delayed, which is the message-loss/delay part of the fault model.; The applied change is taken from the log entry at index 10 exactly as an application does when it applies CommittedEntries.
Excluded scope: Pre-vote, check-quorum and lease-based reads (all disabled by the test configuration stub).; Snapshot-based recovery and asynchronous storage writes.
Declared requirement / prediction: A ReadIndex request that a leader accepts by postponing (raft.go:1363-1368) must be answered once the leader has committed an entry of its term, whichever path performs that commit (raft.go:1550-1554 for the MsgAppResp path, raft.go:2013-2028 for the switchToConfig path), because the helper that discharges the duty is guarded only by committedEntryInCurrentTerm() (raft.go:2127-2145) and the caller's comment states the release is due once the committed index has progressed for the term.
Execution `5d77b839c94544d1bf81b71c506a5b90`: completed, exit code 0; [receipt](logs/5d77b839c94544d1bf81b71c506a5b90/check.json), [full observations](logs/5d77b839c94544d1bf81b71c506a5b90/observations.json), [stdout](logs/5d77b839c94544d1bf81b71c506a5b90/stdout.log), [stderr](logs/5d77b839c94544d1bf81b71c506a5b90/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `95b5c02c9cf545e0bd46770a16fe6d29-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 2 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `readindex_received`: Precondition observation: the leader postponed the received request because no entry of its term was committed (committed_entry_term 1, leader_term 2).
Declared predicate: `{"assertion": {"field": "stashed", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `confchange_applied`: Witness: applying the committed removal of voter 4 performed the leader's first commit of term 2 (committed 10 -> 11, committed_entry_term 2 == leader_term), so the postponed request is due to be answered, but it is still pending and no ReadState was produced.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `confchange_applied`: Variant of the same cause: applying the committed zero change left the joint configuration, so the incoming half committed the leader's first term-2 entry, yet the postponed request is still pending.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [11] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `heartbeat_round`: No repair from the periodic round: two heartbeats are sent with an empty read context (heartbeat_ctx_len 0), the delayed acknowledgement of the previous configuration is already in place (match_3 11), and no ReadState is produced.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [5] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `unrelated_commit`: Control: an unrelated proposal committed by the new configuration releases the postponed request (released_request_ctx A), so the release mechanism works and is reached only through the MsgAppResp commit path.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `unrelated_commit`: Control for the joint variant: the postponed request is only released once the unrelated proposal is committed.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `cb953bd819f247b8b30ac4d1e47e6c4c-experiment` v2: [saved basis](fixed-experiments/cb953bd819f247b8b30ac4d1e47e6c4c-experiment/basis.json).
Scope: Observe the whole interval of one postponed ReadIndex request for two completion paths on the same 4-node group: a local request answered into leader 1's readStates, and a forwarded request (client to follower 2, follower forwards to leader 1) whose answer must be a MsgReadIndexResp delivered back to node 2. In both paths the application then applies an already-committed configuration change whose resulting configuration performs the leader's first commit of the term.
History / supplied conditions: For each case: build four nodes whose storage is bootstrapped with the case ConfState (voters {1,2,3,4}, or the joint configuration voters {1,2,3} + voters_outgoing {1,2,3,4}), append ten term-1 entries with entry 10 the case configuration change, persist HardState{Term:1,Commit:10} and set Applied=10; elect node 1 with a real MsgHup/MsgVote/MsgVoteResp round (voter 4 unreachable, voter 3's MsgAppResp delayed); deliver the read request (locally to node 1, or to follower 2 which forwards it); apply the committed change at index 10 via applyConfChange; deliver the delayed acknowledgement; run one heartbeat round (tick); finally propose one unrelated entry.
Assumptions: Four voters {1,2,3,4} bootstrapped from a ConfState-only snapshot, log entries 1..9 ordinary and entry 10 the configuration change, HardState{Term:1, Commit:10}, applied index 10 (the application reported applied progress but has not yet called ApplyConfChange for entry 10, which node.go:166-187 permits).; Transport preserves raft's per-message semantics; voter 4 is unreachable and voter 3's append acknowledgements are delayed (message loss/delay).; The forwarded request is produced by delivering MsgReadIndex without a From to follower 2, so follower 2 forwards it to the leader it knows, exactly as the Node.ReadIndex path does.
Excluded scope: Pre-vote, check-quorum and lease-based reads.; Snapshot-based recovery and asynchronous storage writes.
Predecessor `8769550822c045a18219e24795b9bdc0-experiment`; revision reason: The harness now also contains the forwarded-completion variant of the same scenario: the client's read reaches follower 2, which forwards it to leader 1, so the answer owed for the postponed request is a MsgReadIndexResp delivered to node 2 rather than a local ReadState. The earlier cases and comparisons are kept.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: A ReadIndex request that a leader accepts by postponing (raft.go:1363-1368) must be answered once the leader has committed an entry of its term, whichever path performs that commit (raft.go:1550-1554 for the MsgAppResp path, raft.go:2013-2028 for the switchToConfig path), because the helper that discharges the duty is guarded only by committedEntryInCurrentTerm() (raft.go:2127-2145) and the caller's comment states the release is due once the committed index has progressed for the term.
Execution `f6f942daf8df40abb36626675d6923fb`: completed, exit code 0; [receipt](logs/f6f942daf8df40abb36626675d6923fb/check.json), [full observations](logs/f6f942daf8df40abb36626675d6923fb/observations.json), [stdout](logs/f6f942daf8df40abb36626675d6923fb/stdout.log), [stderr](logs/f6f942daf8df40abb36626675d6923fb/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `236a9ffeb4824e6f8ac232cc9fd69ac6-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.
Evidence limitations: Comparison 1: the attributed interpretation does not cite its violating events; Comparison 2: the attributed interpretation does not cite its violating events; Comparison 3: the attributed interpretation does not cite its violating events

Comparison 0 · `readindex_received`: Precondition observation: the leader postponed the received request because no entry of its term was committed (committed_entry_term 1, leader_term 2).
Declared predicate: `{"assertion": {"field": "stashed", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 17 {'case': 'remove-voter-4-forwarded-read'}: Admitted operation has no complete applicable result observation

Comparison 1 · `confchange_applied`: Witness: applying the committed removal of voter 4 performed the leader's first commit of term 2 (committed 10 -> 11, committed_entry_term 2 == leader_term), so the postponed request is due to be answered, but it is still pending and no ReadState was produced.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `confchange_applied`: Variant of the same cause: applying the committed zero change left the joint configuration, so the incoming half committed the leader's first term-2 entry, yet the postponed request is still pending.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [11] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `heartbeat_round`: No repair from the periodic round: two heartbeats are sent with an empty read context (heartbeat_ctx_len 0), the delayed acknowledgement of the previous configuration is already in place (match_3 11), and no ReadState is produced.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [5] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `unrelated_commit`: Control: an unrelated proposal committed by the new configuration releases the postponed request (released_request_ctx A), so the release mechanism works and is reached only through the MsgAppResp commit path.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 22 {'case': 'remove-voter-4-forwarded-read'}: Operation admission history: No corresponding prerequisite events reached: stash/readindex_received, cc/confchange_applied

Comparison 5 · `unrelated_commit`: Control for the joint variant: the postponed request is only released once the unrelated proposal is committed.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 22 {'case': 'remove-voter-4-forwarded-read'}: Operation admission history: No corresponding prerequisite events reached: stash/readindex_received, cc/confchange_applied

Comparison 6 · `fwd_readindex_forwarded`: Forwarded-path premise: follower 2 (StateFollower, known leader 1) emits MsgReadIndex addressed to leader 1, so the answer owed is a MsgReadIndexResp to node 2.
Declared predicate: `{"assertion": {"field": "forwarded_to_leader", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 1 {'case': 'apply-removal-of-unreachable-voter-4'}: Admitted operation has no complete applicable result observation; Event 9 {'case': 'apply-leave-joint-config'}: Admitted operation has no complete applicable result observation

Comparison 7 · `fwd_readindex_stashed`: Forwarded-path premise: the leader postponed the forwarded request because no entry of its term was committed.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `fwd_confchange_applied`: Forwarded-path witness: applying the committed change performed the leader's first commit of term 2 (committed 10 -> 11, committed_entry_term 2 == leader_term) yet no MsgReadIndexResp was emitted and follower 2 received no ReadState, so the client's forwarded read stays unanswered.
Declared predicate: `{"assertion": {"field": "node2_read_states", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [20] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 9 · `fwd_unrelated_commit`: Forwarded-path control: the unrelated proposal committed by the new configuration releases the postponed request, and only then does follower 2 receive the MsgReadIndexResp (ctx A, index 12).
Declared predicate: `{"assertion": {"field": "readindex_responses_emitted", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `236a9ffeb4824e6f8ac232cc9fd69ac6-experiment` v3: [saved basis](fixed-experiments/236a9ffeb4824e6f8ac232cc9fd69ac6-experiment/basis.json).
Scope: Observe the whole interval of one postponed ReadIndex request for two completion paths on the same 4-node group: a local request answered into leader 1's readStates, and a forwarded request (client to follower 2, follower forwards to leader 1) whose answer must be a MsgReadIndexResp delivered back to node 2. In both paths the application then applies an already-committed configuration change whose resulting configuration performs the leader's first commit of the term.
History / supplied conditions: For each case: build four nodes whose storage is bootstrapped with the case ConfState (voters {1,2,3,4}, or the joint configuration voters {1,2,3} + voters_outgoing {1,2,3,4}), append ten term-1 entries with entry 10 the case configuration change, persist HardState{Term:1,Commit:10} and set Applied=10; elect node 1 with a real MsgHup/MsgVote/MsgVoteResp round (voter 4 unreachable, voter 3's MsgAppResp delayed); deliver the read request (locally to node 1, or to follower 2 which forwards it); apply the committed change at index 10 via applyConfChange; deliver the delayed acknowledgement; run one heartbeat round (tick); finally propose one unrelated entry.
Assumptions: Four voters {1,2,3,4} bootstrapped from a ConfState-only snapshot, log entries 1..9 ordinary and entry 10 the configuration change, HardState{Term:1, Commit:10}, applied index 10 (the application reported applied progress but has not yet called ApplyConfChange for entry 10, which node.go:166-187 permits).; Transport preserves raft's per-message semantics; voter 4 is unreachable and voter 3's append acknowledgements are delayed (message loss/delay).; The forwarded request is produced by delivering MsgReadIndex without a From to follower 2, so follower 2 forwards it to the leader it knows; the forwarded case emits only fwd_-prefixed events so that each prerequisite alias is matched by exactly one case.
Excluded scope: Pre-vote, check-quorum and lease-based reads.; Snapshot-based recovery and asynchronous storage writes.
Predecessor `cb953bd819f247b8b30ac4d1e47e6c4c-experiment`; revision reason: The forwarded variant previously reused the shared event names (setup, election, delayed_ack_delivered, heartbeat_round), so the aliases of the existing comparisons admitted operations whose result observation does not exist for that case and four comparisons came back unknown in CheckRun f6f942daf8df40abb36626675d6923fb. The forwarded case now emits only fwd_-prefixed events, so every admitted operation has its own result observation while the earlier cases and comparisons stay unchanged.; actual changes: harness, scope
Declared requirement / prediction: A ReadIndex request that a leader accepts by postponing (raft.go:1363-1368) must be answered once the leader has committed an entry of its term, whichever path performs that commit (raft.go:1550-1554 for the MsgAppResp path, raft.go:2013-2028 for the switchToConfig path), because the helper that discharges the duty is guarded only by committedEntryInCurrentTerm() (raft.go:2127-2145) and the caller's comment states the release is due once the committed index has progressed for the term.
Execution `a1859bb05261498c820729722eef035f`: completed, exit code 0; [receipt](logs/a1859bb05261498c820729722eef035f/check.json), [full observations](logs/a1859bb05261498c820729722eef035f/observations.json), [stdout](logs/a1859bb05261498c820729722eef035f/stdout.log), [stderr](logs/a1859bb05261498c820729722eef035f/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `0d78c1124cd84dd5967e78b6ecc69820-interpretation-0` (violated; historical interpretation; the question has a later account).
Other current question interpretations explicitly citing this receipt: [63c5875253ff45f0b609b3c0ee4c71d7-interpretation-0](state.json) (question `8769550822c045a18219e24795b9bdc0-question-0`, fixed-experiment attribution: ce111f77e8d4430ab1fca3ff482b3cd1-experiment; event indices [2, 3, 5, 6, 11, 14, 18, 19, 20, 23]).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `readindex_received`: Precondition observation: the leader postponed the received request because no entry of its term was committed (committed_entry_term 1, leader_term 2).
Declared predicate: `{"assertion": {"field": "stashed", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `confchange_applied`: Witness: applying the committed removal of voter 4 performed the leader's first commit of term 2 (committed 10 -> 11, committed_entry_term 2 == leader_term), so the postponed request is due to be answered, but it is still pending and no ReadState was produced.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `confchange_applied`: Variant of the same cause: applying the committed zero change left the joint configuration, so the incoming half committed the leader's first term-2 entry, yet the postponed request is still pending.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [11] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `heartbeat_round`: No repair from the periodic round: two heartbeats are sent with an empty read context (heartbeat_ctx_len 0), the delayed acknowledgement of the previous configuration is already in place (match_3 11), and no ReadState is produced.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [5] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `unrelated_commit`: Control: an unrelated proposal committed by the new configuration releases the postponed request (released_request_ctx A), so the release mechanism works and is reached only through the MsgAppResp commit path.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-removal-of-unreachable-voter-4"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `unrelated_commit`: Control for the joint variant: the postponed request is only released once the unrelated proposal is committed.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "applicability_conditions": [{"field": "case", "op": "eq", "value": "apply-leave-joint-config"}]}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `fwd_readindex_forwarded`: Forwarded-path premise: follower 2 (StateFollower, known leader 1) emits MsgReadIndex addressed to leader 1, so the answer owed is a MsgReadIndexResp to node 2.
Declared predicate: `{"assertion": {"field": "forwarded_to_leader", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 7 · `fwd_readindex_stashed`: Forwarded-path premise: the leader postponed the forwarded request because no entry of its term was committed.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `fwd_confchange_applied`: Forwarded-path witness: applying the committed change performed the leader's first commit of term 2 (committed 10 -> 11, committed_entry_term 2 == leader_term) yet no MsgReadIndexResp was emitted and follower 2 received no ReadState, so the client's forwarded read stays unanswered.
Declared predicate: `{"assertion": {"field": "node2_read_states", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [20] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 9 · `fwd_unrelated_commit`: Forwarded-path control: the unrelated proposal committed by the new configuration releases the postponed request, and only then does follower 2 receive the MsgReadIndexResp (ctx A, index 12).
Declared predicate: `{"assertion": {"field": "readindex_responses_emitted", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `ce111f77e8d4430ab1fca3ff482b3cd1-experiment` v4: [saved basis](fixed-experiments/ce111f77e8d4430ab1fca3ff482b3cd1-experiment/basis.json).
Scope: Observe a postponed ReadIndex request through the Node interface of a wrapped leader whose application has reported applied progress past a committed configuration change without having applied it yet, and then applies that change: the decisive observation is whether any Ready delivers the ReadState for the request once the leader has committed an entry of its term.
History / supplied conditions: Build the wrapped leader over the four-voter fixture, pump its Readys (persisting buffers and calling Advance) without calling ApplyConfChange so that applied index 10 is reported while the tracker still holds voters=(1 2 3 4); campaign through the Node interface and pump until it reports StateLeader at term 2 with its term entry acknowledged only by voter 2; issue ReadIndex with context A and pump; then call ApplyConfChange for the committed removal of voter 4 and pump, recording every ReadState the Readys deliver.
Assumptions: The wrapped node 1 is a four-voter group {1,2,3,4} whose storage holds ten term-1 entries with the last one removing voter 4, and a persisted HardState committing index 10.; Voter 2 is a bare raft instance whose acknowledgements are delivered; voter 3 is a bare raft instance whose append acknowledgements are held (delayed), and voter 4 is unreachable, so the leader cannot commit under the configuration it still has.; The application consumes Readys, writes entries, hard state and snapshots to the leader's storage, calls Advance (reported applied progress through index 10) and only later calls ApplyConfChange for the change it observed; the campaign and the ReadIndex request are issued through the Node interface.
Excluded scope: StepDownOnRemoval, CheckQuorum and PreVote configurations.; Snapshots and asynchronous storage writes.; Lease-based reads.
Predecessor `236a9ffeb4824e6f8ac232cc9fd69ac6-experiment`; revision reason: The harness now drives the scenario through the public Node/Ready contract instead of a supplied applied index: the application consumes the wrapped leader's Readys and calls Advance while it is still applying the committed configuration change (node.go:166-187 permits this), campaigns, issues its ReadIndex request, and only then calls ApplyConfChange for that change. The comparisons read the delivered ReadStates and the leader's own status rather than internal fields.; actual changes: harness, source_ids, scope, prefix, requirement, responsibility, comparisons
Declared requirement / prediction: A ReadIndex request that a leader accepts by postponing must be answered once the leader has committed an entry of its term, whichever path performs that commit (raft.go:1550-1554 for the MsgAppResp path, raft.go:2013-2028 for the switchToConfig path), because the helper that discharges the duty is guarded only by committedEntryInCurrentTerm() (raft.go:2127-2145).
Execution `c86ee7b6e6604a269dc8aff31adce625`: completed, exit code 0; [receipt](logs/c86ee7b6e6604a269dc8aff31adce625/check.json), [full observations](logs/c86ee7b6e6604a269dc8aff31adce625/observations.json), [stdout](logs/c86ee7b6e6604a269dc8aff31adce625/stdout.log), [stderr](logs/c86ee7b6e6604a269dc8aff31adce625/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `63c5875253ff45f0b609b3c0ee4c71d7-interpretation-0` (violated; current question interpretation).

Comparison 0 · `leader_elected`: Premise: the wrapped node became leader at term 2 through the Node campaign path.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `readindex_requested`: Premise: the ReadIndex request issued through the Node interface was postponed (no entry of the leader's term committed yet).
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `conf_change_applied`: Witness: applying the committed change performed the leader's first commit of term 2 (committed 10 -> 11 with committed_entry_term 2), yet no Ready delivered a ReadState for context A.
Declared predicate: `{"assertion": {"field": "read_states_for_request", "op": "eq", "value": 1}, "antecedent": {"field": "term_has_commit", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `conf_change_applied`: Witness: the postponed request is still held after that commit.
Declared predicate: `{"assertion": {"field": "pending_reads", "op": "eq", "value": 0}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Interpretation history:

- [8769550822c045a18219e24795b9bdc0-interpretation-0](state.json) → [95b5c02c9cf545e0bd46770a16fe6d29-interpretation-0](state.json): conditional → violated; model claim asserted → asserted; changed fields: experiment_id, executions, conclusion, rationale, answers, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [95b5c02c9cf545e0bd46770a16fe6d29-interpretation-0](state.json) → [236a9ffeb4824e6f8ac232cc9fd69ac6-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, answers, knowledge, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [236a9ffeb4824e6f8ac232cc9fd69ac6-interpretation-0](state.json) → [0d78c1124cd84dd5967e78b6ecc69820-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [0d78c1124cd84dd5967e78b6ecc69820-interpretation-0](state.json) → [63c5875253ff45f0b609b3c0ee4c71d7-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
### What does raft do with a ReadIndex request that reaches a node which is no longer a voter of its own configuration, and is the outcome safe - either the request is answered with a current index, or it is refused and retried elsewhere?

Current disposition: active.
Question `9ad1a10e85bb41578fbb8a42a6890ab3-question-0` v9; sources: tracker-singleton, readindex-singleton-branch, prop-removed-leader, switchtoconfig-removal, config-stepdown-doc, readonlysafe-doc, node-readindex-contract ([full references](state.json)).
Current model defect claim: defect asserted (subject to independent verification).

Current interpretation `336a717040a443128fcbb6e3c7c10f9f-interpretation-0` · declared predicate does not hold: Five receipts now cover the same removal in five configurations, and none of them produces the safe outcome the question allows. Source side: tracker.IsSingleton is a size test whose comment asserts that the single voting member is the leader (tracker/tracker.go:158-162); stepLeader's MsgReadIndex case answers from that test without a round (raft.go:1354-1361) and otherwise takes the read-only path, in which it adds the request and counts its own acknowledgement before broadcasting heartbeats; the answer leaves as a MsgReadIndexResp whenever the requester is another node (raft.go:2072-2087) and a follower forwards its read to the leader it knows (raft.go:1764-1770); the write path refuses proposals from a leader that is not in the configuration (raft.go:1294-1303) while the read path has no such guard, and applying a committed removal of the leading node leaves it leading under the default StepDownOnRemoval=false (raft.go:1985-2012, 282-287); a voter inside its election-timeout lease ignores a vote request from a higher term (in-lease guard), which is why a remainder that keeps hearing the removed leader elects nobody. Measured: (1) singleton remainder, CheckQuorum - the stale answer at parsed index 14 of the first receipt against the actual leader's committed index, that leader's control answer at parsed index 4, the one-tick step-down at parsed index 15 and the unanswered read afterwards at parsed index 16; (2) singleton remainder, PreVote - same shape, every comparison resolved; (3) forwarded route, PreVote singleton - the learner consumes the answer as its own read state with index 4 violated against the actual leader's committed 4 (receipt 815614d0 indices 3-4), control at 5, one-tick step-down (6), retry unanswered (7); (4) two-voter remainder, PreVote - the shortcut cannot apply at its parsed index 1, the removed leader takes the request into readOnly at its parsed index 3, steps down after one tick at its parsed index 4 and the accepted request is gone with no answer and no refusal at its violated parsed index 5; (5) two-voter remainder, CheckQuorum - the removal leaves node 1 leading voters (2 3) at its parsed index 1, three heartbeat rounds pass with node 2 and node 3 still followers at term 1 and no replacement elected at its holding parsed index 2, the read is taken into readOnly with two heartbeats broadcast at its holding parsed index 3, and after three further rounds node 1 is still the leader and the request is answered at its violated parsed index 4 (state_is_leader true, read_answered true, unconfirmed_reads back to 0, read_states 1). The last receipt therefore corrects the account's earlier bound: the one-tick end of the exposure is not a property of the quorum option alone but of a replacement leader existing - in the singleton remainder the remaining voter elects itself, and under PreVote the voters grant a new election, while with CheckQuorum and a multi-voter remainder the voters keep answering the removed leader, refuse each other's votes inside their leases, and elect nobody, so the removed leader keeps leading and answers the read from a round whose quorum it counted itself into although it is not one of the configuration's voters. The outcome is safe in none of the five configurations: a frozen index is handed out where the shortcut applies, an accepted request is lost without answer or refusal where the remainder is larger and the leader's term turns, and where CheckQuorum holds the voters in lease the removed leader keeps serving from a round the current configuration did not confirm.

Sources: [tracker-singleton](state.json), [readindex-singleton-branch](state.json), [readindex-follower-forward](state.json), [readindex-forwarded-response](state.json), [readonlysafe-doc](state.json), [heartbeatresp-readonly](state.json), [readonly-maybeadvance](state.json), [prop-removed-leader](state.json), [switchtoconfig-removal](state.json), [config-stepdown-doc](state.json), [inlease-vote-guard](state.json), [node-readindex-contract](state.json), [readme-linearizable](state.json); execution evidence: [11c411f5e9734ad6bb95fffd61f1b7c8](logs/11c411f5e9734ad6bb95fffd61f1b7c8/check.json) ([observations](logs/11c411f5e9734ad6bb95fffd61f1b7c8/observations.json), event indices [1, 2, 3, 4]); [79d6bcb6f89a41dbbd391a742cdf9916](logs/79d6bcb6f89a41dbbd391a742cdf9916/check.json) ([observations](logs/79d6bcb6f89a41dbbd391a742cdf9916/observations.json), event indices [1, 2, 3, 4, 5]); [815614d02b874bc8b0661039ae0552da](logs/815614d02b874bc8b0661039ae0552da/check.json) ([observations](logs/815614d02b874bc8b0661039ae0552da/observations.json), event indices [1, 2, 3, 4, 5, 6, 7]); [c72c66880fd9498ca1efb95774b0b06e](logs/c72c66880fd9498ca1efb95774b0b06e/check.json) ([observations](logs/c72c66880fd9498ca1efb95774b0b06e/observations.json), event indices [1, 2, 3, 4, 5]); [8090da09e0d44e13af56696a62f13d45](logs/8090da09e0d44e13af56696a62f13d45/check.json) ([observations](logs/8090da09e0d44e13af56696a62f13d45/observations.json), event indices [12, 13, 14, 15, 16]).
Interpretation counterevidence: The controls hold in the singleton receipts (parsed index 4 of 8090da09e0d44e13af56696a62f13d45, parsed index 5 of 815614d02b874bc8b0661039ae0552da): the node that is the configuration's voter answers its own read with an index that covers its commit index, so the defect is the answering node's membership, not the singleton answer itself.; The CheckQuorum multi-voter receipt hands out no stale index: no new leader exists there and no entry is committed behind the removed leader's back (both committed indices are 2), so what the receipt shows is that the answering round counted the removed leader's own acknowledgement - a confirmation defect, not yet a stale read.; The same receipt's setup event still carries the field prevote:true, a label copied from the PreVote harness the file was derived from; the executed configuration set Config.CheckQuorum=true and left PreVote false, as the scope of the fixed experiment states.; The voters in that receipt were never ticked, so their election timers did not expire; the receipt shows that the removed leader keeps its lease over six rounds it initiates, not that a ticked voter could never campaign and win.; The two-voter PreVote receipt shows the opposite outcome in the same membership shape (the accepted request is lost without an answer), so the multi-voter defect is configuration-dependent: PreVote ends the leadership, CheckQuorum holds it.; The Node.ReadIndex contract tells callers that requests can be lost without notice and that retries are their duty (node.go:218-224); the receipts add that in this state nothing in the request's path refuses the caller, so only an application that retries unconditionally is safe.
Interpretation limitations: Every scenario needs an application that applies the committed change removing the leading node while Config.StepDownOnRemoval is false and keeps that node running; applications that set the option, or that stop the removed node, do not reach the state.; The witnesses are at the ReadIndex contract level: the receipts show the index handed to the reader (locally or across the wire), or the request disappearing, or a round that counted a non-member - no state machine was run, so a served value that misses an entry is a consequence of the contract rather than a measured value.; The tick ratio is one heartbeat tick against ten election ticks in all five configurations; the multi-voter CheckQuorum receipt delivers no ticks to the voters, so the length of that exposure is unbounded within the receipt.; The lease-based configuration is still supported by source reading rather than by a retained receipt, and read-only rounds that fail (a leader that cannot reach a quorum) are not measured.
Hypothesis: tracker.IsSingleton() only checks that the configuration has one voter, and stepLeader answers MsgReadIndex locally whenever it is true. A leader whose removal the application applied (StepDownOnRemoval false) therefore keeps answering reads immediately with its own, frozen commit index, even though the library knows from its own tracker that the single voter is another node; the write path guards exactly this case, the read path does not.
Registered discriminator: Whether an application using the Node wrapper is handed the same stale index, or the same unanswered request, as the raft-level witnesses; and whether the voters of a multi-voter remainder eventually elect a replacement once their own election timers run, or stay in the removed leader's lease indefinitely.

Fixed experiment `9ad1a10e85bb41578fbb8a42a6890ab3-experiment` v1: [saved basis](fixed-experiments/9ad1a10e85bb41578fbb8a42a6890ab3-experiment/basis.json).
Scope: Observe what raft answers for a ReadIndex request that arrives at a node which the application removed from its configuration while it was leading (StepDownOnRemoval false), after the remaining voter has become leader of the reduced single-voter configuration and committed an entry the removed leader never receives.
History / supplied conditions: Elect node 1 leader of {1,2} with a real MsgHup/MsgVote round, let the application apply the committed empty entry, propose and apply the removal of node 1 on both nodes, then elect node 2 in the reduced configuration {2} and commit one proposal on it; then issue MsgReadIndex to node 1, then the same request to node 2, then three heartbeat intervals on node 1 and a second MsgReadIndex to node 1.
Assumptions: Two voters {1,2} in one process, ReadOnlySafe, default Config (StepDownOnRemoval false, CheckQuorum false, PreVote false).; Node 1 is elected leader, then the application proposes and applies the committed configuration change that removes node 1 on both nodes.; Node 2 campaigns and commits one entry; no message from the current configuration reaches node 1 (its heartbeats at the old term are ignored by node 2 because CheckQuorum and PreVote are disabled).
Excluded scope: Lease-based reads (ReadOnlyLeaseBased).; Check-quorum and pre-vote configurations, which give a leader another way to learn that it is stale.; Snapshot transfer and asynchronous storage writes.
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `c39e3b84d6174ce390e9320c9d2bab1b`: completed, exit code 0; [receipt](logs/c39e3b84d6174ce390e9320c9d2bab1b/check.json), [full observations](logs/c39e3b84d6174ce390e9320c9d2bab1b/observations.json), [stdout](logs/c39e3b84d6174ce390e9320c9d2bab1b/stdout.log), [stderr](logs/c39e3b84d6174ce390e9320c9d2bab1b/stderr.log).
Mechanical comparison: comparison undetermined (`unknown`).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.
Evidence limitations: Execution has no interpretation directly attributed to this fixed experiment

Comparison 0 · `leader_removed`: The node whose removal the application applied is still leading, with a configuration whose single voter is another node (singleton true, is_voter false).
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 1 {'step': 'leader-1-removed'}: No corresponding prerequisite events reached: setup/setup; Event 0 {'step': 'setup'}: Admitted operation has no complete applicable result observation

Comparison 1 · `new_leader_committed`: The actual leader of the reduced configuration has committed an entry that the removed leader's commit index does not cover (committed 4 vs 2).
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 2 {'step': 'node-2-leads'}: No corresponding prerequisite events reached: removed/leader_removed; Event 1 {'step': 'leader-1-removed'}: Admitted operation has no complete applicable result observation

Comparison 2 · `stale_read_answered`: Witness: the removed leader answered the ReadIndex request with index 2, below the commit index 4 the actual leader already had, without sending any message (heartbeats_emitted 0, messages_emitted empty, pending_reads 0).
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 3 {'step': 'read-via-removed-leader'}: No corresponding prerequisite events reached: newlead/new_leader_committed; Event 2 {'step': 'node-2-leads'}: Admitted operation has no complete applicable result observation

Comparison 3 · `control_read_actual_leader`: Control: the same request answered by the node that is the actual leader of the configuration returns an index that covers its commit index, so the local singleton answer is only unsafe on the node that is no longer the voter.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 4 {'step': 'read-via-actual-leader'}: No corresponding prerequisite events reached: stale/stale_read_answered; Event 3 {'step': 'read-via-removed-leader'}: Admitted operation has no complete applicable result observation

Comparison 4 · `second_stale_read`: No repair from the periodic path: after three heartbeat intervals and no replies from the current configuration, the removed leader is still leading at its old term and still answers with the same stale index.
Declared predicate: `{"assertion": {"field": "same_stale_index_as_first", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 5 {'step': 'read-via-removed-leader-after-heartbeats'}: No corresponding prerequisite events reached: control/control_read_actual_leader; Event 4 {'step': 'read-via-actual-leader'}: Admitted operation has no complete applicable result observation

Fixed experiment `8f8a7578765146509956132f0183a8c3-experiment` v2: [saved basis](fixed-experiments/8f8a7578765146509956132f0183a8c3-experiment/basis.json).
Scope: Observe what raft answers for a ReadIndex request that arrives at a node which the application removed from its configuration while it was leading (StepDownOnRemoval false), after the remaining voter has become leader of the reduced single-voter configuration and committed an entry the removed leader never receives.
History / supplied conditions: Elect node 1 leader of {1,2} with a real MsgHup/MsgVote round, let the application apply the committed empty entry, propose and apply the removal of node 1 on both nodes, then elect node 2 in the reduced configuration {2} and commit one proposal on it; then issue MsgReadIndex to node 1, then the same request to node 2, then three heartbeat intervals on node 1 and a second MsgReadIndex to node 1.
Assumptions: Two voters {1,2} in one process, ReadOnlySafe, default Config (StepDownOnRemoval false, CheckQuorum false, PreVote false).; Node 1 is elected leader, then the application proposes and applies the committed configuration change that removes node 1 on both nodes.; Node 2 campaigns and commits one entry; no message from the current configuration reaches node 1 (its heartbeats at the old term are ignored by node 2 because CheckQuorum and PreVote are disabled).
Excluded scope: Lease-based reads (ReadOnlyLeaseBased).; Check-quorum and pre-vote configurations, which give a leader another way to learn that it is stale.; Snapshot transfer and asynchronous storage writes.
Predecessor `9ad1a10e85bb41578fbb8a42a6890ab3-experiment`; revision reason: The first execution of this basis (CheckRun c39e3b84d6174ce390e9320c9d2bab1b) parsed all six events without loss but returned unknown for all five comparisons, with the diagnostics 'No corresponding prerequisite events reached' and 'No complete applicable result observation': identity_fields used the per-event step value, so no prerequisite event could satisfy the witness identity check. The harness now stamps a shared scenario field on every event, and the prerequisite aliases are correlated through it so that each compared event, its admission alias and the alias chain belong to the same scenario.; actual changes: harness, comparisons
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `bc8372740399467686bed25385e51001`: completed, exit code 0; [receipt](logs/bc8372740399467686bed25385e51001/check.json), [full observations](logs/bc8372740399467686bed25385e51001/observations.json), [stdout](logs/bc8372740399467686bed25385e51001/stdout.log), [stderr](logs/bc8372740399467686bed25385e51001/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `09239ebbabb4422fb88c4069ab88d741-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `leader_removed`: The node whose removal the application applied is still leading, with a configuration whose single voter is another node (singleton true, is_voter false).
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `new_leader_committed`: The actual leader of the reduced configuration has committed an entry that the removed leader's commit index does not cover (committed 4 vs 2).
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `stale_read_answered`: Witness: the removed leader answered the ReadIndex request with index 2, below the commit index 4 the actual leader already had, without sending any message (heartbeats_emitted 0, messages_emitted empty, pending_reads 0).
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `control_read_actual_leader`: Control: the same request answered by the node that is the actual leader of the configuration returns an index that covers its commit index, so the local singleton answer is only unsafe on the node that is no longer the voter.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `second_stale_read`: No repair from the periodic path: after three heartbeat intervals and no replies from the current configuration, the removed leader is still leading at its old term and still answers with the same stale index.
Declared predicate: `{"assertion": {"field": "same_stale_index_as_first", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `425ee562e1dc40a2928df98330de575c-experiment` v3: [saved basis](fixed-experiments/425ee562e1dc40a2928df98330de575c-experiment/basis.json).
Scope: Observe the removed-leader ReadIndex path in two configurations of the same removal: a reduced configuration with a single voter (node 2) and a reduced configuration with two voters (nodes 2 and 3), in both cases after the remaining voters elected a leader and committed a entry the removed leader never receives.
History / supplied conditions: Scenario A (single-voter remainder): elect node 1 in {1,2}, apply the committed removal of node 1, elect node 2 in {2} and commit one proposal, deliver MsgReadIndex to node 1, then deliver the same request to node 2, then run three heartbeat intervals on node 1 and deliver a second MsgReadIndex to node 1. Scenario B (two-voter remainder): elect node 1 in {1,2,3}, apply the committed removal of node 1 on all three nodes, elect node 2 in {2,3} and commit one proposal, deliver MsgReadIndex to node 1, then run three heartbeat intervals on node 1 and observe whether any answer is produced.
Assumptions: Two scenarios in one process: voters {1,2} where the removal leaves {2}, and voters {1,2,3} where the removal leaves {2,3}; ReadOnlySafe and default Config (StepDownOnRemoval false, CheckQuorum false, PreVote false).; In each scenario node 1 is elected leader, the application proposes and applies the committed removal of node 1 on every node, the remaining voters then elect node 2 and commit one entry, and only then is the ReadIndex request delivered to node 1.; Nothing from the current configuration carries a higher term back to node 1, so the removed leader stays at its old term while the observations are taken.
Excluded scope: Lease-based reads (ReadOnlyLeaseBased).; Check-quorum and pre-vote configurations, which give the removed leader another way to learn that it is stale.; Snapshot transfer and asynchronous storage writes.
Predecessor `8f8a7578765146509956132f0183a8c3-experiment`; revision reason: The harness now also contains the control scenario for the same cause: the identical two-voter removal but with a three-voter cluster, so the reduced configuration has two voters and the singleton shortcut does not apply to the removed leader. The comparison set keeps the earlier scenario and adds the control's observations, so the stale immediate answer can be distinguished from the alternative explanation that the removed leader simply keeps working as a leader for reads.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `e17ebb2095714b6289c41dc4e029e3d4`: completed, exit code 0; [receipt](logs/e17ebb2095714b6289c41dc4e029e3d4/check.json), [full observations](logs/e17ebb2095714b6289c41dc4e029e3d4/observations.json), [stdout](logs/e17ebb2095714b6289c41dc4e029e3d4/stdout.log), [stderr](logs/e17ebb2095714b6289c41dc4e029e3d4/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `b3c4a8e694814ae283d63a3f9459aa1e-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `leader_removed`: Scenario A premise: the node whose removal the application applied is still leading a configuration whose single voter is another node.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `new_leader_committed`: Scenario A premise: the actual leader of the reduced configuration has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `stale_read_answered`: Scenario A witness: the removed leader answered the read with an index below the commit index of the actual leader, sending no message at all.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `control_read_actual_leader`: Scenario A control: the same request answered by the actual leader returns an index that covers its commit index.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `second_stale_read`: Scenario A persistence: after three heartbeat intervals without replies the removed leader repeats the same stale index.
Declared predicate: `{"assertion": {"field": "same_stale_index_as_first", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `b_leader_removed`: Scenario B premise: the same removal leaves a configuration with two voters, so the singleton shortcut cannot apply to the removed leader (config voters=(2 3)).
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `b_new_leader_committed`: Scenario B premise: the new leader of {2,3} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 7 · `b_read_attempt`: Scenario B control outcome: the same read delivered to the removed leader produces no answer at all, and the leader instead enters the readOnly round (heartbeats_emitted 2 with a read context) - the stale immediate answer is specific to the singleton configuration.
Declared predicate: `{"assertion": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `b_read_attempt`: Scenario B second symptom: the accepted read stays in readOnly.unconfirmed_reads because the current configuration never acknowledges the removed leader's old-term heartbeats, so no repair exists for it inside raft.
Declared predicate: `{"assertion": {"field": "unconfirmed_reads", "op": "eq", "value": 0}, "antecedent": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [9] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 9 · `b_read_after_heartbeats`: Scenario B persistence: three further heartbeat intervals still produce no answer and no reply from the current configuration.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [10] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `bbdf8837c719466ba9f5044f34c9c29f-experiment` v4: [saved basis](fixed-experiments/bbdf8837c719466ba9f5044f34c9c29f-experiment/basis.json).
Scope: Observe the removed-leader ReadIndex path in three configurations of the same removal: a single-voter remainder, a two-voter remainder, and a single-voter remainder with CheckQuorum enabled (where the current leader answers the removed leader's old-term heartbeat with its higher term).
History / supplied conditions: Scenario A (single-voter remainder): elect node 1 in {1,2}, apply the committed removal of node 1, elect node 2 in {2} and commit one proposal, deliver MsgReadIndex to node 1, deliver the same request to node 2, run three heartbeat intervals on node 1 and deliver a second MsgReadIndex to node 1. Scenario B (two-voter remainder): elect node 1 in {1,2,3}, apply the committed removal on all three nodes, elect node 2 in {2,3} and commit one proposal, deliver MsgReadIndex to node 1, then run three heartbeat intervals on node 1. Scenario C (single-voter remainder with CheckQuorum): as scenario A with Config.CheckQuorum true, but the read is delivered before the removed leader has contacted the new leader, then one heartbeat tick is delivered and the step-down is observed, then a further MsgReadIndex is delivered.
Assumptions: Scenarios in one process: voters {1,2} where the removal leaves {2}; voters {1,2,3} where the removal leaves {2,3}; and voters {1,2} with Config.CheckQuorum true on both nodes; ReadOnlySafe and StepDownOnRemoval false in all of them.; In each scenario node 1 is elected leader, the application proposes and applies the committed removal of node 1 on every node, the remaining voters then elect node 2 and commit one entry, and only then is the ReadIndex request delivered to node 1.; In the CheckQuorum scenario the observations are taken before and after the first heartbeat tick of the removed leader, so the receipt covers both the window in which the stale answer is issued and the state after the step-down.
Excluded scope: Lease-based reads (ReadOnlyLeaseBased).; PreVote together with CheckQuorum.; Snapshot transfer and asynchronous storage writes.
Predecessor `425ee562e1dc40a2928df98330de575c-experiment`; revision reason: The harness now also contains a third scenario for the same cause: the single-voter removal with Config.CheckQuorum enabled, so the receipt can measure how long the removed leader keeps answering reads and what happens after it steps down. The earlier scenarios and their comparisons are kept.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `8090da09e0d44e13af56696a62f13d45`: completed, exit code 0; [receipt](logs/8090da09e0d44e13af56696a62f13d45/check.json), [full observations](logs/8090da09e0d44e13af56696a62f13d45/observations.json), [stdout](logs/8090da09e0d44e13af56696a62f13d45/stdout.log), [stderr](logs/8090da09e0d44e13af56696a62f13d45/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `7047250b7d2640f48c0dad5bdcfaba0e-interpretation-0` (violated; historical interpretation; the question has a later account).
Other current question interpretations explicitly citing this receipt: [336a717040a443128fcbb6e3c7c10f9f-interpretation-0](state.json) (question `9ad1a10e85bb41578fbb8a42a6890ab3-question-0`, fixed-experiment attribution: f87487ff302344ad90063b266f2302f5-experiment; event indices [12, 13, 14, 15, 16]).
Historical interpretations explicitly citing this receipt: 7 ([full records](state.json)); these are not current question accounts.
Evidence limitations: Comparison 2: the attributed interpretation does not cite its violating events; Comparison 8: the attributed interpretation does not cite its violating events; Comparison 9: the attributed interpretation does not cite its violating events

Comparison 0 · `leader_removed`: Scenario A premise: the node whose removal the application applied is still leading a configuration whose single voter is another node.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `new_leader_committed`: Scenario A premise: the actual leader of the reduced configuration has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `stale_read_answered`: Scenario A witness: the removed leader answered the read with an index below the commit index of the actual leader, sending no message at all.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `control_read_actual_leader`: Scenario A control: the same request answered by the actual leader returns an index that covers its commit index.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `second_stale_read`: Scenario A persistence: after three heartbeat intervals without replies the removed leader repeats the same stale index.
Declared predicate: `{"assertion": {"field": "same_stale_index_as_first", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `b_leader_removed`: Scenario B premise: the same removal leaves a configuration with two voters, so the singleton shortcut cannot apply to the removed leader (config voters=(2 3)).
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `b_new_leader_committed`: Scenario B premise: the new leader of {2,3} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 7 · `b_read_attempt`: Scenario B control outcome: the same read delivered to the removed leader produces no answer at all, and the leader instead enters the readOnly round (heartbeats_emitted 2 with a read context) - the stale immediate answer is specific to the singleton configuration.
Declared predicate: `{"assertion": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `b_read_attempt`: Scenario B second symptom: the accepted read stays in readOnly.unconfirmed_reads because the current configuration never acknowledges the removed leader's old-term heartbeats, so no repair exists for it inside raft.
Declared predicate: `{"assertion": {"field": "unconfirmed_reads", "op": "eq", "value": 0}, "antecedent": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [9] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 9 · `b_read_after_heartbeats`: Scenario B persistence: three further heartbeat intervals still produce no answer and no reply from the current configuration.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [10] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 10 · `c_leader_removed`: Scenario C premise: with CheckQuorum enabled the removal still leaves node 1 leading a configuration whose single voter is node 2, so the shortcut applies.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 11 · `c_new_leader_committed`: Scenario C premise: the new leader of {2} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 12 · `c_read_before_stepdown`: Scenario C witness before the step-down: enabling CheckQuorum does not remove the stale answer - the removed leader still answers with index 2 below the committed index 4 of the actual leader.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [14] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 13 · `c_stepdown`: Scenario C mitigation: the current leader answers the removed leader's old-term heartbeat with its higher term, so the removed leader becomes a follower (lead None) after one heartbeat tick.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateFollower"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 14 · `c_stepdown`: Scenario C bound: the stale-answer window is at most the heartbeat interval - one tick was enough for the step-down in the exercised configuration.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 15 · `c_read_after_stepdown`: Scenario C after the step-down: the same request is no longer answered (it is dropped because the node has no leader), so the exposure is bounded by the step-down rather than repaired inside raft.
Declared predicate: `{"assertion": {"field": "new_read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [16] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `eebf8913d47f4346a8a753292e43952f-experiment` v5: [saved basis](fixed-experiments/eebf8913d47f4346a8a753292e43952f-experiment/basis.json).
Scope: Observe the removed-leader ReadIndex path in four configurations of the same removal: a single-voter remainder, a two-voter remainder, a single-voter remainder with CheckQuorum enabled, and a single-voter remainder with PreVote enabled and CheckQuorum disabled.
History / supplied conditions: Scenario A (single-voter remainder): elect node 1 in {1,2}, apply the committed removal of node 1, elect node 2 in {2} and commit one proposal, deliver MsgReadIndex to node 1, deliver the same request to node 2, run three heartbeat intervals on node 1 and deliver a second MsgReadIndex to node 1. Scenario B (two-voter remainder): elect node 1 in {1,2,3}, apply the committed removal on all three nodes, elect node 2 in {2,3} and commit one proposal, deliver MsgReadIndex to node 1, then run three heartbeat intervals on node 1. Scenario C (single-voter remainder with CheckQuorum): as scenario A with Config.CheckQuorum true, but the read is delivered before the removed leader has contacted the new leader, then one heartbeat tick is delivered and the step-down is observed, then a further MsgReadIndex is delivered. Scenario D (single-voter remainder with PreVote and without CheckQuorum): as scenario C, but the read is delivered before the removed leader has contacted the new leader, then one heartbeat tick is delivered and the step-down is observed, then a further MsgReadIndex is delivered.
Assumptions: Scenarios in one process: voters {1,2} where the removal leaves {2}; voters {1,2,3} where the removal leaves {2,3}; and voters {1,2} with Config.CheckQuorum true on both nodes; ReadOnlySafe and StepDownOnRemoval false in all of them.; In each scenario node 1 is elected leader, the application proposes and applies the committed removal of node 1 on every node, the remaining voters then elect node 2 and commit one entry, and only then is the ReadIndex request delivered to node 1.; In the CheckQuorum scenario the observations are taken before and after the first heartbeat tick of the removed leader, so the receipt covers both the window in which the stale answer is issued and the state after the step-down.; In the PreVote scenario the observations are taken before and after the first heartbeat tick of the removed leader, as in the CheckQuorum scenario, so the receipt covers the window in which the stale answer is issued and the state after the step-down.
Excluded scope: Lease-based reads (ReadOnlyLeaseBased).; PreVote combined with CheckQuorum.; Snapshot transfer and asynchronous storage writes.
Predecessor `bbdf8837c719466ba9f5044f34c9c29f-experiment`; revision reason: The harness now also contains a fourth scenario for the same cause: the single-voter removal with Config.PreVote enabled and CheckQuorum disabled, so the receipt can measure whether the same code branch that bounds the window under CheckQuorum (the answer to a lower-term message carrying the receiver's term) also bounds it under PreVote alone. The earlier scenarios and comparisons are kept, and the harness was rebuilt from the retained basis after a bad copy damaged the draft.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `eaec4096389145f5a26353274b77a639`: completed, exit code 0; [receipt](logs/eaec4096389145f5a26353274b77a639/check.json), [full observations](logs/eaec4096389145f5a26353274b77a639/observations.json), [stdout](logs/eaec4096389145f5a26353274b77a639/stdout.log), [stderr](logs/eaec4096389145f5a26353274b77a639/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `41aa04d6f89f47f9ad833d25d2c6e73c-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.
Evidence limitations: Comparison 2: the attributed interpretation does not cite its violating events; Comparison 8: the attributed interpretation does not cite its violating events; Comparison 9: the attributed interpretation does not cite its violating events

Comparison 0 · `leader_removed`: Scenario A premise: the node whose removal the application applied is still leading a configuration whose single voter is another node.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `new_leader_committed`: Scenario A premise: the actual leader of the reduced configuration has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `stale_read_answered`: Scenario A witness: the removed leader answered the read with an index below the commit index of the actual leader, sending no message at all.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `control_read_actual_leader`: Scenario A control: the same request answered by the actual leader returns an index that covers its commit index.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `second_stale_read`: Scenario A persistence: after three heartbeat intervals without replies the removed leader repeats the same stale index.
Declared predicate: `{"assertion": {"field": "same_stale_index_as_first", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `b_leader_removed`: Scenario B premise: the same removal leaves a configuration with two voters, so the singleton shortcut cannot apply to the removed leader (config voters=(2 3)).
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `b_new_leader_committed`: Scenario B premise: the new leader of {2,3} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 7 · `b_read_attempt`: Scenario B control outcome: the same read delivered to the removed leader produces no answer at all, and the leader instead enters the readOnly round (heartbeats_emitted 2 with a read context) - the stale immediate answer is specific to the singleton configuration.
Declared predicate: `{"assertion": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `b_read_attempt`: Scenario B second symptom: the accepted read stays in readOnly.unconfirmed_reads because the current configuration never acknowledges the removed leader's old-term heartbeats, so no repair exists for it inside raft.
Declared predicate: `{"assertion": {"field": "unconfirmed_reads", "op": "eq", "value": 0}, "antecedent": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [9] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 9 · `b_read_after_heartbeats`: Scenario B persistence: three further heartbeat intervals still produce no answer and no reply from the current configuration.
Declared predicate: `{"assertion": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [10] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 10 · `c_leader_removed`: Scenario C premise: with CheckQuorum enabled the removal still leaves node 1 leading a configuration whose single voter is node 2, so the shortcut applies.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 17 {'scenario': 'removed-singleton-leader-read-prevote'}: Admitted operation has no complete applicable result observation

Comparison 11 · `c_new_leader_committed`: Scenario C premise: the new leader of {2} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 12 · `c_read_before_stepdown`: Scenario C witness before the step-down: enabling CheckQuorum does not remove the stale answer - the removed leader still answers with index 2 below the committed index 4 of the actual leader.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [14] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 13 · `c_stepdown`: Scenario C mitigation: the current leader answers the removed leader's old-term heartbeat with its higher term, so the removed leader becomes a follower (lead None) after one heartbeat tick.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateFollower"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 14 · `c_stepdown`: Scenario C bound: the stale-answer window is at most the heartbeat interval - one tick was enough for the step-down in the exercised configuration.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 15 · `c_read_after_stepdown`: Scenario C after the step-down: the same request is no longer answered (it is dropped because the node has no leader), so the exposure is bounded by the step-down rather than repaired inside raft.
Declared predicate: `{"assertion": {"field": "new_read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [16] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 16 · `e_leader_removed`: PreVote premise: the removal still leaves node 1 leading a configuration whose single voter is node 2, so the shortcut applies.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 18 {'scenario': 'removed-singleton-leader-read-prevote'}: No corresponding prerequisite events reached: esetup/e_setup

Comparison 17 · `e_new_leader_committed`: PreVote premise: the new leader of {2} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 19 {'scenario': 'removed-singleton-leader-read-prevote'}: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed; Event 18 {'scenario': 'removed-singleton-leader-read-prevote'}: Operation admission history: No corresponding prerequisite events reached: esetup/e_setup

Comparison 18 · `e_read_before_stepdown`: PreVote witness before the step-down: with PreVote only the removed leader still answers with index 2 below the committed index 4 of the actual leader.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 20 {'scenario': 'removed-singleton-leader-read-prevote'}: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed, enewlead/e_new_leader_committed; Event 19 {'scenario': 'removed-singleton-leader-read-prevote'}: Operation admission history: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed

Comparison 19 · `e_stepdown`: PreVote bound: one heartbeat tick is enough for the step-down, matching the guard (checkQuorum || preVote) on messages from a lower term.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 21 {'scenario': 'removed-singleton-leader-read-prevote'}: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed, enewlead/e_new_leader_committed, eread/e_read_before_stepdown; Event 20 {'scenario': 'removed-singleton-leader-read-prevote'}: Operation admission history: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed, enewlead/e_new_leader_committed

Comparison 20 · `e_read_after_stepdown`: PreVote after the step-down: the same request is no longer answered, so PreVote alone bounds the exposure as the source predicts.
Declared predicate: `{"assertion": {"field": "new_read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 22 {'scenario': 'removed-singleton-leader-read-prevote'}: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed, enewlead/e_new_leader_committed, eread/e_read_before_stepdown, estep/e_stepdown; Event 21 {'scenario': 'removed-singleton-leader-read-prevote'}: Operation admission history: No corresponding prerequisite events reached: esetup/e_setup, eremoved/e_leader_removed, enewlead/e_new_leader_committed, eread/e_read_before_stepdown

Fixed experiment `381d89a2dcdc44cd95d8cc9cb5bed4cb-experiment` v6: [saved basis](fixed-experiments/381d89a2dcdc44cd95d8cc9cb5bed4cb-experiment/basis.json).
Scope: Observe the removed-leader ReadIndex path when only PreVote is enabled: the same three-voter removal leaves a single-voter configuration, the remaining voter becomes leader and commits an entry, the removed leader answers a read before its next heartbeat tick, and the observations continue after that tick.
History / supplied conditions: Elect node 1 in {1,2,3} with a real MsgHup/MsgVote round, apply the committed removal of node 1 on all nodes, elect node 2 in {2} and commit one proposal, deliver MsgReadIndex to node 1, deliver one heartbeat tick of node 1 and pump its messages, then deliver a second MsgReadIndex to node 1.
Assumptions: Three voters {1,2,3} with PreVote enabled on every node and CheckQuorum disabled; node 1 is elected leader, the application proposes and applies the committed removal of node 1 on all three nodes, and node 2 then becomes leader of {2} and commits one entry.; The read is delivered to node 1 before it has contacted the new leader, then one heartbeat tick is delivered to node 1 and its messages are pumped, and then a second read is delivered.
Excluded scope: CheckQuorum and lease-based reads.; Snapshots and asynchronous storage writes.
Predecessor `eebf8913d47f4346a8a753292e43952f-experiment`; revision reason: The PreVote scenario now has its own self-contained harness and its own comparisons instead of sharing one prerequisite set with the other three scenarios, because the four-scenario basis left its new comparisons unknown (missing indices pointing at unmatched events of the last scenario). The harness contains only the PreVote scenario and copies the helpers it needs, so each alias's event appears exactly once.; actual changes: harness, source_ids, scope, prefix, responsibility, comparisons
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). The tracker's own comment for IsSingleton says the single voting member is the leader, so answering locally without any check is only sound when that member is the local node.
Execution `c72c66880fd9498ca1efb95774b0b06e`: completed, exit code 0; [receipt](logs/c72c66880fd9498ca1efb95774b0b06e/check.json), [full observations](logs/c72c66880fd9498ca1efb95774b0b06e/observations.json), [stdout](logs/c72c66880fd9498ca1efb95774b0b06e/stdout.log), [stderr](logs/c72c66880fd9498ca1efb95774b0b06e/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `6b71731acf2441de9145c5c6f1d03f8b-interpretation-0` (violated; historical interpretation; the question has a later account).
Other current question interpretations explicitly citing this receipt: [336a717040a443128fcbb6e3c7c10f9f-interpretation-0](state.json) (question `9ad1a10e85bb41578fbb8a42a6890ab3-question-0`, fixed-experiment attribution: f87487ff302344ad90063b266f2302f5-experiment; event indices [1, 2, 3, 4, 5]).
Historical interpretations explicitly citing this receipt: 3 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `e_leader_removed`: Premise: with PreVote enabled the removal still leaves node 1 leading a configuration whose single voter is node 2.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `e_new_leader_committed`: Premise: the new leader of {2} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `e_read_before_stepdown`: Witness before the step-down: with PreVote only, the removed leader answers with index 2 below the committed index 4 of the actual leader.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "antecedent": {"field": "read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [3] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `e_stepdown`: Bound: one heartbeat tick is enough for the step-down, matching the guard (checkQuorum || preVote) on messages from a lower term.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `e_read_after_stepdown`: After the step-down the same request is no longer answered, so PreVote alone bounds the exposure.
Declared predicate: `{"assertion": {"field": "new_read_states", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [5] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `6b71731acf2441de9145c5c6f1d03f8b-experiment` v1: [saved basis](fixed-experiments/6b71731acf2441de9145c5c6f1d03f8b-experiment/basis.json).
Scope: Observe the forwarded route into the same missing membership check. The group's voters are {1,2} and node 3 is its learner; node 1 is elected leader of {1,2}; the learner's application issues a read, which the follower path forwards to node 1; that forwarded request is held; the application proposes and applies the committed removal of node 1 on the two voters; node 2 becomes leader of {2} and commits one entry the removed leader never sees; the held request is then delivered to node 1 and its answer back to the learner, which consumes it; the actual leader's own read is taken as a control; one heartbeat tick is delivered to the removed leader and the learner asks again.
History / supplied conditions: Elect node 1 in a group of voters {1,2} and learner 3 with a real MsgHup/MsgPreVote/MsgVote round, let the learner's application issue a read that raft forwards to node 1 and hold that request, apply the committed removal of node 1 on the two voters, elect node 2 in {2} and commit one proposal, deliver the held request to node 1 and its answer to the learner, take the actual leader's own read as a control, deliver one heartbeat tick of node 1 and pump its messages, then let the learner ask again.
Assumptions: The initial group has voters {1,2} and learner 3 (withLearners(3)), PreVote is enabled on every node and CheckQuorum is disabled, the election tick is 10 and the heartbeat tick is 1, and node 1 is elected with a real MsgHup/MsgPreVote/MsgVote round so that every node, the learner included, knows node 1 as its leader.; The learner's application issues the read while node 1 is still the leader it knows, so raft forwards the request to node 1; the forwarded request and its answer are delivered by hand after the removal has been applied, standing for a delay that outlasts the reconfiguration.; The messages of node 2 are drained rather than delivered, so the requester has not yet heard from the new leader and still routes its read to node 1.
Excluded scope: CheckQuorum and lease-based reads.; Snapshots, asynchronous storage writes, and any state machine behind the read index.
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). A forwarded request is answered from the same singleton shortcut, but the answer leaves the node as a MsgReadIndexResp for the requester (raft.go:1354-1361, 2072-2087), so a stale index is consumed as another node's read state.
Execution `815614d02b874bc8b0661039ae0552da`: completed, exit code 0; [receipt](logs/815614d02b874bc8b0661039ae0552da/check.json), [full observations](logs/815614d02b874bc8b0661039ae0552da/observations.json), [stdout](logs/815614d02b874bc8b0661039ae0552da/stdout.log), [stderr](logs/815614d02b874bc8b0661039ae0552da/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `4f8260f004d94ca39484cbe058bc04f9-interpretation-0` (violated; historical interpretation; the question has a later account).
Other current question interpretations explicitly citing this receipt: [336a717040a443128fcbb6e3c7c10f9f-interpretation-0](state.json) (question `9ad1a10e85bb41578fbb8a42a6890ab3-question-0`, fixed-experiment attribution: f87487ff302344ad90063b266f2302f5-experiment; event indices [1, 2, 3, 4, 5, 6, 7]).
Historical interpretations explicitly citing this receipt: 2 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `e_leader_removed`: Premise: after the removal node 1 still leads and its configuration has exactly one voter, which is not node 1.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `e_new_leader_committed`: Premise: the new leader of {2} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `e_forwarded_request`: Premise: the learner's read was forwarded to node 1, the leader it knows, and node 1 answered it; the requester holds no read state of its own.
Declared predicate: `{"assertion": {"field": "forwarded_to_removed_leader", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `e_forwarded_read_state`: Witness: the answer the requester consumed carries an index below the committed index of the actual leader, so the requester would serve a read that misses that entry.
Declared predicate: `{"assertion": {"field": "read_index_at_least_other_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `e_leader_control`: Control: the node that is the configuration's only voter answers its own read with an index that covers its commit index.
Declared predicate: `{"assertion": {"field": "read_index_at_least_own_committed", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `e_stepdown`: Bound: one heartbeat tick is enough for the removed leader to learn of the new term and leave the leader state, matching the (checkQuorum || preVote) guard.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `e_after_stepdown_read_state`: After the window closed the same request is either not answered at all or answered with an index that covers the actual leader's commit index, so the exposure ended.
Declared predicate: `{"assertion": {"field": "safe_outcome", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `5657629e62d44fc4a14c63b05fe5a81e-experiment` v1: [saved basis](fixed-experiments/5657629e62d44fc4a14c63b05fe5a81e-experiment/basis.json).
Scope: Observe a ReadIndex request delivered to a leader whose removal the application applied and whose reduced configuration still has two voters, with PreVote enabled and CheckQuorum disabled: node 1 is elected in {1,2,3}, the application proposes and applies the committed removal of node 1 on all three nodes, the two remaining voters elect node 2 and it commits an entry the removed leader never sees, the read is delivered to node 1, one heartbeat tick of node 1 is delivered and its messages pumped, and the state of the request is then recorded.
History / supplied conditions: Elect node 1 in {1,2,3} with PreVote enabled, apply the committed removal of node 1 on all three nodes, elect node 2 in {2,3} and commit one proposal, deliver MsgReadIndex to node 1 and read its emitted messages, deliver one heartbeat tick of node 1 and pump its messages, then record the request's fate and node 1's state.
Assumptions: Three voters {1,2,3} with PreVote enabled on every node and CheckQuorum disabled; the election tick is 10 and the heartbeat tick is 1; node 1 is elected with a real MsgHup/MsgPreVote/MsgVote round.; The application applies the committed removal of node 1 on all three nodes, so node 1 keeps leading a configuration of voters (2 3) under the default StepDownOnRemoval=false while node 2 becomes leader of the same configuration at the next term.; The read is delivered to node 1 after node 2 has committed, then one heartbeat tick of node 1 is delivered and its messages are pumped through the network.
Excluded scope: CheckQuorum and lease-based reads.; Snapshots, asynchronous storage writes, and any state machine behind the read index.
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely) and requests that cannot be answered are the caller's to retry. A leader that is not in its own configuration can neither count its own vote for a quorum it is not part of nor answer safely, so the receipt records whether such a request is answered, refused, or accepted and then dropped.
Execution `79d6bcb6f89a41dbbd391a742cdf9916`: completed, exit code 0; [receipt](logs/79d6bcb6f89a41dbbd391a742cdf9916/check.json), [full observations](logs/79d6bcb6f89a41dbbd391a742cdf9916/observations.json), [stdout](logs/79d6bcb6f89a41dbbd391a742cdf9916/stdout.log), [stderr](logs/79d6bcb6f89a41dbbd391a742cdf9916/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `339f17aeedcc4faab24942f8d82e4206-interpretation-0` (violated; historical interpretation; the question has a later account).
Other current question interpretations explicitly citing this receipt: [336a717040a443128fcbb6e3c7c10f9f-interpretation-0](state.json) (question `9ad1a10e85bb41578fbb8a42a6890ab3-question-0`, fixed-experiment attribution: f87487ff302344ad90063b266f2302f5-experiment; event indices [1, 2, 3, 4, 5]).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `e_leader_removed`: Premise: after the removal node 1 still leads, but its configuration has two voters, so the singleton shortcut cannot decide this request.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `e_new_leader_committed`: Premise: the new leader of {2,3} has committed an entry the removed leader's commit index does not cover.
Declared predicate: `{"assertion": {"field": "actual_leader_ahead", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `e_read_taken`: Premise: the removed leader accepts the request into readOnly.unconfirmedReads, broadcasts its heartbeats and answers nothing.
Declared predicate: `{"assertion": {"field": "read_pending_confirmation", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `e_stepdown`: Bound: one heartbeat tick is enough for the removed leader to learn of the new term and leave the leader state.
Declared predicate: `{"assertion": {"field": "ticks_until_stepdown", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `e_after_stepdown_state`: Witness: the request the removed leader accepted is never answered - no read state, no unconfirmed or pending request left behind, and no refusal handed to the caller, so its only recourse is its own retry deadline.
Declared predicate: `{"assertion": {"field": "read_answered", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [5] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `f87487ff302344ad90063b266f2302f5-experiment` v1: [saved basis](fixed-experiments/f87487ff302344ad90063b266f2302f5-experiment/basis.json).
Scope: Observe a ReadIndex request delivered to a leader whose removal the application applied and whose reduced configuration has two voters, with CheckQuorum enabled: node 1 is elected in {1,2,3}, the application proposes and applies the committed removal of node 1 on all three nodes, six heartbeat rounds of node 1 are delivered and pumped, a read is delivered to node 1, and three further heartbeat rounds are delivered and pumped before the request's state is recorded.
History / supplied conditions: Elect node 1 in {1,2,3} with CheckQuorum enabled, apply the committed removal of node 1 on all three nodes, deliver three heartbeat rounds of node 1 and pump its messages, deliver MsgReadIndex to node 1 and read its emitted messages, deliver three more heartbeat rounds of node 1 and pump its messages, then record the request's fate and the state of all three nodes.
Assumptions: Three voters {1,2,3} with CheckQuorum enabled on every node and PreVote disabled; the election tick is 10 and the heartbeat tick is 1; node 1 is elected with a real MsgHup/MsgVote round.; The application applies the committed removal of node 1 on all three nodes, so node 1 keeps leading voters (2 3) under the default StepDownOnRemoval=false while the two remaining voters keep it as their leader.; No ticks are delivered to nodes 2 and 3, so their election timers do not expire and their leases stay in force; the receipt therefore measures the leaders' own rounds only.
Excluded scope: PreVote, and lease-based reads (which force CheckQuorum but bypass the round).; Snapshots, asynchronous storage writes, and any state machine behind the read index.
Declared requirement / prediction: A ReadIndex answer must let the application serve a linearizable read (raft.go:233-244 and README.md:27-32 state that ReadOnlySafe achieves linearizability by communicating with the quorum, and node.go:218-224 states that once the application advances past the returned read index, linearizable reads issued before the request can be processed safely). A leader that its own tracker shows is not in the configuration counts its own acknowledgement toward a round (raft.go:1600) whose quorum belongs to voters it is not one of, so the receipt records whether such a request is answered and whether the configuration replaces the leader at all.
Execution `11c411f5e9734ad6bb95fffd61f1b7c8`: completed, exit code 0; [receipt](logs/11c411f5e9734ad6bb95fffd61f1b7c8/check.json), [full observations](logs/11c411f5e9734ad6bb95fffd61f1b7c8/observations.json), [stdout](logs/11c411f5e9734ad6bb95fffd61f1b7c8/stdout.log), [stderr](logs/11c411f5e9734ad6bb95fffd61f1b7c8/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `336a717040a443128fcbb6e3c7c10f9f-interpretation-0` (violated; current question interpretation).

Comparison 0 · `e_leader_removed`: Premise: after the removal node 1 still leads a configuration of two voters, so the singleton shortcut cannot decide this request.
Declared predicate: `{"assertion": {"field": "singleton", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `e_no_new_leader`: Premise: three heartbeat rounds pass and the two remaining voters elect no replacement - they still answer the removed leader and their leases keep them from voting.
Declared predicate: `{"assertion": {"field": "new_leader_elected", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `e_read_taken`: Premise: the removed leader takes the request into readOnly.unconfirmedReads and broadcasts its heartbeats.
Declared predicate: `{"assertion": {"field": "read_pending_confirmation", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `e_lease_after_rounds`: Premise: after three further rounds the removed leader is still the leader at its own term, so nothing in this configuration ends its lease.
Declared predicate: `{"assertion": {"field": "state_is_leader", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `e_lease_after_rounds`: Witness: the request is answered even though the answering node is not a voter of the configuration whose quorum the round needed - the round counted the removed leader's own acknowledgement, and no replacement leader exists to end the state.
Declared predicate: `{"assertion": {"field": "read_answered", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Interpretation history:

- [9ad1a10e85bb41578fbb8a42a6890ab3-interpretation-0](state.json) → [8f8a7578765146509956132f0183a8c3-interpretation-0](state.json): conditional → unresolved; model claim asserted → asserted; changed fields: executions, conclusion, rationale, answers, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [8f8a7578765146509956132f0183a8c3-interpretation-0](state.json) → [09239ebbabb4422fb88c4069ab88d741-interpretation-0](state.json): unresolved → violated; model claim asserted → asserted; changed fields: experiment_id, executions, conclusion, rationale, answers, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [09239ebbabb4422fb88c4069ab88d741-interpretation-0](state.json) → [b3c4a8e694814ae283d63a3f9459aa1e-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [b3c4a8e694814ae283d63a3f9459aa1e-interpretation-0](state.json) → [a4ea3462a47b4adaada02b5d3c4bda6a-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [a4ea3462a47b4adaada02b5d3c4bda6a-interpretation-0](state.json) → [47945d2fd63048e7b016caa61e6e2d26-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: rationale, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [47945d2fd63048e7b016caa61e6e2d26-interpretation-0](state.json) → [7047250b7d2640f48c0dad5bdcfaba0e-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [7047250b7d2640f48c0dad5bdcfaba0e-interpretation-0](state.json) → [41aa04d6f89f47f9ad833d25d2c6e73c-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [41aa04d6f89f47f9ad833d25d2c6e73c-interpretation-0](state.json) → [6b71731acf2441de9145c5c6f1d03f8b-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [6b71731acf2441de9145c5c6f1d03f8b-interpretation-0](state.json) → [4f8260f004d94ca39484cbe058bc04f9-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, source_ids, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [4f8260f004d94ca39484cbe058bc04f9-interpretation-0](state.json) → [339f17aeedcc4faab24942f8d82e4206-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, source_ids, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [339f17aeedcc4faab24942f8d82e4206-interpretation-0](state.json) → [336a717040a443128fcbb6e3c7c10f9f-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, source_ids, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
### Does the Node wrapper let an application propose again through a node that was removed from the configuration and then added back while the leadership and term are unchanged?

Current disposition: active.
Question `05a1b54cf0ce4ce0bcd9e888623b8fae-question-0` v3; sources: node-propc-guard, node-propc-restore, node-propose-block, node-propose-doc ([full references](state.json)).
Current model defect claim: defect asserted (subject to independent verification).

Current interpretation `75d5bbeabe054ca0bf61d244bde4627e-interpretation-0` · declared predicate does not hold: The measured account is unchanged: source side, node.run sets its proposal channel to nil when an applied configuration change removes the local node from Progress and the node is in neither voter list (node.go:400-432) and restores it from n.propc only in the branch that reacts to a change of r.lead with a leader known (node.go:343-380), while Node.Propose sends into that channel so a nil channel makes the call wait for the caller's context or the node's done channel (node.go:514-551); receipt c53145c01ad94b449ca1c8b81fe8d7b4 measures the whole arc on a conforming prefix - the controls hold and the leader's log advances before the removal (parsed index 1), the two premises hold on the witness event (index 4: the leader's configuration contains node 2 again and the node still knows leader 1 in the same term), both witness assertions are violated (index 4: Propose returns only when its 300ms deadline fires and the group's log does not change), and the restore comparisons hold once the wrapped node wins a leadership change (index 5: StateLeader at term 2; index 6: no error and the commit index advances 5 to 6). This update adds the boundaries that the source fixes: the closed state requires the removal case, because the guard needs the local node's Progress entry to disappear - a demotion to learner keeps that entry and leaves the channel open - and an addition takes the okBefore=false path, so it never re-opens a channel a removal closed; the only repair site is the leadership-change branch, which is why the measured restore works and why the state persists while the same leader remains. It also records that the wrapper offers no distinct signal for this state: Propose can only return ctx.Err() or ErrStopped, the same results an ordinary lost proposal or a stopped node produces, so a caller that uses a deadline cannot tell the closed channel from a lost proposal except by the node's own status. The remaining unmeasured item is the group-size variant named in the question's discriminator.

Sources: [node-propc-guard](state.json), [node-propc-restore](state.json), [node-propose-block](state.json), [node-propose-doc](state.json); execution evidence: [c53145c01ad94b449ca1c8b81fe8d7b4](logs/c53145c01ad94b449ca1c8b81fe8d7b4/check.json) ([observations](logs/c53145c01ad94b449ca1c8b81fe8d7b4/observations.json), event indices [1, 4, 5, 6]).
Interpretation counterevidence: The controls hold in the receipt (parsed index 1), so the blocked behaviour is specific to the state after the removal and the re-add rather than a general property of the wrapper.; The restore comparisons hold (parsed indices 5 and 6), so the fault is bounded by the leadership rather than permanent, and the source's repair mechanism is confirmed by measurement.; A demotion to learner does not reach the closed state: the guard requires the local Progress entry to disappear, so the demotion case leaves the proposal channel open.; The Node.Propose documentation warns that proposals can be lost without notice (node.go:138-140), so a caller with a deadline and retries is not blocked; the source shows the wrapper cannot distinguish this state from that warning's case.
Interpretation limitations: The harness drives a wrapped node against a bare raft instance, so the wrapper's asynchronous ready/advance contract is exercised on one side only, and both nodes run in one process; the leader is installed directly before the removal and the campaign is driven through the wrapper's own Campaign.; The proposed calls use a 300ms deadline: the receipt measures that the call did not complete within it and that the group's log did not change, not the exact duration of the closed channel.; The exercised group has two voters; whether a larger group reaches the same state (where the re-added node's Progress entry is recreated in a different position, and the leader that removed it may not be the leader that re-adds it) is not measured.; Whether an application is expected to keep proposing through a node that has been removed and re-added is itself part of the question; the library's own comment calls the mechanism unsound rather than documenting an intended semantics.
Hypothesis: node.run sets propc to nil when an applied configuration change removes the local node (okBefore && !okAfter and the node is in neither Voters nor VotersOutgoing) and restores it only in the leadership-change branch when a leader is known; applying the change that adds the node back takes the okBefore=false path, so nothing restores the channel. Node.Propose then selects on the nil channel and returns only through the caller's context or the node's done channel, so the re-added member cannot propose until a leadership change occurs.
Registered discriminator: Whether the same closed state is reached in a group larger than two voters, where a re-added node's Progress entry is recreated by the changer in a different position and the leader may not be the same node that removed it.

Fixed experiment `7f6aa45d046c4714992282dd5e6d8389-experiment` v1: [saved basis](fixed-experiments/7f6aa45d046c4714992282dd5e6d8389-experiment/basis.json).
Scope: Observe the application-facing proposal path of the Node wrapper (Node.Propose) for one wrapped node 2 that is removed from the configuration by leader 1 and then added back by the same leader in the same term, comparing Propose before the removal, after the re-add and with the leader's log index before and after each call.
History / supplied conditions: Create the wrapped node 2 and a bare node 1 over storages with voters {1,2}; make node 1 leader at term 1 and broadcast its appends; pump messages until node 2 (through its status channel) knows leader 1 and has committed the bootstrap entry; propose through the wrapper and record the outcome; propose the removal of node 2 on node 1, pump, and apply it on both nodes; propose the re-add of node 2 on node 1, pump, and apply it on both nodes; then propose through the wrapper again and record the outcome and the leader's log index around it.
Assumptions: Two voters {1,2} in one process: node 2 is driven through the Node wrapper (newNodeTestHarness, so Readys are consumed and Advance is called) while node 1 is a bare raft instance driven by the harness's message pump; node 1 is made leader directly and broadcasts its appends.; Both nodes apply the removal and the re-add through the application path (n1.applyConfChange and the wrapper's ApplyConfChange), and every snapshot of node 2 is taken through its status channel (node.Status), which is executed inside the run loop.; Propose is called with a 300ms context deadline; a nil proposal channel makes the call return only when that deadline fires.
Excluded scope: StepDownOnRemoval, CheckQuorum and PreVote configurations.; A leadership-change control: the draft attempted to restore the channel by campaigning node 2, but that attempt is not part of this basis.; Snapshots and asynchronous storage writes.
Declared requirement / prediction: Node.Propose is the application-facing proposal path: its documentation states that it proposes data to be appended to the log and warns only that proposals can be lost without notice (node.go:138-140). A node that the application has added back to the configuration, and that knows the leader of that configuration, must therefore be able to hand a proposal to raft - or report why it cannot - rather than block until the caller's context expires while the group never sees the proposal.
Execution `8b3e88d4b4a641fa8ddc723ecc0ba56d`: completed, exit code 0; [receipt](logs/8b3e88d4b4a641fa8ddc723ecc0ba56d/check.json), [full observations](logs/8b3e88d4b4a641fa8ddc723ecc0ba56d/observations.json), [stdout](logs/8b3e88d4b4a641fa8ddc723ecc0ba56d/stdout.log), [stderr](logs/8b3e88d4b4a641fa8ddc723ecc0ba56d/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `eec8d58027ec48d1bce000c83a57b896-interpretation-0` (conditional; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 5 ([full records](state.json)); these are not current question accounts.
Evidence limitations: Current interpretation remains conditional, disputed or unresolved

Comparison 0 · `propose_before_removal`: Control: while node 2 is a plain member of {1,2} and knows leader 1, Propose returns without error.
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `propose_before_removal`: Control: the proposal forwarded by the follower reaches the group - the leader's log index advances.
Declared predicate: `{"assertion": {"field": "leader_advanced", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 1 {'scenario': 'node-propose-after-readd'}: Missing required result fields: leader_advanced; Event 0 {'scenario': 'node-propose-after-readd'}: Admitted operation has no complete applicable result observation

Comparison 2 · `node2_removed`: Premise: after the removal is applied on both nodes, the leader's configuration no longer contains node 2.
Declared predicate: `{"assertion": {"field": "leader_sees_member", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 2 {'scenario': 'node-propose-after-readd'}: Missing required result fields: leader_sees_member; Event 1 {'scenario': 'node-propose-after-readd'}: Admitted operation has no complete applicable result observation

Comparison 3 · `node2_readded`: Premise: after the re-add is applied on both nodes, the leader's configuration contains node 2 again and node 2 has caught up to the leader's log.
Declared predicate: `{"assertion": {"field": "leader_sees_member", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 3 {'scenario': 'node-propose-after-readd'}: Missing required result fields: leader_sees_member; Event 2 {'scenario': 'node-propose-after-readd'}: Admitted operation has no complete applicable result observation

Comparison 4 · `node2_readded`: Premise: the wrapped node still knows leader 1 in the same term, so the leadership is unchanged across the removal and the re-add.
Declared predicate: `{"assertion": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: comparison undetermined (`unknown`).
Observation coverage: unresolved items remain; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).
Observation gaps: Event 3 {'scenario': 'node-propose-after-readd'}: Missing required result fields: known_leader; Event 2 {'scenario': 'node-propose-after-readd'}: Admitted operation has no complete applicable result observation

Comparison 5 · `propose_after_readd`: Witness: with node 2 a member again and still knowing leader 1, Propose returns only when its context deadline fires (context deadline exceeded after about 300ms).
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "antecedent": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `propose_after_readd`: Witness: the proposal never reached the group - the leader's log index is unchanged across the call.
Declared predicate: `{"assertion": {"field": "leader_advanced", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `c3dd9a52a0c44b21af5b3204cf642efb-experiment` v2: [saved basis](fixed-experiments/c3dd9a52a0c44b21af5b3204cf642efb-experiment/basis.json).
Scope: Observe the application-facing proposal path of the Node wrapper for one wrapped node 2 that leader 1 removes from the configuration and then adds back in the same term, with the application duties of the Ready/Advance contract honoured (entries, hard state and snapshots persisted before messages are sent), comparing Propose before the removal and after the re-add together with the leader's log index around each call.
History / supplied conditions: Create the wrapped node 2 over its own storage and a bare node 1 over storages with voters {1,2}; make node 1 leader at term 1 and broadcast its appends; pump messages (persisting whatever node 2's Readys carry) until node 2 knows leader 1 and has applied the bootstrap entry; propose through the wrapper and record the outcome; propose the removal of node 2 on node 1, pump, and apply it on both nodes; propose the re-add of node 2 on node 1, pump, and apply it on both nodes; then propose through the wrapper again and record the outcome and the leader's log index around it.
Assumptions: Two voters {1,2} in one process: node 2 is driven through the Node wrapper (newNodeTestHarness, Readys consumed, entries/hard state persisted, Advance called) while node 1 is a bare raft instance driven by the harness's message pump; node 1 is made leader directly and broadcasts its appends.; Both nodes apply the removal and the re-add through the application path (n1.applyConfChange and the wrapper's ApplyConfChange), and every snapshot of node 2 is taken through its status channel (node.Status), executed inside the run loop.; Propose is called with a 300ms context deadline.
Excluded scope: StepDownOnRemoval, CheckQuorum and PreVote configurations.; The leadership-change restore path: the diagnostic attempt was removed from the harness because it hung after the witness, so it is not part of this basis.; Snapshots and asynchronous storage writes.
Predecessor `7f6aa45d046c4714992282dd5e6d8389-experiment`; revision reason: The pump now performs the application's persistence duty (Ready.Entries written to the wrapped node's storage, Ready.Snapshot applied, non-empty Ready.HardState persisted, all before the Ready's messages are sent and before Advance) so the basis is a prefix a conforming application produces; the diagnostic campaign block that hung the harness after the witness was removed and the comparison set is reduced to the observations whose fields the events carry at the top level. The witness is unchanged in substance.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: Node.Propose is the application-facing proposal path: its documentation states that it proposes data to be appended to the log and warns only that proposals can be lost without notice (node.go:138-140). A node that the application has added back to the configuration, and that knows the leader of that configuration, must therefore be able to hand a proposal to raft - or report why it cannot - rather than block until the caller's context expires while the group never sees the proposal.
Execution `4dc33f26f12e4cd69f7aae09af6c1ee6`: completed, exit code 0; [receipt](logs/4dc33f26f12e4cd69f7aae09af6c1ee6/check.json), [full observations](logs/4dc33f26f12e4cd69f7aae09af6c1ee6/observations.json), [stdout](logs/4dc33f26f12e4cd69f7aae09af6c1ee6/stdout.log), [stderr](logs/4dc33f26f12e4cd69f7aae09af6c1ee6/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `60fa7da0de1849ce91537198ac34489d-interpretation-0` (violated; historical interpretation; the question has a later account).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `propose_before_removal`: Control: while node 2 is a plain member of {1,2} and knows leader 1, Propose returns no error.
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `propose_before_removal`: Control: the proposal forwarded by the follower reaches the group - the leader's log index is 2 after the call (the bootstrap entry plus this proposal).
Declared predicate: `{"assertion": {"field": "leader_last_index", "op": "eq", "value": 2}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `propose_after_readd`: Premise on the witness event: the leader's configuration contains node 2 again after the re-add.
Declared predicate: `{"assertion": {"field": "leader_sees_member", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `propose_after_readd`: Premise on the witness event: the wrapped node still knows leader 1, in the same term, so the leadership is unchanged across the removal and the re-add.
Declared predicate: `{"assertion": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `propose_after_readd`: Witness: with node 2 a member again and still knowing leader 1, Propose returns only when its context deadline fires (context deadline exceeded after about 300ms).
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "antecedent": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `propose_after_readd`: Witness: the proposal never reached the group - the leader's log index is unchanged at 4 across the call.
Declared predicate: `{"assertion": {"field": "leader_advanced", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Fixed experiment `2318a1c9ee5d4b76995a322bd4bfcf06-experiment` v3: [saved basis](fixed-experiments/2318a1c9ee5d4b76995a322bd4bfcf06-experiment/basis.json).
Scope: Observe the application-facing proposal path of the Node wrapper for one wrapped node 2 that leader 1 removes from the configuration and then adds back in the same term, with the application duties of the Ready/Advance contract honoured: Propose before the removal, after the re-add, and after the wrapped node wins a leadership change.
History / supplied conditions: Create the wrapped node 2 over its own storage and a bare node 1 over storages with voters {1,2}; make node 1 leader at term 1 and broadcast its appends; pump messages (persisting whatever node 2's Readys carry) until node 2 knows leader 1 and has applied the bootstrap entry; propose through the wrapper and record the outcome; propose the removal of node 2 on node 1, pump, and apply it on both nodes; propose the re-add of node 2 on node 1, pump, and apply it on both nodes; then propose through the wrapper again and record the outcome and the leader's log index around it. Then the wrapped node campaigns, the harness pumps until it reports StateLeader, and the Propose call is repeated with the node's commit index recorded around it.
Assumptions: Two voters {1,2} in one process: node 2 is driven through the Node wrapper (newNodeTestHarness, Readys consumed, entries/hard state persisted, Advance called) while node 1 is a bare raft instance driven by the harness's message pump; node 1 is made leader directly and broadcasts its appends.; Both nodes apply the removal and the re-add through the application path (n1.applyConfChange and the wrapper's ApplyConfChange), and every snapshot of node 2 is taken through its status channel (node.Status), executed inside the run loop.; Propose is called with a 300ms context deadline.; After the witness, the wrapped node campaigns; the harness pumps messages until its status reports StateLeader and then repeats the Propose call, recording the node's commit index before and after.
Excluded scope: StepDownOnRemoval, CheckQuorum and PreVote configurations.; Snapshots and asynchronous storage writes.
Predecessor `c3dd9a52a0c44b21af5b3204cf642efb-experiment`; revision reason: The harness now also runs the leadership-change restore path after the witness: the wrapped node campaigns on the corrected prefix (its log is consistent, so the election is winnable) and the same Propose call is repeated; the campaign and the repeated call are observed through the node's status channel. The earlier observations are kept.; actual changes: harness, scope, prefix, comparisons
Declared requirement / prediction: Node.Propose is the application-facing proposal path: its documentation states that it proposes data to be appended to the log and warns only that proposals can be lost without notice (node.go:138-140). A node that the application has added back to the configuration, and that knows the leader of that configuration, must therefore be able to hand a proposal to raft - or report why it cannot - rather than block until the caller's context expires while the group never sees the proposal.
Execution `c53145c01ad94b449ca1c8b81fe8d7b4`: completed, exit code 0; [receipt](logs/c53145c01ad94b449ca1c8b81fe8d7b4/check.json), [full observations](logs/c53145c01ad94b449ca1c8b81fe8d7b4/observations.json), [stdout](logs/c53145c01ad94b449ca1c8b81fe8d7b4/stdout.log), [stderr](logs/c53145c01ad94b449ca1c8b81fe8d7b4/stderr.log).
Mechanical comparison: declared predicate does not hold (`violated`).
Directly attributed interpretation for this execution: `75d5bbeabe054ca0bf61d244bde4627e-interpretation-0` (violated; current question interpretation).
Historical interpretations explicitly citing this receipt: 1 ([full records](state.json)); these are not current question accounts.

Comparison 0 · `propose_before_removal`: Control: while node 2 is a plain member of {1,2} and knows leader 1, Propose returns no error.
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 1 · `propose_before_removal`: Control: the proposal forwarded by the follower reaches the group - the leader's log index is 2 after the call (the bootstrap entry plus this proposal).
Declared predicate: `{"assertion": {"field": "leader_last_index", "op": "eq", "value": 2}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 2 · `propose_after_readd`: Premise on the witness event: the leader's configuration contains node 2 again after the re-add.
Declared predicate: `{"assertion": {"field": "leader_sees_member", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 3 · `propose_after_readd`: Premise on the witness event: the wrapped node still knows leader 1, in the same term, so the leadership is unchanged across the removal and the re-add.
Declared predicate: `{"assertion": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 4 · `propose_after_readd`: Witness: with node 2 a member again and still knowing leader 1, Propose returns only when its context deadline fires (context deadline exceeded after about 300ms).
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "antecedent": {"field": "known_leader", "op": "eq", "value": 1}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 5 · `propose_after_readd`: Witness: the proposal never reached the group - the leader's log index is unchanged at 4 across the call.
Declared predicate: `{"assertion": {"field": "leader_advanced", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate does not hold (`violated`).
Observation coverage: complete; valid violating event indices: [4] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 6 · `campaign_attempt`: Restore premise: after the campaign the wrapped node reports itself as leader, so r.lead changed from 1 to 2 in the same run.
Declared predicate: `{"assertion": {"field": "state", "op": "eq", "value": "StateLeader"}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 7 · `propose_after_leadership_change`: Restore path: with the leadership changed, Propose returns no error.
Declared predicate: `{"assertion": {"field": "proposal_returned_error", "op": "eq", "value": false}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Comparison 8 · `propose_after_leadership_change`: Restore path: the proposal reaches the group - the node's commit index advances from 5 to 6.
Declared predicate: `{"assertion": {"field": "commit_advanced", "op": "eq", "value": true}, "applicability_conditions": []}`
Mechanical comparison: declared predicate holds (`holds`).
Observation coverage: complete; valid violating event indices: [] (zero-based parsed comparisons; not a defect verdict or independent-failure attribution).

Interpretation history:

- [05a1b54cf0ce4ce0bcd9e888623b8fae-interpretation-0](state.json) → [165e6746946545adbb90ad26fa167d81-interpretation-0](state.json): unresolved → unresolved; model claim unresolved → unresolved; changed fields: rationale, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [165e6746946545adbb90ad26fa167d81-interpretation-0](state.json) → [5d2c65575ee548ed81b88d7404745171-interpretation-0](state.json): unresolved → violated; model claim unresolved → asserted; changed fields: experiment_id, executions, conclusion, defect_claim, rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [5d2c65575ee548ed81b88d7404745171-interpretation-0](state.json) → [4208e89fb94d4752a987c5b1cf0361cd-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [4208e89fb94d4752a987c5b1cf0361cd-interpretation-0](state.json) → [5635eebc681c4d38b4a61589e03ec805-interpretation-0](state.json): violated → conditional; model claim asserted → asserted; changed fields: conclusion, rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [5635eebc681c4d38b4a61589e03ec805-interpretation-0](state.json) → [eec8d58027ec48d1bce000c83a57b896-interpretation-0](state.json): conditional → conditional; model claim asserted → asserted; changed fields: rationale, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.
- [eec8d58027ec48d1bce000c83a57b896-interpretation-0](state.json) → [60fa7da0de1849ce91537198ac34489d-interpretation-0](state.json): conditional → violated; model claim asserted → asserted; changed fields: experiment_id, executions, conclusion, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [60fa7da0de1849ce91537198ac34489d-interpretation-0](state.json) → [d2d916388bde4de4be3c17b34d434076-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: experiment_id, executions, rationale, counterevidence, limitations, joint_history. Full accounts, evidence and boundaries remain in state.json.
- [d2d916388bde4de4be3c17b34d434076-interpretation-0](state.json) → [75d5bbeabe054ca0bf61d244bde4627e-interpretation-0](state.json): violated → violated; model claim asserted → asserted; changed fields: rationale, knowledge, counterevidence, limitations. Full accounts, evidence and boundaries remain in state.json.

## Shared understanding and revisions

- `8769550822c045a18219e24795b9bdc0-knowledge-0` r1 · behavior: A leader that receives MsgReadIndex postpones the request (appends it to r.pendingReadIndexMessages and returns without answering) exactly when its current configuration is not a singleton and r.committedEntryInCurrentTerm() is false, i.e. when the entry at its committed index was issued by an earlier term.; conditions: Local raft instance in StateLeader; message type MsgReadIndex; configuration not a singleton (tracker.IsSingleton() false)..
- `8769550822c045a18219e24795b9bdc0-knowledge-1` r1 · behavior: Postponed ReadIndex requests are released only from the MsgAppResp success path when r.maybeCommit() reports that the commit index advanced to an entry of the leader's term; the helper refuses to release them when committedEntryInCurrentTerm() is false.; conditions: StateLeader; MsgAppResp handling for which pr.MaybeUpdate or the probe-recovery condition is true; releasePendingReadIndexMessages is the only consumer of pendingReadIndexMessages..
- `8769550822c045a18219e24795b9bdc0-knowledge-2` r1 · fact: switchToConfig is a second code path on which a leader can perform the term's first commit: when the configuration returned by the conforming changer raises ProgressTracker.Committed() above raftLog.committed and the entry at that index carries the leader's current term, it calls r.maybeCommit() and, on success, only broadcasts appends; it does not release pendingReadIndexMessages.; conditions: StateLeader with a non-empty voter set; called from applyConfChange (application applies a committed configuration change) with the leader's Progress values already reflecting quorum-level acknowledgement of a current-term entry..
- `8769550822c045a18219e24795b9bdc0-knowledge-3` r1 · behavior: A postponed request is not part of readOnly.unconfirmedReads, so readOnly.heartbeatCtx() returns nil, outgoing heartbeats carry no read context, and the MsgHeartbeatResp handler returns early on an empty context: a periodic heartbeat round cannot release a postponed request.; conditions: ReadOnlySafe; pendingReadIndexMessages non-empty while readOnly.unconfirmedReads is empty..
- `8769550822c045a18219e24795b9bdc0-knowledge-4` r1 · behavior: The library permits an application to report applied progress (Advance / MsgStorageApplyResp) while it is still applying the entries of a previous Ready, and it fixes no ordering between that progress report and the required ApplyConfChange call for a committed configuration change; the campaign gate hasUnappliedConfChanges() reads raftLog.applied only.; conditions: Node/RawNode consumer following the documented Ready/Advance contract..
- `9ad1a10e85bb41578fbb8a42a6890ab3-knowledge-0` r1 · behavior: ProgressTracker.IsSingleton returns true exactly when Voters[0] has one member and Voters[1] is empty; it never compares the single voter with the local node id, although its doc comment says the single voting member is the leader.; conditions: tracker.ProgressTracker of any raft instance, including one that is no longer a member of its configuration..
- `9ad1a10e85bb41578fbb8a42a6890ab3-knowledge-1` r1 · behavior: stepLeader answers MsgReadIndex immediately - with a local ReadState for a local request, or with MsgReadIndexResp for a forwarded one - whenever tracker.IsSingleton() is true, using r.raftLog.committed and without sending any heartbeat or consulting readOnly; otherwise it requires committedEntryInCurrentTerm() and a readOnly round.; conditions: StateLeader; MsgReadIndex; tracker.IsSingleton() true..
- `9ad1a10e85bb41578fbb8a42a6890ab3-knowledge-2` r1 · fact: When the configuration change that removes the local node is applied while the node is leading, switchToConfig keeps it leading unless Config.StepDownOnRemoval (false by default) is set; the MsgProp path explicitly refuses proposals from a leader that is not in the configuration ('If we are not currently a member of the range ... drop any new proposals') while the MsgReadIndex path has no equivalent guard.; conditions: StateLeader; applyConfChange on a committed change whose resulting configuration does not contain the local node; Config.StepDownOnRemoval false (the default)..
- `05a1b54cf0ce4ce0bcd9e888623b8fae-knowledge-0` r1 · behavior: node.run sets its proposal channel to nil when an applied configuration change removes the local node from Progress and that node appears in neither cs.Voters nor cs.VotersOutgoing, and restores the channel from n.propc only in the branch that reacts to a change of r.lead with a leader known; applying a change that adds the node back does not restore the channel.; conditions: Node wrapper (node.run) driven through ApplyConfChange; the removal is applied while the node is in Progress and the addition is applied while it is not..
- `05a1b54cf0ce4ce0bcd9e888623b8fae-knowledge-1` r1 · behavior: With the proposal channel nil - either because the node was removed or because no leader is known - Node.Propose sends into a nil channel inside a select that also watches the caller's context and the node's done channel, so the call blocks until one of those fires and then returns ctx.Err() or ErrStopped.; conditions: Node.Propose/stepWait with the run loop's propc variable nil..
- `47945d2fd63048e7b016caa61e6e2d26-knowledge-0` r1 · fact: ReadOnlyLeaseBased cannot be combined with CheckQuorum disabled (Config.validate rejects it), and with CheckQuorum enabled a voter inside its election-timeout lease ignores a vote request from a higher term, so while the remaining voters still hear a leader they will not elect another one; a removed leader that keeps being answered therefore keeps a live lease rather than serving stale lease-based reads, and when the voters stop answering, its own quorum check fails and it steps down.; conditions: Cluster whose remaining voters still answer the removed leader's heartbeats; ReadOnlyLeaseBased with CheckQuorum enabled (the only accepted combination)..
- `75d5bbeabe054ca0bf61d244bde4627e-knowledge-0` r1 · behavior: The Node wrapper closes its proposal channel only when an applied configuration change makes the local node's Progress entry disappear (the guard requires the node to have been in Progress before, to be absent after, and to appear in neither Voters nor VotersOutgoing); a demotion to learner keeps the Progress entry and therefore does not close the channel, and applying a change that adds the node back takes the okBefore=false path, so an addition never re-opens a channel that a removal closed. The only site that re-opens it is the branch that reacts to a change of r.lead while a leader is known.; conditions: Node wrapper driven through ApplyConfChange; Config.StepDownOnRemoval false so the node can keep leading or following without its Progress entry being removed..
- `75d5bbeabe054ca0bf61d244bde4627e-knowledge-1` r1 · behavior: Node.Propose cannot report a closed proposal channel as such: with the channel nil the call waits on a select over that channel, the caller's context and the node's done channel, so it returns only ctx.Err() or ErrStopped, which are the same results an ordinary lost proposal or a stopped node produces.; conditions: Node.Propose/stepWait while node.run has set propc to nil..
- `8fe92a50707247969b4c28151b88dd86-knowledge-0` r1 · behavior: The end of a removed leader's ReadIndex exposure does not follow from the quorum option alone: it follows from a replacement leader being elected. In the single-voter remainder the remaining voter elects itself, and under PreVote the remaining voters grant a new election, so the removed leader learns of the higher term after one heartbeat tick; with CheckQuorum and a remainder of more than one voter the voters keep answering the removed leader's heartbeats, refuse each other's vote requests while inside their election-timeout lease, and elect nobody, so the removed leader keeps leading, keeps its lease, and finishes subsequent read-only rounds from its own frozen commit index - and it begins that election on the leader's own acknowledgement of the round (sendMsgReadIndexResponse adds the local ack before broadcasting heartbeats), an ack that belongs to a node which is not a voter of the configuration whose quorum the round needed.; conditions: Cluster with CheckQuorum enabled; a leading node that the application removed from the configuration while Config.StepDownOnRemoval is false; the resulting configuration has more than one voter; those voters still hear and answer the removed leader's heartbeats and their own election timers do not expire; ReadOnlySafe..
- `8b431a3c90c04e328b833ff48e860d54-knowledge-0` r1 · behavior: A follower that receives MsgReadIndex forwards it to the leader it knows (raising no term, since MsgReadIndex is treated as a local message). If that leader has been removed from a configuration whose single voter is another node and is still leading, the request takes the singleton shortcut and the leader answers it with a MsgReadIndexResp carrying its own frozen commit index; the forwarding node consumes that answer as its own ReadState and, once it advances past that index, serves reads that can miss entries the actual leader of the reduced configuration had already committed.; conditions: ReadOnlySafe; a requester node whose r.lead is a node that is leading but is not a voter of its own configuration, with exactly one voter in that configuration; the requester's request is delivered to that leader before the requester hears from the new term..
- `0a943041d2ed48019061ff1070489d29-knowledge-0` r1 · behavior: If a ReadIndex request reaches a still-leading but removed node whose configuration has more than one voter, the singleton shortcut does not apply, so the request is taken into readOnly (the leader adds it and broadcasts heartbeats) and is answered only if the round completes. When the leadership then ends - the removed leader learns of the higher term from a voter that answers a lower-term message, or its own read-only round cannot reach the configuration's quorum - whatever it accepted is gone: no ReadState, nothing left pending or unconfirmed, and no refusal signalled to the caller, so an application that treats acceptance as a promise waits out its own deadline, and only one that retries unconditionally recovers.; conditions: ReadOnlySafe; a leading node that the application removed from the configuration while Config.StepDownOnRemoval is false; the reduced configuration has more than one voter; the request is delivered while the removed leader's committed entry is from its own term (so the postpone path is not taken)..

## Execution costs and raw records

Codex investigation turns: 44 (not provider request count); controller target executions: 16 (excludes Agent local exploratory checks).
Total target process seconds: 243.67343099999997; action seconds including preparation: 261.7675112969955; these overlap and must not be added together.
Requested model: `deepseek-flash` / `high`; server model identity is only established by receipts.
[Full state and history](state.json), [current work index](research.json), [actual configuration](config.json), [events](events.jsonl).
Scripted products demonstrate framework behavior, not autonomous discovery.
