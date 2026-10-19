//! Audit-only randomized model test for `VecProgress`.
//!
//! Not part of the captured implementation. It compares the incremental quorum
//! scan against a brute-force recomputation of the greatest value granted by a
//! quorum, for uniform and joint quorum sets.

use std::collections::BTreeMap;

use crate::progress::Progress;
use crate::progress::VecProgress;
use crate::quorum::Joint;
use crate::quorum::QuorumSet;

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

fn model_granted<QS: QuorumSet<u64>>(qs: &QS, values: &BTreeMap<u64, u64>, default_v: u64) -> u64 {
    let mut candidates = values.values().cloned().collect::<Vec<_>>();
    candidates.push(default_v);
    candidates.sort_unstable();
    candidates.dedup();

    for v in candidates.into_iter().rev() {
        let ids = values.iter().filter(|(_, x)| **x >= v).map(|(id, _)| *id).collect::<Vec<_>>();
        if qs.is_quorum(ids.iter()) {
            return v;
        }
    }
    default_v
}

fn run<QS>(n: u64, qs: QS, seed: u64, steps: usize)
where
    QS: QuorumSet<u64> + Clone + std::fmt::Debug + 'static,
{
    let ids = (0..n).collect::<Vec<_>>();
    let mut rng = Lcg(seed);
    let mut p = VecProgress::<u64, u64, u64, QS>::new(qs.clone(), [], 0);
    let mut values = ids.iter().map(|i| (*i, 0u64)).collect::<BTreeMap<_, _>>();

    for step in 0..steps {
        let id = rng.below(n);
        let cur = values[&id];
        let new_v = cur + rng.below(4);
        let got = *p.update(&id, new_v).map_err(|e| *e).unwrap();
        values.insert(id, new_v);

        let want = model_granted(&qs, &values, 0);
        assert_eq!(want, got, "step {step}: id {id} -> {new_v}, quorum: {qs:?}, values: {values:?}");

        // All voter values greater than granted must stay sorted descending.
        let granted = got;
        let above = p
            .iter()
            .take(n as usize)
            .map(|(_, v)| *v)
            .filter(|v| *v > granted)
            .collect::<Vec<_>>();
        let mut sorted = above.clone();
        sorted.sort_unstable_by(|a, b| b.cmp(a));
        assert_eq!(sorted, above, "step {step}: values above granted are not sorted: {values:?}");
    }
}

#[test]
fn audit_vec_progress_uniform_majority() {
    for n in 1..=9 {
        for seed in 0..20 {
            run(n, (0..n).collect::<Vec<u64>>(), seed, 300);
        }
    }
}

#[test]
fn audit_vec_progress_joint_majority() {
    // Joint quorum: majority of {0,1,2} AND majority of {1,2,3,4}.
    let qs = Joint::from(vec![vec![0u64, 1, 2], vec![1u64, 2, 3, 4]]);
    for seed in 0..50 {
        let ids = [0u64, 1, 2, 3, 4];
        let n = ids.len() as u64;
        let mut rng = Lcg(seed);
        let mut p = VecProgress::<u64, u64, u64, _>::new(qs.clone(), [], 0);
        let mut values = ids.iter().map(|i| (*i, 0u64)).collect::<BTreeMap<_, _>>();

        for step in 0..500 {
            let id = rng.below(n);
            let cur = values[&id];
            let new_v = cur + rng.below(5);
            let got = *p.update(&id, new_v).map_err(|e| *e).unwrap();
            values.insert(id, new_v);

            let want = model_granted(&qs, &values, 0);
            assert_eq!(want, got, "step {step}: id {id} -> {new_v}, values: {values:?}");
        }
    }
}
