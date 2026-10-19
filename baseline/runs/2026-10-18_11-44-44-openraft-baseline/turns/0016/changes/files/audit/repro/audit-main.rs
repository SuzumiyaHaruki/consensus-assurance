#![cfg_attr(feature = "bt", feature(error_generic_member_access))]
#![cfg_attr(feature = "bt", allow(unused_features))]

#[macro_use]
#[path = "../fixtures/mod.rs"]
mod fixtures;

mod t50_snapshot_install_purge_order;
mod t10_partial_success_none;
mod t11_add_learner_blocking_leader_change;
mod t11_shutdown_sm_worker;
mod t60_quit_leader_replication;
