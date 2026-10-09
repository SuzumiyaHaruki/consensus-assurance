# OmniPaxos correctness audit

Source identity: `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12` (supplied capture). This report is a continuing, partial audit.

The confirmed defects are summarized below; detailed conditions, source locations, controls, and reproduction commands follow.

| Finding | Area | Executed consequence |
| --- | --- | --- |
| 1 | Delta snapshots | Deletes a decided prefix or includes an obsolete unchosen entry |
| 2 | Sparse node IDs | Rejects every positive trim index despite all members deciding it |
| 3 | Promise retry/coalescing | Leader and follower decide different values at the same index |
| 4 | Configuration isolation | Delayed old-configuration traffic becomes a decided new-log value |
| 5 | LRU serialization | Valid bincode round trip panics |
| 6 | LRU leader transition | Decoder panic in debug and optimized release; also checked overflow |
| 7 | LFU synchronization | Reconnected follower decides B where the leader decides C |
| 8 | UniCache plus batching | Partial-batch sync leads to conflicting decoded decided entries |
| 9 | StopSign synchronization | Double counts the StopSign and decides beyond the accepted log |
| 10 | Stale AcceptSync | Erases a previously decided entry during a later reconnect |

The independent Cargo harness in `audit-repro/` depends directly on `../../source/omnipaxos` and `../../source/omnipaxos_storage`, the read-only captured source. No implementation or dependency was edited. It uses the shipped MemoryStorage, public APIs, and deterministic delivery/drop of messages actually emitted by replicas. There are no fabricated protocol messages or diagnostic implementation patches. Snapshots preserve a vector of values, with ordinary concatenation as delta merge.

Run from the work directory:

```sh
./audit-repro/run.sh
```

The script runs `cargo test --offline --locked --manifest-path audit-repro/Cargo.toml -- --nocapture --test-threads=1` and saves full output plus Cargo's exit status in `audit-artifacts/reproduction-output.txt`. Failing assertions express the expected correct behavior; a nonzero test status is expected on the supplied implementation. Current executed result: **5 passing controls, 8 failing reproductions**, Cargo exit 101. `audit-artifacts/initial-snapshot-test.txt` preserves the first build and reproduction. The lockfile is retained. A separate optional-feature harness, `audit-unicache/`, enables `unicache` and `serde`; run `./audit-unicache/run.sh`. Its output is `audit-artifacts/unicache-output.txt`: **5 passing controls, 5 failing reproductions**, exit 101. `./audit-unicache/run-release.sh` separately reproduces the leader-transition decoder panic in the optimized release profile; output is retained in `audit-artifacts/unicache-release-output.txt`.

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

## Finding 6 — A promoted follower retains an invalid LRU encoder, causing overflow or decoder panics

**Impact: high availability defect; decoder panic executed in both debug and optimized release profiles.** A leadership change leaves the promoted follower's encoder at capacity 1 while the logical cache capacity is larger. At capacity 255 this first manifests as checked integer overflow; a smaller cache demonstrates an independent decoder panic without any integer overflow. The reproductions move messages directly between replicas without serialization or extra cloning.

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

### Follow-up: decoder panic in optimized release, without overflow

`leadership::promoted_lru_encoder_outgrows_decoder` uses a supported LRU capacity of **3** and `u8` encodings. All replicas decide A, B, C under leader 1. Node 2 is elected and synchronized; then it appends D, E, F, G, G, delivering all messages after each append.

The promoted encoder's physical capacity remains 1, so its length never reaches its logical size 3. It allocates encodings 4, 5, 6, and 7 instead of reusing them. Followers fill their three-entry decoder with D/E/F at 4/5/6, then correctly reuse encoding 4 for uncached G. The next G is encoded as 7 by the leader, but encoding 7 does not exist at the followers:

```text
leader 2, capacity 3, append G
panicked at .../source/omnipaxos/src/unicache/lru_cache.rs:123:55:
called `Option::unwrap()` on a `None` value
```

This exact test fails in **both** default/debug and optimized release builds. `./audit-unicache/run-release.sh` retains the release command/output. The corresponding `unchanged_leader_small_lru_control` passes, including checking the final decided G at every node. Encoding values never approach the u8 limit in this case. The original 255-entry test's overflow remains specifically a checked-build observation.

Correction direction: establish a valid encoder cache, capacity, and counter on promotion, consistently with the decoder state transferred to followers. Do not merely suppress the overflow check.

## Finding 7 — LFU cache synchronization discards frequency metadata and causes conflicting decided entries

**Impact: high; executed agreement violation on original source.** An ordinary reconnect to the same leader can cause a follower to decode a subsequent field as a different value. All replicas acknowledge and decide the same log index, but the reconnected follower stores B where the leader and other follower store C.

### Expected behavior and basis

`docs/omnipaxos/unicache.md` explicitly guarantees that encoded values are decoded back to the original values before storage and supports both LFU and LRU eviction. A cache synchronized through AcceptSync must preserve enough eviction state to keep later encoding reuse consistent.

### Affected implementation

`omnipaxos/src/unicache/lfu_cache.rs:24–35`, `LFUniCache::clone`, rebuilds the follower decoder by iterating the leader's encoder and calling `set` on each reversed key/value pair. `unicache/lfu/mod.rs`, `LFUCache::set`, inserts each new item at frequency 1. The actual source frequencies (and eviction tie ordering) are lost. `storage/internal_storage.rs:531–538` and `sequence_paxos/leader.rs`, `send_accsync`, use this clone as the cache transferred to a follower. Subsequent uncached fields therefore need not evict the same encoding on both sides.

### Executed reproduction

Test: `lfu_sync::lfu_resync_loses_frequency_metadata` in `audit-unicache/src/lib.rs`. It uses a thin Entry wrapper around the shipped LFU cache with capacity 2 and u8 encodings, with no snapshots. There is one leader throughout.

1. All three nodes decide ten A entries and one B entry under leader 1. The encoder has A at code 1 with frequency 10 and B at code 2 with frequency 1.
2. Call node 3's public `reconnected(1)` to model a re-established transport connection and deliver all emitted messages. Its synchronized decoder now has both frequencies reset to 1.
3. Append B once more. At the leader the frequencies are A:10, B:2; at node 3 they are A:1, B:2.
4. Append C. The leader evicts B and reuses code 2; node 3 evicts A and reuses code 1. Both store this unencoded C correctly for now.
5. Append C again. The leader sends code 2, which node 3 still maps to B. Deliver all messages until all nodes have decided index 14.

Observed public reads at index 13:

```text
node 1 decided entry at index 13: Decided(Item("C"))
node 2 decided entry at index 13: Decided(Item("C"))
node 3 decided entry at index 13: Decided(Item("B"))
```

The comparison fails with left B, right C. Full generated protocol traffic is retained in `unicache-output.txt`. `lfu_without_resync_control` passes with the identical append sequence and no cache resynchronization.

### Alternative explanations checked

No malformed or manually encoded messages are used. The custom Entry only delegates encoding/decoding to the library cache. No leader change, integer overflow, batching, snapshot, serialization, or extra message cloning is involved. Although LFU clone iterates a HashMap, this test does **not** depend on its random iteration order: the additional B produces strictly different frequency orderings before eviction. This is separate from Finding 6's promoted encoder-capacity defect.

Correction direction: transfer the LFU counters and eviction ordering along with the key/encoding mapping so that future evictions remain deterministic and identical at encoder and decoder.

## Finding 8 — Synchronization copies the cache ahead of the batched log and corrupts subsequent decoded entries

**Impact: high; executed agreement violation on original source.** A follower resynchronized while the leader has an unflushed batch receives cache state that already includes those pending entries, but a log that does not. Later delivery of the original encoded batch applies its cache misses a second time, shifting encoding assignments. A subsequent repeated field is stored and decided as another value.

### Expected behavior and affected implementation

Batching and UniCache are supported features. A synchronized cache must represent exactly the log/message prefix already consumed by the recipient. `storage/state_cache.rs`, `append_entry` and `append_entries`, calls `unicache.try_encode` immediately and buffers both entries and their processed representation, **before** the batch is flushed. `sequence_paxos/leader.rs`, `send_accsync`, captures a log suffix from persisted/accepted entries but obtains the live cache through `internal_storage.get_unicache()`. That cache includes buffered entries excluded from the suffix. There is no flush or earlier cache-state boundary in this path.

### Executed reproduction

Test: `leadership::sync_copies_cache_ahead_of_batched_log` in `audit-unicache/src/lib.rs`.

1. Build three nodes with batch size 2 and a shipped LRU cache of capacity 3, u8 encoding. Elect leader 1 and deliver all initial messages.
2. Append A once at the leader. Assert accepted index 0 and batched length 1. Its encoder has nevertheless assigned A code 1.
3. Resynchronize node 3 using `reconnected(1)` and deliver all traffic. Its log remains empty, but the transferred decoder already contains A at code 1.
4. Append A again. The batch flushes as uncached A followed by encoded 1. Node 3 applies the cache miss again, creating another A mapping at code 2. Both log values still appear correct.
5. Append B twice, flushing another batch. The leader uses uncached B then code 2; node 3 assigns the uncached B to code 3, then decodes code 2 as A.

All nodes have decided index 4. Observed values:

```text
batching: node 1 decided ["A", "A", "B", "B"]
batching: node 2 decided ["A", "A", "B", "B"]
batching: node 3 decided ["A", "A", "B", "A"]
```

`batching_without_resync_control` passes with all three nodes deciding A,A,B,B. There is no leader change, serialization, overflow, snapshotting, message loss, or extra cloning. This uses LRU, so it is independent of the LFU frequency-loss defect. The problematic sync is initiated with a legitimate reconnect notification after the first append; all resulting protocol messages are library-generated.

Correction direction: synchronize the log and cache from a common boundary. For example, flush the pending batch before capturing both, with correct replication/message ordering, or keep a cache version corresponding exactly to the accepted prefix. Sending the current cache with an older log suffix is unsafe.

## Finding 9 — Resynchronizing an accepted StopSign counts it twice and advances decisions beyond the log

**Impact: high; executed on original source with both pending and completed reconfiguration.** A follower that already accepted the StopSign can increase its accepted index by one merely by reconnecting. With two such followers, the leader decides the phantom extra position, exceeding its own accepted index. Previously decided data disappears from whole-log reads, and a previously complete reconfiguration becomes absent from the leader's `is_reconfigured()` result.

### Expected behavior and affected implementation

The StopSign is one terminal log entry. Reconnection must preserve its position and the invariant that the decided index does not exceed the accepted log. `docs/omnipaxos/reconfiguration.md` relies on the decided StopSign to seal the log and let callers start the next configuration. `InternalStorage::load_cache` correctly counts one StopSign in the accepted index.

In `omnipaxos/src/sequence_paxos/leader.rs`, `send_accsync` uses the follower's accepted index as `followers_valid_entries_idx` when it has accepted in the current round (or the minimum of previous accepted indices when rounds match). This index already includes the StopSign. `sequence_paxos/mod.rs`, `create_log_sync`, uses that value unchanged as `sync_idx` when no snapshot is needed, and attaches the StopSign separately. `storage/internal_storage.rs:343–348`, `sync_log`, sets:

```rust
accepted_idx = sync.sync_idx + sync.suffix.len();
// ... when sync.stopsign is Some:
accepted_idx += 1;
```

Thus an index already including the StopSign is treated as the end of ordinary entries, and the StopSign is counted again. The storage's actual ordinary-entry vector remains shorter. `leader.rs`, `handle_accepted`, trusts the inflated acknowledgments and can decide that nonexistent index once they form a quorum.

### Executed reproductions

Both tests are in `audit-repro/src/lib.rs`, using the original MemoryStorage and public APIs.

- `resync_counts_existing_stopsign_twice`: elect node 1 in `[1,2,3]`, decide value 10, then decide a reconfiguration StopSign. Assert all replicas have accepted/decided index 2 and report the reconfiguration. Reconnect node 2 to 1 and drain messages, then reconnect node 3 to 1 and drain messages.
- `pending_stopsign_resync_counts_twice`: same setup, but withhold the original Accepted responses for the StopSign. Assert all replicas have accepted index 2, decided index 1, and **none** reports reconfiguration complete. Then perform the same reconnects. This rules out any requirement to retire an already-stopped instance as the sole explanation.

The sender-generated AcceptSync has `sync_idx: 2`, empty suffix, and the StopSign; the receiver replies with accepted index **3**. After both reconnects, both variants reach:

```text
node 1: accepted 2, decided 3, is_reconfigured None, decided suffix None
node 2: accepted 3, decided 3, decided suffix Some([StopSign(..., true)])
node 3: accepted 3, decided 3, decided suffix Some([StopSign(..., true)])
```

The original value 10 is omitted from follower whole decided-log reads: the inflated index makes the read request include a nonexistent ordinary entry, and the backend's contractually correct empty interval result is followed by the StopSign. The test asserts that all accepted and decided indices remain 2 and the completed reconfiguration remains visible; both variants fail. Before reconnecting, the ordinary reconfiguration path in the first test passes those assertions.

### Alternative explanations checked

No application entry is appended after the reconfiguration, and no second StopSign is proposed. There is no malformed message, extra message cloning, batch interaction, or UniCache. The problematic sync contains `decided_snapshot: None`, so the defect is independent of Finding 1. The completed variant loses no network messages; the pending variant withholds only library-generated acknowledgments before reconnecting, then delivers all later messages. The follower's count changes on an empty-suffix synchronization, and the retained trace shows the exact inflated acknowledgment used by the leader.

Correction direction: distinguish the ordinary-log prefix from the accepted index including a StopSign when constructing synchronization payloads. Ensure the StopSign is counted exactly once, and enforce coherent accepted/decided indices before acknowledging synchronization.

## Finding 10 — A delayed old AcceptSync can erase a decided log during a later reconnect

**Impact: high; executed loss of a previously decided entry on original source.** A follower in Prepare accepts an old same-ballot AcceptSync without validating its session. It can reset accepted and decided indices to zero and truncate already-decided data. The current synchronization response then arrives while the follower is already in Accept and is ignored, leaving the replica empty even after all queued traffic has been delivered.

### Expected behavior and necessary conditions

`docs/omnipaxos/log.md` guarantees that decided entries cannot be reverted. The protocol carries session/sequence numbers to identify obsolete or missing messages; normal AcceptDecide/Decide handling checks those numbers. This trigger requires an older synchronization message to remain delayed while a Promise retry produces a newer synchronization that is delivered first, and for the old message to reach the follower during a subsequent Prepare phase. It uses reordering/delivery across a reconnect. A transport that permanently discards every old queued message at reconnection prevents this trigger; the supplied communication documentation does not state such a requirement.

### Affected implementation

`omnipaxos/src/sequence_paxos/follower.rs`, `handle_acceptsync` (lines 54–83), checks the ballot and `(Follower, Prepare)` state, but not the incoming session/sequence number, before calling `sync_log`. It then unconditionally stores the incoming sequence number and enters Accept. `handle_prepare` resets `current_seq_num` to default, losing the earlier session's watermark. `storage/internal_storage.rs`, `sync_log`, installs the supplied decided index and prefix/suffix, including truncating the old log.

### Executed reproduction and observation

`delayed_old_acceptsync_erases_decided_log_after_reconnect` in `audit-repro/src/lib.rs`:

1. Create a three-node cluster with election timeout 1000 and resend timeout 1. Elect node 1; hold its first AcceptSync to node 2 (session 1, decided index 0, empty log).
2. Tick node 2 once to emit a genuine Promise retry. Deliver that retry and its newer AcceptSync, session 2. No messages are forged.
3. Append 10 at leader 1 and deliver all current traffic. Assert all three replicas have decided index 1 and read `[10]`.
4. Call node 2's `reconnected(1)`. Deliver its PrepareReq and the leader's Prepare, leaving it in Prepare with a new Promise queued.
5. Deliver the retained original session-1 AcceptSync, then all remaining current messages.

Observed:

```text
immediately after stale sync: accepted 0, decided 0, values []
after all current traffic: accepted 0, decided 0, values []
```

The trace shows the later session-3 AcceptSync with decided index 1 arriving and being ignored. It was constructed from node 2's Promise reporting accepted index 1, generated before the stale sync erased the log. The assertion that decided index remains 1 fails with actual 0.

`reconnect_without_delayed_old_sync_control` passes with the same first-message delay, Promise retry, append, and reconnection, but discards the retained old AcceptSync instead of delivering it. This is not a missed quorum, pre-decision proposal loss, different configuration, snapshot bug, or coalescing-cache issue. The old packet is delivered once, with its original ballot, session number, and payload. The finding is limited to the executed local data loss; a separate larger-cluster consequence has not been tested.

Correction direction: reject obsolete synchronization sessions and preserve enough session/request information across same-ballot Prepare/Recover transitions to match AcceptSync to the current synchronization attempt. A matching ballot alone is insufficient.

## Coverage and remaining work

A separate bounded exploration checked **all 998 undirected five-node static topologies with at least one quorum-connected node**, using the default majority quorum and election timers. It ticks replicas, delivers traffic over present edges, and retries proposals periodically. All cases decided an entry within 200 ticks. Source: `audit-repro/src/bin/ble_topologies.rs`; retained output: `audit-artifacts/ble-topologies-output.txt` (exit 0). Reproduce with:

```sh
cargo run --offline --locked --manifest-path audit-repro/Cargo.toml --bin ble_topologies
```

This is bounded static-topology progress coverage, not a proof of liveness under arbitrary scheduling, message loss, crashes, or changing topology. The supplied repository tests were read selectively, not executed as a suite. The reproductions use the original MemoryStorage; actual disk-crash persistence and the runtime crate have not been validated. See `audit-notes.md` for unresolved investigation targets. This report does not claim exhaustive coverage or that other paths are correct.
