//! Audit-only randomized model for `MembershipState::update_committed`.
//!
//! Inputs model a real snapshot:
//! - `c` is the newest membership entry covered by the snapshot, so its index
//!   is `>=` the committed membership index and `<= snapshot_last_index`;
//! - the local `effective` membership may be newer than the snapshot
//!   (uncommitted), in which case the snapshot must not replace it;
//! - if the effective membership is covered by the snapshot, its backing log
//!   entry is purged, so `c` must become both effective and committed.
//!
//! Checks: resulting effective/committed memberships, the `changed` signal,
//! and that the committed membership log id never regresses.

use std::collections::BTreeSet;
use std::sync::Arc;

use crate::testing::log_id;
use crate::EffectiveMembership;
use crate::Membership;
use crate::MembershipState;

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

fn mem(n: u64) -> Membership<u64, ()> {
    let set = (1..=n).collect::<BTreeSet<_>>();
    Membership::new(vec![set], None)
}

fn eff(index: u64, m: Membership<u64, ()>) -> Arc<EffectiveMembership<u64, ()>> {
    // Term grows with the index, as in a real log.
    Arc::new(EffectiveMembership::new(Some(log_id(1 + index / 3, 1, index)), m))
}

#[test]
fn audit_update_committed_model() {
    for seed in 0..2000 {
        let mut rng = Lcg(seed);
        let snap = 1 + rng.below(12);

        // Committed membership and committed index both lie within the snapshot.
        let committed_idx = rng.below(snap + 1);
        let committed_mem_idx = rng.below(committed_idx + 1);

        // The local effective membership may be newer than the snapshot, or be
        // covered by it.  The snapshot holds the newest membership entry it
        // covers (`c`), so its index is `>=` the effective index when the
        // effective entry is covered, and `<` it otherwise.
        let effective_idx = committed_idx + rng.below(16 - committed_idx);
        let c_idx = if effective_idx <= snap {
            effective_idx + rng.below(snap - effective_idx + 1)
        } else {
            committed_mem_idx + rng.below(snap - committed_mem_idx + 1)
        };

        let committed_m = mem(1 + rng.below(3));
        let effective_m = mem(1 + rng.below(3));
        let mut c_m = mem(1 + rng.below(3));
        // The same log id can only carry one membership.
        if c_idx == committed_mem_idx {
            c_m = committed_m.clone();
        }

        let committed = eff(committed_mem_idx, committed_m);
        let effective = eff(effective_idx, effective_m);
        let c = eff(c_idx, c_m);

        let mut state = MembershipState::<u64, ()>::new(committed.clone(), effective.clone());
        let old_committed_log_id = state.committed().log_id().clone();

        let changed = state.update_committed(c.clone(), snap);
        let purged = effective_idx <= snap;

        let expected_effective = if purged { c.clone() } else { effective.clone() };
        // `c` is the newest membership covered by the snapshot and is at least
        // as new as the old committed membership.
        let expected_committed = c.clone();
        let expected_changed = purged && c.membership() != effective.membership();

        assert_eq!(
            expected_effective.as_ref(),
            state.effective().as_ref(),
            "seed {seed}: effective; committed_idx {committed_idx}, committed_mem_idx {committed_mem_idx}, \
             effective_idx {effective_idx}, c_idx {c_idx}, snap {snap}"
        );
        assert_eq!(
            expected_committed.as_ref(),
            state.committed().as_ref(),
            "seed {seed}: committed; committed_idx {committed_idx}, committed_mem_idx {committed_mem_idx}, \
             effective_idx {effective_idx}, c_idx {c_idx}, snap {snap}"
        );
        assert_eq!(expected_changed, changed.is_some(), "seed {seed}: changed signal");
        if let Some(x) = changed {
            assert_eq!(
                expected_effective.as_ref(),
                x.as_ref(),
                "seed {seed}: returned effective membership"
            );
        }
        assert!(
            state.committed().log_id() >= &old_committed_log_id,
            "seed {seed}: committed membership log id regressed from {:?} to {:?}",
            old_committed_log_id,
            state.committed().log_id()
        );
    }
}
