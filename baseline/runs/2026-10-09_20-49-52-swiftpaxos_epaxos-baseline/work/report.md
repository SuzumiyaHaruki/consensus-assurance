# EPaxos correctness audit — partial report

Source identity: `35c69365f1c7737a08e237bfbaf828ee68897080`.
Scope: EPaxos and the authorized supporting packages. No implementation or dependency files were changed. Added test code is in `epaxos/audit_test.go`, `epaxos/audit_codec_test.go`, and `epaxos/audit_liveness_test.go`, and `epaxos/audit_order_test.go`. `audit/source-sha256.txt` records hashes of all 28 original files in scope, checked byte-for-byte against the read-only source.

## Reproduction and evidence

From the work directory, run:

```sh
./audit/run-tests.sh
```

This runs `go test ./epaxos -run TestAudit -v -count=1`, saves output to `audit/test-output.txt`, and returns the Go test exit status. **Exit 1 is expected:** these are regression assertions of required behavior, and the supplied implementation violates them. All eight tests compiled and executed locally using Go 1.23.5; the failures below are observed, not inferred.

The harness creates small synchronous replicas with the N=3/F=1 or N=5/F=2 settings with thriftiness enabled, memory-backed peer writers, and the original handlers, serialization, dependency routines and executor. It avoids the network constructor, background goroutines and enormous instance allocations. Handler replies are marshalled and unmarshalled. It does not modify handlers or inject diagnostic fixes. These are deterministic handler/executor reproductions, not a live TCP deployment or timing test. Some preconditions are installed directly as described below.

## 1. Recovery invents a newer value ballot for an empty slot, then commits a different command

**Affected code:** `epaxos/epaxos.go:1152–1165`, `1240–1245`, `1278–1312`; subsequent handling at `handlePreAcceptReply` and `handleAccept`.

**Required behavior and basis:** a committed instance must retain its command across recovery. The implementation distinguishes promised ballot (`bal`) from value ballot (`vbal`), explicitly noting the addition of the latter as a correctness fix near the top of the file. Its recovery selection treats the highest value ballot as authoritative. Starting a prepare does not create a newly accepted value.

**Conditions:** a replica recovers an empty slot while a surviving peer has a committed PUT for that slot at the original ballot. N=3, F=1; the original leader need not participate. Recovering holes/missing instances is an explicit branch of `startRecoveryForInstance` and the execution loop.

**Observed reproduction:** `TestAuditRecoveryDiscardsCommittedValue` establishes a commit for row 0, instance 0 through replica 0's original `startPhase1`, replica 2's `handlePreAccept`, and the resulting `handlePreAcceptReply`/`handleCommit` sequence. The commit for replica 1 remains undelivered. The original leader also generates the commit for a later, independent instance. Delivering that commit to replica 1 first exposes a hole; the original executor schedules recovery of slot 0.0 after its unchanged grace period. Replica 1 processes that recovery request. Its ballot is 4. Replica 2 responds through `handlePrepare` with status COMMITTED, value ballot 0 and PUT(10,"chosen"). Replica 1's synthetic self-reply instead claims value ballot 4 with status NONE and no command, because recovery overwrites both `bal` and `vbal`. Selection ignores the actual committed value and starts phase 1 with NOOP. Driving the resulting PreAccept and Accept through the surviving peer and their replies through replica 1 ends with:

```text
final replica1 status=4 cmds=[{0 0 []}]; replica2 status=4 cmds=[{1 10 [99 104 111 115 101 110]}]
```

Both replicas report COMMITTED for the same slot, one with NOOP and one with PUT("chosen").

**Alternatives checked:** replica 2 really returns the committed command and original value ballot; it does not return an empty or malformed response. Its higher promise does not change that value ballot. PreAccept returns its committed status, but because that response's value ballot is below the new leader bookkeeping ballot, the recovery coordinator retains its no-op. Accept at the already committed peer returns the matching promised ballot, allowing the coordinator to commit. No duplicate reply or Byzantine message is required in this handler trace.

**Evidence limit:** the original commits and automatic timeout trigger are now executed, and the test dispatches the resulting recovery request to the normal handler. Message delivery order is controlled by the fixture; it is not a live TCP deployment. The production replica listener dispatches decoded RPCs in separate goroutines (`replica/replica.go:451–459`), so TCP byte order does not ensure handler order. The first commit remains undelivered through recovery. The value-ballot corruption itself is directly executed on original source.

## 2. Accept acknowledges a value without recording ACCEPTED status

**Affected code:** `epaxos/epaxos.go:974–1004` (`handleAccept`).

**Required behavior and basis:** a successful Accept must move an uncommitted instance to ACCEPTED, preserving that fact for later prepares. Recovery has a dedicated ACCEPTED branch at lines 1257–1258 and 1300–1303; replying NONE or PREACCEPTED instead selects a different recovery case.

**Conditions:** a valid Accept at a ballot at least as high as the promise, for an empty or preaccepted slot. This is the normal slow-path handler; no fault is needed to trigger the local error.

**Observed reproduction:** `TestAuditAcceptDoesNotRecordAccepted` exercises both cases, then sends a higher-ballot Prepare and decodes the actual reply. The empty slot reports status 0 (NONE); the preaccepted slot reports status 2 (PREACCEPTED_EQ). Both retain accepted sequence 7 and value ballot 0, but neither reports required status 3 (ACCEPTED).

**Cause:** the successful branch updates dependencies, sequence and both ballots, persists metadata and replies, but never assigns `inst.Status = ACCEPTED`.

**Alternatives checked:** the test uses a nonstale ballot and noncommitted slots; neither rejection branch applies. Accept need not carry commands for the status transition to be required. The error also occurs when commands were received normally by PreAccept. This finding is a local recovery-state defect; no independent cluster-wide loss from this particular omission is claimed.

## 3. Batched proposals omit later conflicting dependencies and can execute differently

**Affected code:** `epaxos/epaxos.go:657–690`, particularly the `break` at line 676. Batches are formed by `handlePropose:725–746` even when timed batching is disabled: it drains already queued proposals.

**Required behavior and basis:** a batch must depend on the maximum conflicting instance in each row. The executor traverses that row only through the dependency bound (`epaxos/exec.go:76–81`), so a smaller bound cannot order a later conflicting instance. Sequence numbers sort members of one strongly connected component; they do not globally order independent components.

**Conditions:** a row has instance 0 writing key 10 and instance 1 writing key 20; the new batch writes key 10 then key 20. Both earlier instances are known when computing dependencies.

**Observed reproduction:** `TestAuditBatchDependencySkipsLaterCommand` feeds those known commands through `updateConflicts` and computes the batch attributes. Result: sequence 2, dependencies `[-1,0,-1]`, instead of row-1 dependency 1. The command loop breaks immediately after finding the key-10 conflict and never examines key 20 for that row.

The test then uses the original executor on two copies of the same committed log. Executing the batch first leaves key 20 as "old" after row 1 instance 1 executes; executing row 1 instance 1 before the batch leaves it as "new". All these executor calls succeed. This demonstrates state divergence permitted by the omitted edge, without concurrency or data races.

**Alternatives checked:** the final max-sequence pass does raise sequence to 2 but does not restore the dependency. Prefix traversal only covers row 1 instance 0. Reversing the batch command order is a control: it yields dependency 1, showing that the result improperly depends on which conflicting key is visited first.

**Evidence limit:** the earlier committed instances and final batch commit are fixture states, not established by a network run. Attribute calculation and both executions are original code. The test demonstrates the local dependency defect and its consequence for the same committed graph.

## 4. SCAN range conflicts are absent from EPaxos dependency tracking

**Affected code:** `epaxos/epaxos.go:629–654` and `657–690` (index and lookup only by `Command.K`).

**Required behavior and basis:** SCAN is exposed by `client.Client.SendScan` (`client/client.go:232`) and `BufferClient.Scan`. `state.Command.Execute` reads the inclusive range [K,K+count]. `state.Conflict` explicitly treats a PUT anywhere inside that range as conflicting. Such a conflict must enter EPaxos dependencies so reads and writes can be ordered consistently.

**Conditions:** SCAN starting at key 10 with count 10, and PUT at key 15. Both are ordinary well-formed operations supported by the common client/state interface.

**Observed reproduction:** `TestAuditScanDependencyMissing` tests both PUT-then-SCAN and SCAN-then-PUT. `state.ConflictBatch` returns true in each case. After registering the known earlier command through `updateConflicts`, `updateAttributes` returns all dependencies -1 for the later command, omitting the conflicting instance.

**Cause:** scans are indexed only at their starting key; incoming scans likewise look up only that key. The code never searches the range or tests interval overlap in the normal dependency path.

**Alternatives checked:** the PUT is strictly inside the range, so this is not an inclusive-endpoint ambiguity. The payload is a correctly encoded eight-byte count. Treating SCAN as a write (`Op != GET`) does not solve the key mismatch. Although the try-preaccept conflict helper calls `ConflictBatch`, normal proposals and preaccepts use the faulty attribute path.

**Evidence limit:** this reproduction establishes missing read/write dependency edges; it does not assert an observed stale client reply or completed non-linearizable client history.

## 5. Value length wraps at 64 KiB, corrupting even scans over smaller values

**Affected code:** `state/state.go:230–254` (`Value.Marshal`/`Unmarshal`); all command and reply codecs that use it, including `replica/defs/defs.go:435–484` (`ProposeReplyTS`).

**Required behavior and basis:** a successful SCAN must return the concatenation produced by `state.Command.Execute`; serialization must preserve its bytes and the following timestamp/message boundary. `Client.SendWrite` accepts byte slices, and configuration `commandSize` is parsed as an integer without an upper-bound check. More decisively, even writes below 65,536 bytes can produce a scan result above that size. No oversized input or malformed wire data is needed.

**Cause:** `Value.Marshal` allocates a four-byte length header but writes only `uint16(len(value))`, then writes the *entire* value. `Unmarshal` reads a uint16 length, consuming only length modulo 65,536. The remainder becomes subsequent protocol fields/messages.

**Observed reproductions:** `epaxos/audit_codec_test.go` contains two tests. `TestAuditValueLengthBoundary` verifies a 65,535-byte control succeeds; 65,536 bytes decode as length 0 with 65,536 bytes left; 65,537 decode as length 1 with 65,536 bytes left. `TestAuditScanReplyLengthOverflow` round-trips two separate 32,768-byte PUTs through the original command codec and executes them. It then executes a committed scan over those two keys using the original EPaxos executor and reply writer. The original reply decoder reports:

```text
executed scan bytes=65536; client decoded OK=1 command=7 bytes=0 timestamp=4702111234474983745 remaining-stream-bytes=65536
```

The expected result is 65,536 bytes with timestamp 123 and no remaining bytes. Instead the client sees success with an empty result, reads value bytes as timestamp, and leaves the connection stream misaligned.

**Alternatives checked:** the write codec control proves each input value fits the existing uint16 field. The scan executes successfully and its raw state-machine result has the expected length, isolating corruption to the wire codec rather than scan dependency tracking. The test does not require the missing range-dependency finding. There is no decoder error warning the client of truncation.

**Evidence limit:** execution and reply serialization are local, with a memory-backed client writer; initial writes and committed scan state are fixtures. No live TCP client was used. This is an observed incorrect successful response and stream framing defect, not a claim of a particular subsequent network failure.

## 6. A committed command can block forever on an unseen dependency without triggering recovery

**Affected code:** `epaxos/epaxos.go:393–424` (`executeCommands`), `1066–1111` (`handleCommit`); dependency traversal at `epaxos/exec.go:76–81`. PreAccept likewise updates the receiving instance's row bound, not its dependencies' bounds.

**Required behavior and basis:** surviving replicas must be able to recover missing commands needed for execution. The implementation explicitly has a ten-second recovery grace period and an executor-to-protocol recovery channel. A committed dependency graph is not executable merely because its root commands are committed: absent dependencies also require fetching/recovery.

**Conditions and executed schedule:** `TestAuditUnseenDependencyNeverRecovered` uses N=3/F=1 and original marshalled protocol messages. Replica 0's write A commits at replicas 0 and 2; its commit to replica 1 is not delivered. Replica 0 becomes unavailable. Replica 2 then proposes a conflicting write B, and B commits through the two surviving replicas. Replica 1 has B with dependency row 0 instance 0, but has never received A itself. Its row-0 `crtInstance` remains -1. A subsequent GET submitted locally to replica 1 also commits through the surviving quorum.

The original executor is run for 13 seconds, exceeding the unchanged ten-second grace period. B remains COMMITTED rather than EXECUTED; no recovery request is queued for A. The local read also remains COMMITTED, with zero reply bytes. Observed output: `B status=4; local read status=4 reply bytes=0; recovery requests=0; missing-row bound=-1`.

**Cause and why waiting longer does not repair it:** the outer loop only scans through `crtInstance[q]`. Since row 0's bound is -1, it never considers A. The timeout branch runs only for a scanned slot that is itself missing, uncommitted or lacks commands. For B (and the later read), the slot is committed with commands; `executeCommand` returns false on the missing dependency, but that failure has no timeout/recovery action. There is no incoming traffic or other loop condition that can change this state. Replica 2 already has A committed, so its own executor does not initiate recovery or retransmission for A.

**Alternatives checked:** A is genuinely committed at a live peer, and the live quorum successfully commits B and the later read. This is not a failure to reach a quorum. B's dependency is valid and present in the decoded commit. The failure needs no batch, scan, malformed input, duplicate reply or inconsistent committed value. Waiting for the configured recovery grace period is insufficient because the code never starts that timer for an unseen dependency.

**Evidence limit:** the crash is modeled by ceasing replica 0's steps, leaving its commit to replica 1 undelivered and marking it unavailable to the survivors. Transport is a deterministic memory-backed RPC schedule, not a live socket failure. The unmodified executor loop and elapsed-time observation are executed locally; the indefinite nature follows from the loop bounds and absence of a recovery action on traversal failure.

## 7. SCC execution uses local arrival time to order equal-sequence writes, causing divergent state

**Affected code:** `epaxos/exec.go:166–167` (`nodeArray.Less`); timestamp creation at `epaxos/epaxos.go:1512–1513` (`newInstance`). Equal sequence numbers are reachable through `startPhase1:764–765` and `handlePreAccept:808–823`: leader bookkeeping starts at sequence -1 instead of the computed sequence, broadcasts that value, and followers update their max-sequence index with the incoming rather than adjusted sequence.

**Required behavior and basis:** every replica must use the same total order when executing a strongly connected dependency component. Sequence and replica ID can tie for two instances in one row. A tie must be resolved by a replicated, stable identifier; independently sampled `time.Now().UnixNano()` values are not such an identifier.

**Executed reproduction:** `TestAuditLocalTimeChangesSCCOrder` (`epaxos/audit_order_test.go`) runs five synchronous replicas with F=2 and thriftiness enabled. All committed commands are generated by original handlers and transmitted through original RPC codecs; no instance sequence, dependency, or timestamp is patched.

1. Replica 1 commits a seed write through the fast path and delivers it to everyone.
2. Replica 2 proposes read B of that key to replicas 0 and 1; delay its PreAccept at replica 1. Replica 0 learns B and replies.
3. Replica 0 proposes writes A0 and A1 to the same key, both depending on B. Its fast-quorum voters are replicas 3 and 4.
4. Replica 3 handles A0 before A1; replica 4 handles A1 before A0. Both return sequence 0 for both writes. The writes commit through the original fast path.
5. Deliver both write commits to replica 1, then its delayed PreAccept for B. Its reply adds dependency on A1. B commits through the original slow path with sequence 1.
6. Replicas 3 and 4 execute the resulting component. A0 depends on B; B depends on A1 (and its row prefix); A1 depends on A0 and B. The two writes therefore share a component and have identical sequence and replica ID. B is a read, so it does not overwrite the final write value.

Observed shared attributes and divergent result:

```text
A0 seq=0 deps=[-1 0 0 -1 -1]
A1 seq=0 deps=[0 0 0 -1 -1]
B  seq=1 deps=[1 0 -1 -1 -1]
same committed commands/attributes: replica3 key10="A1" replica4 key10="A0"
```

**Alternatives checked:** commands and dependencies agree at both replicas; only locally assigned arrival timestamps differ. Both executions complete. No recovery, crash, batching, scan, malformed message, duplicate reply, concurrent executor, or altered clock is needed. Handling the two PreAccepts in different orders is allowed by the actual transport: `replicaListener` launches a separate goroutine for each decoded RPC (`replica/replica.go:459–462`), so FIFO TCP bytes do not guarantee FIFO handler delivery. The test explicitly controls that delivery order rather than depending on a scheduler race.

**Evidence limit:** this is a complete normal-path handler/executor schedule with memory-backed transport, not a live deployment. The timer values in the output are actual constructor samples and were not synthesized. The fixture uses the supplied implementation's quorum functions unchanged. This finding does not depend on declaring those quorum formulas correct or incorrect.

## Remaining work

See `audit/unresolved.md`. This is an ongoing partial audit, not an assertion that the remaining implementation is correct.
