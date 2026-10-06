use omnipaxos::{OmniPaxos, OmniPaxosConfig, ClusterConfig, ServerConfig};
use omnipaxos::storage::{Entry, Snapshot, SnapshotType};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Serialize, Deserialize};
use serde_json::json;
use std::collections::VecDeque;

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Item(u64);
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Prefix(Vec<u64>);
impl Entry for Item { type Snapshot = Prefix; }
impl Snapshot<Item> for Prefix {
    fn create(entries: &[Item]) -> Self { Self(entries.iter().map(|x| x.0).collect()) }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
type Node = OmniPaxos<Item, MemoryStorage<Item>>;
fn event(v: serde_json::Value) { println!("CA_EVENT {}", v); }
fn contents(node: &Node) -> String {
    let mut result = Vec::new();
    if let Some(entries) = node.read_decided_suffix(0) {
        for entry in entries {
            match entry {
                LogEntry::Decided(x) => result.push(x.0),
                LogEntry::Snapshotted(s) => result.extend(s.snapshot.0),
                other => panic!("Unexpected decided representation: {:?}", other),
            }
        }
    }
    serde_json::to_string(&result).unwrap()
}
fn collect(nodes: &mut [Node], queue: &mut VecDeque<Message<Item>>) {
    for node in nodes {
        let mut out = Vec::new();
        node.take_outgoing_messages(&mut out);
        queue.extend(out);
    }
}
// FIFO delivery for every connected pair; disconnection discards all traffic
// involving node 3, independent of message type or observed protocol result.
fn drain(nodes: &mut [Node], disconnected: bool) {
    let mut queue = VecDeque::new();
    collect(nodes, &mut queue);
    for step in 0..1000 {
        let Some(msg) = queue.pop_front() else { return; };
        let from = msg.get_sender();
        let to = msg.get_receiver();
        if disconnected && (from == 3 || to == 3) {
            event(json!({"event":"transport_drop", "from":from,"to":to,"message":format!("{:?}", msg)}));
        } else {
            nodes[(to - 1) as usize].handle_incoming(msg);
        }
        collect(nodes, &mut queue);
        assert!(step < 999, "Transport did not quiesce");
    }
}
#[test]
fn delta_snapshot_preserves_decided_prefix() {
    let mut nodes: Vec<Node> = (1..=3).map(|pid| {
        let config = OmniPaxosConfig {
            cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None },
            server_config: ServerConfig { pid, batch_size: 1, ..Default::default() },
        };
        config.build(MemoryStorage::default()).unwrap()
    }).collect();
    // Public manual leadership attempt still performs actual prepare/accept quorums.
    nodes[0].try_become_leader();
    drain(&mut nodes, false);
    assert!(nodes.iter().all(|n| n.get_current_leader() == Some((1, true))));
    nodes[0].append(Item(11)).unwrap();
    drain(&mut nodes, false);
    assert!(nodes.iter().all(|n| n.get_decided_idx() == 1 && contents(n) == "[11]"));
    // Transport disconnects node 3; majority {1,2} remains connected.
    nodes[0].append(Item(22)).unwrap();
    drain(&mut nodes, true);
    assert_eq!(nodes[0].get_decided_idx(), 2);
    assert_eq!(nodes[1].get_decided_idx(), 2);
    assert_eq!(contents(&nodes[0]), "[11,22]");
    assert_eq!(contents(&nodes[1]), "[11,22]");
    assert_eq!(nodes[2].get_decided_idx(), 1);
    assert_eq!(nodes[2].get_accepted_idx(), 1);
    assert_eq!(contents(&nodes[2]), "[11]");
    let expected = contents(&nodes[0]);
    event(json!({"event":"prefix_ready","case":"delta_missing_entry","receiver":3,"sync_id":1,
        "leader_decided":nodes[0].get_decided_idx(),"receiver_decided":nodes[2].get_decided_idx(),
        "receiver_accepted":nodes[2].get_accepted_idx(),"receiver_content":contents(&nodes[2]),"expected_content":expected}));
    // The simulated link is restored before issuing the documented notification.
    nodes[2].reconnected(1);
    let mut queue = VecDeque::new();
    collect(&mut nodes, &mut queue);
    let mut observed = false;
    let mut promise_seen = false;
    for _ in 0..1000 {
        let Some(msg) = queue.pop_front() else { break; };
        let to = msg.get_receiver();
        if let Message::SequencePaxos(p) = &msg {
            if p.from == 3 {
                if let PaxosMsg::Promise(prom) = &p.msg {
                    assert_eq!(prom.decided_idx, 1);
                    assert_eq!(prom.accepted_idx, 1);
                    promise_seen = true;
                    event(json!({"event":"recovery_promise","case":"delta_missing_entry","receiver":3,"sync_id":1,"ballot":format!("{:?}",prom.n),"decided":prom.decided_idx,"accepted":prom.accepted_idx}));
                }
            }
            if to == 3 {
                if let PaxosMsg::AcceptSync(sync) = &p.msg {
                    assert!(promise_seen);
                    assert!(!observed);
                    assert_eq!(sync.n, nodes[2].get_promise());
                    assert_eq!(sync.decided_idx, 2);
                    assert_eq!(sync.log_sync.sync_idx, 2);
                    let delta = match &sync.log_sync.decided_snapshot {
                        Some(SnapshotType::Delta(s)) => s.0.clone(),
                        other => panic!("Expected actual Delta from target, got {:?}", other),
                    };
                    event(json!({"event":"sync_admitted","case":"delta_missing_entry","receiver":3,"sync_id":1,
                        "expected_content":expected,"delta":delta,"decided":sync.decided_idx,
                        "sync_idx":sync.log_sync.sync_idx,"ballot":format!("{:?}",sync.n),"sequence":format!("{:?}",sync.seq_num)}));
                    let ballot = sync.n;
                    nodes[2].handle_incoming(msg);
                    let mut replies = Vec::new();
                    nodes[2].take_outgoing_messages(&mut replies);
                    let acknowledged = replies.iter().any(|r| matches!(r,
                        Message::SequencePaxos(p) if p.from==3 && p.to==1 && matches!(&p.msg,
                            PaxosMsg::Accepted(a) if a.n==ballot && a.accepted_idx==2)));
                    event(json!({"event":"sync_result","case":"delta_missing_entry","receiver":3,"sync_id":1,
                        "completed":acknowledged && nodes[2].get_current_leader()==Some((1,true)),
                        "actual_content":contents(&nodes[2]),"decided":nodes[2].get_decided_idx(),
                        "accepted":nodes[2].get_accepted_idx(),"compacted":nodes[2].get_compacted_idx(),
                        "read":format!("{:?}",nodes[2].read_decided_suffix(0))}));
                    queue.extend(replies);
                    observed = true;
                    continue;
                }
            }
        }
        nodes[(to-1) as usize].handle_incoming(msg);
        collect(&mut nodes, &mut queue);
    }
    assert!(observed, "No recovery AcceptSync was delivered");
    assert!(queue.is_empty(), "Recovery message exchange did not finish");
}
