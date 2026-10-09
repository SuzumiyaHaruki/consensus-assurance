use omnipaxos::{OmniPaxos, OmniPaxosConfig, ClusterConfig, ServerConfig, messages::{Message, sequence_paxos::PaxosMsg}, storage::{Entry, Snapshot}, util::LogEntry};
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Serialize, Deserialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Value(pub u64);
impl Entry for Value { type Snapshot = Values; }
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Values(pub Vec<u64>);
impl Snapshot<Value> for Values {
    fn create(entries: &[Value]) -> Self { Self(entries.iter().map(|e| e.0).collect()) }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
pub type Node = OmniPaxos<Value, MemoryStorage<Value>>;
pub fn cluster(ids: &[u64]) -> Vec<Node> {
    ids.iter().map(|id| OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id: 1, nodes: ids.to_vec(), flexible_quorum: None },
        server_config: ServerConfig { pid: *id, ..Default::default() },
    }.build(MemoryStorage::default()).unwrap()).collect()
}
pub fn drain(nodes: &mut [Node], mut allow: impl FnMut(&Message<Value>) -> bool) {
    for _ in 0..100 {
        let mut msgs = vec![];
        for node in nodes.iter_mut() { node.take_outgoing_messages(&mut msgs); }
        if msgs.is_empty() { return; }
        for msg in msgs {
            if allow(&msg) {
                println!("deliver {:?}", msg);
                let to = msg.get_receiver();
                nodes.iter_mut().find(|n| n.get_pid() == to).unwrap().handle_incoming(msg);
            } else { println!("drop {:?}", msg); }
        }
    }
    panic!("message loop did not quiesce");
}
pub fn values(node: &Node) -> Vec<u64> {
    let mut result = vec![];
    for entry in node.read_decided_suffix(0).unwrap_or_default() {
        match entry {
            LogEntry::Decided(v) => result.push(v.0),
            LogEntry::Snapshotted(s) => result.extend(s.snapshot.0),
            e => panic!("unexpected decided entry: {:?}", e),
        }
    }
    result
}

#[test]
fn delta_snapshot_loses_previously_decided_prefix() {
    let mut nodes = cluster(&[1, 2, 3]);
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(10)).unwrap();
    drain(&mut nodes, |_| true);
    assert_eq!(values(&nodes[2]), vec![10]);
    // Node 3 is disconnected while nodes 1 and 2 decide another entry.
    nodes[0].append(Value(20)).unwrap();
    drain(&mut nodes, |m| m.get_receiver() != 3 && m.get_sender() != 3);
    assert_eq!(nodes[0].get_decided_idx(), 2);
    assert_eq!(nodes[2].get_decided_idx(), 1);
    // Elect node 2: node 3's older accepted round makes it need a delta snapshot.
    nodes[1].try_become_leader();
    drain(&mut nodes, |_| true);
    println!("leader values: {:?}; caught-up follower values: {:?}; decided index: {}", values(&nodes[1]), values(&nodes[2]), nodes[2].get_decided_idx());
    assert_eq!(nodes[2].get_decided_idx(), 2);
    assert_eq!(values(&nodes[2]), vec![10, 20]);
}

#[test]
fn delta_snapshot_includes_overwritten_undecided_entry() {
    let mut nodes = cluster(&[1, 2, 3]);
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(10)).unwrap();
    drain(&mut nodes, |_| true);
    // Old leader accepts 999 locally, but neither follower ever receives it.
    nodes[0].append(Value(999)).unwrap();
    drain(&mut nodes, |_| false);
    assert_eq!(nodes[0].get_decided_idx(), 1);
    assert_eq!(nodes[0].get_accepted_idx(), 2);
    nodes[1].try_become_leader();
    drain(&mut nodes, |m| m.get_receiver() != 1 && m.get_sender() != 1);
    nodes[1].append(Value(20)).unwrap();
    drain(&mut nodes, |m| m.get_receiver() != 1 && m.get_sender() != 1);
    assert_eq!(values(&nodes[1]), vec![10, 20]);
    nodes[0].reconnected(2);
    drain(&mut nodes, |_| true);
    println!("leader values: {:?}; recovered old leader snapshot: {:?}", values(&nodes[1]), values(&nodes[0]));
    assert_eq!(values(&nodes[0]), vec![10, 20]);
}

#[test]
fn complete_snapshot_control_preserves_prefix() {
    let mut nodes = cluster(&[1, 2, 3]);
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(10)).unwrap();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(20)).unwrap();
    drain(&mut nodes, |m| m.get_receiver() != 3 && m.get_sender() != 3);
    // Snapshot on the sender forces a Complete snapshot for the same lagging node.
    nodes[0].snapshot(None, true).unwrap();
    nodes[2].reconnected(1);
    drain(&mut nodes, |_| true);
    assert_eq!(values(&nodes[2]), vec![10, 20]);
}

#[test]
fn trim_with_sparse_node_ids() {
    let mut nodes = cluster(&[2, 4, 6]);
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(10)).unwrap();
    drain(&mut nodes, |_| true);
    assert!(nodes.iter().all(|n| n.get_decided_idx() == 1 && n.get_accepted_idx() == 1));
    let automatic = nodes[0].trim(None);
    println!("trim(None) = {:?}, compacted index = {}", automatic, nodes[0].get_compacted_idx());
    let explicit = nodes[0].trim(Some(1));
    println!("trim(Some(1)) = {:?}", explicit);
    assert!(explicit.is_ok(), "all configured nodes have decided index 1");
}

#[test]
fn trim_contiguous_ids_control() {
    let mut nodes = cluster(&[1, 2, 3]);
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    nodes[0].append(Value(10)).unwrap();
    drain(&mut nodes, |_| true);
    nodes[0].trim(Some(1)).unwrap();
    drain(&mut nodes, |_| true);
    assert!(nodes.iter().all(|n| n.get_compacted_idx() == 1));
}

fn promise_retry_scenario(drain_before_retry: bool) {
    let mut nodes: Vec<Node> = [1, 2, 3].into_iter().map(|id| OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None },
        server_config: ServerConfig { pid: id, election_tick_timeout: 1000, resend_message_tick_timeout: 1, ..Default::default() },
    }.build(MemoryStorage::default()).unwrap()).collect();
    nodes[0].try_become_leader();
    // Node 2's first AcceptSync is lost. It remains in Prepare and retries its Promise.
    drain(&mut nodes, |m| !matches!(m, Message::SequencePaxos(p) if p.to == 2 && matches!(p.msg, PaxosMsg::AcceptSync(_))));
    assert_eq!(nodes[1].get_current_leader(), Some((1, false)));
    nodes[0].append(Value(10)).unwrap();
    if drain_before_retry { drain(&mut nodes, |_| true); }
    // Leave the leader's AcceptDecide buffered while handling a genuine Promise retry.
    nodes[1].tick();
    let mut retry = vec![];
    nodes[1].take_outgoing_messages(&mut retry);
    assert!(retry.iter().any(|m| matches!(m, Message::SequencePaxos(p) if matches!(p.msg, PaxosMsg::Promise(_)))));
    for m in retry {
        println!("deliver retry {:?}", m);
        let to = m.get_receiver();
        nodes.iter_mut().find(|n| n.get_pid() == to).unwrap().handle_incoming(m);
    }
    // New data after the retry should be in the NEW session, after AcceptSync.
    nodes[0].append(Value(20)).unwrap();
    drain(&mut nodes, |_| true);
    println!("after retry: leader {:?}, follower {:?}", values(&nodes[0]), values(&nodes[1]));
    nodes[0].append(Value(30)).unwrap();
    drain(&mut nodes, |_| true);
    println!("after next append: leader {:?}, follower {:?}", values(&nodes[0]), values(&nodes[1]));
    assert!(nodes[1].get_decided_idx() >= 2);
    assert_eq!(nodes[1].read(1), nodes[0].read(1), "decided entry at index 1 must agree");
}

#[test]
fn promise_retry_coalesces_entries_into_obsolete_session() {
    promise_retry_scenario(false);
}

#[test]
fn promise_retry_with_drained_buffer_control() {
    promise_retry_scenario(true);
}

fn old_configuration_message_scenario(deliver_old: bool) {
    let mut old = cluster(&[1, 2, 3]);
    old[0].try_become_leader();
    drain(&mut old, |_| true);
    let mut delayed = None;
    old[0].append(Value(10)).unwrap();
    drain(&mut old, |m| {
        if matches!(m, Message::SequencePaxos(p) if p.to == 3 && matches!(p.msg, PaxosMsg::AcceptDecide(_))) {
            delayed = Some(m.clone());
            false // retain this exact outgoing message for later delivery
        } else { true }
    });
    // Node 3 sees a later sequence number, resynchronizes, and learns 10 normally.
    assert_eq!(values(&old[2]), vec![10]);
    let next = ClusterConfig { configuration_id: 2, nodes: vec![1,2,3], flexible_quorum: None };
    old[0].reconfigure(next.clone(), None).unwrap();
    drain(&mut old, |_| true);
    assert!(old.iter().all(|n| n.is_reconfigured().is_some()));
    // Follow the documented reconfiguration procedure: new instances, fresh storage.
    let mut nodes: Vec<Node> = [1,2,3].into_iter().map(|pid|
        next.clone().build_for_server(ServerConfig { pid, ..Default::default() }, MemoryStorage::default()).unwrap()
    ).collect();
    nodes[0].try_become_leader();
    drain(&mut nodes, |_| true);
    assert!(nodes.iter().all(|n| n.get_accepted_idx() == 0));
    let delayed = delayed.unwrap();
    println!("deliver delayed old-configuration message {:?}", delayed);
    if deliver_old { nodes[2].handle_incoming(delayed); }
    println!("new configuration follower after old packet: {:?}", nodes[2].read_entries(..));
    nodes[0].append(Value(20)).unwrap();
    drain(&mut nodes, |_| true);
    println!("new config leader values {:?}, follower values {:?}", values(&nodes[0]), values(&nodes[2]));
    assert_eq!(nodes[2].read(0), nodes[0].read(0), "old config data must not be decided as a new log entry");
}

#[test]
fn delayed_old_configuration_accept_is_applied_to_new_log() {
    old_configuration_message_scenario(true);
}

#[test]
fn old_configuration_packet_filtered_control() {
    old_configuration_message_scenario(false);
}
