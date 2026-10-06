use std::collections::BTreeMap;
use omnipaxos::{ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::storage::{Entry, Snapshot, SnapshotType};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Value { key: u64, value: u64 }
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct State(BTreeMap<u64, u64>);
impl Entry for Value { type Snapshot = State; }
impl Snapshot<Value> for State {
    fn create(entries: &[Value]) -> Self {
        let mut s = Self::default();
        for e in entries { s.0.insert(e.key, e.value); }
        s
    }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
type Node = OmniPaxos<Value, MemoryStorage<Value>>;
fn emit(v: serde_json::Value) { println!("CA_EVENT {}", v); }
fn application_state(n: &Node) -> String {
    let mut state = State::default();
    if let Some(entries) = n.read_decided_suffix(0) {
        for e in entries {
            match e {
                LogEntry::Decided(v) => { state.0.insert(v.key, v.value); }
                LogEntry::Snapshotted(s) => state.merge(s.snapshot),
                other => panic!("Unexpected entry in decided read: {:?}", other),
            }
        }
    }
    serde_json::to_string(&state.0).unwrap()
}
// Each drain preserves producer order, including each sender-to-receiver stream.
// Only traffic across the declared disconnected link is discarded.
fn deliver(nodes: &mut [Node], disconnected: bool, observe_sync: bool, seq: &mut usize) -> usize {
    let mut syncs = 0;
    for _ in 0..100 {
        let mut batch = Vec::new();
        for node in nodes.iter_mut() { node.take_outgoing_messages(&mut batch); }
        if batch.is_empty() { return syncs; }
        for m in batch {
            *seq += 1;
            let from = m.get_sender();
            let to = m.get_receiver();
            let dropped = disconnected && (from == 3 || to == 3);
            emit(json!({"event":"transport", "ordinal":*seq,"from":from,"to":to,"dropped":dropped,"message":format!("{:?}",m)}));
            if dropped { continue; }
            let targeted = observe_sync && to == 3 && matches!(&m, Message::SequencePaxos(p) if matches!(&p.msg, PaxosMsg::AcceptSync(_)));
            if targeted {
                if let Message::SequencePaxos(p) = &m {
                    if let PaxosMsg::AcceptSync(s) = &p.msg {
                        let delta = matches!(&s.log_sync.decided_snapshot, Some(SnapshotType::Delta(_)));
                        let before_decided = nodes[2].get_decided_idx();
                        let before_accepted = nodes[2].get_accepted_idx();
                        assert_eq!(nodes[2].get_current_leader(), Some((1,false)));
                        assert_eq!(nodes[2].get_promise(), s.n);
                        assert_eq!(from,1);
                        assert_eq!(before_decided,1);
                        assert_eq!(before_accepted,1);
                        assert_eq!(s.decided_idx,3);
                        assert_eq!(s.log_sync.sync_idx,3);
                        assert!(delta, "This fixed check requires an actual delta transfer");
                        emit(json!({"event":"sync_admitted","case":"delta_missing_suffix","node":3,"ordinal":*seq,"delta":delta,"before_decided":before_decided,"before_accepted":before_accepted,"transfer_decided":s.decided_idx,"transfer_compacted":s.log_sync.sync_idx,"expected_state":application_state(&nodes[0]),"old_state":application_state(&nodes[2]),"ballot":format!("{:?}",s.n)}));
                    }
                }
            }
            nodes[(to-1) as usize].handle_incoming(m);
            if targeted {
                syncs += 1;
                emit(json!({"event":"sync_result","case":"delta_missing_suffix","node":3,"ordinal":*seq,"returned":true,"actual_state":application_state(&nodes[2]),"decided":nodes[2].get_decided_idx(),"accepted":nodes[2].get_accepted_idx(),"compacted":nodes[2].get_compacted_idx(),"phase_accept":nodes[2].get_current_leader()==Some((1,true))}));
            }
        }
    }
    panic!("Message delivery did not quiesce within the construction bound");
}
#[test]
fn delta_sync_preserves_decided_application_state() {
    let mut nodes: Vec<Node> = (1..=3).map(|pid| {
        OmniPaxosConfig {
            cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], ..Default::default() },
            server_config: ServerConfig {
                pid, batch_size: 1,
                ..Default::default()
            },
        }.build(MemoryStorage::default()).unwrap()
    }).collect();
    let mut seq = 0;
    nodes[0].try_become_leader();
    deliver(&mut nodes,false,false,&mut seq);
    for n in &nodes { assert_eq!(n.get_current_leader(),Some((1,true))); }
    nodes[0].append(Value{key:11,value:110}).unwrap();
    deliver(&mut nodes,false,false,&mut seq);
    for n in &nodes { assert_eq!(n.get_decided_idx(),1); }
    let common = application_state(&nodes[0]);
    assert_eq!(application_state(&nodes[2]),common);
    emit(json!({"event":"common_prefix","decided":1,"state":common}));
    // Disconnect follower 3 after the common prefix is fully delivered.
    for (key,value) in [(22,220),(33,330)] {
        nodes[0].append(Value{key,value}).unwrap();
        deliver(&mut nodes,true,false,&mut seq);
    }
    assert_eq!(nodes[0].get_decided_idx(),3);
    assert_eq!(nodes[1].get_decided_idx(),3);
    assert_eq!(nodes[2].get_decided_idx(),1);
    assert_eq!(nodes[2].get_accepted_idx(),1);
    assert_eq!(nodes[0].get_compacted_idx(),0);
    assert_eq!(application_state(&nodes[0]),application_state(&nodes[1]));
    // Restore the link and notify both endpoints using the documented callback.
    nodes[2].reconnected(1);
    nodes[0].reconnected(3);
    let syncs = deliver(&mut nodes,false,true,&mut seq);
    assert_eq!(syncs,1,"Need one independently correlated synchronization");
    emit(json!({"event":"final_state","follower":application_state(&nodes[2]),"leader":application_state(&nodes[0]),"follower_decided":nodes[2].get_decided_idx(),"leader_decided":nodes[0].get_decided_idx()}));
}
