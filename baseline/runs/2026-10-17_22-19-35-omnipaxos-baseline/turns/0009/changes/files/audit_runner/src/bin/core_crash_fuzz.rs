use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use omnipaxos::{
    messages::Message,
    storage::{Entry, NoSnapshot, StopSign, Storage, StorageOp, StorageResult},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

#[derive(Clone)]
struct SharedStorage<T: Entry>(Arc<Mutex<MemoryStorage<T>>>);

impl<T: Entry> Storage<T> for SharedStorage<T> {
    fn write_atomically(&mut self, ops: Vec<StorageOp<T>>) -> StorageResult<()> {
        self.0.lock().unwrap().write_atomically(ops)
    }
    fn append_entry(&mut self, entry: T) -> StorageResult<()> {
        self.0.lock().unwrap().append_entry(entry)
    }
    fn append_entries(&mut self, entries: Vec<T>) -> StorageResult<()> {
        self.0.lock().unwrap().append_entries(entries)
    }
    fn append_on_prefix(&mut self, from_idx: usize, entries: Vec<T>) -> StorageResult<()> {
        self.0.lock().unwrap().append_on_prefix(from_idx, entries)
    }
    fn set_promise(&mut self, n_prom: omnipaxos::ballot_leader_election::Ballot) -> StorageResult<()> {
        self.0.lock().unwrap().set_promise(n_prom)
    }
    fn set_decided_idx(&mut self, ld: usize) -> StorageResult<()> {
        self.0.lock().unwrap().set_decided_idx(ld)
    }
    fn get_decided_idx(&self) -> StorageResult<usize> {
        self.0.lock().unwrap().get_decided_idx()
    }
    fn set_accepted_round(&mut self, na: omnipaxos::ballot_leader_election::Ballot) -> StorageResult<()> {
        self.0.lock().unwrap().set_accepted_round(na)
    }
    fn get_accepted_round(
        &self,
    ) -> StorageResult<Option<omnipaxos::ballot_leader_election::Ballot>> {
        self.0.lock().unwrap().get_accepted_round()
    }
    fn get_entries(&self, from: usize, to: usize) -> StorageResult<Vec<T>> {
        self.0.lock().unwrap().get_entries(from, to)
    }
    fn get_log_len(&self) -> StorageResult<usize> {
        self.0.lock().unwrap().get_log_len()
    }
    fn get_suffix(&self, from: usize) -> StorageResult<Vec<T>> {
        self.0.lock().unwrap().get_suffix(from)
    }
    fn get_promise(
        &self,
    ) -> StorageResult<Option<omnipaxos::ballot_leader_election::Ballot>> {
        self.0.lock().unwrap().get_promise()
    }
    fn set_stopsign(&mut self, s: Option<StopSign>) -> StorageResult<()> {
        self.0.lock().unwrap().set_stopsign(s)
    }
    fn get_stopsign(&self) -> StorageResult<Option<StopSign>> {
        self.0.lock().unwrap().get_stopsign()
    }
    fn trim(&mut self, idx: usize) -> StorageResult<()> {
        self.0.lock().unwrap().trim(idx)
    }
    fn set_compacted_idx(&mut self, idx: usize) -> StorageResult<()> {
        self.0.lock().unwrap().set_compacted_idx(idx)
    }
    fn get_compacted_idx(&self) -> StorageResult<usize> {
        self.0.lock().unwrap().get_compacted_idx()
    }
    fn set_snapshot(&mut self, snapshot: Option<<T as Entry>::Snapshot>) -> StorageResult<()> {
        self.0.lock().unwrap().set_snapshot(snapshot)
    }
    fn get_snapshot(&self) -> StorageResult<Option<<T as Entry>::Snapshot>> {
        self.0.lock().unwrap().get_snapshot()
    }
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

type Op = OmniPaxos<TestEntry, SharedStorage<TestEntry>>;

fn build(pid: NodeId, nodes: &[NodeId], storage: SharedStorage<TestEntry>) -> Op {
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
    .build(storage)
    .unwrap()
}

fn record_decision(
    op: &Op,
    pid: NodeId,
    step: usize,
    history: &mut HashMap<usize, u64>,
) {
    for idx in 0..op.get_decided_idx() {
        if let Some(LogEntry::Decided(TestEntry(value))) = op.read(idx) {
            if let Some(previous) = history.insert(idx, value) {
                assert_eq!(
                    previous, value,
                    "decided-index conflict at step {step}, idx {idx}, pid {pid}"
                );
            }
        }
    }
}

fn main() {
    let nodes: Vec<NodeId> = (1..=5).collect();
    let storages: HashMap<NodeId, SharedStorage<TestEntry>> = nodes
        .iter()
        .map(|&pid| {
            (
                pid,
                SharedStorage(Arc::new(Mutex::new(MemoryStorage::<TestEntry>::default()))),
            )
        })
        .collect();
    let mut ops: HashMap<NodeId, Option<Op>> = nodes
        .iter()
        .map(|&pid| (pid, Some(build(pid, &nodes, storages[&pid].clone()))))
        .collect();
    let mut down_for = vec![0u32; nodes.len() + 1];
    let mut links_up = [[true; 6]; 6];
    let mut in_flight: Vec<Message<TestEntry>> = Vec::new();
    let mut history = HashMap::new();
    let mut rng = Lcg(0xc0ff_ee12_3456_789a);
    let mut next_value = 1u64;
    let mut crash_count = 0;

    for step in 0..5000 {
        for from in 1..=5 {
            for to in 1..=5 {
                if from != to && rng.chance(1, 50) {
                    links_up[from][to] = false;
                } else if rng.chance(1, 6) {
                    links_up[from][to] = true;
                }
            }
        }

        // Crash one live node occasionally, then rebuild it from the same
        // persistent in-memory backend after a short outage.
        if rng.chance(1, 250) {
            let live: Vec<_> = nodes
                .iter()
                .copied()
                .filter(|pid| ops[pid].is_some())
                .collect();
            if !live.is_empty() {
                let pid = live[(rng.next() as usize) % live.len()];
                ops.insert(pid, None);
                down_for[pid as usize] = 4 + (rng.next() as u32 % 20);
                crash_count += 1;
            }
        }
        for &pid in &nodes {
            if ops[&pid].is_none() {
                down_for[pid as usize] -= 1;
                if down_for[pid as usize] == 0 {
                    ops.insert(pid, Some(build(pid, &nodes, storages[&pid].clone())));
                }
            }
        }

        for &pid in &nodes {
            if let Some(op) = ops.get_mut(&pid).unwrap() {
                op.tick();
            }
        }

        if step > 20 && step % 4 == 0 {
            for _ in 0..2 {
                let live: Vec<_> = nodes
                    .iter()
                    .copied()
                    .filter(|pid| ops[pid].is_some())
                    .collect();
                if live.is_empty() {
                    break;
                }
                let pid = live[(rng.next() as usize) % live.len()];
                let _ = ops.get_mut(&pid).unwrap().as_mut().unwrap().append(TestEntry(next_value));
                next_value += 1;
            }
        }

        for &pid in &nodes {
            if let Some(op) = ops.get_mut(&pid).unwrap() {
                op.take_outgoing_messages(&mut in_flight);
            }
        }
        for i in (1..in_flight.len()).rev() {
            let j = (rng.next() as usize) % (i + 1);
            in_flight.swap(i, j);
        }

        let mut delayed = Vec::new();
        for msg in in_flight.drain(..) {
            let from = msg.get_sender();
            let to = msg.get_receiver();
            if links_up[from as usize][to as usize] {
                if let Some(op) = ops.get_mut(&to).and_then(Option::as_mut) {
                    op.handle_incoming(msg.clone());
                }
                if rng.chance(1, 20) {
                    if let Some(op) = ops.get_mut(&to).and_then(Option::as_mut) {
                        op.handle_incoming(msg);
                    }
                }
            } else if rng.chance(4, 5) {
                delayed.push(msg);
            }
        }
        in_flight = delayed;
        if in_flight.len() > 5000 {
            in_flight.drain(..in_flight.len() - 5000);
        }

        if step % 10 == 0 {
            for &pid in &nodes {
                if let Some(op) = ops[&pid].as_ref() {
                    record_decision(op, pid, step, &mut history);
                }
            }
        }
    }

    // Bring every node back, heal all links, and quiesce.
    for &pid in &nodes {
        if ops[&pid].is_none() {
            ops.insert(pid, Some(build(pid, &nodes, storages[&pid].clone())));
        }
    }
    for _ in 0..2000 {
        for &pid in &nodes {
            ops.get_mut(&pid).unwrap().as_mut().unwrap().tick();
        }
        for &pid in &nodes {
            ops.get_mut(&pid)
                .unwrap()
                .as_mut()
                .unwrap()
                .take_outgoing_messages(&mut in_flight);
        }
        for msg in in_flight.drain(..) {
            if let Some(op) = ops.get_mut(&msg.get_receiver()).and_then(Option::as_mut) {
                op.handle_incoming(msg);
            }
        }
    }
    for &pid in &nodes {
        if let Some(op) = ops[&pid].as_ref() {
            record_decision(op, pid, 5000, &mut history);
        }
    }

    let decided: Vec<_> = nodes
        .iter()
        .map(|pid| (*pid, ops[pid].as_ref().unwrap().get_decided_idx()))
        .collect();
    println!(
        "PASS: {crash_count} crashes, {} proposals, no decided-prefix conflict; decided indexes: {decided:?}",
        next_value - 1
    );
}
