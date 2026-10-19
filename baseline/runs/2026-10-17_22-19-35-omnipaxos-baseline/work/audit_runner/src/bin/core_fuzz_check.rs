use std::collections::HashMap;

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.0
    }

    fn chance(&mut self, numerator: u64, denominator: u64) -> bool {
        self.next() % denominator < numerator
    }
}

fn build(pid: NodeId, nodes: &[NodeId]) -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: nodes.to_vec(),
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid,
            election_tick_timeout: 2,
            resend_message_tick_timeout: 3,
            flush_batch_tick_timeout: 2,
            batch_size: 3,
            buffer_size: 1024,
            ..Default::default()
        },
    }
    .build(MemoryStorage::default())
    .unwrap()
}

fn main() {
    let nodes: Vec<NodeId> = vec![1, 2, 3, 4, 5];
    let mut ops: HashMap<NodeId, _> = nodes
        .iter()
        .map(|&pid| (pid, build(pid, &nodes)))
        .collect();
    let mut rng = Lcg(0x5eed_cafe_f00d_1234);
    let mut links_up = [[true; 5]; 5];
    let mut in_flight = Vec::new();
    let mut history: HashMap<usize, u64> = HashMap::new();
    let mut next_value = 1u64;

    for step in 0..4000 {
        // Frequently create short-lived asymmetric partitions, then heal most links.
        for from in 0..5 {
            for to in 0..5 {
                if from != to && rng.chance(1, 40) {
                    links_up[from][to] = false;
                } else if rng.chance(1, 5) {
                    links_up[from][to] = true;
                }
            }
        }

        for op in ops.values_mut() {
            op.tick();
        }

        if step >= 20 && step % 3 == 0 {
            for _ in 0..2 {
                let idx = (rng.next() as usize) % nodes.len();
                let pid = nodes[idx];
                let value = next_value;
                next_value += 1;
                let _ = ops.get_mut(&pid).unwrap().append(TestEntry(value));
            }
        }

        for op in ops.values_mut() {
            op.take_outgoing_messages(&mut in_flight);
        }
        for i in (1..in_flight.len()).rev() {
            let j = (rng.next() as usize) % (i + 1);
            in_flight.swap(i, j);
        }

        let mut undelivered = Vec::new();
        for msg in in_flight.drain(..) {
            let from = msg.get_sender();
            let to = msg.get_receiver();
            let from_idx = (from - 1) as usize;
            let to_idx = (to - 1) as usize;
            if links_up[from_idx][to_idx] {
                if let Some(op) = ops.get_mut(&to) {
                    op.handle_incoming(msg.clone());
                }
                if rng.chance(1, 20) {
                    if let Some(op) = ops.get_mut(&to) {
                        op.handle_incoming(msg);
                    }
                }
            } else if rng.chance(4, 5) {
                // Most messages blocked by a partition are delayed until a later
                // round; some are lost.
                undelivered.push(msg);
            }
        }
        in_flight = undelivered;
        if in_flight.len() > 5000 {
            in_flight.drain(..in_flight.len() - 5000);
        }

        if step % 10 == 0 {
            for (&pid, op) in &ops {
                for idx in 0..op.get_decided_idx() {
                    if let Some(LogEntry::Decided(TestEntry(value))) = op.read(idx) {
                        if let Some(previous) = history.insert(idx, value) {
                            assert_eq!(
                                previous, value,
                                "decided-index conflict at step {step}, idx {idx}: \
                                 previously {previous}, pid {pid} now {value}"
                            );
                        }
                    }
                }
            }
        }
    }

    // Heal all links and quiesce. This is a safety check, not a liveness
    // assertion: every decided index observed at any time must retain one value.
    for _ in 0..1000 {
        for op in ops.values_mut() {
            op.tick();
        }
        for op in ops.values_mut() {
            op.take_outgoing_messages(&mut in_flight);
        }
        for msg in in_flight.drain(..) {
            if let Some(op) = ops.get_mut(&msg.get_receiver()) {
                op.handle_incoming(msg);
            }
        }
    }
    for (&pid, op) in &ops {
        for idx in 0..op.get_decided_idx() {
            if let Some(LogEntry::Decided(TestEntry(value))) = op.read(idx) {
                if let Some(previous) = history.insert(idx, value) {
                    assert_eq!(
                        previous, value,
                        "decided-index conflict after healing at idx {idx}: \
                         previously {previous}, pid {pid} now {value}"
                    );
                }
            }
        }
    }

    let decided: Vec<_> = nodes
        .iter()
        .map(|pid| (*pid, ops[pid].get_decided_idx()))
        .collect();
    println!(
        "PASS: {} unique proposals; no decided-index conflict; per-node decided indexes: {decided:?}",
        next_value - 1
    );
}
