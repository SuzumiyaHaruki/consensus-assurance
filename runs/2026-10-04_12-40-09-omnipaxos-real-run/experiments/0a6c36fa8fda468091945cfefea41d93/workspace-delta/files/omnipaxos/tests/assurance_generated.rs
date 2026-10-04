use omnipaxos::{OmniPaxos, OmniPaxosConfig, ClusterConfig, ServerConfig};
use omnipaxos::storage::{Entry, Snapshot, SnapshotType};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde_json::json;
use std::collections::VecDeque;

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct Item(u64);
impl Entry for Item { type Snapshot = History; }
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct History(Vec<u64>);
impl Snapshot<Item> for History {
    fn create(entries: &[Item]) -> Self { Self(entries.iter().map(|e| e.0).collect()) }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
type Node = OmniPaxos<Item, MemoryStorage<Item>>;
fn emit(v: serde_json::Value) { println!("CA_EVENT {}", v); }
fn drain(nodes: &mut [Node], isolated: bool, case: &str) {
    let mut queue = VecDeque::new();
    for node in nodes.iter_mut() { let mut out=vec![]; node.take_outgoing_messages(&mut out); queue.extend(out); }
    let mut deliveries=0;
    while let Some(msg)=queue.pop_front() {
        let from=msg.get_sender(); let to=msg.get_receiver();
        if isolated && (from==3 || to==3) {
            emit(json!({"event":"partition_drop","case":case,"from":from,"to":to,"message":format!("{:?}",msg)}));
            continue;
        }
        if let Message::SequencePaxos(p)=&msg {
            match &p.msg {
                PaxosMsg::Promise(p) => emit(json!({"event":"promise","case":case,"from":from,"to":to,"decided":p.decided_idx,"accepted":p.accepted_idx})),
                PaxosMsg::AcceptSync(a) => {
                    let (kind,values)=match &a.log_sync.decided_snapshot {
                        Some(SnapshotType::Delta(s)) => ("delta",s.0.clone()),
                        Some(SnapshotType::Complete(s)) => ("complete",s.0.clone()),
                        None => ("none",vec![]),
                    };
                    emit(json!({"event":"sync_delivery","case":case,"from":from,"to":to,"kind":kind,"snapshot":values,"sync_idx":a.log_sync.sync_idx,"incoming_decided":a.decided_idx,"receiver_decided":nodes[(to-1) as usize].get_decided_idx(),"receiver_accepted":nodes[(to-1) as usize].get_accepted_idx()}));
                }
                _ => (),
            }
        }
        nodes[(to-1) as usize].handle_incoming(msg);
        let mut out=vec![]; nodes[(to-1) as usize].take_outgoing_messages(&mut out); queue.extend(out);
        deliveries+=1; assert!(deliveries<1000,"drain did not terminate");
    }
    emit(json!({"event":"queue_drained","case":case,"deliveries":deliveries,"isolated":isolated}));
}
fn contents(node: &Node)->Vec<u64> {
    let mut values=vec![];
    for entry in node.read_decided_suffix(0).unwrap_or_default() {
        match entry { LogEntry::Decided(e)=>values.push(e.0),LogEntry::Snapshotted(s)=>values.extend(s.snapshot.0),x=>panic!("unexpected decided export: {:?}",x) }
    }
    values
}
#[test]
fn explore_delta_base() {
    for prefix in [0usize,1] {
        let case=if prefix==0 {"complete_control"} else {"delta_missing_range"};
        let mut nodes:Vec<Node>=(1..=3).map(|pid| OmniPaxosConfig {
            cluster_config:ClusterConfig{configuration_id:1,nodes:vec![1,2,3],..Default::default()},
            server_config:ServerConfig{pid,..Default::default()},
        }.build(MemoryStorage::default()).unwrap()).collect();
        nodes[0].try_become_leader(); drain(&mut nodes,false,case);
        if prefix==1 { nodes[0].append(Item(11)).unwrap(); drain(&mut nodes,false,case); }
        for n in &nodes { assert_eq!(n.get_decided_idx(),prefix); assert_eq!(n.get_accepted_idx(),prefix); }
        emit(json!({"event":"initial_prefix","case":case,"decided":prefix,"values":contents(&nodes[2])}));
        // Disconnect node 3, deliver the new proposal only through the remaining quorum.
        nodes[0].append(Item(22)).unwrap(); drain(&mut nodes,true,case);
        assert_eq!(nodes[0].get_decided_idx(),prefix+1);
        assert_eq!(nodes[1].get_decided_idx(),prefix+1);
        assert_eq!(nodes[2].get_decided_idx(),prefix);
        emit(json!({"event":"before_reconnect","case":case,"source_values":contents(&nodes[0]),"receiver_values":contents(&nodes[2]),"source_decided":nodes[0].get_decided_idx(),"receiver_decided":nodes[2].get_decided_idx()}));
        // The transport reports that the previously disconnected link is now restored.
        nodes[2].reconnected(1); drain(&mut nodes,false,case);
        emit(json!({"event":"result","case":case,"source_values":contents(&nodes[0]),"receiver_values":contents(&nodes[2]),"source_decided":nodes[0].get_decided_idx(),"receiver_decided":nodes[2].get_decided_idx(),"receiver_accepted":nodes[2].get_accepted_idx(),"receiver_compacted":nodes[2].get_compacted_idx()}));
    }
}
