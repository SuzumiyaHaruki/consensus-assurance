//! Audit-only randomized model test for `LogIdList`.
//!
//! Not part of the captured implementation. It checks the compressed key-log-id
//! representation against a plain `Vec<LogId>` model under append, truncate and
//! purge operations.

use crate::engine::LogIdList;
use crate::testing::log_id;
use crate::LogId;

struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        self.0 >> 33
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

#[derive(Default)]
struct Model {
    /// All non-purged logs, consecutive, ordered by index.
    logs: Vec<LogId<u64>>,
    /// Log id returned at the purged boundary, if any.
    purged_upto: Option<LogId<u64>>,
}

impl Model {
    fn last_index(&self) -> Option<u64> {
        self.logs.last().map(|x| x.index).or(self.purged_upto.map(|x| x.index))
    }

    fn get(&self, index: u64) -> Option<LogId<u64>> {
        if let Some(p) = self.purged_upto {
            if index <= p.index {
                return (index == p.index).then_some(p);
            }
        }
        self.logs.iter().find(|x| x.index == index).cloned()
    }

    fn first(&self) -> Option<LogId<u64>> {
        self.purged_upto.or_else(|| self.logs.first().cloned())
    }

    fn last(&self) -> Option<LogId<u64>> {
        self.logs.last().cloned().or(self.purged_upto)
    }

    fn append(&mut self, lid: LogId<u64>) {
        if let Some(last) = self.logs.last() {
            assert!(lid.index > last.index, "test bug: non-monotonic append {lid:?} after {last:?}");
        }
        self.logs.push(lid);
    }

    fn truncate(&mut self, at: u64) {
        if let Some(p) = self.purged_upto {
            assert!(at > p.index, "test bug: truncate {at} into purged region {}", p.index);
        }
        self.logs.retain(|x| x.index < at);
    }

    fn purge(&mut self, upto: LogId<u64>) {
        self.logs.retain(|x| x.index > upto.index);
        self.purged_upto = Some(upto);
    }
}

fn check(ids: &LogIdList<u64>, m: &Model, ctx: &str) {
    let last = m.last_index();

    for i in 0..last.map(|x| x + 3).unwrap_or(0) {
        assert_eq!(
            m.get(i),
            ids.get(i),
            "{ctx}: get({i}) mismatch; keys: {:?}, logs: {:?}, purged: {:?}",
            ids.key_log_ids(),
            m.logs,
            m.purged_upto
        );
    }

    assert_eq!(m.first(), ids.first().cloned(), "{ctx}: first; keys: {:?}", ids.key_log_ids());
    assert_eq!(m.last(), ids.last().cloned(), "{ctx}: last; keys: {:?}", ids.key_log_ids());

    for k in ids.key_log_ids() {
        assert_eq!(Some(k.clone()), ids.get(k.index), "{ctx}: key log id not reachable via get: {k}");
    }
}

#[test]
fn audit_log_id_list_random_ops() {
    for seed in 0..60 {
        let mut rng = Lcg(seed);
        let mut ids = LogIdList::<u64>::default();
        let mut m = Model::default();
        let mut next_index = 0u64;
        let mut term = 1u64;

        for step in 0..400 {
            let op = if next_index == 0 { 0 } else { rng.below(8) };
            let ctx = format!("seed {seed} step {step} op {op}");

            match op {
                // append one log with a random leader id
                0 | 1 => {
                    if rng.below(4) == 0 {
                        term += 1;
                    }
                    let lid = log_id(term, 1, next_index);
                    ids.append(lid);
                    m.append(lid);
                    next_index += 1;
                }
                // append a batch by the same leader
                2 | 3 => {
                    term += 1;
                    let n = 1 + rng.below(4);
                    let batch = (0..n).map(|k| log_id(term, 1, next_index + k)).collect::<Vec<_>>();
                    ids.extend_from_same_leader(&batch);
                    for lid in &batch {
                        m.append(*lid);
                    }
                    next_index += n;
                }
                // append a batch with mixed leaders
                4 => {
                    let n = 1 + rng.below(4);
                    let batch = (0..n)
                        .map(|k| {
                            if rng.below(2) == 0 {
                                term += 1;
                            }
                            log_id(term, 1, next_index + k)
                        })
                        .collect::<Vec<_>>();
                    ids.extend(&batch);
                    for lid in &batch {
                        m.append(*lid);
                    }
                    next_index += n;
                }
                // truncate: delete logs at and after `at`
                5 | 6 => {
                    let lower = m.purged_upto.map(|x| x.index + 1).unwrap_or(0);
                    if next_index <= lower {
                        continue;
                    }
                    let at = lower + rng.below(next_index - lower);
                    ids.truncate(at);
                    m.truncate(at);
                    next_index = at;
                }
                // purge upto an existing log id
                7 => {
                    let lower = m.purged_upto.map(|x| x.index).unwrap_or(0);
                    if next_index <= lower {
                        continue;
                    }
                    let idx = lower + rng.below(next_index - lower);
                    let lid = m.get(idx).expect("log exists");
                    ids.purge(&lid);
                    m.purge(lid);
                }
                _ => unreachable!(),
            }

            check(&ids, &m, &ctx);
        }
    }
}
