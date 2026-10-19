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

These suites do not cover the four conditions above; the standalone repros do.

Raw suite logs are retained in the run's read-only `executions/` directory, for example:

- `executions/9f81f5e9ed18462a803ad54903793ef1/stdout.txt` (targeted persistence/quorum tests)
- `executions/803560c971894458ad9be83faaf630b6/stdout.txt` (log/snapshot consistency)
- `executions/8a98568fcfce4ad4ade8155c2e7b6ca4/stdout.txt` (general server package)
- `executions/84c955ae81634fe7a0caca104173ee7d/stdout.txt` (election/epoch)
- `executions/4e85b57a9eb54370b4c9ab1226dea27d/stdout.txt` (quorum package)

## Notes / unresolved

- All four findings are local defects demonstrated from the captured source.  I did not
  modify the captured implementation or its dependencies to create them.
- F1 is a recovery-state issue in `FileSnap`; a fix would need to reset the `DataTree`
  ephemeral/container/TTL sets and the caller's session map before each retry (or discard the
  failed attempt's state).
- F2 is specific to the documented `0` boundary.  Negative values were not observed to hit
  the same divide-by-zero, but should be handled consistently with the "non-positive"
  documentation.
- F3 and F4 involve the oracle feature, which is non-default but is documented and supported
  by the source.  F4 is especially relevant when an `oraclePath` is present in a 3+ voter
  configuration.
- This is a partial audit; no final claim is made that the list is exhaustive.
