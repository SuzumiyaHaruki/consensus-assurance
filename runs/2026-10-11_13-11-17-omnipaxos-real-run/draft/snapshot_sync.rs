use std::collections::BTreeMap;
use omnipaxos::{OmniPaxos, OmniPaxosConfig};
use omnipaxos::storage::{Entry, Snapshot};
use omnipaxos::messages::Message;
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Serialize, Deserialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Put { key: u64, value: u64 }
#[derive(Clone, Debug, Serialize, Deserialize)]
struct KvSnapshot(BTreeMap<u64, u64>);
impl Entry for Put { type Snapshot = KvSnapshot; }
impl Snapshot<Put> for KvSnapshot {
    fn create(entries: &[Put]) -> Self {
        let mut map = BTreeMap::new();
        for entry in entries { map.insert(entry.key, entry.value); }
        Self(map)
    }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
type Node = OmniPaxos<Put, MemoryStorage<Put>>;
fn emit(value: Value) { println!("CA_EVENT {}", value); }
fn view(node: &Node) -> Value {
    let entries = node.read_decided_suffix(0);
    let raw = format!("{:?}", entries);
    let mut map = BTreeMap::new();
    if let Some(entries) = entries {
        for entry in entries {
            match entry {
                LogEntry::Decided(p) => { map.insert(p.key, p.value); }
                LogEntry::Snapshotted(s) => { map.extend(s.snapshot.0); }
                other => panic!("Unexpected decided representation: {:?}", other),
            }
        }
    }
    json!({"pid":node.get_pid(), "decided":node.get_decided_idx(),
        "accepted":node.get_accepted_idx(), "compacted":node.get_compacted_idx(),
        "state":serde_json::to_string(&map).unwrap(), "raw":raw})
}
fn pump(nodes: &mut [Node], case: &str, phase: &str, isolated: Option<u64>) {
    for _ in 0..100 {
        let mut messages: Vec<Message<Put>> = Vec::new();
        for node in nodes.iter_mut() { node.take_outgoing_messages(&mut messages); }
        if messages.is_empty() { return; }
        for message in messages {
            let from = message.get_sender();
            let to = message.get_receiver();
            let dropped = isolated.map_or(false, |pid| from == pid || to == pid);
            if phase != "initialization" {
                emit(json!({"event":"transport", "case":case, "phase":phase,
                    "from":from, "to":to, "dropped":dropped, "message":message}));
            }
            if !dropped { nodes[(to-1) as usize].handle_incoming(message); }
        }
    }
    panic!("Message drain did not quiesce");
}
fn run(case: &str, complete_snapshot: bool) {
    let mut nodes: Vec<Node> = (1..=3).map(|pid| {
        let mut config = OmniPaxosConfig::default();
        config.cluster_config.configuration_id = 1;
        config.cluster_config.nodes = vec![1,2,3];
        config.server_config.pid = pid;
        config.server_config.election_tick_timeout = 5;
        config.server_config.leader_priority = if pid == 3 { 10 } else { 0 };
        config.server_config.custom_logger = Some(slog::Logger::root(slog::Discard, slog::o!()));
        config.build(MemoryStorage::default()).unwrap()
    }).collect();
    for _ in 0..40 {
        for node in &mut nodes { node.tick(); }
        pump(&mut nodes, case, "initialization", None);
    }
    for node in &nodes { assert_eq!(node.get_current_leader(), Some((3,true))); }
    nodes[2].append(Put { key:101, value:1001 }).unwrap();
    pump(&mut nodes, case, "first_decision", None);
    for node in &nodes { assert_eq!(node.get_decided_idx(),1); }
    emit(json!({"event":"before_disconnect", "case":case,
        "nodes":nodes.iter().map(view).collect::<Vec<_>>()}));
    emit(json!({"event":"disconnect", "case":case, "isolated_pid":1}));
    nodes[2].append(Put { key:202, value:2002 }).unwrap();
    nodes[2].append(Put { key:303, value:3003 }).unwrap();
    pump(&mut nodes, case, "partition", Some(1));
    assert_eq!(nodes[0].get_decided_idx(),1);
    assert_eq!(nodes[0].get_accepted_idx(),1);
    assert_eq!(nodes[2].get_decided_idx(),3);
    assert_eq!(nodes[1].get_decided_idx(),3);
    if complete_snapshot { nodes[2].snapshot(Some(3),true).unwrap(); }
    let leader = view(&nodes[2]);
    emit(json!({"event":"admission", "case":case, "receiver":1,
        "leader":leader, "receiver_before":view(&nodes[0]),
        "expected_state":leader["state"], "expected_decided":leader["decided"],
        "leader_compacted_for_control":complete_snapshot}));
    // The transport now restores node 1's connections after the recorded partition.
    nodes[0].reconnected(3);
    pump(&mut nodes, case, "reconnection", None);
    let after = view(&nodes[0]);
    emit(json!({"event":"endpoint", "case":case, "receiver":1,
        "actual_state":after["state"], "actual_decided":after["decided"],
        "receiver_after":after, "leader_after":view(&nodes[2])}));
}
#[test]
fn snapshot_sync_preserves_decided_state() {
    run("delta_after_partition", false);
    run("complete_snapshot_control", true);
}
