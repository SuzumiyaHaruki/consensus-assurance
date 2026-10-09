use omnipaxos::{OmniPaxos, ClusterConfig, ServerConfig, storage::{Entry, NoSnapshot}, messages::{Message, sequence_paxos::PaxosMsg}, util::LogEntry};
use omnipaxos_storage::memory_storage::MemoryStorage;
#[derive(Clone, Debug)]
struct Item(u64);
impl Entry for Item { type Snapshot = NoSnapshot; }
type Node = OmniPaxos<Item, MemoryStorage<Item>>;
fn deliver(nodes: &mut [Node], mut allow: impl FnMut(&Message<Item>) -> bool) {
    for _ in 0..100 {
        let mut msgs = vec![];
        for n in nodes.iter_mut() { n.take_outgoing_messages(&mut msgs); }
        if msgs.is_empty() { return; }
        for m in msgs {
            if allow(&m) {
                println!("deliver {:?}", m);
                nodes[m.get_receiver() as usize - 1].handle_incoming(m);
            } else { println!("drop {:?}", m); }
        }
    }
    panic!("message loop did not quiesce");
}
fn scenario(trim: bool, lost_decide: bool) {
    let mut nodes: Vec<Node> = (1..=3).map(|pid|
        ClusterConfig {configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None}
        .build_for_server(ServerConfig {pid, ..Default::default()}, MemoryStorage::default()).unwrap()
    ).collect();
    nodes[0].try_become_leader();
    deliver(&mut nodes, |_| true);
    nodes[0].append(Item(10)).unwrap();
    // Node 3 accepts the value, but its decision notification is lost.
    deliver(&mut nodes, |m| !lost_decide || !matches!(m, Message::SequencePaxos(p) if p.to == 3 && matches!(p.msg, PaxosMsg::Decide(_))));
    assert_eq!(nodes[2].get_accepted_idx(), 1);
    assert_eq!(nodes[2].get_decided_idx(), if lost_decide {0} else {1});
    if trim {
        let result = nodes[0].trim(Some(1));
        println!("trim while node3 decided index is {}: {:?}", nodes[2].get_decided_idx(), result);
        result.unwrap();
        deliver(&mut nodes, |_| true);
        assert_eq!(nodes[0].get_compacted_idx(), 1);
        assert_eq!(nodes[1].get_compacted_idx(), 1);
        assert_eq!(nodes[2].get_compacted_idx(), if lost_decide {0} else {1});
    }
    // Nodes 1 and 2 enter a newer accepted round while node 3 is disconnected.
    nodes[1].try_become_leader();
    deliver(&mut nodes, |m| m.get_receiver() != 3 && m.get_sender() != 3);
    // Node 3's next ballot beats node 2 by pid and its Prepare advertises decided index 0.
    nodes[2].try_become_leader();
    deliver(&mut nodes, |_| true);
    println!("candidate after election: accepted {}, decided {}, entry zero {:?}", nodes[2].get_accepted_idx(), nodes[2].get_decided_idx(), nodes[2].read(0));
    assert_eq!(nodes[2].get_decided_idx(), 1);
    assert!(nodes[2].get_accepted_idx() >= nodes[2].get_decided_idx(), "decided index exceeds the recovered accepted log");
    match nodes[2].read(0).unwrap() {
        LogEntry::Decided(Item(10)) => (),
        LogEntry::Trimmed(1) if trim => (),
        e => panic!("lost previously chosen entry: {e:?}"),
    }
}
#[test]
fn trim_before_all_decide_panics_on_later_prepare() { scenario(true, true); }
#[test]
fn untrimmed_leader_change_control() { scenario(false, true); }

#[test]
fn all_decided_before_trim_control() { scenario(true, false); }
