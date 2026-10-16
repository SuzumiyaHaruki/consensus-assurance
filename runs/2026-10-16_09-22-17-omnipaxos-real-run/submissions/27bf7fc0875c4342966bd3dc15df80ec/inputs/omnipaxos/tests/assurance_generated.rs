//! Generated assurance harness (audit draft).
//!
//! Question: after a replica has accepted a StopSign, does re-synchronizing it with the leader
//! preserve the observable "reconfiguration decided" endpoint and the consistency between the
//! reported accepted index and the actual log content?
//!
//! Two cases share one execution:
//!  * `case = "resync"`: both followers report a re-established connection to the leader.
//!  * `case = "control"`: identical prefix, no reconnect.
//!
//! The protocol is driven by hand (no Kompact, no wall-clock waits): a deterministic FIFO network
//! queue in one process, BLE messages dropped, leadership obtained via `try_become_leader`.
use omnipaxos::{
    messages::Message,
    storage::{Entry, NoSnapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
use std::collections::VecDeque;

#[derive(Clone, Debug, PartialEq)]
pub struct Value(pub u64);

impl Entry for Value {
    type Snapshot = NoSnapshot;
}

type Op = OmniPaxos<Value, MemoryStorage<Value>>;

const NUM_ENTRIES: usize = 5;
const STOPSIGN_IDX: usize = NUM_ENTRIES; // 0-based index occupied by the StopSign of 5 entries

fn cluster_nodes() -> Vec<NodeId> {
    vec![1, 2, 3]
}

fn build_node(pid: NodeId) -> Op {
    let config = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: cluster_nodes(),
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid,
            ..Default::default()
        },
    };
    config
        .build(MemoryStorage::default())
        .expect("node should build from a valid config")
}

struct Cluster {
    nodes: Vec<Op>,
    queue: VecDeque<Message<Value>>,
    delivered: usize,
    dropped_ble: usize,
}

impl Cluster {
    fn new() -> Self {
        Self {
            // index pid-1 for pid in 1..=3
            nodes: cluster_nodes().into_iter().map(build_node).collect(),
            queue: VecDeque::new(),
            delivered: 0,
            dropped_ble: 0,
        }
    }

    fn node(&mut self, pid: NodeId) -> &mut Op {
        &mut self.nodes[(pid - 1) as usize]
    }

    fn collect_outgoing(&mut self) {
        let mut buf: Vec<Message<Value>> = Vec::new();
        for n in self.nodes.iter_mut() {
            n.take_outgoing_messages(&mut buf);
        }
        for m in buf {
            match m {
                Message::BLE(_) => self.dropped_ble += 1,
                other => self.queue.push_back(other),
            }
        }
    }

    /// Deliver queued messages in FIFO order until the queue drains.
    fn pump(&mut self, max_steps: usize) {
        let mut steps = 0usize;
        loop {
            self.collect_outgoing();
            match self.queue.pop_front() {
                None => break,
                Some(m) => {
                    let to = m.get_receiver();
                    if let Some(n) = self.nodes.get_mut((to - 1) as usize) {
                        n.handle_incoming(m);
                        self.delivered += 1;
                    }
                }
            }
            steps += 1;
            if steps >= max_steps {
                println!(
                    "CA_EVENT {{\"event\":\"PUMP_CAP_HIT\",\"steps\":{}}}",
                    steps
                );
                break;
            }
        }
    }
}

/// Emits one distinct event name per lifecycle stage so that a result event is admitted by an
/// earlier, separately named event.
fn emit_sample(c: &mut Cluster, case: &str, event: &str, pids: &[NodeId]) {
    for pid in pids {
        let n = c.node(*pid);
        let accepted_idx = n.get_accepted_idx();
        let decided_idx = n.get_decided_idx();
        let reconfig = n.is_reconfigured().is_some();
        let (read5, ss_decided) = match n.read(STOPSIGN_IDX) {
            Some(LogEntry::StopSign(_, decided)) => ("stop_sign", decided),
            Some(LogEntry::Decided(_)) => ("decided_entry", false),
            Some(LogEntry::Undecided(_)) => ("undecided_entry", false),
            Some(LogEntry::Trimmed(_)) => ("trimmed", false),
            Some(LogEntry::Snapshotted(_)) => ("snapshotted", false),
            None => ("none", false),
        };
        let (suffix_read_state, suffix_entries) = match n.read_decided_suffix(0) {
            None => ("none", -1i64),
            Some(v) => ("ok", v.len() as i64),
        };
        println!(
            "CA_EVENT {{\"event\":\"{}\",\"case\":\"{}\",\"node\":{},\
\"accepted_idx\":{},\"decided_idx\":{},\"decided_eq_accepted\":{},\"is_reconfigured\":{},\
\"read_idx5\":\"{}\",\"stopsign_entry_decided\":{},\"suffix_read_state\":\"{}\",\
\"suffix_entries\":{}}}",
            event,
            case,
            pid,
            accepted_idx,
            decided_idx,
            decided_idx == accepted_idx,
            reconfig,
            read5,
            ss_decided,
            suffix_read_state,
            suffix_entries
        );
    }
}

/// Shared prefix: node 3 leads, five entries are decided, then a StopSign is decided.
fn run_prefix(case: &str) -> Cluster {
    let tag = if case == "resync" { "RESYNC" } else { "CONTROL" };
    let mut c = Cluster::new();
    c.node(3).try_become_leader();
    c.pump(2_000);
    emit_sample(&mut c, case, &format!("{}_LEADER_ELECTED", tag), &[1, 2, 3]);

    for i in 0..NUM_ENTRIES as u64 {
        c.node(3)
            .append(Value(i))
            .expect("leader in accept phase accepts appends");
    }
    c.pump(4_000);
    emit_sample(&mut c, case, &format!("{}_ENTRIES_DECIDED", tag), &[1, 2, 3]);

    let next_config = ClusterConfig {
        configuration_id: 2,
        nodes: cluster_nodes(),
        flexible_quorum: None,
    };
    c.node(3)
        .reconfigure(next_config, None)
        .expect("leader accepts a reconfiguration proposal");
    c.pump(4_000);
    emit_sample(&mut c, case, &format!("{}_STOPSIGN_DECIDED", tag), &[1, 2, 3]);
    c
}

#[test]
fn stopsign_resync_inflates_accepted_index() {
    let case = "resync";
    let mut c = run_prefix(case);

    // Both followers signal that their connection to the leader has been re-established.
    c.node(1).reconnected(3);
    c.node(2).reconnected(3);
    c.pump(4_000);
    emit_sample(&mut c, case, "RESYNC_AFTER", &[1, 2, 3]);

    println!(
        "CA_EVENT {{\"event\":\"RUN_END\",\"case\":\"{}\",\"delivered\":{},\"dropped_ble\":{}}}",
        case, c.delivered, c.dropped_ble
    );
}

#[test]
fn stopsign_no_resync_control() {
    let case = "control";
    let mut c = run_prefix(case);
    // No reconnect: the leader is simply given more opportunities to make progress.
    c.pump(4_000);
    emit_sample(&mut c, case, "CONTROL_AFTER", &[1, 2, 3]);

    println!(
        "CA_EVENT {{\"event\":\"RUN_END\",\"case\":\"{}\",\"delivered\":{},\"dropped_ble\":{}}}",
        case, c.delivered, c.dropped_ble
    );
}
