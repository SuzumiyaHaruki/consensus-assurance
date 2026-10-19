# ZooKeeper Audit Report

Source: `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/source`

Source identity: `a355171b081b5b60749db8f19cca1528b0df936f`

Build: ZooKeeper `3.9.6-SNAPSHOT` (pom version `3.9.6`), Java 17, offline Maven.

Scope: `zookeeper-server` server/quorum paths.  The captured source was not modified.
All reproductions are standalone programs under `repro/` and use classes compiled from the
captured source.

## Summary

The audit currently contains 23 reproduced local findings.  The highest-risk groups are:

- Snapshot/recovery state: F1, F5, F7, F8, F10, F11.
- Transaction-log boundaries and duplicates: F6, F15.
- Election and oracle behavior: F3, F4, F22.
- Follower/observer packet handling: F14, F16, F17, F18, F19, F20, F21, F23.
- Malformed transaction handling: F12, F13.
- Reconfiguration leader selection: F9.
- Snapshot-size configuration: F2.

## Findings

### F1. Rejected-snapshot state leaks into the older snapshot used for recovery

**Severity:** high for crash recovery / local state consistency.

**Expected behavior.** `FileSnap.deserialize` is explicitly allowed to reject a bad recent
snapshot and retry an older valid one (`FileSnap.java`, `deserialize` loop).  When it falls
back, the resulting `DataTree` and session table must represent the older snapshot only.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileSnap.java:75-124`
  retries older files after `deserialize` throws.
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1345-1390`
  clears `nodes` but does not clear `ephemerals`, `containers`, or `ttls`.
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/util/SerializeUtils.java:145-160`
  inserts sessions into the caller-provided map without clearing it.

**Necessary conditions.** A newer snapshot is structurally recognizable as a snapshot (so it
passes `SnapStream.isValidSnapshot`) but fails during or after `DataTree.deserialize`, and an
older valid snapshot exists.  The newer snapshot contains an ephemeral/container/TTL node or
a session entry.  A checksum corruption after the tree payload is one concrete trigger.

**Observed result (executed).** The fallback loaded the older snapshot (`zxid 1`), but retained
the rejected snapshot's ephemeral, container, TTL, and session entries:

```
restored zxid: 1
ephemerals after fallback: {1=[/ephemeral-from-bad-snapshot]}
containers after fallback: [/container-from-bad-snapshot]
ttls after fallback: [/ttl-from-bad-snapshot]
sessions after fallback: {123=4000}
node /ephemeral-from-bad-snapshot exists: false
Exception in thread "main" java.lang.AssertionError: ephemeral state from the rejected snapshot leaked into the restored tree
```

This is not a test-harness artifact: the program calls the production `FileSnap.serialize`
and `FileSnap.deserialize` APIs, corrupts only the trailing checksum of the newer snapshot,
and then checks the restored tree and session map.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/snapshot_retry repro/snapshot_retry/SnapshotRetryRepro.java
java -Dzookeeper.extendedTypesEnabled=true -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/snapshot_retry:$CP" SnapshotRetryRepro
```

The output is preserved at `repro/snapshot_retry/output.txt`.  The command exits non-zero
because the assertion fails on the leaked state.

**Consequence and limits.** The local restored state can report sessions, ephemerals,
containers, or TTL nodes that do not exist in the recovered tree.  This report establishes
the local state inconsistency; it does not claim a specific larger cluster-wide failure.

### F2. Setting `zookeeper.snapSizeLimitInKb=0` crashes the sync thread

**Severity:** medium; documented configuration disables the feature but kills the
`SyncRequestProcessor`.

**Expected behavior.** `zookeeper-docs/src/main/resources/markdown/zookeeperAdmin.md`
(`snapSizeLimitInKb`, around lines 650-657) says: "A non-positive value will disable the
feature."  `ZooKeeperServer.getSnapSizeInBytes` logs that a non-positive value disables the
feature and returns `size * 1024`.  With `0`, the size-based snapshot trigger should be off
and the sync processor should keep running.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java:1301-1306`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/SyncRequestProcessor.java:143-152`

`resetSnapshotStats` unconditionally evaluates:

```java
randSize = Math.abs(ThreadLocalRandom.current().nextLong() % (snapSizeInBytes / 2));
```

When the configured value is `0`, `snapSizeInBytes` is `0`, so `/ 2` is `0` and the modulo
throws `ArithmeticException`.

**Observed result (executed).** Starting a `SyncRequestProcessor` with
`-Dzookeeper.snapSizeLimitInKb=0` produces:

```
zookeeper.snapSizeLimitInKb set to a non-positive value 0; disabling feature
java.lang.ArithmeticException: / by zero
  at org.apache.zookeeper.server.SyncRequestProcessor.resetSnapshotStats(SyncRequestProcessor.java:152)
  at org.apache.zookeeper.server.SyncRequestProcessor.run(SyncRequestProcessor.java:160)
SyncRequestProcessor exited!
sync thread alive after startup: false
AssertionError: SyncRequestProcessor exited during startup with snapshot size disabled
```

`SyncRequestProcessor.run` catches the throwable and calls the critical-thread handler, so
this is a server-side failure path, not merely a failed assertion.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/snapsize_zero repro/snapsize_zero/SnapSizeZeroRepro.java
java -Dzookeeper.snapSizeLimitInKb=0 -cp "repro/snapsize_zero:$CP" SnapSizeZeroRepro
```

Output is preserved at `repro/snapsize_zero/output.txt`.  A negative value does not hit this
particular modulo-zero case; `0` is the documented boundary value and is the reproduced
condition.

### F3. Oracle revalidation can spin forever when `tryToCommit` returns false

**Severity:** high for availability of a two-node oracle configuration.

**Expected behavior.** `QuorumOracleMaj.revalidateOutstandingProp` is called from `Leader.lead`
when the leader has lost its normal quorum and the oracle has authorized revalidation.  It
should either commit the outstanding proposals or return `false` so the leader can take the
lost-quorum path.  `Leader.tryToCommit` returning `false` is a normal "not enough acks"
result and is explicitly handled by the method's own `break`.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/flexible/QuorumOracleMaj.java:122-150`
- caller: `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java:816-837`

The inner loop is:

```java
int i = 0;
while (i < outstandingProposal.size()) {
    p = outstandingProposal.get(i);
    if (p.getZxid() > lastCommitted) {
        ...
        if (!self.tryToCommit(p, p.getZxid(), null)) {
            break;
        } else {
            ...
            outstandingProposal.remove(p);
        }
    }
}
```

`i` is never incremented, and the `break` leaves the outer
`while (outstandingProposal.size() >= 1)` loop with the same list and no progress.  A
proposal whose zxid is `<= lastCommitted` has the same result: neither the element nor `i`
changes.

**Observed result (executed).** With one outstanding proposal and a mocked
`Leader.tryToCommit` returning `false`, a call with a 2-second future timeout does not return:

```
Exception in thread "main" java.lang.AssertionError:
revalidateOutstandingProp did not return within 2 seconds while tryToCommit was false
```

The worker thread remains in the loop.  This is a direct unit-level reproduction of the
non-progress condition; it does not depend on timing or a real socket.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/oracle_revalidate repro/oracle_revalidate/OracleRevalidateRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/oracle_revalidate:$CP" OracleRevalidateRepro
```

Output is preserved at `repro/oracle_revalidate/output.txt`.

**Reachability.** The method is only called after `overrideQuorumDecision` has authorized
the oracle path.  A transition from "oracle grants" to `tryToCommit` returning false can
occur if the oracle file changes between the two reads, or when the outstanding proposal's
quorum verifier requires a real majority that is absent.  When it occurs, the leader's
`lead()` thread is blocked inside the call and cannot process its normal shutdown/lost-quorum
handling.

### F4. Election oracle path can accept a leader without a majority in a 3+ voter cluster

**Severity:** high for safety of clustered deployment with `oraclePath`.

**Expected behavior.** The ZooKeeper oracle documentation says the oracle is for a 2-voter
ensemble and that outside that case `QuorumOracleMaj` shall behave as `QuorumMaj`
(`zookeeper-docs/src/main/resources/markdown/zookeeperOracleQuorums.md:31-77`).  A
`LEADING` notification must not be accepted without a real majority when there are more than
two voting members.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/FastLeaderElection.java:1185-1211`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/flexible/QuorumOracleMaj.java:51,73-76,157-170`

`QuorumOracleMaj.needOracle` starts as `true`.  `updateNeedOracle` is only called from the
leader path (`Leader.addForwardingFollower`), not during `LOOKING`/FLE.  Therefore
`receivedLeadingNotification` checks `getNeedOracle()` without checking the voting-member
count.  If `receivedFollowingNotification` found no quorum, the oracle branch can still
return a vote for the proposed leader.

**Observed result (executed).** With three voters, one vote for leader 2, and oracle file
content `0`, the production method returns a vote:

```
result with one of three votes: (2, 5, 1)
Exception in thread "main" java.lang.AssertionError:
a LEADING notification was accepted without a majority in a three-voter config
```

`QuorumMaj` requires two of three votes; the result should have been `null` (no decision).

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/oracle_fle repro/oracle_fle/org/apache/zookeeper/server/quorum/OracleFleRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/oracle_fle:$CP" org.apache.zookeeper.server.quorum.OracleFleRepro
```

Output is preserved at `repro/oracle_fle/output.txt`.  The repro invokes the private
`receivedLeadingNotification` method directly with a real `QuorumOracleMaj` and a mocked
`QuorumPeer`; it does not start a cluster.

### F5. Snapshot restore fails when digest is disabled but lastProcessedZxid serialization remains enabled

**Severity:** high for an upgrade/rollback configuration that the documented flags permit.

**Expected behavior.** The digest feature documentation says it is backward and forward
compatible and can be enabled or later disabled without compatibility issues
(`zookeeper-docs/src/main/resources/markdown/zookeeperAdmin.md:1050-1115`).
`zookeeper.serializeLastProcessedZxid.enabled` independently defaults to `true`
(`ZooKeeperServer.java:170-171`).  A snapshot written with digest enabled and
lastProcessedZxid enabled should therefore remain readable after disabling only the digest.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileSnap.java:88-106`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1702-1787`

When digest is disabled, `DataTree.deserializeZxidDigest` returns `false` without consuming
the serialized digest record.  `FileSnap.deserialize` then calls
`deserializeLastProcessedZxid`, which reads the first eight bytes of that unconsumed digest as
the last-processed zxid; the subsequent seal check sees the remaining digest bytes and
reports CRC corruption.  The snapshot is rejected even though it is structurally valid.

The reverse transition has the same root cause: a snapshot written without digest but with
lastProcessedZxid serialization enabled is read as if it had a digest.  The reader consumes
the lastZxid bytes as digest fields and fails with an unhelpful `Unreasonable length`
exception instead of treating the absent digest as an EOF case.

**Observed result (executed).**

```
snapshot valid before toggle: true
snapshot valid after toggle: true
WARN ... problem reading snap file .../snapshot.00000007
java.io.IOException: CRC corruption
  at org.apache.zookeeper.server.persistence.SnapStream.checkSealIntegrity(SnapStream.java:178)
  at org.apache.zookeeper.server.persistence.FileSnap.deserialize(FileSnap.java:105)
java.io.IOException: Not able to find valid snapshots in ...
Exception in thread "main" java.lang.AssertionError:
snapshot written with digest could not be restored with digest disabled
```

```
java.io.IOException: Unreasonable length = 1749897198
  at org.apache.jute.BinaryInputArchive.checkLength(BinaryInputArchive.java:168)
  at org.apache.zookeeper.server.DataTree$ZxidDigest.deserialize(DataTree.java:1940)
  at org.apache.zookeeper.server.DataTree.deserializeZxidDigest(DataTree.java:1709)
  at org.apache.zookeeper.server.persistence.FileSnap.deserialize(FileSnap.java:99)
java.io.IOException: Not able to find valid snapshots in ...
Exception in thread "main" java.lang.AssertionError:
snapshot written without digest could not be restored with digest enabled
```

The program writes a valid snapshot with the default digest setting, then calls
`ZooKeeperServer.setDigestEnabled(false)` before restoring it.  The snapshot remains
`SnapStream.isValidSnapshot == true` after the toggle, so the failure is in the format/reader
logic, not in the file validity check.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/digest_toggle repro/digest_toggle/DigestToggleRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/digest_toggle:$CP" DigestToggleRepro
```

The reverse direction is reproduced separately:

```bash
javac -cp "$CP" -d repro/digest_toggle_reverse \
  repro/digest_toggle_reverse/DigestToggleReverseRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/digest_toggle_reverse:$CP" DigestToggleReverseRepro
```

Outputs are preserved at `repro/digest_toggle/output.txt` and
`repro/digest_toggle_reverse/output.txt`.

**Limits.** The existing `SnapshotDigestTest.testBackwardCompatible` toggles both digest and
lastProcessedZxid together, so it does not cover this independent-flag combination.  This
repro is local snapshot I/O; it does not claim a specific ensemble-level outcome.

### F6. Truncating to zxid 0 retains data in both the log and the production `ZKDatabase` path

**Severity:** high for recovery from an empty leader; it can retain a transaction that the
leader did not have.

**Expected behavior.** `FileTxnLog.truncate(zxid)` is the log-side operation used after a
leader sends `TRUNC`.  Truncating to zxid `0` means the follower should discard every
transaction; afterward `getLastLoggedZxid()` should not report a positive zxid.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileTxnLog.java:481-500`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java:611-623`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileTxnSnapLog.java:513-535`
- follower handling: `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:618-628`
- leader selection: `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java:858-867`

`FileTxnIterator(logDir, 0)` reads the first transaction during initialization.  `truncate`
then uses `input.getPosition()` immediately after that transaction and truncates the file
there, so a log containing zxid `1,2,...` remains a log containing zxid `1`.

In addition, `ZKDatabase.truncateLog` clears the in-memory database, truncates only the
transaction log, and then calls `loadDataBase()`.  `FileTxnSnapLog.truncateLog` does not remove
any snapshots, so an existing snapshot is restored again after the requested truncation.

**Reachability.** If the leader has no committed log and
`lastProcessedZxid == 0`, `syncFollower` sets `minCommittedLog = maxCommittedLog = 0`.  For a
follower whose `peerLastZxid` is positive and is not an epoch-boundary zxid, the
`peerLastZxid > maxCommittedLog && !isPeerNewEpochZxid` branch queues `TRUNC(0)`.  The
follower then executes `truncateLog(0)`, which reaches this method.

**Observed result (executed).** A direct reproduction writes transactions with zxid 1 and 2,
closes the log, calls `truncate(0)`, and reopens it:

```
last logged zxid after truncate(0): 1
Exception in thread "main" java.lang.AssertionError:
transaction log still contains zxid 1 after truncate(0)
```

The retained transaction is not just an in-memory artifact; `getLastLoggedZxid()` scans the
reopened on-disk log and returns it.

The production wrapper has the same failure with both a snapshot and a log:

```
loaded zxid: 8
before truncate: snapshot=true, txnlog=true
after truncate: snapshot=true, txnlog=true
Exception in thread "main" java.lang.AssertionError: truncateLog(0) retained user data
```

The `/from-snapshot` node is restored from `snapshot.00000007`; the `/from-txn-log` node is
retained in the zxid-8 transaction log.

The leader-side selection is also executed with a mocked `LearnerMaster` and empty
`ZKDatabase`:

```
need snap: false
queued TRUNC zxid: 0
confirmed: leader requested truncate(0)
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/truncate_zero repro/truncate_zero/TruncateZeroRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/truncate_zero:$CP" TruncateZeroRepro
```

The production-wrapper reproduction is:

```bash
javac -cp "$CP" -d repro/truncate_zero_db repro/truncate_zero_db/TruncateZeroDbRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/truncate_zero_db:$CP" TruncateZeroDbRepro
```

The protocol-selection reproduction is:

```bash
javac -cp "$CP" -d repro/truncate_zero_protocol \
  repro/truncate_zero_protocol/org/apache/zookeeper/server/quorum/TruncateZeroProtocolRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/truncate_zero_protocol:$CP" \
  org.apache.zookeeper.server.quorum.TruncateZeroProtocolRepro
```

Outputs are preserved at `repro/truncate_zero/output.txt`,
`repro/truncate_zero_db/output.txt`, and
`repro/truncate_zero_protocol/output.txt`.

**Limits.** The storage and leader-selection pieces are executed locally; a full
leader/follower cluster experiment is not claimed.

### F7. Runtime exception in a malformed snapshot aborts fallback to an older snapshot

**Severity:** high for recovery with a corrupt snapshot and a valid older snapshot.

**Expected behavior.** `FileSnap.deserialize` loops over up to 100 candidate snapshots so
that a bad newer file can be skipped and an older valid snapshot used.  That loop should
handle malformed snapshot content, not only I/O failures.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileSnap.java:84-112`
  catches `IOException` only.
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1368-1376`
  calls `EphemeralType.get`.
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/EphemeralType.java:177-181`
  throws `IllegalArgumentException` for an unknown extended feature bit.

**Necessary conditions.** Extended ephemeral types are enabled; the newer snapshot is
structurally valid but contains a node with an invalid `ephemeralOwner`; an older valid
snapshot exists.  A corrupt or partially tampered snapshot can satisfy this.

**Observed result (executed).** The newer snapshot passes `SnapStream.isValidSnapshot`, then
aborts recovery:

```
newer snapshot accepted by pre-check: true
java.lang.IllegalArgumentException: Invalid ephemeralOwner. [ff00010000000001]
  at org.apache.zookeeper.server.EphemeralType.get(EphemeralType.java:180)
  at org.apache.zookeeper.server.DataTree.deserialize(DataTree.java:1370)
  at org.apache.zookeeper.server.util.SerializeUtils.deserializeSnapshot(SerializeUtils.java:159)
  at org.apache.zookeeper.server.persistence.FileSnap.deserialize(FileSnap.java:141)
Exception in thread "main" java.lang.AssertionError:
runtime failure in the newer snapshot aborted the fallback
```

The older `snapshot.00000001` is never loaded.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/snapshot_runtime repro/snapshot_runtime/SnapshotRuntimeRepro.java
java -Dzookeeper.extendedTypesEnabled=true -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/snapshot_runtime:$CP" SnapshotRuntimeRepro
```

Output is preserved at `repro/snapshot_runtime/output.txt`.

**Limits.** The repro uses a deliberately malformed node owner; the relevant behavior is the
exception type escaping the fallback loop, not the source of the corruption.

### F8. Empty tail transaction log makes `getLastLoggedZxid()` overstate the durable log

**Severity:** high for election/recovery accuracy.

**Expected behavior.** If the newest transaction-log file is empty (for example, a crash
occurred just after file creation), `FileTxnLog.getLastLoggedZxid()` should return the last
transaction actually present in the older log.  The empty tail should not count as a
transaction.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileTxnLog.java:365-388`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java` uses
  `getLastLoggedZxid()` when constructing the initial election vote.

`getLastLoggedZxid` initializes `zxid` from the newest filename before scanning:

```java
long maxLog = files.length > 0
    ? Util.getZxidFromName(files[files.length - 1].getName(), LOG_FILE_PREFIX) : -1;
long zxid = maxLog;
...
return zxid;
```

`FileTxnIterator` deletes the empty tail, but the scan then finds no transaction with the
filename’s zxid and the method still returns `maxLog`.

**Observed result (executed).**

```
newest log cleared: log.2
WARN ... Delete empty tail log file to recover from corruption file: log.2
reported last logged zxid: 2
Exception in thread "main" java.lang.AssertionError:
empty tail made getLastLoggedZxid report 2 instead of 1
```

The test writes zxid 1 in an older log and zxid 2 in the newest log, then truncates the newest
file to zero bytes.  Only zxid 1 remains, but the method reports 2.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/last_logged_empty repro/last_logged_empty/LastLoggedEmptyRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/last_logged_empty:$CP" LastLoggedEmptyRepro
```

Output is preserved at `repro/last_logged_empty/output.txt`.

**Limits.** The empty-file condition is local; the election consequence is inferred from the
`QuorumPeer` use of this value.

### F9. Single-voter reconfiguration with a changed leader address can throw from leader selection

**Severity:** medium/high for reconfiguration; the leader can fail with an unchecked exception.

**Expected behavior.** `Leader.getDesignatedLeader` must return a designated leader for a
committed reconfiguration.  A new view containing only the current voter is a valid quorum,
and the method should handle the case where its address changed without throwing.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java:916-934`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java:1001-1010`

The method removes the current leader from the candidate set:

```java
HashSet<Long> candidates = new HashSet<>(newQVAcksetPair.getAckset());
candidates.remove(self.getMyId());
long curCandidate = candidates.iterator().next();
```

When the new view has only the current leader, and its address differs from the current
leader address, the first same-address check fails, the single ack is removed, and
`iterator().next()` throws `NoSuchElementException`.

**Observed result (executed).** The isolated reproduction creates a real `Leader` with a
one-voter `QuorumMaj` whose member address differs from the leader’s listen address and invokes
the production private method:

```
java.util.NoSuchElementException
  at java.base/java.util.HashMap$HashIterator.nextNode(HashMap.java:1599)
  at org.apache.zookeeper.server.quorum.Leader.getDesignatedLeader(Leader.java:931)
Exception in thread "main" java.lang.AssertionError:
getDesignatedLeader threw instead of returning a valid leader
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/designated_leader_empty \
  repro/designated_leader_empty/org/apache/zookeeper/server/quorum/DesignatedLeaderEmptyRepro.java
# The Leader constructor binds a local socket; run this part through isolated_exec.
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/designated_leader_empty:$CP" \
  org.apache.zookeeper.server.quorum.DesignatedLeaderEmptyRepro
```

Output is preserved at `repro/designated_leader_empty/output.txt`.

**Limits.** The repro invokes the production method with a direct one-voter reconfig proposal;
it does not run a full reconfig client workflow.  A normal one-voter static configuration is
standalone, but the method is also reachable from dynamic reconfiguration code.

### F10. `ZKDatabase.clear()` leaves transaction-count and log-size state stale

**Severity:** low/medium; this changes snapshot scheduling rather than directly corrupting
tree data.

**Expected behavior.** `ZKDatabase.clear()` is documented to clear the database state, and
`rollLog()` resets the transaction count and total log-size accounting
(`ZKDatabase.resetTxnCount`).  A clear followed by a reload or truncation should not inherit
the previous database’s snapshot-trigger counters.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java:175-193`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/ZKDatabase.java:784-801`

**Observed result (executed).**

```
txn count before clear: 1
log size before clear: 67108880
txn count after clear: 1
log size after clear: 67108880
Exception in thread "main" java.lang.AssertionError: txnCount survived ZKDatabase.clear()
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/clear_txn_count repro/clear_txn_count/ClearTxnCountRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/clear_txn_count:$CP" ClearTxnCountRepro
```

Output is preserved at `repro/clear_txn_count/output.txt`.

**Limits.** This is a snapshot-trigger state leak.  It does not by itself show a data-tree
inconsistency; the failure is that the next snapshot may be scheduled using stale counters.

### F11. Missing `acceptedEpoch` is initialized below an existing `currentEpoch` and startup fails

**Severity:** high for upgraded or partially initialized nodes.

**Expected behavior.** `QuorumPeer.loadDataBase` explicitly handles a missing
`acceptedEpoch` file as a migration/defaulting case.  If `currentEpoch` is already present
and ahead of the snapshot epoch, the chosen default for `acceptedEpoch` must be at least
`currentEpoch`; otherwise the node immediately rejects the value it just wrote.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java:1182-1204`

The missing-file branch initializes `acceptedEpoch` from `epochOfZxid`, but the subsequent
invariant requires `acceptedEpoch >= currentEpoch`.

**Observed result (executed).** With a snapshot at zxid 5 (`epochOfZxid == 0`), a
`currentEpoch` file containing `6`, and no `acceptedEpoch` file:

```
currentEpoch=6, acceptedEpoch missing, snapshot zxid=5
ERROR ... Unable to load database on disk
java.io.IOException: The accepted epoch, 0 is less than the current epoch, 6
  at org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase(QuorumPeer.java:1200)
java.lang.RuntimeException: Unable to run quorum server
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/epoch_missing repro/epoch_missing/EpochMissingRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/epoch_missing:$CP" EpochMissingRepro
```

Output is preserved at `repro/epoch_missing/output.txt`.

**Limits.** The repro exercises the local startup/load path; it does not require a running
ensemble.  The missing `acceptedEpoch` file is the input condition, not a source modification.

### F12. Malformed multi-op is reported as OK and advances `lastProcessedZxid`

**Severity:** high for malformed/corrupt transaction replay.

**Expected behavior.** If a multi-op contains an unsupported sub-transaction type, the
transaction must not be counted as successfully applied.  `processTxn` should either throw
or return a non-OK error and must not advance the durable processing watermark.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1005-1041`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1091-1108`

The `default` branch throws `IOException("Invalid type of op: ...")`; the surrounding
`catch (IOException)` only logs and leaves `rc.err` at its initialized `Code.OK` value.
Afterward, the non-subtransaction path advances `lastProcessedZxid` to `rc.zxid`.

**Observed result (executed).** A multi-op containing sub-transaction type `999` produced:

```
lastProcessedZxid before: 0
result error: 0 (OK=0)
lastProcessedZxid after: 42
Exception in thread "main" java.lang.AssertionError:
malformed multi-op was reported as successfully processed
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/malformed_multi repro/malformed_multi/MalformedMultiRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/malformed_multi:$CP" MalformedMultiRepro
```

Output is preserved at `repro/malformed_multi/output.txt`.

**Limits.** The repro invokes the production transaction-application method directly.  It
establishes the local error/watermark behavior; a full cluster replay experiment is not
claimed.

### F13. Unknown top-level transaction type is silently accepted and advances the watermark

**Severity:** high for corrupt/unsupported transaction replay.

**Expected behavior.** A transaction type not handled by `DataTree.processTxn` must produce
an error or be rejected, and must not advance `lastProcessedZxid` as if data had been applied.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:855-1041`
- watermark update: `zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java:1091-1108`

The top-level `switch (header.getType())` has no `default` branch.  An unknown type falls
through with `rc.err` initialized to `Code.OK`, then the non-subtransaction path advances the
watermark.

**Observed result (executed).**

```
result error: 0 (OK=0)
lastProcessedZxid after: 43
Exception in thread "main" java.lang.AssertionError:
unknown top-level txn type was silently accepted and advanced the watermark
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/unknown_txn repro/unknown_txn/UnknownTxnRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/unknown_txn:$CP" UnknownTxnRepro
```

Output is preserved at `repro/unknown_txn/output.txt`.

**Limits.** The repro calls the production `DataTree.processTxn` method directly; a corrupt
or unsupported on-disk transaction is the motivating input.

### F14. Redundant follower `PROPOSE` is not released and creates duplicate pending transactions

**Severity:** high for the protocol scenario where an old leader resends an outstanding
proposal.

**Expected behavior.** The supplied protocol notes
(`zookeeper-specifications/protocol-spec/issues.md`, Issue 2) state that a follower that
receives a redundant `PROPOSE` should release/ignore it.  Duplicate pending transactions can
otherwise make the next `COMMIT` mismatch.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java:161-181`
- commit matching: `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/FollowerZooKeeperServer.java:99-109`

The follower logs a warning for a non-consecutive zxid but still calls
`fzk.logRequest(...)` unconditionally.  A second proposal with the same zxid therefore adds a
second pending transaction.

**Observed result (executed).** Two identical `Leader.PROPOSE` packets produced:

```
WARN ... Got zxid 0x5 expected 0x1
WARN ... Got zxid 0x5 expected 0x6
AssertionError: the same PROPOSE was delivered to logRequest twice instead of being released
```

`logRequest` was verified with `times(2)`.  After one `COMMIT(5)`, the second duplicate
remains at the head of `pendingTxns`; the next commit would fail the zxid check and invoke
`ServiceUtils.requestSystemExit(ExitCode.UNMATCHED_TXN_COMMIT)`.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/duplicate_proposal \
  repro/duplicate_proposal/org/apache/zookeeper/server/quorum/DuplicateProposalRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/duplicate_proposal:$CP" \
  org.apache.zookeeper.server.quorum.DuplicateProposalRepro
```

Output is preserved at `repro/duplicate_proposal/output.txt`.

**Limits.** The repro drives `Follower.processPacket` with a mocked `FollowerZooKeeperServer`
to count storage calls; it does not start a cluster.  The subsequent commit mismatch is
inferred from the verified duplicate queue behavior and the production `commit` method.

### F15. `FileTxnLog.append` accepts duplicate zxid and persists both records

**Severity:** medium/high for duplicate-proposal or replay paths.

**Expected behavior.** Transaction-log entries are ordered by zxid.  A non-increasing zxid
must not be accepted as a successful append; otherwise duplicate records survive on disk and
can be replayed.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileTxnLog.java:279-335`

The method logs a warning for `hdr.getZxid() <= lastZxidSeen` but continues through the
normal write path and returns `true`.

**Observed result (executed).**

```
first append: true
WARN ... Current zxid 1 is <= 1 for create
second append: true
logged zxid: 1
logged zxid: 1
txn count: 2
Exception in thread "main" java.lang.AssertionError: duplicate zxid was retained in the transaction log
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/duplicate_append repro/duplicate_append/DuplicateAppendRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/duplicate_append:$CP" DuplicateAppendRepro
```

Output is preserved at `repro/duplicate_append/output.txt`.

**Limits.** This is a direct storage-layer reproduction.  The follower-side path that can
feed a duplicate proposal is documented separately as F14.

### F16. Follower accepts a proposal with a missing predecessor

**Severity:** high for recovery/continuity of the follower log.

**Expected behavior.** A follower should not apply a proposal whose predecessor is absent.
It should reject the packet, stop the following session, or trigger resynchronization rather
than treating the gap as an ordinary warning.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java:161-180`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:637-640`
  documents that the initial `lastQueued` is zero.

The live proposal path logs a warning when `hdr.getZxid() != lastQueued + 1` and then
unconditionally calls `fzk.logRequest(...)`.

**Observed result (executed).** A fresh follower received a proposal at zxid 5 with no
predecessor:

```
WARN ... Got zxid 0x5 expected 0x1
AssertionError: a proposal with a missing predecessor was queued for logging
```

`logRequest` was verified as called once.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/gap_proposal \
  repro/gap_proposal/org/apache/zookeeper/server/quorum/GapProposalRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/gap_proposal:$CP" \
  org.apache.zookeeper.server.quorum.GapProposalRepro
```

Output is preserved at `repro/gap_proposal/output.txt`.

**Limits.** The repro drives `Follower.processPacket` with a mocked learner server; it
establishes the acceptance/queueing behavior, not a full cluster divergence.

### F17. `syncFollower` can send a TRUNC across an epoch boundary

**Severity:** high for cross-epoch recovery.

**Expected behavior.** `queueCommittedProposals` explicitly refuses to send a TRUNC that
crosses an epoch boundary (`LearnerHandler.java:999-1005`) because the learner cannot safely
truncate across epochs.  `syncFollower` must apply the same rule and fall back to a snapshot.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java:858-867`
- comparison rule: `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java:995-1005`

The `peerLastZxid > maxCommittedLog && !isPeerNewEpochZxid` branch compares only the numeric
zxid.  With `maxCommittedLog` in epoch 0 and `peerLastZxid` in epoch 1, it queues
`TRUNC(maxCommittedLog)` across the boundary.

**Observed result (executed).**

```
need snap: false
queued TRUNC zxid: 0x5
AssertionError: syncFollower queued a cross-epoch TRUNC instead of a snapshot
```

The repro uses a follower zxid of `0x100000005` (epoch 1, counter 5) and a leader committed
zxid of `5` (epoch 0).

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/cross_epoch_trunc \
  repro/cross_epoch_trunc/org/apache/zookeeper/server/quorum/CrossEpochTruncRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/cross_epoch_trunc:$CP" \
  org.apache.zookeeper.server.quorum.CrossEpochTruncRepro
```

Output is preserved at `repro/cross_epoch_trunc/output.txt`.

**Limits.** The repro invokes the production `syncFollower` selection with a mocked learner
master; it does not run a full leader/follower cluster.

### F18. Follower `COMMITANDACTIVATE` with no pending proposal throws from `pendingTxns.element()`

**Severity:** high for out-of-order or malformed reconfiguration packets.

**Expected behavior.** A follower that receives `COMMITANDACTIVATE` without a matching
pending reconfiguration proposal should reject or disconnect with a controlled error, not
throw an unchecked queue exception from the packet-processing thread.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java:209-221`

The method calls `fzk.pendingTxns.element()` before checking whether a pending proposal
exists or whether the zxid matches.

**Observed result (executed).**

```
java.util.NoSuchElementException
  at java.base/java.util.AbstractQueue.element(AbstractQueue.java:136)
  at org.apache.zookeeper.server.quorum.Follower.processPacket(Follower.java:211)
AssertionError: empty COMMITANDACTIVATE escaped as an unchecked queue exception
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/commit_activate_empty \
  repro/commit_activate_empty/org/apache/zookeeper/server/quorum/CommitActivateEmptyRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/commit_activate_empty:$CP" \
  org.apache.zookeeper.server.quorum.CommitActivateEmptyRepro
```

Output is preserved at `repro/commit_activate_empty/output.txt`.

**Limits.** The repro invokes the production packet handler with a mocked follower server;
the malformed/out-of-order packet is the input condition, not a source modification.

### F19. `Learner.syncWithLeader` dereferences a missing proposal for `COMMITANDACTIVATE`

**Severity:** high for malformed or out-of-order synchronization packets.

**Expected behavior.** During sync, `COMMITANDACTIVATE` should be accepted only when a
matching proposal is present in `packetsNotLogged`.  A missing proposal must produce a
controlled protocol error, not a `NullPointerException`.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:670-690`

The code calls `packetsNotLogged.peekFirst()` and immediately dereferences `pif.hdr` without
checking whether `pif` is null.

**Observed result (executed).** A sync stream containing `DIFF` then
`COMMITANDACTIVATE` produced:

```
java.lang.NullPointerException: Cannot read field "hdr" because "pif" is null
  at org.apache.zookeeper.server.quorum.Learner.syncWithLeader(Learner.java:673)
AssertionError: syncWithLeader dereferenced a missing proposal for COMMITANDACTIVATE
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/sync_commit_activate \
  repro/sync_commit_activate/org/apache/zookeeper/server/quorum/SyncCommitActivateRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/sync_commit_activate:$CP" \
  org.apache.zookeeper.server.quorum.SyncCommitActivateRepro
```

Output is preserved at `repro/sync_commit_activate/output.txt`.

**Limits.** The repro feeds the production sync loop a malformed packet sequence; it does
not require a real leader connection.

### F20. `Learner.syncWithLeader` dereferences a missing proposal for `COMMIT` after TRUNC

**Severity:** high for malformed/out-of-order synchronization packets.

**Expected behavior.** After a `TRUNC`, a `COMMIT` without a matching proposal should be
rejected or trigger a controlled sync failure, not throw from `pif.hdr`.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:670-690`

`writeToTxnLog` is false for the TRUNC path, so the `COMMIT` branch reaches
`pif.hdr.getZxid()` with `pif == null`.

**Observed result (executed).**

```
WARN ... Truncating log to get in sync with the leader 0x0
java.lang.NullPointerException: Cannot read field "hdr" because "pif" is null
  at org.apache.zookeeper.server.quorum.Learner.syncWithLeader(Learner.java:673)
AssertionError: syncWithLeader dereferenced a missing proposal for COMMIT
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/sync_commit_empty \
  repro/sync_commit_empty/org/apache/zookeeper/server/quorum/SyncCommitEmptyRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/sync_commit_empty:$CP" \
  org.apache.zookeeper.server.quorum.SyncCommitEmptyRepro
```

Output is preserved at `repro/sync_commit_empty/output.txt`.

**Limits.** The repro feeds the production sync loop a malformed `TRUNC`/`COMMIT` sequence;
it does not use a live leader connection.

### F21. Observer sync auto-unboxes a missing commit zxid at `UPTODATE`

**Severity:** high for observer synchronization when a proposal is received without a
matching commit.

**Expected behavior.** At the end of observer sync, a proposal without a committed zxid
should be handled explicitly (for example, retained for later commit or rejected); it must not
cause a null-unboxing exception.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:850-860`

After `UPTODATE`, the observer branch iterates `packetsNotLogged` and evaluates:

```java
Long zxid = packetsCommitted.peekFirst();
if (p.hdr.getZxid() != zxid) { ... }
```

If `packetsCommitted` is empty, the comparison auto-unboxes null.

**Observed result (executed).**

```
java.lang.NullPointerException: Cannot invoke "java.lang.Long.longValue()" because "zxid" is null
  at org.apache.zookeeper.server.quorum.Learner.syncWithLeader(Learner.java:855)
AssertionError: observer sync auto-unboxed a missing commit zxid
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/observer_sync_empty \
  repro/observer_sync_empty/org/apache/zookeeper/server/quorum/ObserverSyncEmptyRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/observer_sync_empty:$CP" \
  org.apache.zookeeper.server.quorum.ObserverSyncEmptyRepro
```

Output is preserved at `repro/observer_sync_empty/output.txt`.

**Limits.** The repro feeds the production observer sync loop `DIFF`, `PROPOSAL`, and
`UPTODATE` packets; it does not start a cluster.

### F22. Missing/unreadable oracle is treated as permission to follow a leader

**Severity:** high for safety in two-node oracle deployments.

**Expected behavior.** If the oracle cannot be read, the election code must fail closed:
the node must not follow a leader merely because `askOracle()` returned `false` on an I/O
error.  A valid negative answer is different from an unavailable oracle.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/flexible/QuorumOracleMaj.java:80-103`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/FastLeaderElection.java:1199-1204`

`askOracle()` returns `false` for both a file containing `0` and any exception (including a
missing file).  The election branch treats `!askOracle()` as an affirmative decision to
follow.

**Observed result (executed).** With an oracle path of `null` and a two-voter
`QuorumOracleMaj`, one LEADING notification produced:

```
java.io.FileNotFoundException: nullnull (No such file or directory)
  at org.apache.zookeeper.server.quorum.flexible.QuorumOracleMaj.askOracle(QuorumOracleMaj.java:84)
  at org.apache.zookeeper.server.quorum.FastLeaderElection.receivedLeadingNotification(FastLeaderElection.java:1199)
result with missing oracle: (2, 5, 1)
AssertionError: missing oracle was treated as permission to follow a leader
```

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/oracle_missing \
  repro/oracle_missing/org/apache/zookeeper/server/quorum/OracleMissingRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/oracle_missing:$CP" \
  org.apache.zookeeper.server.quorum.OracleMissingRepro
```

Output is preserved at `repro/oracle_missing/output.txt`.

**Limits.** The repro invokes the production election method directly with a missing oracle;
it does not start a cluster.  The distinction between a valid `0` and an unavailable oracle
is the defect.

### F23. Sync path starts with `lastQueued = 0` and cannot validate the first proposal

**Severity:** high for gap detection during synchronization.

**Expected behavior.** `Learner.syncWithLeader` should initialize its continuity check from
the actual synchronization position (the DIFF/SNAP/TRUNC position or the peer’s last zxid),
so a first proposal with a missing predecessor is rejected or causes resynchronization.

**Affected code.**

- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:637-640`
- `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java:540-566`

The code explicitly initializes `long lastQueued = 0` with a TODO explaining that the
LearnerHandler does not currently provide the ideal last processed zxid.  That leaves
`enforceContinuousProposal` unable to reject a first proposal at an arbitrary zxid.

**Observed result (executed).**

```
enforceContinuousProposal returned: 5
AssertionError: first sync proposal at zxid 5 was accepted with no predecessor
```

The proposal’s predecessor was not present; only the `lastQueued == 0` sentinel was used.

**Reproduction.**

```bash
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/work
CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
javac -cp "$CP" -d repro/sync_first_gap \
  repro/sync_first_gap/org/apache/zookeeper/server/quorum/SyncFirstGapRepro.java
java -Dlogback.configurationFile=repro/logback-warn.xml \
  -cp "repro/sync_first_gap:$CP" \
  org.apache.zookeeper.server.quorum.SyncFirstGapRepro
```

Output is preserved at `repro/sync_first_gap/output.txt`.

**Limits.** The repro calls the production continuity method directly.  The normal leader
usually sends contiguous proposals; the defect is the missing validation when synchronization
starts at a nonzero position or receives an out-of-order first proposal.

## Test-suite evidence

The following suites were executed against the captured source:

- `FileTxnLogTest`, `FileTxnSnapLogTest`, `QuorumMajorityTest`, `QuorumOracleMajTest`,
  `GetProposalFromTxnTest`: all passed.
- `DataTreeTest`, `ZkDatabaseCorruptionTest`, `SnapshotDigestTest`, `TxnLogDigestTest`,
  `InvalidSnapshotTest`, `RestoreCommittedLogTest`, `QuorumZxidSyncTest`, `DIFFSyncTest`,
  `DIFFSyncConsistencyTest`, `FollowerResyncConcurrencyTest`: all passed.
- Election/epoch tests (`FLEBackwardElectionRoundTest`, `FLELostMessageTest`,
  `FLEMalformedNotificationMessageTest`, `FLEOutOfElectionTest`, `FLENewEpochTest`,
  `Zab1_0Test`, `QuorumPeerTest`, `QuorumPeerMainTest`, `CurrentEpochWriteFailureTest`,
  `EpochWriteFailureTest`): all passed.
- General `org.apache.zookeeper.server` test package: passed.
- Quorum package suite (excluding auth/SSL/Kerberos): 490 tests, 0 failures, 1 error.
  The single error was `MultipleAddressesTest.testRecreateSocketAddresses`, caused by
  external DNS resolution of `google.com` in the network-isolated sandbox, not by the
  source.
- Focused recovery/election tests (`EmptiedSnapshotRecoveryTest`,
  `DuplicateLocalSessionUpgradeTest`, `FLERestartTest`, `FLEPredicateTest`,
  `FourLetterWordsQuorumTest`, `SnapshotAndRestoreCommandTest`,
  `ZookeeperServerRestoreTest`, `TxnLogToolkitTest`, `SnapshotFormatterTest`,
  `InvalidSnapshotTest`): passed.
- Client/server integration tests (`ACLTest`, `CreateTest`, `CreateModeTest`, `CheckTest`,
  `EventTypeTest`, `DisconnectedWatcherTest`, `ClientRetryTest`, `NullDataTest`,
  `MultiAsyncTransactionTest`, `AsyncTest`): passed.
- Session/expiry tests (`SessionTrackerTest`, `ExpiryQueueTest`): passed.

These suites do not cover the twenty-three conditions above; the standalone repros do.

Raw suite logs are retained in the run's read-only `executions/` directory, for example:

- `executions/9f81f5e9ed18462a803ad54903793ef1/stdout.txt` (targeted persistence/quorum tests)
- `executions/803560c971894458ad9be83faaf630b6/stdout.txt` (log/snapshot consistency)
- `executions/8a98568fcfce4ad4ade8155c2e7b6ca4/stdout.txt` (general server package)
- `executions/84c955ae81634fe7a0caca104173ee7d/stdout.txt` (election/epoch)
- `executions/4e85b57a9eb54370b4c9ab1226dea27d/stdout.txt` (quorum package)
- `executions/4637440e5b1a48d8aef60391fd85f0c1/stdout.txt` (focused recovery/election tests)
- `executions/0deb78f954d74b3dae14f3a4096ceed4/stdout.txt` (client/server integration tests)
- `executions/ca44b2970bd141519c596c0a6a6568f4/stdout.txt` (session/expiry tests)

## Coverage and negative results

The following paths were reviewed in addition to the finding-specific code:

- `FileTxnLog`, `FileSnap`, `FileTxnSnapLog`, `DataTree`, `ZKDatabase`
- `QuorumPeer`, `Leader`, `Follower`, `Learner`, `LearnerHandler`, `Observer`, `ObserverMaster`
- `FastLeaderElection`, `QuorumOracleMaj`, `CommitProcessor`, `SyncRequestProcessor`
- session/expiry tracking, request processors, and snapshot/restore tests

The existing focused recovery/election, client/server integration, and session/expiry tests
passed.  No additional defect was established from the session/expiry or observer-master
review; those areas remain covered by the passing suites and the source inspection above.

## Notes / unresolved

- All twenty-three findings are local defects demonstrated from the captured source.  The source
  implementation itself was not modified.
- F1 is a recovery-state issue in `FileSnap`; a fix would need to reset the `DataTree`
  ephemeral/container/TTL sets and the caller's session map before each retry (or discard the
  failed attempt's state).
- F2 is specific to the documented `0` boundary.  Negative values were not observed to hit
  the same divide-by-zero, but should be handled consistently with the "non-positive"
  documentation.
- F3 and F4 involve the oracle feature, which is non-default but is documented and supported
  by the source.  F4 is especially relevant when an `oraclePath` is present in a 3+ voter
  configuration.
- F5 is an independent digest/lastProcessedZxid flag combination; the source's existing
  compatibility test couples the two flags and therefore misses it.
- F6's direct storage behavior and its leader-side `TRUNC(0)` selection are executed;
  a full leader/follower cluster experiment remains possible future work.
- F7 demonstrates the `RuntimeException` escape from the fallback loop; it is separate
  from F1's `IOException` fallback state leak.
- F8 is direct log recovery behavior; the election impact follows from the `QuorumPeer`
  vote initialization using `getLastLoggedZxid()`.
- F9 is a reconfiguration edge; its reproduction invokes the production method under
  isolated execution because the `Leader` constructor binds a local socket.
- F10 is a lower-severity snapshot-scheduling state leak; it is included separately from
  the data-correctness findings.
- F11 is a local startup/load failure caused by the missing-epoch-file migration path.
- F12 is the malformed multi-op error/watermark behavior in `DataTree.processTxn`.
- F13 is the unknown top-level transaction-type error/watermark behavior in the same method.
- F14 is the follower-side duplicate-proposal handling mismatch with the supplied protocol
  notes.
- F15 is the storage-layer duplicate-zxid append behavior that permits duplicate records to
  survive on disk.
- F16 is the follower-side acceptance of a proposal with a missing predecessor.
- F17 is the cross-epoch TRUNC selection in `syncFollower`.
- F18 is the unguarded `pendingTxns.element()` access for `COMMITANDACTIVATE`.
- F19 is the unguarded `pif.hdr` access in the sync-path `COMMITANDACTIVATE` branch.
- F20 is the corresponding unguarded `pif.hdr` access in the sync-path `COMMIT` branch after
  TRUNC.
- F21 is the observer sync null-unboxing of `packetsCommitted.peekFirst()` at `UPTODATE`.
- F22 is the election treatment of an unavailable oracle as permission to follow.
- F23 is the uninitialized continuity check in the synchronization path.
- This is a partial audit; no final claim is made that the list is exhaustive.
