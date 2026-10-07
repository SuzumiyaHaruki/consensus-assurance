use omnipaxos::{messages::{Message, sequence_paxos::PaxosMsg}, storage::{Entry, Snapshot, SnapshotType}, util::LogEntry, ClusterConfig, ServerConfig, OmniPaxos};
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
            let mut selected_sync = None;
            if let Message::SequencePaxos(p) = &msg {
                if let PaxosMsg::AcceptSync(a) = &p.msg {
                    if stage == "reconnect" && to == 3 {
                        let delta = matches!(&a.log_sync.decided_snapshot, Some(SnapshotType::Delta(_)));
                        let receiver = observe(&nodes[(to-1) as usize]);
                        let leader = observe(&nodes[(from-1) as usize]);
                        let expected = serde_json::to_string(&leader["state"]).unwrap();
                        println!("CA_EVENT {}",json!({"event":"sync_admitted","case_id":"delta_reconnect","receiver":to,"leader":from,"config":a.n.config_id,"round":a.n.n,"session":a.seq_num.session,"delta":delta,"old_decided":receiver["decided"],"old_accepted":receiver["accepted"],"old_state":serde_json::to_string(&receiver["state"]).unwrap(),"leader_decided":leader["decided"],"incoming_decided":a.decided_idx,"sync_idx":a.log_sync.sync_idx,"expected_state":expected}));
                        selected_sync = Some((a.n.config_id,a.n.n,a.seq_num.session,a.decided_idx));
                    }
                }
            }
            nodes[(to-1) as usize].handle_incoming(msg);
            if let Some((config,round,session,incoming_decided)) = selected_sync {
                let n = &nodes[(to-1) as usize];
                let observed = observe(n);
                let completed = n.get_current_leader() == Some((from,true)) && n.get_decided_idx() == incoming_decided && n.get_accepted_idx() >= incoming_decided;
                println!("CA_EVENT {}",json!({"event":"sync_result","case_id":"delta_reconnect","receiver":to,"leader":from,"config":config,"round":round,"session":session,"completed":completed,"decided":n.get_decided_idx(),"accepted":n.get_accepted_idx(),"compacted":n.get_compacted_idx(),"actual_state":serde_json::to_string(&observed["state"]).unwrap(),"read":format!("{:?}",n.read_decided_suffix(0))}));
            }
        }
    }
}
#[test]
fn check_delta_reconnect() {
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
