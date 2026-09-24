# Partial implementation discovery

This is a working discovery note, not an accepted research map, normative unit, executed check or coverage claim. The structured current question and its cited source ranges are in submission.json. No Behavior/Fact IDs are claimed as registered.

## Boundary and selection

The target is the raft Go package. NewRaft takes caller-selected Config, FSM, LogStore, StableStore, SnapshotStore and Transport implementations (api.go:496-560). It restores term/log/snapshot/configuration state and starts the main, FSM and snapshot owners (api.go:570-625). The selected question concerns live object replacement within one Raft instance, not process crash recovery.

The repository includes InmemStore (inmem_store.go:11-32), InmemSnapshotStore (inmem_snapshot.go:13-33), FileSnapshotStore (file_snapshot.go:85-95), InmemTransport (inmem_transport.go:49-75), and NetworkTransport (net_transport.go:210-230). Their availability does not establish deployment selection. Built-in storage is not externalized because NewRaft accepts interfaces; storage failure and durability semantics remain unread beyond the interfaces and constructors for this question. LogStore also has an optional MonotonicLogStore capability (log.go:110-142). Application FSM implementation is caller-owned, while scheduling is repository-owned (fsm.go:15-48; api.go:621-624).

Replication variants include ordinary RPC, optional pipelining with fallback, independent heartbeat work, and snapshot transfer (replication.go:135-197, 299-440, 446-566). Protocol version, transport-supported pre-vote and BatchApplyCh are configuration variants visible in api.go:529-546, 570-580; none is assumed active in a deployment.

## Responsibility coordinates and surfaces

| Coordinate | Applicability and partial understanding | Surface or remaining read |
|---|---|---|
| A1 | Applicable: support aggregation and commit consumption are recovered for the selected ownership relation. | commitment.go:35-104; raft.go:785-825. Support truth remains unchecked. |
| A2 | Applicable: main owner serializes leader entry; each entry creates fresh objects. | raft.go:134-155, 455-575. Election support and persistent voting are not recovered here. |
| A3 | Applicable: startup restore and outbound snapshot transfer are observed. | api.go:588-607; replication.go:299-383. Inbound restoration and post-crash participation remain partial. |
| A4 | Applicable: latest configuration drives replication and can change commitment membership. | raft.go:578-645, 647-663, 1216-1239. Membership transition safety and peer reuse are separate unknowns. |
| A5 | Applicable: commit processing calls processLogs; FSM interface documents application. | raft.go:785-825; fsm.go:15-48. Queue/restore/application interactions are not recovered. |
| A6 | Applicable: dispatch persists before local match; snapshot interfaces expose publication and storage. | raft.go:1242-1282; snapshot.go:14-67. Compaction/deletion implementations and crash atomicity remain deferred. |
| A7 | Applicable: leader cleanup completes inflight futures with ErrLeadershipLost. | raft.go:517-525; fsm.go:22-23. Client completion, retries, barriers and cancellation are not recovered. |

The table is one partial reverse-surfaces list. Constructor/startup, main loops, response handlers, commit notifications, storage interfaces, membership control and application callbacks are represented without implying full coverage. Snapshot compaction functions were located by search but not semantically read. No unclassified responsibility was needed for the selected ownership relation; the remaining source is not classified exhaustively.

## Selected behavior and fact lifecycle

- Main owner on leader entry: allocates commitment C, channel N, replication map and stepdown channel. The established fact is ownership of C and N by this leader incarnation; no quorum support is implied.
- Main owner when creating a peer worker: captures C in followerReplication S. This establishes which aggregate receives later reports from S; it does not establish any durable follower prefix.
- Ordinary replication owner on successful non-newer-term response: reports the last sent entry index through S.commitment. RPC error, rejection and higher reply term branches do not take that success edge. The weakest fact is a report of matching prefix to C; the truth of the follower's durable prefix remains upstream.
- Pipeline decoder on successful non-newer-term response: uses its passed S and the same report helper. Pipeline future validity is retained as an unresolved upstream contract, not inferred from the success field.
- Snapshot transfer owner on successful non-newer-term response: reports snapshot metadata index through S.commitment. Snapshot validity and receiver completion are not established by this local report observation.
- Commitment owner under its mutex: monotonically updates eligible voter matches, computes quorum index, applies startIndex threshold, and notifies its own N. This is the aggregate representation consumed locally, conditional on the reports; it is not independently verified distributed durability.
- Main owner on commit notification: reads the current commitment and schedules committed inflight logs. The consumer does not look up old worker state.
- Independent heartbeat owner: updates contact and verify futures, with no commitment.match call. Contact observation is not represented as durable log support.

Interfering event: stepdown closes stop channels without waiting for every blocked RPC, clears leaderState, and later leader entry allocates new C and N. A late report can still update its original C; pointer and channel identity keep this direct update outside the new consumer. This is a source interpretation, not an executed interleaving.

## Disposition and gaps

The selected cross-incarnation support-consumption suspicion is explained by captured objects and fresh consumer channels. An additional global term check is not required merely to obtain that object isolation. Numeric term checks, voter filtering and startIndex checks are retained as additional protections without being mistaken for the primary discriminator.

No formal run, model search, calibration, or implementation reproduction is claimed. The submission creates no obligation. A future question about response validity, durable support, same-incarnation membership reuse or old-worker request construction would require its own bounded relation and source review; those concerns are not silently resolved here.
