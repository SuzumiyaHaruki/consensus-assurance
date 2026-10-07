use omnipaxos::{messages::{Message, sequence_paxos::PaxosMsg}, storage::{Entry, Snapshot}, util::LogEntry, ClusterConfig, ServerConfig, OmniPaxos};
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Serialize, Deserialize};
use serde_json::json;
use std::collections::{BTreeMap, VecDeque};

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Value { key: String, value: u64 }
impl Entry for Value { type Snapshot = State; }
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct State(BTreeMap<String, u64>);
impl Snapshot<Value> for State {
    fn create(entries: &[Value]) -> Self {
        let mut s = Self::default();
        for e in entries { s.0.insert(e.key.clone(), e.value); }
        s
    }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
type Node = OmniPaxos<Value, MemoryStorage<Value>>;
fn observe(node: &Node) -> serde_json::Value {
    let mut state = State::default();
    if let Some(entries) = node.read_decided_suffix(0) {
        for entry in entries {
            match entry {
                LogEntry::Decided(e) => { state.0.insert(e.key, e.value); }
                LogEntry::Snapshotted(s) => state.merge(s.snapshot),
                other => panic!("Unexpected decided representation: {:?}", other),
            }
        }
    }
    json!({"pid": node.get_pid(), "decided": node.get_decided_idx(), "accepted": node.get_accepted_idx(), "compacted": node.get_compacted_idx(), "state": state.0})
}
// One FIFO queue contains all generated messages; the partition drops every message
// to/from node 3. No delivered message is changed, forged, or reordered within a link.
fn pump(nodes: &mut [Node], partitioned: bool, stage: &str) {
    let mut queue = VecDeque::new();
    let mut count = 0;
    loop {
        for node in nodes.iter_mut() {
            let mut out = Vec::new(); node.take_outgoing_messages(&mut out);
            queue.extend(out);
        }
        let Some(msg) = queue.pop_front() else { break };
        count += 1; assert!(count < 1000, "Message pump did not quiesce");
        let from = msg.get_sender(); let to = msg.get_receiver();
        let dropped = partitioned && (from == 3 || to == 3);
        println!("CA_EVENT {}", json!({"event":"transport", "stage":stage,"from":from,"to":to,"dropped":dropped,"message":format!("{:?}",msg)}));
        if !dropped {
            if let Message::SequencePaxos(p) = &msg {
                if let PaxosMsg::AcceptSync(a) = &p.msg {
                    println!("CA_EVENT {}",json!({"event":"sync_input","stage":stage,"from":from,"to":to,"decided":a.decided_idx,"sync_idx":a.log_sync.sync_idx,"snapshot":format!("{:?}",a.log_sync.decided_snapshot),"receiver_before":observe(&nodes[(to-1) as usize])}));
                }
            }
            nodes[(to-1) as usize].handle_incoming(msg);
        }
    }
}
#[test]
fn explore_delta_reconnect() {
    let cluster = ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], ..Default::default() };
    let mut nodes: Vec<Node> = (1..=3).map(|pid| cluster.clone().build_for_server(ServerConfig {pid, ..Default::default()}, MemoryStorage::default()).unwrap()).collect();
    nodes[0].try_become_leader();
    pump(&mut nodes,false,"leadership");
    nodes[0].append(Value {key:"base".into(),value:11}).unwrap();
    pump(&mut nodes,false,"prefix");
    for n in &nodes { assert_eq!(n.get_decided_idx(),1); }
    println!("CA_EVENT {}",json!({"event":"prefix","nodes":nodes.iter().map(observe).collect::<Vec<_>>()}));
    nodes[0].append(Value {key:"tail".into(),value:22}).unwrap();
    pump(&mut nodes,true,"partition");
    assert_eq!(nodes[0].get_decided_idx(),2); assert_eq!(nodes[2].get_decided_idx(),1);
    println!("CA_EVENT {}",json!({"event":"partition_end","nodes":nodes.iter().map(observe).collect::<Vec<_>>()}));
    // The simulated network link has now been restored in both directions.
    nodes[2].reconnected(1); nodes[0].reconnected(3);
    pump(&mut nodes,false,"reconnect");
    println!("CA_EVENT {}",json!({"event":"result","nodes":nodes.iter().map(observe).collect::<Vec<_>>()}));
}
