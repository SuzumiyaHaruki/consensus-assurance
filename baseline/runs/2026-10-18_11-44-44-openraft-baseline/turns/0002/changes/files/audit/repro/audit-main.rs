#![cfg_attr(feature = "bt", feature(error_generic_member_access))]
#![cfg_attr(feature = "bt", allow(unused_features))]

#[macro_use]
#[path = "../fixtures/mod.rs"]
mod fixtures;

mod t50_snapshot_install_purge_order;
mod t10_partial_success_none;
