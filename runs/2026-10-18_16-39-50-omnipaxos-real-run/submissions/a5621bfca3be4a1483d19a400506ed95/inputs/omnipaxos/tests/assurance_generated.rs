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
            let to = m.get_receiver();
            let slot = nodes
                .iter()
                .position(|n| n.get_pid() == to)
                .expect("message addressed to a pid not in the probe");
            nodes[slot].handle_incoming(m);
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

// ---------------------------------------------------------------------------
// Sparse-pid variant: ClusterConfig nodes {1,2,5} leaves placeholder slots for
// pids 3 and 4 in LeaderState, whose accepted indexes stay 0. Probe whether the
// leader's automatic trim sees the true minimum accepted index.
// ---------------------------------------------------------------------------

fn build_node_sparse(pid: u64) -> Node {
    let cluster = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2, 5],
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
    .expect("sparse node build failed")
}

#[test]
fn sparse_pids_block_automatic_trim() {
    let mut nodes: Vec<Node> = vec![build_node_sparse(1), build_node_sparse(2), build_node_sparse(5)];
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);
    for i in 1..=3u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }
    let decided = nodes[0].get_decided_idx();
    let all_accepted_min = nodes
        .iter()
        .map(|n| n.get_accepted_idx())
        .min()
        .unwrap_or(0);
    emit(format!(
        "{{\"run\":3,\"event\":\"setup\",\"nodes\":3,\"pids\":\"1,2,5\",\"decided\":{},\"all_accepted_min\":{}}}",
        decided, all_accepted_min
    ));

    let requested = 2usize;
    let (trim_ok, err_min) = match nodes[0].trim(Some(requested)) {
        Ok(()) => (true, 0usize),
        Err(omnipaxos::CompactionErr::NotAllDecided(m)) => (false, m),
        Err(_) => (false, usize::MAX),
    };
    let compacted_after_some = nodes[0].get_compacted_idx();
    let none_res = nodes[0].trim(None);
    let compacted_after_none = nodes[0].get_compacted_idx();
    emit(format!(
        "{{\"run\":3,\"event\":\"trim_result\",\"requested\":{},\"all_accepted_min\":{},\"trim_ok\":{},\"error_min\":{},\"compacted_after_some\":{},\"none_ok\":{},\"compacted_after_none\":{},\"decided\":{}}}",
        requested,
        all_accepted_min,
        trim_ok,
        err_min,
        compacted_after_some,
        none_res.is_ok(),
        compacted_after_none,
        decided
    ));
}

// ---------------------------------------------------------------------------
// Fan-out variant: two subscribers with different cursors over a trimmed log.
// Reproduces actor.rs push_to_all_subs: min_next = trailing cursor, one read
// from min_next, start = sub.next_idx - min_next, one cursor step per element.
// ---------------------------------------------------------------------------

fn value_token(e: &LogEntry<Value>) -> String {
    match e {
        LogEntry::Decided(Value(v)) => v.to_string(),
        LogEntry::Undecided(Value(v)) => format!("u{}", v),
        LogEntry::Trimmed(t) => format!("T{}", t),
        _ => "?".to_string(),
    }
}

#[test]
fn fanout_skips_entries_for_fast_subscriber_with_lagging_peer() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);
    for i in 1..=10u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }
    nodes[0].trim(Some(5)).expect("trim failed");
    settle(&mut nodes, &mut q);
    let decided = nodes[0].get_decided_idx();
    let compacted = nodes[0].get_compacted_idx();
    emit(format!(
        "{{\"run\":4,\"event\":\"setup\",\"decided\":{},\"compacted\":{},\"slow_cursor\":1,\"fast_cursor\":6}}",
        decided, compacted
    ));

    let mut slow = 1usize;
    let mut fast = 6usize;
    let mut fast_stream: Vec<String> = Vec::new();
    let mut slow_stream: Vec<String> = Vec::new();
    for _ in 0..3 {
        let min_next = slow.min(fast);
        if min_next >= decided {
            break;
        }
        let Some(entries) = nodes[0].read_decided_suffix(min_next) else {
            break;
        };
        for (which, cursor) in [("slow", &mut slow), ("fast", &mut fast)] {
            let start = cursor.saturating_sub(min_next);
            for e in entries.iter().skip(start) {
                let tok = value_token(e);
                if which == "slow" {
                    slow_stream.push(tok);
                } else {
                    fast_stream.push(tok);
                }
                *cursor += 1;
            }
        }
    }
    emit(format!(
        "{{\"run\":4,\"event\":\"fanout\",\"slow_stream\":\"{}\",\"fast_stream\":\"{}\",\"fast_cursor_after\":{},\"slow_cursor_after\":{}}}",
        slow_stream.join(","),
        fast_stream.join(","),
        fast,
        slow
    ));
}

// ---------------------------------------------------------------------------
// Authority-transition variant: entry 5 is a StopSign decided only on node 5.
// The reconnect path then lowers node 5's decided index while the StopSign
// stays accepted, so is_reconfigured() flips Some -> None -> Some.
// ---------------------------------------------------------------------------

#[test]
fn decided_stopsign_flips_through_reconnect_sync() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);
    for i in 1..=4u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }
    let next = ClusterConfig {
        configuration_id: 2,
        nodes: vec![1, 2, 3, 4, 5],
        flexible_quorum: None,
    };
    nodes[0]
        .reconfigure(next, None)
        .expect("reconfigure failed");
    collect(&mut nodes, &mut q);
    // Deliver the StopSign to 2, 3 and 5 only (drop the one for 4).
    route(&mut nodes, &mut q, |m| {
        !matches!(m, Message::SequencePaxos(p) if p.to == 4 && matches!(p.msg, PaxosMsg::AcceptStopSign(_)))
    });
    purge(&mut q, |m| {
        matches!(m, Message::SequencePaxos(p) if p.to == 4 && matches!(p.msg, PaxosMsg::AcceptStopSign(_)))
    });
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    // Deliver the leader's decision to node 5 only.
    route(&mut nodes, &mut q, |m| {
        !is_decide_to(m, 2) && !is_decide_to(m, 3) && !is_decide_to(m, 4)
    });

    emit(format!(
        "{{\"run\":5,\"event\":\"ready\",\"phase\":\"before\",\"node\":5,\"decided\":{},\"accepted\":{},\"reconfig\":{},\"decided_node2\":{},\"accepted_node2\":{}}}",
        nodes[4].get_decided_idx(),
        nodes[4].get_accepted_idx(),
        nodes[4].is_reconfigured().is_some(),
        nodes[1].get_decided_idx(),
        nodes[1].get_accepted_idx()
    ));

    // Cut node 1; node 2 elected by 3 and 4; node 5 misses the Prepare and
    // reconnects through the public API.
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
    nodes[4].reconnected(2);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);
    collect(&mut nodes, &mut q);
    route(&mut nodes, &mut q, |_| true);

    let decided_after = nodes[4].get_decided_idx();
    let reconfig_after = nodes[4].is_reconfigured().is_some();
    emit(format!(
        "{{\"run\":5,\"event\":\"late_sync\",\"phase\":\"after_sync\",\"node\":5,\"decided\":{},\"accepted\":{},\"decided_before\":5,\"reconfig\":{},\"decided_leader2\":{},\"lost_prepare_count\":{}}}",
        decided_after,
        nodes[4].get_accepted_idx(),
        reconfig_after,
        nodes[1].get_decided_idx(),
        lost_prepare_count
    ));

    for m in held_acks {
        let to = m.get_receiver();
        let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
        nodes[slot].handle_incoming(m);
    }
    settle_cut1(&mut nodes, &mut q);
    emit(format!(
        "{{\"run\":5,\"event\":\"late_sync\",\"phase\":\"after_redecide\",\"node\":5,\"decided\":{},\"accepted\":{},\"reconfig\":{},\"decided_leader2\":{}}}",
        nodes[4].get_decided_idx(),
        nodes[4].get_accepted_idx(),
        nodes[4].is_reconfigured().is_some(),
        nodes[1].get_decided_idx()
    ));
    emit(format!(
        "{{\"run\":5,\"event\":\"control\",\"node\":4,\"decided\":{},\"accepted\":{},\"reconfig\":{}}}",
        nodes[3].get_decided_idx(),
        nodes[3].get_accepted_idx(),
        nodes[3].is_reconfigured().is_some()
    ));
}

// ---------------------------------------------------------------------------
// Seeded safety stress: five real instances, random appends, ticks, message
// delivery and message loss. After every action the decided prefixes of all
// pairs are compared; agreement must hold at every index decided on both.
// ---------------------------------------------------------------------------

fn decided_values(n: &Node) -> Vec<u64> {
    match n.read_decided_suffix(0) {
        Some(entries) => entries
            .iter()
            .filter_map(|e| match e {
                LogEntry::Decided(Value(v)) => Some(*v),
                _ => None,
            })
            .collect(),
        None => Vec::new(),
    }
}

#[test]
fn randomized_lossy_agreement() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0x9e3779b97f4a7c15;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":6,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();

    for _ in 0..900 {
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            nodes[slot].append(Value(appended)).expect("append failed");
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 12 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..40 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    emit(format!(
        "{{\"run\":6,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}

#[test]
fn randomized_lossy_agreement_seed2() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0x243f6a8885a308d3;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":7,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();

    for _ in 0..900 {
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            nodes[slot].append(Value(appended)).expect("append failed");
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 12 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..40 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    emit(format!(
        "{{\"run\":7,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}


#[test]
fn randomized_lossy_agreement_seed3_highloss() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0x13198a2e03707344;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":8,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();

    for _ in 0..900 {
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            nodes[slot].append(Value(appended)).expect("append failed");
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 30 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..40 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    emit(format!(
        "{{\"run\":8,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}



#[test]
fn randomized_lossy_decided_monotonicity() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0x452821e638d01377;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":9,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();
    let mut max_decided = vec![0usize; 5];
    let mut regressions = 0u64;
    let mut first_regression = String::new();

    for _ in 0..900 {
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            nodes[slot].append(Value(appended)).expect("append failed");
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 20 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
        for (slot, n) in nodes.iter().enumerate() {
            let d = n.get_decided_idx();
            if d < max_decided[slot] {
                regressions += 1;
                if first_regression.is_empty() {
                    first_regression =
                        format!("node {}: {} -> {}", slot + 1, max_decided[slot], d);
                }
            } else {
                max_decided[slot] = d;
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..40 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    emit(format!(
        "{{\"run\":9,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"regressions\":{},\"first_regression\":\"{}\",\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        regressions,
        first_regression,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}




#[test]
fn randomized_reconfig_agreement() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0xbe5466cf34e90c6c;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":10,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();
    let mut max_decided = vec![0usize; 5];
    let mut regressions = 0u64;
    let mut first_regression = String::new();

    let mut reconfigured_once = false;
    for step in 0..900 {
        if step == 450 && !reconfigured_once {
            reconfigured_once = true;
            let next_config = ClusterConfig {
                configuration_id: 2,
                nodes: vec![1, 2, 3, 4, 5],
                flexible_quorum: None,
            };
            let _ = nodes[0].reconfigure(next_config, None);
        }
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            if nodes[slot].append(Value(appended)).is_err() {
                appended -= 1;
            }
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 20 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
        for (slot, n) in nodes.iter().enumerate() {
            let d = n.get_decided_idx();
            if d < max_decided[slot] {
                regressions += 1;
                if first_regression.is_empty() {
                    first_regression =
                        format!("node {}: {} -> {}", slot + 1, max_decided[slot], d);
                }
            } else {
                max_decided[slot] = d;
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..40 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    let reconfigured = nodes.iter().any(|n| n.is_reconfigured().is_some());
    emit(format!(
        "{{\"run\":10,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"regressions\":{},\"first_regression\":\"{}\",\"reconfigured\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        regressions,
        first_regression,
        reconfigured,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}





#[test]
fn randomized_reconfig_converges() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0xbe5466cf34e90c6c;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":11,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();
    let mut max_decided = vec![0usize; 5];
    let mut regressions = 0u64;
    let mut first_regression = String::new();

    let mut reconfigured_once = false;
    for step in 0..900 {
        if step == 450 && !reconfigured_once {
            reconfigured_once = true;
            let next_config = ClusterConfig {
                configuration_id: 2,
                nodes: vec![1, 2, 3, 4, 5],
                flexible_quorum: None,
            };
            let _ = nodes[0].reconfigure(next_config, None);
        }
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            if nodes[slot].append(Value(appended)).is_err() {
                appended -= 1;
            }
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 20 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
        for (slot, n) in nodes.iter().enumerate() {
            let d = n.get_decided_idx();
            if d < max_decided[slot] {
                regressions += 1;
                if first_regression.is_empty() {
                    first_regression =
                        format!("node {}: {} -> {}", slot + 1, max_decided[slot], d);
                }
            } else {
                max_decided[slot] = d;
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..150 {
        collect(&mut nodes, &mut q);
        if q.is_empty() && nodes.iter().any(|n| n.get_decided_idx() > 0) {
            break;
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    let reconfigured = nodes.iter().any(|n| n.is_reconfigured().is_some());
    emit(format!(
        "{{\"run\":11,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"regressions\":{},\"first_regression\":\"{}\",\"reconfigured\":{},\"converged_all\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        regressions,
        first_regression,
        reconfigured,
        {
            let d: Vec<usize> = nodes.iter().map(|n| n.get_decided_idx()).collect();
            d.iter().all(|x| *x == d[0])
        },
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}






#[test]
fn randomized_reconfig_converges_fully() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0xbe5466cf34e90c6c;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":12,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();
    let mut max_decided = vec![0usize; 5];
    let mut regressions = 0u64;
    let mut first_regression = String::new();

    let mut reconfigured_once = false;
    for step in 0..900 {
        if step == 450 && !reconfigured_once {
            reconfigured_once = true;
            let next_config = ClusterConfig {
                configuration_id: 2,
                nodes: vec![1, 2, 3, 4, 5],
                flexible_quorum: None,
            };
            let _ = nodes[0].reconfigure(next_config, None);
        }
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            if nodes[slot].append(Value(appended)).is_err() {
                appended -= 1;
            }
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 20 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
        for (slot, n) in nodes.iter().enumerate() {
            let d = n.get_decided_idx();
            if d < max_decided[slot] {
                regressions += 1;
                if first_regression.is_empty() {
                    first_regression =
                        format!("node {}: {} -> {}", slot + 1, max_decided[slot], d);
                }
            } else {
                max_decided[slot] = d;
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    for _ in 0..150 {
        collect(&mut nodes, &mut q);
        {
            let d: Vec<usize> = nodes.iter().map(|n| n.get_decided_idx()).collect();
            if q.is_empty() && d[0] > 0 && d.iter().all(|x| *x == d[0]) {
                break;
            }
        }
        route(&mut nodes, &mut q, |_| true);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        route(&mut nodes, &mut q, |_| true);
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    let reconfigured = nodes.iter().any(|n| n.is_reconfigured().is_some());
    emit(format!(
        "{{\"run\":12,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"regressions\":{},\"first_regression\":\"{}\",\"reconfigured\":{},\"converged_all\":{},\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        regressions,
        first_regression,
        reconfigured,
        {
            let d: Vec<usize> = nodes.iter().map(|n| n.get_decided_idx()).collect();
            d.iter().all(|x| *x == d[0])
        },
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}







#[test]
fn randomized_reconfig_diagnose_lag() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    let mut state: u64 = 0xbe5466cf34e90c6c;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    emit("{\"run\":13,\"event\":\"setup_start\",\"nodes\":5,\"actions\":900}".to_string());
    let mut appended = 0u64;
    let mut delivered = 0u64;
    let mut dropped = 0u64;
    let mut divergences = 0u64;
    let mut first_divergence = String::new();
    let mut max_decided = vec![0usize; 5];
    let mut regressions = 0u64;
    let mut first_regression = String::new();
    let mut p4_promises: Vec<String> = Vec::new();
    let mut p4_acc_changes: Vec<String> = Vec::new();
    let mut p4_last_accepted = nodes[3].get_accepted_idx();

    let mut reconfigured_once = false;
    for step in 0..900 {
        if step == 450 && !reconfigured_once {
            reconfigured_once = true;
            let next_config = ClusterConfig {
                configuration_id: 2,
                nodes: vec![1, 2, 3, 4, 5],
                flexible_quorum: None,
            };
            let _ = nodes[0].reconfigure(next_config, None);
        }
        let choice = next() % 100;
        if choice < 25 && appended < 120 {
            appended += 1;
            let slot = (next() % 5) as usize;
            if nodes[slot].append(Value(appended)).is_err() {
                appended -= 1;
            }
        } else if choice < 45 {
            let slot = (next() % 5) as usize;
            nodes[slot].tick();
        } else if !q.is_empty() {
            let idx = (next() as usize) % q.len();
            let m = q.swap_remove(idx);
            if next() % 100 < 20 {
                dropped += 1;
            } else {
                let to = m.get_receiver();
                let slot = nodes.iter().position(|n| n.get_pid() == to).unwrap();
                if to == 4 && p4_promises.len() < 40 {
                    if let Some(tag) = promise_tag(&m) {
                        p4_promises.push(format!("{step}:{tag}"));
                    }
                }
                nodes[slot].handle_incoming(m);
                delivered += 1;
            }
        }
        collect(&mut nodes, &mut q);
        let a4 = nodes[3].get_accepted_idx();
        if a4 != p4_last_accepted && p4_acc_changes.len() < 20 {
            p4_acc_changes.push(format!("{step}:{}->{}", p4_last_accepted, a4));
            p4_last_accepted = a4;
        }
        if q.len() > 4000 {
            let excess = q.len() - 4000;
            q.drain(..excess);
        }
        let prefixes: Vec<Vec<u64>> = nodes.iter().map(decided_values).collect();
        for a in 0..prefixes.len() {
            for b in (a + 1)..prefixes.len() {
                let n = prefixes[a].len().min(prefixes[b].len());
                for i in 0..n {
                    if prefixes[a][i] != prefixes[b][i] {
                        divergences += 1;
                        if first_divergence.is_empty() {
                            first_divergence = format!(
                                "{}:{}={} vs {}:{}={}",
                                a + 1, i, prefixes[a][i], b + 1, i, prefixes[b][i]
                            );
                        }
                    }
                }
            }
        }
        for (slot, n) in nodes.iter().enumerate() {
            let d = n.get_decided_idx();
            if d < max_decided[slot] {
                regressions += 1;
                if first_regression.is_empty() {
                    first_regression =
                        format!("node {}: {} -> {}", slot + 1, max_decided[slot], d);
                }
            } else {
                max_decided[slot] = d;
            }
        }
    }

    // Fair-delivery convergence: deliver everything and tick every node so the
    // messy history can still reach decisions before the agreement check.
    let mut rounds_run = 0u32;
    let mut n3_accepted_changes = 0u32;
    let mut n3_last_accepted = nodes[2].get_accepted_idx();
    let mut n3_trace: Vec<String> = Vec::new();
    let mut n3_prepreq = 0u32;
    let mut n3_promise = 0u32;
    for _ in 0..150 {
        rounds_run += 1;
        collect(&mut nodes, &mut q);
        {
            let d: Vec<usize> = nodes.iter().map(|n| n.get_decided_idx()).collect();
            if q.is_empty() && d[0] > 0 && d.iter().all(|x| *x == d[0]) {
                break;
            }
        }
        for m in q.iter() {
            if m.get_sender() == 3 {
                match msg_tag(m).as_str() {
                    "prepreq" => n3_prepreq += 1,
                    "promise" => n3_promise += 1,
                    _ => {}
                }
            }
        }
        route_traced(&mut nodes, &mut q, &mut n3_trace, 3, 12);
        for n in nodes.iter_mut() {
            n.tick();
        }
        collect(&mut nodes, &mut q);
        for m in q.iter() {
            if m.get_sender() == 3 {
                match msg_tag(m).as_str() {
                    "prepreq" => n3_prepreq += 1,
                    "promise" => n3_promise += 1,
                    _ => {}
                }
            }
        }
        route_traced(&mut nodes, &mut q, &mut n3_trace, 3, 12);
        let a = nodes[2].get_accepted_idx();
        if a != n3_last_accepted {
            n3_accepted_changes += 1;
            n3_last_accepted = a;
        }
    }
    let progressed = nodes.iter().any(|n| n.get_decided_idx() > 0);
    let reconfigured = nodes.iter().any(|n| n.is_reconfigured().is_some());
    emit(format!(
        "{{\"run\":13,\"event\":\"safety\",\"appended\":{},\"delivered\":{},\"dropped\":{},\"divergences\":{},\"first_divergence\":\"{}\",\"progressed\":{},\"regressions\":{},\"first_regression\":\"{}\",\"reconfigured\":{},\"converged_all\":{},\"rounds_run\":{},\"n3_accepted\":{},\"n3_decided\":{},\"n3_leader_pid\":{},\"n3_accept\":{},\"n3_promise_n\":{},\"n3_accepted_changes\":{},\"n3_prepreq\":{},\"n3_promise_sent\":{},\"n3_trace\":\"{}\",\"p4_accepted\":{},\"p4_decided\":{},\"p4_promises\":\"{}\",\"p4_acc_changes\":\"{}\",\"decided\":\"{}\"}}",
        appended,
        delivered,
        dropped,
        divergences,
        first_divergence,
        progressed,
        regressions,
        first_regression,
        reconfigured,
        {
            let d: Vec<usize> = nodes.iter().map(|n| n.get_decided_idx()).collect();
            d.iter().all(|x| *x == d[0])
        },
        rounds_run,
        nodes[2].get_accepted_idx(),
        nodes[2].get_decided_idx(),
        nodes[2].get_current_leader().map(|(p, _)| p).unwrap_or(0),
        nodes[2].get_current_leader().map(|(_, a)| a).unwrap_or(false),
        nodes[2].get_promise().n,
        n3_accepted_changes,
        n3_prepreq,
        n3_promise,
        n3_trace.join("|"),
        nodes[3].get_accepted_idx(),
        nodes[3].get_decided_idx(),
        p4_promises.join("|"),
        p4_acc_changes.join("|"),
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}








// Minimal witness: node 5 misses the AcceptStopSign; the leader decides the
// StopSign and then only ever resends the Decide. Elections are effectively
// disabled (large election_tick_timeout) so no new Prepare can repair node 5.
// Both the missed AcceptStopSign and the leader's first Decide to node 5 are
// dropped, so the only later traffic to node 5 is the tick-driven resend,
// which reuses the AcceptStopSign's sequence number and is therefore accepted
// as the next expected message.
fn build_node_slow_election(pid: u64) -> Node {
    let cluster = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2, 3, 4, 5],
        flexible_quorum: None,
    };
    let server = ServerConfig {
        pid,
        election_tick_timeout: 1000,
        resend_message_tick_timeout: 100,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config: cluster,
        server_config: server,
    }
    .build(MemoryStorage::default())
    .expect("node build failed")
}

fn is_stopsign_to(m: &Message<Value>, to: u64) -> bool {
    matches!(m, Message::SequencePaxos(p) if p.to == to && matches!(p.msg, PaxosMsg::AcceptStopSign(_)))
}

/// Deliver everything that is not the StopSign or a Decide addressed to `cut`,
/// and discard those two message kinds instead of keeping them for later.
fn settle_without_stopsign_to(nodes: &mut [Node], q: &mut Vec<Message<Value>>, cut: u64) {
    for _ in 0..2000 {
        collect(nodes, q);
        purge(q, |m| is_stopsign_to(m, cut) || is_decide_to(m, cut));
        if q.is_empty() {
            return;
        }
        route(nodes, q, |_| true);
    }
    panic!("cut settlement did not quiesce");
}

fn decide_seq(m: &Message<Value>) -> Option<u64> {
    match m {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::Decide(d) => Some(d.seq_num.counter),
            _ => None,
        },
        _ => None,
    }
}

fn promise_tag(m: &Message<Value>) -> Option<String> {
    match m {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::Promise(prom) => Some(format!(
                "from{},n{},na{},aidx{},didx{},ss{}",
                p.from,
                prom.n.n,
                prom.n_accepted.n,
                prom.accepted_idx,
                prom.decided_idx,
                u8::from(
                    prom.log_sync
                        .as_ref()
                        .map(|l| l.stopsign.is_some())
                        .unwrap_or(false)
                )
            )),
            _ => None,
        },
        _ => None,
    }
}

fn msg_tag(m: &Message<Value>) -> String {
    match m {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::Prepare(_) => "prepare".to_string(),
            PaxosMsg::Promise(_) => "promise".to_string(),
            PaxosMsg::AcceptSync(a) => format!("accsync{}", a.seq_num.counter),
            PaxosMsg::AcceptDecide(a) => format!("accdec{}", a.seq_num.counter),
            PaxosMsg::Accepted(_) => "accepted".to_string(),
            PaxosMsg::NotAccepted(_) => "notaccepted".to_string(),
            PaxosMsg::Decide(d) => format!("decide{}", d.seq_num.counter),
            PaxosMsg::PrepareReq(_) => "prepreq".to_string(),
            PaxosMsg::AcceptStopSign(a) => format!("accss{}", a.seq_num.counter),
            PaxosMsg::ProposalForward(_) => "proposal".to_string(),
            PaxosMsg::Compaction(_) => "compaction".to_string(),
            PaxosMsg::ForwardStopSign(_) => "fwdss".to_string(),
        },
        _ => "other".to_string(),
    }
}

/// Deliver `traced`'s inbound messages one at a time, recording the message
/// kind, sequence counter and local (accepted, decided) pair around each one;
/// every other queued message is routed normally afterwards.
fn route_traced(
    nodes: &mut [Node],
    q: &mut Vec<Message<Value>>,
    trace: &mut Vec<String>,
    traced: u64,
    cap: usize,
) {
    let mut to_traced: Vec<Message<Value>> = Vec::new();
    let mut rest: Vec<Message<Value>> = Vec::new();
    for m in std::mem::take(q) {
        if m.get_receiver() == traced {
            to_traced.push(m);
        } else {
            rest.push(m);
        }
    }
    *q = rest;
    let slot = nodes
        .iter()
        .position(|n| n.get_pid() == traced)
        .expect("traced pid not in probe");
    for m in to_traced {
        let tag = msg_tag(&m);
        let is_paxos = tag != "other";
        let before = (nodes[slot].get_accepted_idx(), nodes[slot].get_decided_idx());
        nodes[slot].handle_incoming(m);
        let after = (nodes[slot].get_accepted_idx(), nodes[slot].get_decided_idx());
        if is_paxos && trace.len() < cap {
            trace.push(format!(
                "{tag}:{}-{}>{}-{}",
                before.0, before.1, after.0, after.1
            ));
        }
    }
    route(nodes, q, |_| true);
}

#[test]
fn decided_stopsign_only_decide_is_resent() {
    let mut nodes: Vec<Node> = (1..=5).map(build_node_slow_election).collect();
    let mut q: Vec<Message<Value>> = Vec::new();
    settle(&mut nodes, &mut q);
    nodes[0].try_become_leader();
    settle(&mut nodes, &mut q);
    for i in 1..=2u64 {
        nodes[0].append(Value(i)).expect("append failed");
        settle(&mut nodes, &mut q);
    }
    emit(format!(
        "{{\"run\":14,\"event\":\"ready\",\"n5_accepted\":{},\"n5_decided\":{},\"n5_accept\":{},\"n5_promise_n\":{},\"decided\":\"{}\"}}",
        nodes[4].get_accepted_idx(),
        nodes[4].get_decided_idx(),
        nodes[4].get_current_leader().map(|(_, a)| a).unwrap_or(false),
        nodes[4].get_promise().n,
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
    let next = ClusterConfig {
        configuration_id: 2,
        nodes: vec![1, 2, 3, 4, 5],
        flexible_quorum: None,
    };
    nodes[0].reconfigure(next, None).expect("reconfigure failed");
    collect(&mut nodes, &mut q);
    // Lose both the AcceptStopSign and the first Decide addressed to node 5.
    settle_without_stopsign_to(&mut nodes, &mut q, 5);
    let leader_decided = nodes[0].get_decided_idx();
    // Only ticks and delivery now; elections cannot fire (1000-tick timeout).
    let mut n5_decides = 0usize;
    let mut n5_decide_seq = 0u64;
    let mut n5_prepares = 0usize;
    let mut n5_accsyncs = 0usize;
    let mut n5_stopsigns = 0usize;
    let mut trace: Vec<String> = Vec::new();
    for _ in 0..150 {
        for n in nodes.iter_mut() {
            n.tick();
        }
        // Pump to quiescence, delivering node 5's messages one at a time so the
        // ordered trace records the sequence numbers and their local effect.
        for _ in 0..100 {
            collect(&mut nodes, &mut q);
            if q.is_empty() {
                break;
            }
            let mut to5: Vec<Message<Value>> = Vec::new();
            let mut rest: Vec<Message<Value>> = Vec::new();
            for m in std::mem::take(&mut q) {
                if m.get_receiver() == 5 {
                    to5.push(m);
                } else {
                    rest.push(m);
                }
            }
            q = rest;
            for m in to5 {
                let tag = msg_tag(&m);
                if tag.starts_with("decide") {
                    n5_decides += 1;
                    n5_decide_seq = decide_seq(&m).unwrap_or(0);
                } else if tag == "prepare" {
                    n5_prepares += 1;
                } else if tag.starts_with("accsync") {
                    n5_accsyncs += 1;
                } else if tag.starts_with("accss") {
                    n5_stopsigns += 1;
                }
                let is_paxos = tag != "other";
                let before = (nodes[4].get_accepted_idx(), nodes[4].get_decided_idx());
                nodes[4].handle_incoming(m);
                let after = (nodes[4].get_accepted_idx(), nodes[4].get_decided_idx());
                if is_paxos && trace.len() < 10 {
                    trace.push(format!(
                        "{tag}:{}-{}>{}-{}",
                        before.0, before.1, after.0, after.1
                    ));
                }
            }
            route(&mut nodes, &mut q, |_| true);
        }
    }
    let n5 = &nodes[4];
    let leader = n5.get_current_leader();
    emit(format!(
        "{{\"run\":14,\"event\":\"after_resend\",\"n5_accepted\":{},\"n5_decided\":{},\"n5_leader_pid\":{},\"n5_accept\":{},\"n5_promise_n\":{},\"leader_decided\":{},\"decision_gap\":{},\"n5_decides\":{},\"n5_decide_seq\":{},\"n5_prepares\":{},\"n5_accsyncs\":{},\"n5_stopsigns\":{},\"trace\":\"{}\",\"decided\":\"{}\"}}",
        n5.get_accepted_idx(),
        n5.get_decided_idx(),
        leader.map(|(p, _)| p).unwrap_or(0),
        leader.map(|(_, a)| a).unwrap_or(false),
        n5.get_promise().n,
        leader_decided,
        leader_decided.saturating_sub(n5.get_decided_idx()),
        n5_decides,
        n5_decide_seq,
        n5_prepares,
        n5_accsyncs,
        n5_stopsigns,
        trace.join("|"),
        nodes
            .iter()
            .map(|n| n.get_decided_idx().to_string())
            .collect::<Vec<_>>()
            .join(",")
    ));
}
