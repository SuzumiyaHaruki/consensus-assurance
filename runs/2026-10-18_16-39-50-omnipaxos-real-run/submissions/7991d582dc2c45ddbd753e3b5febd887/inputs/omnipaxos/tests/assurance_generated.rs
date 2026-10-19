//! Focused probe: can a new leader's AcceptSync lower the decided index of a
//! follower that had already decided a later entry?
//!
//! Five real OmniPaxos instances run in one process with in-memory storage and
//! an explicit message pump. Messages are dropped or delayed selectively to
//! build the state: entry 5 is decided with a majority, two acceptors never see
//! the Decide, a new leader is elected by those lagging nodes, and the follower
//! that did see index 4 as Decided promises only after that leader's prepare
//! quorum is complete.

use omnipaxos::{
    messages::{sequence_paxos::PaxosMsg, Message},
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
        nodes: vec![1, 2, 3, 4, 5],
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

fn collect(nodes: &mut [Node], q: &mut Vec<Message<Value>>) {
    for n in nodes.iter_mut() {
        let mut out = Vec::new();
        n.take_outgoing_messages(&mut out);
        q.extend(out);
    }
}

fn route<F>(nodes: &mut [Node], q: &mut Vec<Message<Value>>, mut keep: F)
where
    F: FnMut(&Message<Value>) -> bool,
{
    let all = std::mem::take(q);
    let mut kept = Vec::new();
    for m in all {
        if keep(&m) {
            let to = m.get_receiver() as usize;
            nodes[to - 1].handle_incoming(m);
        } else {
            kept.push(m);
        }
    }
    *q = kept;
}

fn purge<F>(q: &mut Vec<Message<Value>>, drop_if: F)
where
    F: Fn(&Message<Value>) -> bool,
{
    q.retain(|m| !drop_if(m));
}

fn extract<F>(q: &mut Vec<Message<Value>>, pred: F) -> Vec<Message<Value>>
where
    F: Fn(&Message<Value>) -> bool,
{
    let mut taken = Vec::new();
    let mut rest = Vec::new();
    for m in std::mem::take(q) {
        if pred(&m) {
            taken.push(m);
        } else {
            rest.push(m);
        }
    }
    *q = rest;
    taken
}

fn settle(nodes: &mut [Node], q: &mut Vec<Message<Value>>) {
    for _ in 0..2000 {
        collect(nodes, q);
        if q.is_empty() {
            return;
        }
        route(nodes, q, |_| true);
    }
    panic!("message pump did not quiesce");
}

/// Settle every message that does not touch the cut node 1.
fn settle_cut1(nodes: &mut [Node], q: &mut Vec<Message<Value>>) {
    for _ in 0..2000 {
        collect(nodes, q);
        purge(q, |m| m.get_sender() == 1 || m.get_receiver() == 1);
        if q.is_empty() {
            return;
        }
        route(nodes, q, |_| true);
    }
    panic!("cut settlement did not quiesce");
}

fn is_acceptdecide_to(m: &Message<Value>, to: u64) -> bool {
    matches!(m, Message::SequencePaxos(p) if p.to == to && matches!(p.msg, PaxosMsg::AcceptDecide(_)))
}

fn is_decide_to(m: &Message<Value>, to: u64) -> bool {
    matches!(m, Message::SequencePaxos(p) if p.to == to && matches!(p.msg, PaxosMsg::Decide(_)))
}

fn entry_status(e: Option<LogEntry<Value>>) -> &'static str {
    match e {
        Some(LogEntry::Decided(_)) => "decided",
        Some(LogEntry::Undecided(_)) => "undecided",
        Some(LogEntry::Trimmed(_)) => "trimmed",
        Some(LogEntry::Snapshotted(_)) => "snapshotted",
        Some(LogEntry::StopSign(_, _)) => "stopsign",
        None => "none",
    }
}

fn emit(line: String) {
    println!("CA_EVENT {}", line);
}

fn run_probe() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);

    // Node 1 becomes leader with all five nodes connected.
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);

    // Entries 1..=4 are decided everywhere.
    for i in 1..=4u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }

    // Entry 5: accept on 2, 3 and 5 (not 4); the leader decides with 1,2,3,5;
    // only node 5 receives the Decide, so 2 and 3 accept 5 but stay decided=4.
    nodes[0].append(Value(5)).expect("append 5 failed");
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |m| !is_acceptdecide_to(m, 4));
    purge(&mut q, |m| is_acceptdecide_to(m, 4));
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |m| {
        !is_decide_to(m, 2) && !is_decide_to(m, 3) && !is_decide_to(m, 4)
    });

    let before_decided = nodes[4].get_decided_idx();
    let before_status = entry_status(nodes[4].read(4));
    emit(format!(
        "{{\"run\":1,\"event\":\"ready\",\"phase\":\"before\",\"node\":5,\"decided\":{},\"entry_status\":\"{}\",\"decided_leader1\":{},\"decided_node2\":{},\"accepted_node2\":{}}}",
        before_decided,
        before_status,
        nodes[0].get_decided_idx(),
        nodes[1].get_decided_idx(),
        nodes[1].get_accepted_idx()
    ));

    // Cut node 1 permanently; node 2 becomes leader with promises from 3 and 4.
    let touches_1 = |m: &Message<Value>| m.get_sender() == 1 || m.get_receiver() == 1;
    nodes[1].try_become_leader();
    collect(&mut nodes, &mut q);
    purge(&mut q, touches_1);
    let held = extract(&mut q, |m| m.get_receiver() == 5);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    // Node 2 is now in Accept with promises from 3 and 4; its AcceptSync to
    // those two is delivered, but their Accepted(5) replies are held back.
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let held_acks = extract(&mut q, |m| {
        matches!(m, Message::SequencePaxos(p) if (p.from == 3 || p.from == 4) && matches!(p.msg, PaxosMsg::Accepted(_)))
    });

    // Deliver the delayed Prepare to node 5 and let it promise in Accept phase.
    for m in held {
        let to = m.get_receiver() as usize;
        nodes[to - 1].handle_incoming(m);
    }
    collect(&mut nodes, &mut q);
    let promises = extract(&mut q, |m| {
        matches!(m, Message::SequencePaxos(p) if p.from == 5 && matches!(p.msg, PaxosMsg::Promise(_)))
    });
    let promise_seen = !promises.is_empty();
    for m in promises {
        nodes[1].handle_incoming(m);
    }
    collect(&mut nodes, &mut q);
    let syncs = extract(&mut q, |m| {
        matches!(m, Message::SequencePaxos(p) if p.to == 5 && matches!(p.msg, PaxosMsg::AcceptSync(_)))
    });
    let acceptsync_seen = !syncs.is_empty();
    for m in syncs {
        nodes[4].handle_incoming(m);
    }
    collect(&mut nodes, &mut q);
    let n5_accepted_reply = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.from == 5 && matches!(p.msg, PaxosMsg::Accepted(_)))
    });

    let after_decided = nodes[4].get_decided_idx();
    let after_status = entry_status(nodes[4].read(4));
    let n5_leader = nodes[4].get_current_leader();
    let n5_promise = nodes[4].get_promise();
    let n2_leader = nodes[1].get_current_leader();
    emit(format!(
        "{{\"run\":1,\"event\":\"late_sync\",\"phase\":\"after_sync\",\"node\":5,\"decided\":{},\"decided_before\":{},\"entry_status\":\"{}\",\"decided_leader2\":{},\"regressed\":{},\"n5_leader_pid\":{},\"n5_accept\":{},\"n5_promise_n\":{},\"n5_promise_pid\":{},\"n2_accept\":{},\"promise_seen\":{},\"acceptsync_seen\":{},\"n5_accepted_reply\":{}}}",
        after_decided,
        before_decided,
        after_status,
        nodes[1].get_decided_idx(),
        after_decided < before_decided,
        n5_leader.map(|(p, _)| p).unwrap_or(0),
        n5_leader.map(|(_, a)| a).unwrap_or(false),
        n5_promise.n,
        n5_promise.pid,
        n2_leader.map(|(_, a)| a).unwrap_or(false),
        promise_seen,
        acceptsync_seen,
        n5_accepted_reply
    ));

    // Deliver the held Accepted(5) replies so the new leader re-decides index 5.
    for m in held_acks {
        let to = m.get_receiver() as usize;
        nodes[to - 1].handle_incoming(m);
    }
    settle_cut1(&mut nodes, &mut q);

    emit(format!(
        "{{\"run\":1,\"event\":\"late_sync\",\"phase\":\"after_redecide\",\"node\":5,\"decided\":{},\"entry_status\":\"{}\",\"decided_leader2\":{}}}",
        nodes[4].get_decided_idx(),
        entry_status(nodes[4].read(4)),
        nodes[1].get_decided_idx()
    ));
}

#[test]
fn late_promise_sync_regresses_decided() {
    run_probe();
}

// ---------------------------------------------------------------------------
// Variant: the new leader's Prepare to node 5 is lost (never delivered). Node 5
// keeps following the cut leader, then the documented `reconnected` path sends
// a PrepareReq to the new leader, whose Accept-phase reply is an AcceptSync
// stamped with its lower decided index.
// ---------------------------------------------------------------------------

#[test]
fn lost_prepare_reconnect_regresses_decided() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);
    for i in 1..=4u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }

    nodes[0].append(Value(5)).expect("append 5 failed");
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |m| !is_acceptdecide_to(m, 4));
    purge(&mut q, |m| is_acceptdecide_to(m, 4));
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |m| {
        !is_decide_to(m, 2) && !is_decide_to(m, 3) && !is_decide_to(m, 4)
    });

    let before_decided = nodes[4].get_decided_idx();
    let before_status = entry_status(nodes[4].read(4));
    emit(format!(
        "{{\"run\":2,\"event\":\"ready\",\"phase\":\"before\",\"node\":5,\"decided\":{},\"entry_status\":\"{}\",\"decided_node2\":{},\"accepted_node2\":{}}}",
        before_decided,
        before_status,
        nodes[1].get_decided_idx(),
        nodes[1].get_accepted_idx()
    ));

    // Cut node 1, elect node 2, and lose the Prepare addressed to node 5.
    nodes[1].try_become_leader();
    collect(&mut nodes, &mut q);
    purge(&mut q, |m| m.get_sender() == 1 || m.get_receiver() == 1);
    let lost_prepare = extract(&mut q, |m| m.get_receiver() == 5);
    let lost_prepare_count = lost_prepare.len();
    drop(lost_prepare);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let held_acks = extract(&mut q, |m| {
        matches!(m, Message::SequencePaxos(p) if (p.from == 3 || p.from == 4) && matches!(p.msg, PaxosMsg::Accepted(_)))
    });

    // Node 5 still follows the cut leader; the user reports the new connection.
    nodes[4].reconnected(2);
    collect(&mut nodes, &mut q);
    let preparereq_seen = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.to == 2 && matches!(p.msg, PaxosMsg::PrepareReq(_)))
    });
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let prepare_seen = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.to == 5 && matches!(p.msg, PaxosMsg::Prepare(_)))
    });
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let promise_seen = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.from == 5 && matches!(p.msg, PaxosMsg::Promise(_)))
    });
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let acceptsync_seen = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.to == 5 && matches!(p.msg, PaxosMsg::AcceptSync(_)))
    });
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    let n5_accepted_reply = q.iter().any(|m| {
        matches!(m, Message::SequencePaxos(p) if p.from == 5 && matches!(p.msg, PaxosMsg::Accepted(_)))
    });

    let after_decided = nodes[4].get_decided_idx();
    let n5_leader = nodes[4].get_current_leader();
    emit(format!(
        "{{\"run\":2,\"event\":\"late_sync\",\"phase\":\"after_sync\",\"node\":5,\"decided\":{},\"decided_before\":{},\"entry_status\":\"{}\",\"decided_leader2\":{},\"regressed\":{},\"n5_accept\":{},\"n2_accept\":{},\"lost_prepare_count\":{},\"preparereq_seen\":{},\"prepare_seen\":{},\"promise_seen\":{},\"acceptsync_seen\":{},\"n5_accepted_reply\":{}}}",
        after_decided,
        before_decided,
        entry_status(nodes[4].read(4)),
        nodes[1].get_decided_idx(),
        after_decided < before_decided,
        n5_leader.map(|(_, a)| a).unwrap_or(false),
        nodes[1].get_current_leader().map(|(_, a)| a).unwrap_or(false),
        lost_prepare_count,
        preparereq_seen,
        prepare_seen,
        promise_seen,
        acceptsync_seen,
        n5_accepted_reply
    ));
    for m in held_acks {
        let to = m.get_receiver() as usize;
        nodes[to - 1].handle_incoming(m);
    }
    settle_cut1(&mut nodes, &mut q);
    emit(format!(
        "{{\"run\":2,\"event\":\"late_sync\",\"phase\":\"after_redecide\",\"node\":5,\"decided\":{},\"entry_status\":\"{}\",\"decided_leader2\":{}}}",
        nodes[4].get_decided_idx(),
        entry_status(nodes[4].read(4)),
        nodes[1].get_decided_idx()
    ));
}
