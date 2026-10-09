# Audit report

Target: `github.com/hashicorp/raft`, captured source identity `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`.

Implementation and dependencies are unchanged. Added `audit_*_test.go` files are reproductions. Commands and actual outputs are retained in `audit-results/`. Tests run offline on Go 1.25.8 using the supplied in-memory transport or TCP restricted to the authorized private network namespace; no external network is involved. Findings below distinguish executed behavior from inferred consequences.

## 1. Leader verification counts nonvoters and succeeds on a stale leader

**Affected code:** `raft.go:965–986` (`verifyLeader`), `replication.go:100–111,437` (heartbeat verification votes), `future.go:274–295`; compare the voter-only quorum calculation at `raft.go:1086–1095` and lease check at `raft.go:1050–1076`.

**Expected behavior and basis:** `api.go:880–882` documents `VerifyLeader` as ensuring the peer is still leader and preventing stale FSM reads after leadership is lost. Verification must intersect an election quorum. Nonvoters cannot provide that intersection: `configuration.go:15–19` explicitly excludes them from elections and commitment.

**Necessary conditions:** A configuration with three voters and at least one nonvoter; an old leader can still communicate with a nonvoter while isolated from the other two voters. Its local leader lease has not yet caused it to step down when verification runs. For an observed stale read, the other two voters have already elected a newer leader and committed additional state.

**Defect:** `verifyLeader` counts the leader itself, obtains the quorum size from the voting members, but registers the verification future with *all* replication peers. The nonvoter's successful heartbeat increments the same vote counter. In a three-voter cluster, the old leader plus one nonvoter supplies the two acknowledgments needed to report success, although neither of the other voters was contacted.

**Executed reproduction:** `audit_verify_test.go`, `TestAuditVerifyLeaderNonvoter`. This starts four real Raft instances using public APIs, bootstraps three voters and one nonvoter, commits an initial command, partitions voter 0 plus the nonvoter from voters 1 and 2, and lets the voting majority elect a new leader and commit another command. Local timeout values accepted by `ValidateConfig`/`ReloadConfig` make the overlap deterministic: the old leader has a one-second lease, and the majority followers are reloaded to 100ms election/heartbeat timeouts with 50ms local leases. No implementation state is forced or altered.

Actual output in `audit-results/verify-leader.txt`:

```
old term=2 new term=3 old FSM=["before partition"] new FSM=["before partition" "committed after partition"] VerifyLeader error=<nil>
```

The test fails because verification succeeded on the stale FSM. The paired control disconnects the nonvoter too; verification returns `leadership lost while committing log` and the control passes. This rules out the mere local `Leader` state or recent lease contact as the source of success. Different legal local timeouts widen the observation window; they do not supply the missing quorum or make a nonvoter eligible to verify leadership. No claim is made that default identical timers reproduce this exact schedule.

**Impact:** Executed violation of the API's stale-read protection after a newer leader has committed state. Restrict positive verification votes to eligible voting members, including membership changes while verification is pending.

## 2. Interrupted vote persistence can grant a vote to an out-of-date candidate after restart

**Affected code:** `raft.go:2130–2137` (`persistVote`) and `raft.go:1685–1723` (`requestVote`, especially duplicate handling at 1697–1704).

**Expected behavior and basis:** A candidate must have a log at least as up to date as the receiver's to receive its vote. The implementation explicitly enforces that comparison at `raft.go:1707–1723`, and `StableStore` is documented as providing stable storage to ensure safety. A crash between individually successful stable-store operations must not manufacture a vote that bypasses this comparison.

**Necessary conditions:** The store contains a vote for A in an earlier term. The follower subsequently obtains a newer log entry from another leader. While processing an up-to-date candidate C in a later term, the vote-term write persists but the candidate write does not. The follower restarts, and A requests a vote in that later term while still lacking the newer log. A request without successful pre-voting is possible with supported `PreVoteDisabled` elections (or leader-transfer elections); this is a vote-handler reproduction, not an executed whole-cluster election.

**Defect:** `persistVote` first writes `LastVoteTerm`, then writes `LastVoteCand` as a separate operation. An interruption leaves the new term paired with the previous candidate. On restart, `requestVote` treats this as a duplicate vote for A, grants it, and returns *before* the log freshness check.

**Executed reproduction:** `audit_vote_test.go`, `TestAuditInterruptedVotePersistence`. Public transport RPCs produce the following history on follower F: vote for A in term 2; receive and commit index 2/term 3 from B; restart; process C's up-to-date request for term 4. A test `StableStore` wrapper returns an error before persisting exactly the candidate write, while preserving every preceding successful write. The node rejects C, then is shut down/recreated with exactly that store and log. A's term-4 request advertises only index 1/term 1.

Actual output in `audit-results/interrupted-vote.txt`:

```
vote C granted=false; durable vote=(term 4, candidate A); after restart stale A (last log 1/1, follower 2/3) granted=true
```

The regression assertion fails. In the paired control, the candidate write completes, the stored candidate is C, and A is rejected.

**Limits and alternatives checked:** This executes an injected individual-store-operation failure followed by restart, not an OS crash or disk fault. The same durable pair follows directly from the source for a crash between those writes. The wrapper implements the public storage interface and never rewrites a successful value, the source, or a dependency. The follower already has the newer committed log, both candidates belong to its voting configuration, and a restart clears the volatile leader hint, so membership rejection and the known-leader optimization do not explain the grant. The previous A vote was in term 2, not term 4: the duplicate vote record is manufactured by the interrupted write. No cluster-wide election or committed-data-loss outcome has been executed or claimed.

**Impact:** Executed violation of local vote eligibility after recovery; this undermines the log-freshness premise used for leader completeness. A durable vote representation must not combine a new term with an old candidate, and duplicate handling must not bypass freshness on an unvalidated torn record.

## 3. Concurrent heartbeat handlers can decrease both current and persisted term

**Affected code:** `net_transport.go:724–731` dispatches the heartbeat fast path on the connection handler; `raft.go:1418–1433` calls `appendEntries` directly; `raft.go:1456–1468` compares the incoming term and updates it without serializing the comparison/update; `raft.go:2141–2146` persists and then publishes the new term.

**Expected behavior and basis:** Raft current terms must be monotonically increasing, including across restarts. A server that has accepted a term-3 leader must reject a term-2 heartbeat. The lower-term rejection at `raft.go:1456` implements this rule for serial requests, but the TCP fast path executes handlers concurrently. `api.go:615–617` explicitly requires that the heartbeat callback be safe alongside a blocking RPC.

**Necessary conditions:** Heartbeats from different terms overlap on separate TCP connections. The older-term handler has already passed the term check but is delayed before its term write completes; a newer-term heartbeat completes in the interim. Delayed messages from an earlier leader during a newer election are sufficient; no malformed or Byzantine RPC is required.

**Executed reproduction:** `audit_heartbeat_test.go`, `TestAuditConcurrentHeartbeatTermRegression`, uses the original `NetworkTransport` over private loopback TCP, three real transports, and one real Raft follower. A thread-safe `StableStore` wrapper delays the term-2 operation before its atomic write; it neither changes values nor fails any operation. The term-3 heartbeat on another connection completes and the API reports term 3. Releasing the older write then makes both the API and store report term 2 and resets the leader hint to A.

Actual output in `audit-results/heartbeat-term-control.txt`:

```
new heartbeat success=true; current term before releasing old write=3; old heartbeat success=true; current term after=2; durable term=2; leader=A
serial control: term-2 heartbeat success=false current term=3
```

The serial control confirms ordinary lower-term rejection works; the overlapping comparison/write is the issue. An initial three-repetition run also reproduced the term decrease every time (`audit-results/heartbeat-term.txt`). Both runs used `-race` and produced no race-detector warnings: this is a logical interleaving defect despite thread-safe individual field/store operations.

**Limits:** The transport/Raft implementation is untouched. The wrapper chooses a permitted delay between entering a store method and taking its write lock; it does not weaken individual-operation atomicity. The test establishes local term regression and acceptance of an older leader, not a whole-cluster split or double vote. An initial harness attempt accidentally shut the node down while registering a defer and timed out before exercising the handler; its output is retained as `heartbeat-term-initial-harness-error.txt` and is not defect evidence. That harness-only error was corrected before the successful reproductions.

**Impact:** A fundamental term monotonicity invariant fails, in memory and durable state. Term checks and transitions need serialization across the main Raft loop and concurrent heartbeat handlers, including persistence/publication ordering.

## Reproduction validation

The first two findings and their controls were also run together with `-race -count=3`: all six defect cases failed the intended assertions, all six controls passed, and no race-detector warning appeared (`audit-results/repeated-race.txt`). Commands, including the private-network requirement for finding 3, are in `audit-results/commands.md`.

## Unresolved work and coverage

- Continue checking snapshot installation/restoration and log conflict handling.
- Follower commit advancement uses its local last index rather than the last matched index of a request. A naive synthetic RPC can expose a mismatch, but normal leader backtracking may prevent that request/state combination. No finding claimed without a reachable execution.
- In-memory snapshot publication appears to expose the new snapshot before `Close`; cancellation and concurrent reads need investigation before reporting.
- No exhaustive correctness claim or full upstream test-suite run is made.
