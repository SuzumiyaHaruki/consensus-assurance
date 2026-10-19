//! Audit-only reproduction: `AppendEntriesResponse::PartialSuccess(None)` is
//! documented as valid when the request's `prev_log_id` is `None`, but
//! `ReplicationHandler::update_matching()` asserts that a matching id is
//! always `Some`.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use maplit::btreeset;
use openraft::Config;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn partial_success_none() -> Result<()> {
    let config = Arc::new(Config { ..Default::default() }.validate()?);

    let mut router = RaftRouter::new(config.clone());

    // Quota 0 makes the test network truncate every AppendEntries payload to
    // zero entries and report `PartialSuccess(prev_log_id)`. A brand-new
    // learner has prev_log_id = None, so the response is PartialSuccess(None).
    router.set_append_entries_quota(Some(0));

    let res = tokio::time::timeout(
        Duration::from_secs(3),
        router.new_cluster(btreeset! {0}, btreeset! {1}),
    )
    .await;
    tracing::info!(?res, "new_cluster with quota 0");

    // If RaftCore panicked on the debug assertion, the node can no longer
    // serve state.
    let n0 = router.get_raft_handle(&0)?;
    let state_res = tokio::time::timeout(Duration::from_secs(2), n0.with_raft_state(|_| ())).await;
    tracing::info!(?state_res, "node-0 state access after quota-0 replication");

    match state_res {
        Ok(Ok(())) => anyhow::bail!("BUG NOT REPRODUCED: node 0 still serves state"),
        Ok(Err(e)) => {
            tracing::info!(error = %e, "node 0 stopped");
            Ok(())
        }
        Err(_) => anyhow::bail!("node 0 hung"),
    }
}
