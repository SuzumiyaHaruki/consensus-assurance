# OmniPaxos correctness audit

Source identity: `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12` (supplied capture). This report is a continuing, partial audit.

The independent Cargo harness in `audit-repro/` depends directly on `../../source/omnipaxos` and `../../source/omnipaxos_storage`, the read-only captured source. No implementation or dependency was edited. It uses the shipped MemoryStorage, public APIs, and deterministic delivery/drop of messages actually emitted by replicas. There are no fabricated protocol messages or diagnostic implementation patches. Snapshots preserve a vector of values, with ordinary concatenation as delta merge.

Run from the work directory:

```sh
./audit-repro/run.sh
```

The script runs `cargo test --offline --locked --manifest-path audit-repro/Cargo.toml -- --nocapture --test-threads=1` and saves full output plus Cargo's exit status in `audit-artifacts/reproduction-output.txt`. Failing assertions express the expected correct behavior; a nonzero test status is expected on the supplied implementation. Current executed result: **4 passing controls, 5 failing reproductions**, Cargo exit 101. `audit-artifacts/initial-snapshot-test.txt` preserves the first build and reproduction. The lockfile is retained. A separate optional-feature harness, `audit-unicache/`, enables `unicache` and `serde`; run `./audit-unicache/run.sh`. Its output is `audit-artifacts/unicache-output.txt`: **2 passing controls, 2 failing reproductions**, exit 101.

## Finding 1 — Delta snapshot synchronization can delete decided data or include an unchosen entry

**Impact: high; executed on original source.** A healthy replica receiving a legitimate synchronization message can expose a snapshot inconsistent with the decided log. No storage failure, malformed message, process crash, or explicit user snapshot request is necessary. Snapshot support must be enabled for the application's Entry type, and the receiver must have a nonempty decided prefix behind the sender, resulting in a delta rather than a complete snapshot.

### Expected behavior and basis

`docs/omnipaxos/compaction.md` describes snapshotting as preserving data and limiting snapshots to decided entries. `storage::SnapshotType::Delta` describes changes since an earlier snapshot. The decided prefix already present at the receiver must be preserved, and an unchosen divergent suffix must be replaced. `sequence_paxos/mod.rs` explicitly promises strongly consistent, linearizable decided entries.

### Affected implementation

- `omnipaxos/src/storage/internal_storage.rs:320`: `sync_log` sets the cached decided index to the **incoming** decided index before reconstructing the receiver's snapshot.
- Lines 333–339: the delta branch calls `create_decided_snapshot()` and merges the incoming delta.
- Lines 362–375: snapshot construction reads through that newly set index, although storage still contains the **old** log. The actual atomic write occurs only at line 358.
- `omnipaxos/src/storage/mod.rs`, `Storage::get_entries`: the storage contract requires an empty vector when the complete requested interval is unavailable. The shipped MemoryStorage follows this contract.
- `sequence_paxos/mod.rs`, `create_log_sync`, and `storage/internal_storage.rs`, `create_diff_snapshot`: the delta starts at the receiver's original decided index, so rebuilding the base using the new decided index is incorrect.

### Reproduction A: loss of an already decided prefix

Test: `delta_snapshot_loses_previously_decided_prefix` in `audit-repro/src/lib.rs`.

1. Build three replicas, IDs 1, 2, 3; elect 1 through `try_become_leader`; deliver all emitted messages.
2. Append 10 and deliver all messages. All replicas decide `[10]`.
3. Disconnect 3; append 20 at 1. Nodes 1 and 2 decide `[10, 20]`; 3 retains decided/accepted index 1.
4. Elect node 2 and resume message delivery to all nodes.
5. Node 2 emits an AcceptSync to 3 with `decided_idx: 2`, `sync_idx: 2`, and `Delta(Values([20]))`.

Observed output:

```text
leader values: [10, 20]; caught-up follower values: [20]; decided index: 2
assertion `left == right` failed
  left: [20]
 right: [10, 20]
```

Receiver 3 tries to read `[0,2)` from its one-entry log; MemoryStorage correctly returns an empty vector. The receiver merges `[20]` into an empty base, trims its original entry, persists `[20]` as a snapshot through index 2, and acknowledges accepted index 2. The missing 10 was already decided before disconnection.

### Reproduction B: unchosen data included in a decided snapshot

Test: `delta_snapshot_includes_overwritten_undecided_entry`.

1. All three nodes decide 10 under leader 1.
2. Isolate leader 1 after it appends 999 locally; drop its outgoing messages. Its log is `[10,999]`, decided index 1. Neither follower receives 999.
3. Nodes 2 and 3 elect 2, then decide 20 at index 1. Their decided log is `[10,20]`.
4. Reconnect old leader 1 via `reconnected(2)` and deliver all emitted messages.

Observed output:

```text
leader values: [10, 20]; recovered old leader snapshot: [10, 999, 20]
assertion `left == right` failed
  left: [10, 999, 20]
 right: [10, 20]
```

Here the incorrectly enlarged local read succeeds and incorporates the obsolete 999 before merging the correct delta. This shows the issue is not merely a short-read quirk of the storage backend.

### Alternative explanations checked

- All sync/prepare/promise/accepted messages are generated by real replicas. The harness only delivers, drops, or routes them to their indicated receiver.
- The snapshot implementation satisfies the trait: creating a vector from a contiguous slice and concatenating a subsequent delta preserves order and data. No idempotent or set-like merge requirement exists. The loss case also applies to distinct keys in the documented map snapshot design.
- MemoryStorage's empty result on an incomplete interval is explicitly required by the Storage trait, not a faulty test backend.
- `complete_snapshot_control_preserves_prefix` passes: forcing a complete snapshot from the sender preserves `[10,20]` in an otherwise similar catch-up scenario.
- No claim of persistence across process restart or a separate cluster-wide decision violation is needed: the executed public read result already violates the local decided-snapshot semantics.

Correction direction: reconstruct the base snapshot using the receiver's pre-sync decided boundary (and pre-sync StopSign state), then apply the delta and update the cached decided index. Audit both leader-side Promise synchronization and follower-side AcceptSync, which share this method.

## Finding 2 — Trimming is permanently blocked for valid non-contiguous node IDs

**Impact: medium; executed on original source.** Every positive trim index is rejected when the configured ID set leaves holes below its maximum. Automatic `trim(None)` succeeds without compacting anything. This can cause unbounded retained log data for users relying on trimming.

### Expected behavior and basis

`docs/omnipaxos/compaction.md` says trimming is allowed once all nodes have decided the requested prefix, and `None` uses the highest trimmable index. IDs must be unique and nonzero; there is no requirement that they be contiguous. In particular, the documented reconfiguration example in `docs/omnipaxos/reconfiguration.md` explicitly uses `[1,2,4]`. The reproduction's `[2,4,6]` configuration validates, elects a leader, and replicates successfully.

### Affected implementation

`omnipaxos/src/util.rs:96` allocates `accepted_indexes` with `max_pid` elements, including zero-initialized slots for nonexistent nodes. `LeaderState::get_min_all_accepted_idx` takes the minimum over the entire vector, including these never-updated holes. `sequence_paxos/mod.rs`, `trim`, treats that minimum as the all-members trim limit.

### Reproduction and observation

Test: `trim_with_sparse_node_ids`.

Build `[2,4,6]`, elect 2, append 10, and deliver all messages until quiescent. Assert all three configured nodes have accepted index 1 and decided index 1. Then:

```text
trim(None) = Ok(()), compacted index = 0
trim(Some(1)) = Err(NotAllDecided(0))
```

The test fails because the explicit trim should succeed. The companion `trim_contiguous_ids_control` performs the same append/trim with `[1,2,3]` and passes, including verifying compaction at all nodes. Thus this is not an undelivered acknowledgment, insufficient quorum, or follower-only trim attempt.

Correction direction: compute the minimum over actual configured members, or use membership-indexed storage instead of treating every integer up to the maximum ID as a member.

## Finding 3 — Promise retries leave a stale coalescing cache, causing different decided values at the same index

**Impact: high; executed agreement violation on original source.** After a lost initial AcceptSync, the built-in Promise retry can start a new message session while a buffered AcceptDecide from the previous session remains eligible for coalescing. An append after the retry gets inserted into that obsolete message. The follower silently misses the entry and subsequently appends later data at the wrong log position. Both leader and follower then expose different `Decided` values at the same index.

### Expected behavior and basis

`docs/omnipaxos/log.md` describes an append-only replicated log, permits pipelined appends, and guarantees that a `Decided` entry will not be reverted and is safe to apply. `docs/omnipaxos/communication.md` requires periodically taking outgoing messages; it does not require draining them between each local API call and incoming message. Promise retries and lost messages are explicitly handled by `resend_messages_follower` and the protocol's session/sequence numbers. All calls in this reproduction are serialized; there is no concurrent access or data race.

### Affected implementation

- `omnipaxos/src/sequence_paxos/leader.rs`, `handle_promise_accept`: on a matching-ballot Promise, stores the promise and calls `send_accsync`.
- `leader.rs:175–190`: `send_accsync` captures the current suffix, increments the follower's session, and queues an AcceptSync. It does **not** invalidate that follower's `latest_accept_meta`.
- `leader.rs:193–217`: `send_acceptdecide` reuses the cached AcceptDecide and extends its entries. `get_latest_accdec_message` checks only the ballot, not the session.
- `follower.rs`, `handle_acceptdecide`: the stale AcceptDecide is ignored because the follower is still in Prepare. The subsequent AcceptSync contains only the earlier suffix, captured before the later append. Later sequence numbers are contiguous within the new session, so the missing log entry is not detected.

### Reproduction

Test: `promise_retry_coalesces_entries_into_obsolete_session` in `audit-repro/src/lib.rs`.

1. Create nodes 1, 2, 3. Use election timeout 1000 and resend timeout 1 so a single tick specifically triggers the normal resend mechanism. Elect node 1.
2. Deliver all emitted messages except node 2's first AcceptSync. Node 2 remains in Prepare; node 3 enters Accept.
3. Append 10 at the leader, leaving its generated AcceptDecide messages in the outgoing buffer.
4. Tick node 2 once, collect its actual retransmitted Promise, and deliver it to leader 1. The leader queues a new-session AcceptSync containing `[10]`.
5. Append 20 at leader 1 before collecting its outgoing messages. The implementation merges 20 into the **old-session** AcceptDecide, preceding the new AcceptSync in the buffer.
6. Deliver all messages, append 30, and again deliver all messages.

The retained trace shows, in sender order to node 2:

```text
AcceptDecide(session: 1, counter: 2, entries: [10,20])
AcceptSync(session: 2, counter: 1, suffix: [10])
```

The first is ignored in Prepare, and the second installs only 10. After appending 30, observed public reads are:

```text
after retry: leader [10, 20], follower [10]
after next append: leader [10, 20, 30], follower [10, 30]
assertion `left == right` failed: decided entry at index 1 must agree
  left: Some(Decided(Value(30)))
 right: Some(Decided(Value(20)))
```

### Alternative explanations checked

- Exactly one genuine initial AcceptSync is dropped. The Promise is emitted by `tick`, not constructed or artificially duplicated by the test. All later traffic is delivered and reaches quiescence.
- No message reordering is needed: the faulty old-session/new-session ordering is the leader's own outgoing order.
- No snapshot transfer occurs in this trace (`decided_snapshot: None`); this is independent of Finding 1.
- `promise_retry_with_drained_buffer_control` passes when the pending AcceptDecide buffer is drained before processing the retry, with the same lost initial sync and retransmission. The follower then receives new entries in the correct session.
- Timer settings are validated supported values; only one follower tick is needed. No claim depends on real-time scheduling precision.

Correction direction: invalidate the follower's cached AcceptDecide whenever beginning a new synchronization session, and ensure that entries appended after the sync suffix is captured are queued in that new session. Add a regression for incoming Promise retries interleaved with buffered appends.

## Finding 4 — An old-configuration AcceptDecide can be accepted and decided in the new configuration

**Impact: high when delayed traffic can cross the configuration transition; executed on original source.** A stale message carrying configuration ID 1 can be accepted by a fresh configuration-2 replica. With the same leader ID, priority, and initial ballot number, the follower treats the old message as the next expected accept. It then rejects the real configuration-2 accept as a duplicate and applies the new leader's Decide to the old value. The reproduced result is different decided values at index 0 of the new log.

### Expected behavior and basis

`Ballot::config_id` identifies the configuration to which a ballot belongs. `docs/omnipaxos/reconfiguration.md` instructs users to start fresh instances and storage after the old StopSign is decided. The old application state is carried separately into the new configuration, not appended again to the new log. The communication documentation routes messages by receiving node ID and specifies no requirement to filter old configuration traffic externally. BLE itself filters replies by configuration ID.

**Necessary transport condition:** an old outgoing message remains delayed in the transport/application queue and is later delivered to the new instance of its intended receiver. Deployments that separately fence/drain every old configuration's traffic avoid this trigger. The test exercises the library's handling of such a legitimate, delayed message; it does not claim every transport permits this condition.

### Affected implementation

- `omnipaxos/src/ballot_leader_election.rs:53–61`: `Ballot::cmp` and `partial_cmp` compare only `(n, priority, pid)`, ignoring `config_id`. Derived equality does include the configuration ID, so the ordering also contradicts equality.
- `omnipaxos/src/sequence_paxos/follower.rs:196–199`: `check_valid_ballot` accepts `cmp == Equal`; it does not require actual ballot equality or matching configuration IDs.
- `follower.rs`, `handle_acceptdecide`: on the resulting successful check, the old entry is appended and consumes the new session's expected sequence number.
- `OmniPaxos::handle_incoming` routes SequencePaxos traffic without filtering the configuration.

### Reproduction

Test: `delayed_old_configuration_accept_is_applied_to_new_log`.

1. Elect leader 1 in a three-node configuration 1. Append 10; retain the actual outgoing AcceptDecide for node 3, without delivering it.
2. Deliver later messages normally. The subsequent Decide exposes a sequence gap; node 3 requests and completes synchronization and learns the old log through the normal protocol. The retained original AcceptDecide is still in the transport queue.
3. Reconfigure to ID 2 with the same members. Deliver all messages and verify that **all three old nodes have decided the StopSign**.
4. Build fresh configuration-2 instances and MemoryStorage, as documented, and elect leader 1. Assert every new accepted index is zero.
5. Deliver the retained old AcceptDecide to its original receiver, node 3. The packet has `config_id: 1`, `n: 1`, `pid: 1`, and `(session: 1, counter: 2)`; the new leader's ballot has `config_id: 2` but the same other fields.
6. Append 20 at the new leader and deliver all new traffic.

Observed:

```text
new configuration follower after old packet: Some([Undecided(Value(10))])
new config leader values [20], follower values [10]
assertion `left == right` failed: old config data must not be decided as a new log entry
  left: Some(Decided(Value(10)))
 right: Some(Decided(Value(20)))
```

### Alternative explanations checked

No ballot, sequence number, or payload was forged or changed. The delayed packet was withheld once, then delivered once. All replicas completed the original reconfiguration; no node was switched to the new configuration prematurely. The new storage was empty before delivery. The old packet is initially accepted only as undecided, but the genuine **new-configuration** Decide makes it visible as decided. The leader properly ignores the resulting old-configuration Accepted response (which uses actual ballot equality), so the failure is not an invented quorum acknowledgment. `old_configuration_packet_filtered_control` follows the same setup while discarding the old packet and passes.

Correction direction: explicitly reject messages outside the instance's configuration before protocol handling, and make Ballot ordering consistent with equality. Fixing the follower equality check alone would address this accept path but would not establish comprehensive configuration isolation for other message types.

## Finding 5 — Valid LRU UniCache state panics when deserialized with bincode

**Impact: medium; executed local API defect on original source.** With `unicache` and `serde` enabled, a valid serialized LRU cache can panic during deserialization. This prevents ordinary transfer of the cache representation used in AcceptSync with bincode. The executed reproduction is the cache round trip itself; no full networked-cluster failure is claimed for this finding.

### Expected behavior and basis

`docs/omnipaxos/unicache.md` documents the LRU policy as a supported cache choice. `LRUniCache` exposes Serialize/Deserialize under the serde feature, and AcceptSync carries the application's UniCache to synchronize followers. Serializing and deserializing valid state should reconstruct that state, including empty internal caches. An empty cache is normal, not malformed input.

### Affected implementation and necessary conditions

`omnipaxos/src/unicache/lru_cache.rs:209–210`, `LruWrapperVisitor::visit_seq`, uses the serialized sequence's element count as the capacity:

```rust
let size = seq.size_hint().unwrap_or(u8::MAX as usize);
let mut lru = LruCache::new(NonZeroUsize::new(size).unwrap());
```

Bincode reports the exact sequence length; an empty internal cache gives `Some(0)`. `NonZeroUsize::new(0)` is None, so the unwrap panics. `LRUniCache::clone` explicitly creates an empty encoder and a populated decoder for transfer to a follower, making this condition routine. Even a completely empty initial cache has the same problem.

### Executed reproduction and control

`audit-unicache/src/lib.rs`, `lru_cache_bincode_roundtrip`:

1. Create `LRUniCache<String,u8>::new(3)`.
2. Encode `"A"` once, then clone the cache, exactly the documented encoder-to-follower clone operation.
3. Serialize that valid state using bincode 1.3.3; 35 bytes are produced.
4. Deserialize those same bytes as `LRUniCache<String,u8>`.

Observed:

```text
serialized valid LRU follower cache into 35 bytes
panicked at .../source/omnipaxos/src/unicache/lru_cache.rs:210:65:
called `Option::unwrap()` on a `None` value
```

`lfu_cache_bincode_roundtrip_control` passes using the same string, encoding type, capacity, clone, and serializer; it also verifies that the deserialized cache decodes `"A"` correctly. No malformed bytes, mismatched types, or dependency edits are involved. Bincode's known-length sequence is a legitimate Serde deserializer; this does not rely on an exotic serialization format.

Correction direction: preserve the configured cache capacity independently of the serialized number of live entries, and allow empty serialized caches without constructing a zero-capacity LruCache. Also check the capacity after loading a partially full cache, rather than merely replacing zero with one.

## Finding 6 — A follower promoted to leader overflows a valid full LRU cache's encoding counter

**Impact: medium; executed panic in the normal Cargo test/debug profile.** With a supported `u8` LRU cache of capacity 255, a leadership change leaves the promoted follower's encoding state unable to append another distinct value. This is independent of serialization: the reproduction moves messages directly between replicas without serialization or extra cloning.

### Expected behavior and affected code

The documented UniCache feature supports LRU eviction and a `u8` encoding with maximum cache size 255 (`omnipaxos_macros/src/lib.rs`, UniCacheEntry attribute documentation). Filling the cache should cause eviction/reuse for later distinct fields, and ordinary leader changes should preserve the ability to append.

`omnipaxos/src/unicache/lru_cache.rs`, `Clone`, creates a follower cache with an empty encoder whose actual capacity is **1**, while retaining the configured logical `size` and `encoding` counter. The follower populates only the decoder and advances that counter when decoding uncached values. On promotion, the implementation continues using the same cache for encoding; no encoder reconstruction or reset occurs in the leader transition. `try_encode` at lines 102–113 compares the encoder's current length with the logical size. The empty encoder is considered not full, so it adds one to the already-maximal `u8` encoding instead of reusing an evicted encoding. The checked build panics at line 111.

### Executed reproduction and control

`audit-unicache/src/lib.rs`, `leadership::new_leader_lru_encoding_overflow`, creates three normal replicas. Its Entry implementation is a thin wrapper around the shipped `LRUniCache<String,u8>` at capacity 255, with NoSnapshot; it does not alter the caching algorithm. Elect node 1, append and decide 255 distinct values with all traffic delivered after each append, then elect node 2 using `try_become_leader` and deliver all transition traffic. Append one more distinct value at the new leader.

```text
255 distinct values decided; leader now 2; appending another distinct value
panicked at .../source/omnipaxos/src/unicache/lru_cache.rs:111:37:
attempt to add with overflow
```

`leadership::unchanged_leader_full_lru_control` passes for the same initial 255 values and extra distinct value when retaining leader 1. All three nodes then decide index 256. Thus capacity 255 and the workload itself are supported; the trigger is the follower-to-leader cache state transition.

The executed consequence is limited to a build with overflow checking enabled. An unchecked optimized build may wrap the counter instead; subsequent behavior there has **not** been tested and is not claimed here. The source-level mismatch between actual encoder capacity and logical size also merits investigation beyond this checked-overflow case.

Correction direction: establish a valid encoder cache, capacity, and counter on promotion, consistently with the decoder state transferred to followers. Do not merely suppress the overflow check.

## Coverage and remaining work

See `audit-notes.md` for unresolved investigation targets. This report does not claim exhaustive coverage or that other paths are correct.
