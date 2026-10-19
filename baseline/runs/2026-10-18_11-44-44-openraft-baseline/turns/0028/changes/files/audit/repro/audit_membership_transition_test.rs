//! Audit-only randomized model test for membership transitions.
//!
//! Checks `Membership::change` against a small model: the intermediate
//! config must be coherent with the current config and with the goal, the
//! goal must be reachable in one more step, and `retain=false` must remove
//! only old voters absent from the new voter set.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use maplit::btreeset;

use crate::quorum::Coherent;
use crate::quorum::Joint;
use crate::ChangeMembers;
use crate::Membership;

type M = Membership<u64, ()>;

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

fn all_nodes() -> BTreeMap<u64, ()> {
    (0..6).map(|i| (i, ())).collect()
}

fn union(configs: &[BTreeSet<u64>]) -> BTreeSet<u64> {
    configs.iter().flatten().cloned().collect()
}

fn to_joint(configs: &[BTreeSet<u64>]) -> Joint<u64, Vec<u64>, Vec<Vec<u64>>> {
    Joint::from(configs.iter().map(|c| c.iter().cloned().collect::<Vec<_>>()).collect::<Vec<_>>())
}

fn goal_vec(goal: &BTreeSet<u64>) -> Vec<u64> {
    goal.iter().cloned().collect()
}

fn expected_configs(current: &[BTreeSet<u64>], goal: &BTreeSet<u64>) -> Vec<BTreeSet<u64>> {
    if current.iter().any(|c| c == goal) {
        vec![goal.clone()]
    } else {
        vec![current.last().unwrap().clone(), goal.clone()]
    }
}

fn subset(rng: &mut Lcg, universe: &[u64]) -> BTreeSet<u64> {
    universe.iter().filter(|_| rng.below(2) == 0).cloned().collect()
}

fn non_empty_subset(rng: &mut Lcg, universe: &[u64]) -> BTreeSet<u64> {
    for _ in 0..100 {
        let s = subset(rng, universe);
        if !s.is_empty() {
            return s;
        }
    }
    btreeset! { universe[0] }
}

fn map_of(set: &BTreeSet<u64>) -> BTreeMap<u64, ()> {
    set.iter().map(|x| (*x, ())).collect()
}

#[test]
fn audit_membership_change_model() {
    let universe = [0u64, 1, 2, 3, 4, 5];

    for seed in 0..30 {
        let mut rng = Lcg(seed);
        let mut current = if seed % 2 == 0 {
            vec![btreeset! {0u64, 1, 2}]
        } else {
            vec![btreeset! {0u64, 1, 2}, btreeset! {2u64, 3, 4}]
        };

        for step in 0..200 {
            let m = M::new(current.clone(), all_nodes());
            let retain = rng.below(2) == 0;
            let kind = rng.below(8);
            let old_voters = union(&current);
            let last = current.last().unwrap().clone();

            let (change, goal, expected_nodes) = match kind {
                0 => {
                    let goal = non_empty_subset(&mut rng, &universe);
                    let nodes = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::ReplaceAllVoters(goal.clone()), goal, nodes)
                }
                1 => {
                    let add = subset(&mut rng, &universe);
                    let goal = last.union(&add).cloned().collect::<BTreeSet<_>>();
                    let nodes = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::AddVoterIds(add), goal, nodes)
                }
                2 => {
                    let add = subset(&mut rng, &universe);
                    let goal = last.union(&add).cloned().collect::<BTreeSet<_>>();
                    let nodes = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::AddVoters(map_of(&add)), goal, nodes)
                }
                3 => {
                    let rem = non_empty_subset(&mut rng, &last.iter().cloned().collect::<Vec<_>>());
                    let goal = last.difference(&rem).cloned().collect::<BTreeSet<_>>();
                    if goal.is_empty() {
                        continue;
                    }
                    let nodes = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::RemoveVoters(rem), goal, nodes)
                }
                4 => {
                    let add = subset(&mut rng, &universe);
                    let nodes = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::AddNodes(map_of(&add)), last.clone(), nodes)
                }
                5 => {
                    let learner = universe.iter().find(|x| !old_voters.contains(x)).cloned();
                    let mut nodes = old_voters.clone();
                    if let Some(l) = learner {
                        nodes.insert(l);
                    }
                    let expected = all_nodes().into_keys().collect::<BTreeSet<_>>();
                    (ChangeMembers::SetNodes(map_of(&nodes)), last.clone(), expected)
                }
                6 => {
                    let learners = all_nodes().into_keys().filter(|x| !old_voters.contains(x)).collect::<BTreeSet<_>>();
                    if learners.is_empty() {
                        continue;
                    }
                    let rem = non_empty_subset(&mut rng, &learners.iter().cloned().collect::<Vec<_>>());
                    let expected = all_nodes().into_keys().filter(|x| !rem.contains(x)).collect::<BTreeSet<_>>();
                    (ChangeMembers::RemoveNodes(rem), last.clone(), expected)
                }
                7 => {
                    let learner = universe.iter().find(|x| !old_voters.contains(x)).cloned();
                    let mut nodes = old_voters.clone();
                    if let Some(l) = learner {
                        nodes.insert(l);
                    }
                    let expected = nodes.clone();
                    (ChangeMembers::ReplaceAllNodes(map_of(&nodes)), last.clone(), expected)
                }
                _ => unreachable!(),
            };

            // Node-only changes leave the voter configs untouched.  Only a
            // voter change goes through `next_coherent`/`find_coherent`.
            let expected_cfg = if kind < 4 {
                expected_configs(&current, &goal)
            } else {
                current.clone()
            };
            let mut want_nodes = expected_nodes;

            // Voter changes with retain=false remove old voters that are absent
            // from the new voter set.
            if kind < 4 && !retain {
                let new_voters = union(&expected_cfg);
                want_nodes.retain(|x| !old_voters.contains(x) || new_voters.contains(x));
            }

            let got = m
                .change(change.clone(), retain)
                .unwrap_or_else(|e| panic!("seed {seed} step {step} kind {kind}: change failed: {e:?}"));

            assert_eq!(
                expected_cfg,
                got.get_joint_config().clone(),
                "seed {seed} step {step} kind {kind} retain {retain}"
            );
            assert!(
                to_joint(&current).is_coherent_with(&to_joint(&expected_cfg)),
                "seed {seed} step {step}: current and intermediate are not coherent"
            );
            assert!(
                to_joint(&expected_cfg).is_coherent_with(&goal_vec(&goal)),
                "seed {seed} step {step}: intermediate and goal are not coherent"
            );

            if kind < 4 && expected_cfg.len() > 1 {
                let converged = got
                    .clone()
                    .change(ChangeMembers::ReplaceAllVoters(goal.clone()), true)
                    .expect("convergence change failed");
                assert_eq!(
                    vec![goal.clone()],
                    converged.get_joint_config().clone(),
                    "seed {seed} step {step}: did not converge in one step"
                );
            }

            let got_nodes = got.nodes().map(|(id, _)| *id).collect::<BTreeSet<_>>();
            assert_eq!(want_nodes, got_nodes, "seed {seed} step {step} kind {kind} retain {retain}: nodes");

            current = got.get_joint_config().clone();
        }
    }
}
