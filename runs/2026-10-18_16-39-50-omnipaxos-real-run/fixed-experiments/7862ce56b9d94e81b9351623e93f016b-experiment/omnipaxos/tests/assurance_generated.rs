//! Focused probe: shape of `read_decided_suffix(from)` when `from` is below the
//! compacted index, and the consequence for a consumer that advances one cursor
//! step per returned element (the runtime actor's `DecidedSub` arithmetic in
//! omnipaxos_runtime/src/actor.rs is reproduced here; the runtime crate itself
//! is not linked into this test target).
//!
//! Two real OmniPaxos instances run in one process with in-memory storage and a
//! synchronous message pump, so delivery, ordering and batching are exactly the
//! ones the library sees from a network layer.

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    util::LogEntry,
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct Value(u64);

impl Entry for Value {
    type Snapshot = NoSnapshot;
}

type Node = OmniPaxos<Value, MemoryStorage<Value>>;

fn build_node(pid: u64) -> Node {
    let cluster = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2],
        flexible_quorum: None,
    };
    let server = ServerConfig {
        pid,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config: cluster,
        server_config: server,
    }
    .build(MemoryStorage::default())
    .expect("node build failed")
}

/// Deliver every produced message to its addressed node until nothing is left.
fn pump(nodes: &mut [Node]) {
    for _ in 0..500 {
        let mut moved = false;
        for i in 0..nodes.len() {
            let mut out = Vec::new();
            nodes[i].take_outgoing_messages(&mut out);
            for m in out {
                let to = m.get_receiver();
                assert!(to >= 1 && (to as usize) <= nodes.len(), "bad receiver");
                nodes[(to as usize) - 1].handle_incoming(m);
                moved = true;
            }
        }
        if !moved {
            return;
        }
    }
    panic!("message pump did not quiesce");
}

fn kind(e: &LogEntry<Value>) -> &'static str {
    match e {
        LogEntry::Decided(_) => "decided",
        LogEntry::Undecided(_) => "undecided",
        LogEntry::Trimmed(_) => "trimmed",
        LogEntry::Snapshotted(_) => "snapshotted",
        LogEntry::StopSign(_, _) => "stopsign",
    }
}

fn token(e: &LogEntry<Value>) -> String {
    match e {
        LogEntry::Decided(Value(v)) => v.to_string(),
        LogEntry::Undecided(Value(v)) => format!("u{}", v),
        LogEntry::Trimmed(t) => format!("T{}", t),
        _ => "?".to_string(),
    }
}

fn emit(line: String) {
    println!("CA_EVENT {}", line);
}

fn run_probe() {
    let mut nodes = vec![build_node(1), build_node(2)];
    pump(&mut nodes);

    // Make node 1 the leader through the public API and let it reach Accept.
    nodes[0].try_become_leader();
    pump(&mut nodes);

    let leader_state = nodes[0].get_current_leader();

    // Six decided entries, one at a time, each pump completing the round trip.
    for i in 1..=6u64 {
        nodes[0].append(Value(i)).expect("append failed");
        pump(&mut nodes);
    }

    let decided = nodes[0].get_decided_idx();
    let decided_peer = nodes[1].get_decided_idx();

    // The leader is allowed to trim up to the minimum accepted index.
    nodes[0].trim(Some(4)).expect("leader trim failed");
    pump(&mut nodes);
    let compacted = nodes[0].get_compacted_idx();

    emit(format!(
        "{{\"run\":1,\"event\":\"ready\",\"leader_is_1_accept\":{},\"decided\":{},\"decided_peer\":{},\"compacted\":{}}}",
        matches!(leader_state, Some((1, true))),
        decided,
        decided_peer,
        compacted
    ));

    // Shape of the decided suffix for a consumer that starts below compaction.
    for from in [1usize, 4usize] {
        let suffix = nodes[0].read_decided_suffix(from);
        match suffix {
            Some(entries) => {
                let kinds: Vec<&str> = entries.iter().map(kind).collect();
                let tokens: Vec<String> = entries.iter().map(token).collect();
                emit(format!(
                    "{{\"run\":1,\"event\":\"suffix_shape\",\"from\":{},\"decided\":{},\"compacted\":{},\"len\":{},\"decided_minus_from\":{},\"kinds\":\"{}\",\"tokens\":\"{}\"}}",
                    from,
                    decided,
                    compacted,
                    entries.len(),
                    decided.saturating_sub(from),
                    kinds.join(","),
                    tokens.join(",")
                ));
            }
            None => emit(format!(
                "{{\"run\":1,\"event\":\"suffix_shape\",\"from\":{},\"decided\":{},\"compacted\":{},\"len\":null}}",
                from, decided, compacted
            )),
        }
    }

    // Reproduce the actor's cursor arithmetic over the real outputs:
    //   push_to_sub: for each element of read_decided_suffix(next_idx):
    //                try_send(entry); next_idx += 1
    //   push_to_all_subs: min_next = min(next_idx); read from min_next, then
    //                for each sub: start = sub.next_idx - min_next; push
    //                entries[start..], next_idx += 1 per pushed element.
    let mut cursor = 1usize;
    let mut delivered: Vec<u64> = Vec::new();
    let mut catchup_tokens: Vec<String> = Vec::new();
    if let Some(entries) = nodes[0].read_decided_suffix(cursor) {
        for e in &entries {
            catchup_tokens.push(token(e));
            if let LogEntry::Decided(Value(v)) = e {
                delivered.push(*v);
            }
            cursor += 1;
        }
    }
    let cursor_after_catchup = cursor;
    let mut next_push_tokens: Vec<String> = Vec::new();
    if let Some(entries) = nodes[0].read_decided_suffix(cursor) {
        for e in &entries {
            next_push_tokens.push(token(e));
            if let LogEntry::Decided(Value(v)) = e {
                delivered.push(*v);
            }
            cursor += 1;
        }
    }
    let mut duplicates: Vec<u64> = Vec::new();
    for (i, v) in delivered.iter().enumerate() {
        if delivered[..i].contains(v) && !duplicates.contains(v) {
            duplicates.push(*v);
        }
    }
    let dstr: Vec<String> = delivered.iter().map(|v| v.to_string()).collect();
    let dupstr: Vec<String> = duplicates.iter().map(|v| v.to_string()).collect();
    emit(format!(
        "{{\"run\":1,\"event\":\"cursor_replay\",\"start_from\":1,\"catchup_tokens\":\"{}\",\"cursor_after_catchup\":{},\"next_push_from\":{},\"next_push_tokens\":\"{}\",\"delivered_values\":\"{}\",\"duplicate_values\":\"{}\",\"duplicates\":{},\"decided\":{}}}",
        catchup_tokens.join(","),
        cursor_after_catchup,
        cursor_after_catchup,
        next_push_tokens.join(","),
        dstr.join(","),
        dupstr.join(","),
        !duplicates.is_empty(),
        decided
    ));
}

#[test]
fn decided_suffix_collapses_trimmed_prefix() {
    run_probe();
}
