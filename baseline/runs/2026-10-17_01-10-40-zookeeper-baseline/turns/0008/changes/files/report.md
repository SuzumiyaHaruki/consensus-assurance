# Audit report — Apache ZooKeeper 3.9.6 server, source identity a355171b081b5b60749db8f19cca1528b0df936f

Scope: `zookeeper-server` main sources (`org/apache/zookeeper/server/**` — quorum/Zab,
request pipeline, persistence, sessions, data tree) audited against their own documented
behaviour, with the server test suite used as an oracle. Working copy: this directory;
the captured read-only tree at `../source` is byte-identical to it
(`diff -rq ../source .` reports only the harness-added `.aws` entry).

Status: **one confirmed, reproduced defect** — **F2** (§3): the admin `snapshot` command
enforces a 300 ms rate-limit interval instead of the documented/configured 5 minutes
(1000× looser), reproduced with a standalone program over the production objects.
Nothing else was confirmed: **F1** is a nondeterministic test race (falsified on re-run),
**E1/E2** are environment artifacts.

Shape of the evidence: essentially the whole `zookeeper-server` test suite that can run in
this sandbox passes (239 classes / 1763+ methods), including every
election/Zab/recovery/reconfig/durability class, and the consensus-critical code paths were
read against their documented contracts without finding a deviation. F2 was found outside
that coverage: no test asserts the admin rate limit, and the harness zeroes the interval
(`ZKTestCase.java:102`), so the suite passes while the limit is 1000× off — a reminder that
the passing suite is not by itself evidence about behaviour it disables. Remaining leads
are listed in §6.

---

## 1. Environment facts established by experiment (needed to reproduce anything)

1. **Only `isolated_exec` can run socket-based tests.** In the ordinary shell every
   `ServerSocket` bind is refused, so ZooKeeper's `PortAssignment.unique()` exhausts its
   per-fork port range and every port-using class fails, e.g.
   `audit-notes/test-batch1.log`:

   ```
   java.lang.IllegalStateException: Could not assign port from range 14812 - 18402.
   The entire range has been exhausted.
        at org.apache.zookeeper.PortAssignment.unique(PortAssignment.java:79)
        at org.apache.zookeeper.server.persistence.FileTxnLogTest.<clinit>(FileTxnLogTest.java:173)
   ```

   The same class passes under `isolated_exec`.
2. Maven is offline and `package` cannot be used because
   `org.cyclonedx:cyclonedx-maven-plugin:2.7.9` is missing locally; `-am` is required so
   `zookeeper-jute` resolves from the reactor. Working command:

   ```
   mvn -o test -pl zookeeper-server -am -DfailIfNoTests=false -Dtest=<classes> \
       -Dspotbugs.skip -Dcheckstyle.skip -DtrimStackTrace=false
   ```

3. `isolated_exec` caps a single invocation at 1200 s; longer selections are killed
   (exit -9) and only the finished classes report.
4. Raw logs are retained read-only at `../executions/<execution_id>/{stdout.txt,stderr.txt}`;
   the ids used here are indexed in §4.

## 2. Executed results (oracle: existing test suite)

239 test classes / 1763 test methods were executed through `isolated_exec` (this covers
all of `org.apache.zookeeper.server.*`, 49 of the quorum classes and ~100 of the 130
classes in `org.apache.zookeeper.test`); per-class summaries were copied to
`audit-notes/test-summary.txt`.

Consensus-relevant classes executed and **passing**: `Zab1_0Test`, `FLETest`,
`FLEPredicateTest`, `FLEZeroWeightTest`, `FLENewEpochTest`, `FLERestartTest`,
`FLEOutOfElectionTest`, `FLEBackwardElectionRoundTest`, `QuorumPeerTest`,
`QuorumPeerConfigTest`, `QuorumPeerMainTest`, `QuorumPeerMainMultiAddressTest`,
`QuorumSyncTest`, `QuorumZxidSyncTest`, `QuorumDigestTest`, `QuorumMajorityTest`,
`QuorumOracleMajTest`, `QuorumRequestPipelineTest`, `QuorumRestartTest`, `QuorumTest`,
`QuorumUtilTest`, `HierarchicalQuorumTest`, `ObserverLETest`, `ObserverMasterTest`,
`LeaderWithObserverTest`, `LeaderMetricsTest`, `LearnerTest`, `LearnerHandlerTest`,
`LearnerHandlerMetricsTest`, `LearnerMetricsTest`, `LearnerSyncThrottlerTest`,
`DIFFSyncTest`, `DIFFSyncConsistencyTest`, `FuzzySnapshotRelatedTest`, `RaceConditionTest`,
`CloseSessionTxnTest`, `EphemeralNodeDeletionTest`, `SessionUpgradeQuorumTest`,
`WatchLeakTest`, `EpochWriteFailureTest`, `CurrentEpochWriteFailureTest`,
`FollowerResyncConcurrencyTest`, `TruncateTest`, `RestoreCommittedLogTest`,
`LoadFromLogTest`, `LoadFromLogNoServerTest`, `EmptiedSnapshotRecoveryTest`,
`InvalidSnapshotTest`, `RecoveryTest`, `ZkDatabaseCorruptionTest`, `RepeatStartupTest`,
`ReconfigLegacyTest`, `ReconfigRecoveryTest`, `ReconfigDuringLeaderSyncTest`,
`ReconfigFailureCasesTest`, `ReconfigBackupTest`, `ReconfigRollingRestartCompatibilityTest`,
`ReadOnlyZooKeeperServerTest`, `ReadOnlyModeTest`, `StandaloneDisabledTest`,
`CnxManagerTest`, `QuorumCnxManagerSocketConnectionTimeoutTest`, `CommitProcessorTest`,
`CommitProcessorConcurrencyTest`, `SendAckRequestProcessorTest`,
`FollowerRequestProcessorTest`, `PrepRequestProcessorTest`, `DataTreeTest`,
`FileTxnLogTest`, `FileTxnSnapLogTest`, `FileTxnSnapLogMetricsTest`, `SnapStreamTest`,
`EmptySnapshotTest`, `TxnLogToolkitTest`, `TxnLogCountTest`, `TxnLogDigestTest`,
`SnapshotDigestTest`, `ZxidRolloverTest`, `ZookeeperServerRestoreTest`,
`ZookeeperServerSnapshotTest`, `SessionTrackerTest`, `LeaderSessionTrackerTest`,
`SessionInvalidationTest`, `SessionTimeoutTest`, `SessionTrackerCheckTest`,
`SessionUpgradeTest`, `DuplicateLocalSessionUpgradeTest`, `LocalSessionsOnlyTest`,
`LocalSessionRequestTest`, `ReferenceCountedACLCacheTest`, `JvmPauseMonitorTest`,
`NettyServerCnxnFactoryTest`, `NettyServerCnxnTest`, `NIOServerCnxnTest`.

## 3. Findings

### F1 (executed) `QuorumPeerMainTest#testLeaderOutOfView` fails intermittently — test race, not an implementation defect

First run (`execution_id 0e78d6c6679f4511a67ce2bacefe1abf`):

```
Tests run: 26, Failures: 1, Errors: 0 ... in org.apache.zookeeper.server.quorum.QuorumPeerMainTest
testLeaderOutOfView  Time elapsed: 1.051 s  <<< FAILURE!
org.opentest4j.AssertionFailedError: expected: <LOOKING> but was: <FOLLOWING>
    at org.apache.zookeeper.server.quorum.QuorumPeerMainTest.testLeaderOutOfView(QuorumPeerMainTest.java:881)
```

Evidence: `audit-notes/evidence/org.apache.zookeeper.server.quorum.QuorumPeerMainTest.txt`
and the server log for `2026-10-16 17:16:0{2,3}` in
`zookeeper-server/target/surefire-reports/org.apache.zookeeper.server.quorum.QuorumPeerMainTest-output.txt`.

Why it is a race, not a defect: the test starts node 1 with a 2-member view `{1,2}` and
nodes 2,3 with the full view, then asserts immediately after nodes 2 and 3 are up that
node 1 is `LOOKING` if node 2 is not `LEADING` (`QuorumPeerMainTest.java:874-882`). The
log shows the legal interleaving that breaks that assumption:

```
17:16:03,301 [WorkerReceiver[myid=1]] Notification: ... n.sid:2, n.leader:2   (node 2's initial self-vote)
17:16:03,301 [WorkerReceiver[myid=1]] Notification: ... n.sid:2, n.leader:3   (node 2 already switched)
17:16:03,302 [myid=1] WARN FastLeaderElection@1125 Ignoring notification for non-cluster member sid 3 from sid 2
17:16:03,302 [WorkerReceiver[myid=1]] Notification: ... n.sid:1, n.leader:2   (node 1's own re-broadcast)
17:16:03,502 [myid=3] LEADING
17:16:03,504 [myid=1] Peer state changed: following                            (node 1 elected leader 2)
```

Node 1's quorum is 2 of `{1,2}`; node 2 did vote for itself in round 1, and node 1's own
re-broadcast completed that quorum, so node 1 legitimately concludes "leader 2" (a state
the test anticipates in its `firstAndSecondNodeFormedCluster` branch) and only returns to
`LOOKING` after the follow attempt fails. The test samples `mt[1].getPeerState()`
inconsistently with that transient state.

Falsification: the next invocation ran the same class again
(`execution_id b502da095ec0488ebdf5fc0338ff1ea2`) with
`Tests run: 26, Failures: 0, Errors: 0 ... in ...QuorumPeerMainTest`. The failure is
nondeterministic, so it is recorded as test flakiness, not as an implementation defect.

### F2 (executed) Admin `snapshot` command ignores the documented rate-limit interval (1000× looser than configured)

Affected code: `zookeeper-server/src/main/java/org/apache/zookeeper/server/admin/Commands.java`
line 766 — `SnapshotCommand` builds its limiter as
`new RateLimiter(1, rateLimiterInterval, TimeUnit.MICROSECONDS)`, while `RestoreCommand`
(line 646) builds `new RateLimiter(1, rateLimiterInterval, TimeUnit.MILLISECONDS)`.
`rateLimiterInterval` comes from the property `zookeeper.admin.rateLimiterIntervalInMS`
(line 87-88) with default `300000`, i.e. milliseconds, and
`zookeeper-docs/.../zookeeperAdmin.md:2228-2231` documents
*"admin.rateLimiterIntervalInMS … The time interval for rate limiting admin command to
protect the server. Defaults to 5 mins."* `RateLimiter` converts the value with
`unit.toMillis(interval)`, so the snapshot command's effective interval is
`300000 µs = 300 ms` instead of `300000 ms = 5 min` (factor 1000).

Expected behaviour (basis: property name, documented default, sibling command):
the admin `snapshot` endpoint accepts one request per `admin.rateLimiterIntervalInMS`
(5 minutes by default) and answers `429` otherwise — exactly what `RestoreCommand` does.

What actually happens: after one accepted request the snapshot limiter resets after
~300 ms, so an authenticated admin client (`Perms.ALL` on `/` is required by the command)
can force whole-datatree snapshot streaming several times per second, defeating the
documented protection. Necessary conditions: admin endpoint enabled
(`zookeeper.admin.snapshot.enabled`, default true), `serializeLastProcessedZxid` enabled,
admin credentials. Scope: local to the admin `snapshot` command; no Zab safety impact.

Reproduction (source tree untouched; helper kept separately under `work/repro/`):

```
$ cd work
$ CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find ~/.m2/repository -name '*.jar' ! -name '*sources*' ! -name '*javadoc*' | tr '\n' ':')"
$ javac -nowarn -cp "$CP" -d repro repro/SnapshotRateLimitCheck.java
$ java -cp "repro:$CP" SnapshotRateLimitCheck
zookeeper.admin.rateLimiterIntervalInMS = 300000 (default)
SnapshotCommand rate limiter intervalInMs = 300
RestoreCommand  rate limiter intervalInMs = 300000
same RateLimiter parameter as RestoreCommand? false
documented (5 min) interval honoured by snapshot? false
snapshot limiter: first=true secondImmediately=false secondAfter400ms=true
```

The program reflects the private `rateLimiter` field of a freshly constructed
`Commands.SnapshotCommand`/`Commands.RestoreCommand` and reads `RateLimiter.intervalInMs`,
so it exercises the production objects, then repeats the limiter's own arithmetic
(second request accepted again after 400 ms). Output saved in `repro/out.txt`.
Alternative explanations checked: the value is not overridden by configuration (default
used), the property name/type is `…InMS`, and the other user of the same property treats
it as milliseconds — so `MICROSECONDS` in `SnapshotCommand` is a unit bug, not a
deliberate faster limit. Whether it is injected or pre-existing upstream is not
determined from this workspace (no reference tree available).

Two further checks (both executed):

* `TimeUnit.MICROSECONDS` occurs **exactly once** in the whole `zookeeper-server` +
  `zookeeper-jute` main source trees — at `Commands.java:766`. No other component reads a
  millisecond-typed interval and converts it as microseconds, so this is an isolated unit
  slip rather than a convention.
  Relatedly there are only two `new RateLimiter(...)` call sites in main sources
  (`Commands.java:646` restore — MILLISECONDS; `Commands.java:766` snapshot —
  MICROSECONDS), both fed by the same `rateLimiterInterval`
  (`Integer.parseInt(System.getProperty("zookeeper.admin.rateLimiterIntervalInMS", "300000"))`).
* The suite cannot see the defect because the test harness globally disables this limiter:
  `zookeeper-server/src/test/java/org/apache/zookeeper/ZKTestCase.java:102` and
  `.../common/ssl/Cert.java:63` set `zookeeper.admin.rateLimiterIntervalInMS = "0"`, which
  makes `RateLimiter.intervalInMs` zero for both commands. No test in
  `org/apache/zookeeper/server/admin/` references the rate limiter, the interval property
  or HTTP 429 (`grep` over that package returns nothing), and the `server/admin` test
  classes were not part of the executed sweep. A test that does exercise it must set a
  non-zero interval and assert the second request within the interval is rejected with
  `TOO_MANY_REQUESTS_429`.
  Confirmed by execution afterwards (`execution_id 5ead762ee1714eeab4a781a0a9c2388d`):
  `mvn -o test -pl zookeeper-server -am -Dtest=CommandsTest,CommandAuthTest,CommandResponseTest`
  → `Tests run: 42, Failures: 0, Errors: 0` — the admin command suite passes even though
  the snapshot limiter is 1000× off, because the harness zeroes the interval
  (`ZKTestCase.java:102`) and no assertion looks at it.
* Repo-wide sweep for the same defect class (`grep -rn "TimeUnit\." zookeeper-server/src/main/java`
  and checking every timeout/interval call site): the only unit mismatch is this one.
  Spot-checked companions are consistent — `SyncCommand` (`SYNC_TIMEOUT = SECONDS.toMillis(30)`
  fed to `CompletableFuture.get(..., MILLISECONDS)`), `ContainerManager.getMinIntervalMs()`
  (`MINUTES.toMillis(1) / maxPerMinute`), `FileTxnLog` (`NANOSECONDS.toMillis` for the fsync
  metric), `DatadirCleanupManager` (`HOURS.toMillis(purgeInterval)`),
  `RequestPathMetricsCollector` (`scheduleAtFixedRate(..., MINUTES)` with a minute-valued delay).

### E1 (environment blocker, not a defect) `FLELostMessageTest`, `FLEMalformedNotificationMessageTest` cannot run here

The sandbox's generated `/etc/hosts` lists the host name without an address:

```
$ cat ../executions/a71efe1b699f46afafa7e194c26b9ac2/hosts
127.0.0.1 localhost
::1 localhost
nitro-virtual-machine
```

These tests then die resolving their own host:

```
java.net.UnknownHostException: nitro-virtual-machine: Temporary failure in name resolution
    at java.net.InetAddress.getLocalHost(InetAddress.java:1666)
    at org.apache.zookeeper.server.quorum.QuorumCnxManager.initiateConnection(QuorumCnxManager.java:381)
```

No in-scope workaround: `unshare -rn` is permitted but socket creation inside it is
denied (`PermissionError: [Errno 1] Operation not permitted`), and `/etc/hosts` is a
read-only bind mount.

The same root cause also breaks every test that calls `InetAddress.getLocalHost()`
through `isolated_exec`; it is the *only* cause of the second batch of failures seen in
this audit: `ClientSSLTest` (24 tests: 6 failures + 6 errors, all
`java.net.UnknownHostException: nitro-virtual-machine` — the negative-path cases report
`unexpected exception type thrown; expected:<java.lang.AssertionError> but
was:<java.net.UnknownHostException>`). The SSL-relevant classes that do not need the
local hostname pass: `X509AuthTest` 6/6, `SSLAuthTest` 2/2, `ReadOnlyModeWithSSLTest`
1/1, `QuorumAuthUpgradeTest` 5/5, `QuorumDigestAuthTest` 6/6 `QuorumAuthObserverTest` 1/1.
So this is an environment artifact, not evidence about the implementation.

### E2 (environment blocker) `MultipleAddressesTest#testRecreateSocketAddresses` needs external DNS

`java.net.UnknownHostException: google.com: Temporary failure in name resolution`. The
other 16 tests of that class pass.

## 4. Raw evidence index

| execution_id | selection | outcome |
|---|---|---|
| `7a10e2220f6e404399ad0e73672a9d53` | `LearnerTest` | 7/7 pass (fails in plain shell) |
| `0e78d6c6679f4511a67ce2bacefe1abf` | 28 quorum classes | killed at 1200 s; F1 observed; all other finished classes passed |
| `5450022a928546cca2193f43ade4816c` | 16 consensus integration classes | all pass |
| `5ce58f3443a74da18947b225cbb3645a` | 32 classes (persistence, util, metric, auth, controller, embedded) | all pass |
| `c630e530ab094cc49674a634553c2fe0` | 45 `org.apache.zookeeper.server.*` core classes | all pass |
| `ac776f833401462283073939128340da` | 23 classes (QuorumTest, RecoveryTest, sessions, snapshots) | all pass |
| `b502da095ec0488ebdf5fc0338ff1ea2` | 24 quorum/observer/reconfig classes | QuorumPeerMainTest passes on re-run; MultipleAddressesTest E2; rest pass |
| `a71efe1b699f46afafa7e194c26b9ac2` | FLE lost/malformed + FLE predicate/election classes | killed at 1200 s; E1 for lost/malformed; QuorumPeerTest 4/4, FLEOutOfElectionTest 5/5, FLEPredicateTest 1/1 pass |
| `a2f9a87cbaff433f853b60d3d77bf183` | 48 classes: sessions, watchers, ACLs, chroot, multi, quotas, reconfig, 4lw, cnxn limits | all pass (295 s) |
| `544c5d355a7b47cc880d1ac0fbcf3799` | 27 classes: auth, SASL (non-Kerberos), chroot, netty/NIO suites, quotas, observers | all pass (48 s) |
| `db6ba359674e43dea167ae377eb85545` | SSL/auth/hammer classes | killed at 600 s; `ClientSSLTest` fails only on E1; `X509AuthTest`, `SSLAuthTest`, `ReadOnlyModeWithSSLTest`, `QuorumAuthUpgradeTest`, `QuorumDigestAuthTest`, `QuorumAuthObserverTest`, `ClientHammerTest`, `AsyncHammerTest`, `ObserverQuorumHammerTest` all pass; `QuorumSSLTest` did not finish |

Local logs: `audit-notes/build2.log`, `audit-notes/test-batch1.log`,
`audit-notes/test-summary.txt`, `audit-notes/evidence/`.

## 5. Source review performed (negative results)

Areas read against the behaviour their own comments/documentation claim, with no
deviation found:

* Quorum arithmetic: `QuorumMaj` (`half = votingMembers.size()/2`, `ackSet.size() > half`),
  `QuorumHierarchical` group/weight majority, `SyncedLearnerTracker`
  (`addAck`/`hasSid`/`hasAllQuorums`), `QuorumOracleMaj`.
* `Leader`: `lead()` epoch proposal and handshake, `getEpochToPropose` (monotone epoch,
  quorum of `connectingFollowers`), `waitForEpochAck`, `waitForNewLeaderAck`,
  `startZkServer`, `processAck`/`tryToCommit` (commit only after `p.hasAllQuorums()`,
  in-order guard, reconfig cascade), `propose` (rollover guard), `commit`/`inform*`,
  `startForwarding`, `getDesignatedLeader`, tick-loop `syncedAckSet` check.
* Learner sync: `Learner.registerWithLeader` (acceptedEpoch/ACKEPOCH, `-1` marker),
  `syncWithLeader` DIFF/SNAP/TRUNC, `enforceContinuousProposal`, NEWLEADER drain with
  `zk.getZKDatabase().commit()` before the ack, `setCurrentEpoch` placement;
  `LearnerHandler.run`/`syncFollower`/`queueCommittedProposals` (TRUNC only inside an
  epoch; DIFF/SNAP fallbacks).
* `Follower`/`Observer`: `followLeader`, `processPacket`, `FollowerZooKeeperServer.commit`
  zxid match, `ObserverMaster.startForwarding`/`revalidateLearnerSession`,
  `LearnerZooKeeperServer.shutdownComponents` (syncProcessor shutdown).
* Election: `FastLeaderElection.totalOrderPredicate`, `checkLeader`, `getVoteTracker`,
  `lookForLeader` paths, `validVoter` (`getCurrentAndNextConfigVoters`), `Vote.equals`.
* Epochs/state: `QuorumPeer.loadDataBase`, `setCurrentEpoch`/`setAcceptedEpoch`,
  `setQuorumVerifier`/`setLastSeenQuorumVerifier` stale-config guards,
  `updateElectionVote`, SyncMode/ZabState, `run()` state machine, `processReconfig`.
* Connections: `QuorumCnxManager.handleConnection` sid tie-break, `connectOne`,
  `MessageTracker`/`CircularBuffer` (enabled only via `zookeeper.messageTracker.Enabled`).
* Durability: `FileTxnLog.commit` (`forceSync` → `channel.force(false)`), `append` guard,
  `FileTxnSnapLog.restore`/`fastForwardFromEdits`, `FileSnap.deserialize` (100-snapshot
  scan, seal/digest checks), `ZKDatabase.addCommittedProposal` order guard,
  min/max committed log, `getProposalsFromTxnLog`, `truncateLog`.
* Pipeline/state machine: `PrepRequestProcessor.pRequest2Txn` (all write ops, ephemeral
  bookkeeping, `setSessionClosing`), `CommitProcessor.needCommit`/batching,
  `Leader.ToBeAppliedRequestProcessor`, `FinalRequestProcessor`, `DataTree.processTxn`
  (multi-op errors, NODEEXISTS fixup, `lastProcessedZxid` ordering vs snapshot,
  `killSession`), `ZooKeeperServer` (connect-request zxid check, expiry,
  `shutdown(fullyShutDown)`, `processTxn`/`outstandingChanges`), `SessionTrackerImpl`,
  `UpgradeableSessionTracker`, `ZxidUtils`, `SerializeUtils`, `ReferenceCountedACLCache`.
* Final pass (defaults and untested fragments): `ZKDatabase.allowDiscontinuousProposals`
  is `false` in production code (only `zookeeper.test.allowDiscontinuousProposals`, set by
  `ZxidRolloverTest`/`TxnLogDigestTest`, enables it), so the ZOOKEEPER-4925 order guard is
  active; `ObserverMaster` `proposedPkts`/`committedPkts` retention
  (`removeProposedPacket` consistency check, amortized 5-packet eviction, hard cap);
  `SyncRequestProcessor.shouldSnapshot`/`resetSnapshotStats` (`logCount > snapCount/2 +
  randRoll`, `randRoll ∈ [0, snapCount/2)`); defaults vs `zookeeperAdmin.md`:
  `DEFAULT_TICK_TIME=3000`, `globalOutstandingLimit=1000`, `maxClientCnxns=60`,
  `snapCount=100000`, `snapSizeLimitInKb=4 GiB`, `commitLogCount=500`,
  `snapshotSizeFactor=0.33`, `preAllocSize=64 M`, `fsync.warningthresholdms=1000`,
  `jute.maxbuffer=0xfffff`, session timeouts 2×/20× tick.
  All consistent; no deviation found.
* Fix-presence checklist from `zookeeper-docs/src/main/resources/markdown/releasenotes.md`
  (hypothesis: this variant may be an upstream state with a specific fix reverted).
  Verified **present**: ZOOKEEPER-4712, 4394, 4785, 4858, 4925, 4909, 5044, 4846.
  Also verified present: 4843 (`BinaryInputArchive` clamps
  `maxBufferSize + extraMaxBufferSize` to `Integer.MAX_VALUE`), 4919 (`ResponseCache`
  backed by `LinkedHashMap` with `accessOrder=true` and `removeEldestEntry`), 4730
  (recursive `ZooKeeperServer.getDirSize` used by `dirs` 4lw and admin).

## 6. Unresolved work / next steps

1. Remaining unrun classes are now only the slow/Kerberos/hostname-dependent ones:
   `QuorumHammerTest`, `NioNettySuiteHammerTest`, `NettyNettySuiteHammerTest`,
   `QuorumSSLTest`, `SaslDigestAuthOverSSLTest`, `SaslKerberosAuthOverSSLTest`,
   `MiniKdcTest`, `SaslAuthFailFipsModeTest`, `OOMTest` (disabled),
   `NettyNettySuiteTest`/`NioNettySuiteTest` (ran in `544c5d35…`), plus the quorum bean
   tests (`LeaderBeanTest`, `LocalPeerBeanTest`, `RemotePeerBeanTest`, `QuorumBeanTest`).
   Since ~239 of ~330 test classes now pass, further bulk test running has low expected
   yield; source-level review of *untested* consensus code is the better next step.
2. `FLELostMessageTest`/`FLEMalformedNotificationMessageTest` need an environment whose
   `/etc/hosts` maps the host name (E1); they are the only election tests not executed.
3. Continue the release-note checklist for server-side items not yet checked:
   ZOOKEEPER-4872 (`SnapshotCommand`/`fastForwardFromEdits`), 5049 (Prometheus keystore
   passwords), 5082 (audit-log characters), 4886 (small-myid observer joining a SASL
   quorum), 4954/4790 (TLS hostname verification), 4843 (`jute.maxbuffer` ≥ 1 GB),
   2332 (empty txn log startup), 2623 (CheckVersion outside Multi), 4730 (datadir/logdir
   size in admin and `dirs`), 4736 (socket fd leak), 4919 (`ResponseCache` LRU),
   4933 (throttle rejecting all connections).
4. If the tested surface is exhausted without a finding, use the TLA+ material in
   `zookeeper-specifications/` (`protocol-spec/issues.md` documents three Zab ambiguities
   and the chosen repairs; `system-spec/zk-3.7/` models the implementation's FLE) to
   derive unit-level harnesses for Agreement, TotalOrder, LocalPrimaryOrder,
   PrimaryIntegrity and PrefixConsistency.
