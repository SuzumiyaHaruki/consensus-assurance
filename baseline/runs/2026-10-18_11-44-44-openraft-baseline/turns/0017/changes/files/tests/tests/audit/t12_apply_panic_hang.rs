//! Audit-only probe: a panic in `RaftStateMachine::apply()` kills the
//! state-machine worker, but RaftCore is not notified. The client responder
//! for the entry being applied is held in `client_resp_channels`, so
//! `client_write()` can wait forever while the core remains alive.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use maplit::btreeset;
use openraft::Config;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn apply_panic_hangs_client_write() -> Result<()> {
    let config = Arc::new(Config { enable_heartbeat: false, ..Default::default() }.validate()?);
    let mut router = RaftRouter::new(config);

    let log_index = router.new_cluster(btreeset! {0}, btreeset! {}).await?;
    tracing::info!(log_index, "single-node cluster ready");

    let (log_store, _sm) = router.get_storage_handle(&0)?;
    log_store.storage_mut().await.set_panic_on_apply(true);

    let write = tokio::time::timeout(Duration::from_secs(2), router.client_request_many(0, "audit", 1)).await;
    tracing::info!(?write, "client write with apply panic");

    let n0 = router.get_raft_handle(&0)?;
    let core = tokio::time::timeout(Duration::from_secs(1), n0.with_raft_state(|_| ())).await;
    tracing::info!(?core, "core state after apply panic");

    eprintln!("apply panic: client_write={:?}, core={:?}", write.is_err(), core);
    assert!(write.is_err(), "expected client_write to hang after the apply panic");
    assert!(
        matches!(core, Ok(Ok(()))),
        "expected RaftCore to remain alive while the client responder is held"
    );

    Ok(())
}
