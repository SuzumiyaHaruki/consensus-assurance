use std::collections::{BTreeMap, VecDeque};
use omnipaxos::{ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::storage::{Entry, Snapshot, SnapshotType};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Put { key: u64, value: u64 }
impl Entry for Put { type Snapshot = KvSnapshot; }

// The same overwrite-on-merge semantics as the documented key-value snapshot.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct KvSnapshot(BTreeMap<u64, u64>);
impl Snapshot<Put> for KvSnapshot {
    fn create(entries: &[Put]) -> Self {
        let mut result = Self::default();
        for entry in entries { result.0.insert(entry.key, entry.value); }
        result
    }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}

type Node = OmniPaxos<Put, MemoryStorage<Put>>;
const OP: &str = "reconnect-node-2-first-session";
fn emit(mut value: Value) {
    value["operation"] = json!(OP);
    value["follower"] = json!(2);
    println!("CA_EVENT {}", value);
}
fn materialized(node: &Node) -> BTreeMap<u64, u64> {
    let mut result = BTreeMap::new();
    for entry in node.read_decided_suffix(0).unwrap_or_default() {
        match entry {
            LogEntry::Decided(e) => { result.insert(e.key, e.value); }
            LogEntry::Snapshotted(s) => { result.extend(s.snapshot.0); }
            other => panic!("Unexpected entry in decided view: {:?}", other),
        }
    }
    result
}
fn state(node: &Node) -> Value {
    json!({"pid":node.get_pid(), "accepted":node.get_accepted_idx(),
        "decided":node.get_decided_idx(), "compacted":node.get_compacted_idx(),
        "promise":node.get_promise(), "view":materialized(node)})
}

// Delivery preserves each sender's outgoing order. During the explicit
// disconnection, messages incident to node 2 are discarded, not reordered.
fn pump(nodes: &mut [Node], disconnected: bool, observe_sync: bool) -> usize {
    let mut queue = VecDeque::new();
    let mut delivered = 0;
    let mut observed = 0;
    loop {
        for node in nodes.iter_mut() {
            let mut outgoing = Vec::new();
            node.take_outgoing_messages(&mut outgoing);
            queue.extend(outgoing);
        }
        let Some(message) = queue.pop_front() else { break };
        delivered += 1;
        assert!(delivered < 1000, "Message delivery did not quiesce");
        let from = message.get_sender();
        let to = message.get_receiver();
        if disconnected && (from == 2 || to == 2) {
            emit(json!({"event":"disconnected_drop", "from":from, "to":to,
                        "message":format!("{:?}", message)}));
            continue;
        }
        emit(json!({"event":"message_delivery", "from":from, "to":to,
            "message":format!("{:?}", message)}));
        let mut monitored = false;
        if observe_sync && from == 3 && to == 2 {
            if let Message::SequencePaxos(p) = &message {
                if let PaxosMsg::AcceptSync(sync) = &p.msg {
                    let (kind, snapshot) = match &sync.log_sync.decided_snapshot {
                        Some(SnapshotType::Delta(s)) => ("delta", Some(&s.0)),
                        Some(SnapshotType::Complete(s)) => ("complete", Some(&s.0)),
                        None => ("none", None),
                    };
                    let target = &nodes[1];
                    emit(json!({"event":"sync_admitted", "from":from, "to":to,
                        "snapshot_kind":kind, "snapshot":snapshot,
                        "sync_idx":sync.log_sync.sync_idx,
                        "incoming_decided":sync.decided_idx,
                        "incoming_ballot":sync.n,
                        "ballot_matches":sync.n == target.get_promise(),
                        "target_leader":target.get_current_leader(),
                        "follower_accepted":target.get_accepted_idx(),
                        "follower_decided":target.get_decided_idx(),
                        "follower_compacted":target.get_compacted_idx(),
                        "before_view":materialized(target),
                        "leader_decided":nodes[2].get_decided_idx(),
                        "leader_view":materialized(&nodes[2]),
                        "suffix_len":sync.log_sync.suffix.len(),
                        "sequence":format!("{:?}",sync.seq_num)}));
                    monitored = true;
                    observed += 1;
                }
            }
        }
        nodes[(to - 1) as usize].handle_incoming(message);
        if monitored {
            let target = &nodes[1];
            emit(json!({"event":"sync_returned", "handler_returned":true,
                "follower_decided":target.get_decided_idx(),
                "follower_accepted":target.get_accepted_idx(),
                "follower_compacted":target.get_compacted_idx(),
                "follower_view":materialized(target),
                "raw_decided":format!("{:?}", target.read_decided_suffix(0)),
                "leader_view":materialized(&nodes[2])}));
        }
    }
    observed
}

#[test]
fn reconnect_delta_preserves_decided_key_value_state() {
    let mut nodes: Vec<Node> = (1..=3).map(|pid| {
        OmniPaxosConfig {
            cluster_config: ClusterConfig {
                configuration_id: 1, nodes: vec![1, 2, 3], flexible_quorum: None,
            },
            server_config: ServerConfig {
                pid, batch_size: 1,
                election_tick_timeout: 100,
                custom_logger: Some(slog::Logger::root(slog::Discard, slog::o!())),
                ..Default::default()
            },
        }.build(MemoryStorage::default()).unwrap()
    }).collect();
    // No durable state, votes, promises, or log contents are supplied by the fixture.
    nodes[2].try_become_leader();
    pump(&mut nodes, false, false);
    assert_eq!(nodes[2].get_current_leader(), Some((3, true)));
    nodes[2].append(Put { key: 11, value: 111 }).unwrap();
    pump(&mut nodes, false, false);
    for node in &nodes {
        assert_eq!(node.get_decided_idx(), 1);
        assert_eq!(materialized(node), BTreeMap::from([(11, 111)]));
    }
    emit(json!({"event":"prefix_decided", "nodes":nodes.iter().map(state).collect::<Vec<_>>(),
        "follower_decided":nodes[1].get_decided_idx(),
        "follower_view":materialized(&nodes[1])}));

    // A second, distinct key is committed by nodes 3 and 1 during disconnection.
    nodes[2].append(Put { key: 22, value: 222 }).unwrap();
    pump(&mut nodes, true, false);
    assert_eq!(nodes[2].get_decided_idx(), 2);
    assert_eq!(nodes[0].get_decided_idx(), 2);
    assert_eq!(nodes[1].get_decided_idx(), 1);
    assert_eq!(nodes[1].get_accepted_idx(), 1);
    emit(json!({"event":"reconnect_requested", "nodes":nodes.iter().map(state).collect::<Vec<_>>(),
        "follower_decided":nodes[1].get_decided_idx(),
        "leader_decided":nodes[2].get_decided_idx(),
        "expected_view":materialized(&nodes[2])}));
    // The transport has now re-established the previously disconnected link.
    nodes[1].reconnected(3);
    let observed = pump(&mut nodes, false, true);
    assert_eq!(observed, 1, "Expected exactly one real AcceptSync for this reconnection");
    emit(json!({"event":"network_quiesced", "nodes":nodes.iter().map(state).collect::<Vec<_>>()}));
    // The semantic comparison is performed by the external monitor, allowing
    // a complete returned-handler observation even if the property is violated.
}
