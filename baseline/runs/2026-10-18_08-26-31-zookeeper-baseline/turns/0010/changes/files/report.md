# ZooKeeper Audit Report

Source: `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-18_08-26-31-zookeeper-baseline/source`

Source identity: `a355171b081b5b60749db8f19cca1528b0df936f`

Build: ZooKeeper `3.9.6-SNAPSHOT` (pom version `3.9.6`), Java 17, offline Maven.

Scope: `zookeeper-server` server/quorum paths.  The captured source was not modified.
All reproductions are standalone programs under `repro/` and use classes compiled from the
captured source.

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

These suites do not cover the nine conditions above; the standalone repros do.

Raw suite logs are retained in the run's read-only `executions/` directory, for example:

- `executions/9f81f5e9ed18462a803ad54903793ef1/stdout.txt` (targeted persistence/quorum tests)
- `executions/803560c971894458ad9be83faaf630b6/stdout.txt` (log/snapshot consistency)
- `executions/8a98568fcfce4ad4ade8155c2e7b6ca4/stdout.txt` (general server package)
- `executions/84c955ae81634fe7a0caca104173ee7d/stdout.txt` (election/epoch)
- `executions/4e85b57a9eb54370b4c9ab1226dea27d/stdout.txt` (quorum package)

## Notes / unresolved

- All nine findings are local defects demonstrated from the captured source.  The source
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
- This is a partial audit; no final claim is made that the list is exhaustive.
