//! Audit-only reproduction: `AppendEntriesResponse::PartialSuccess(None)` is
//! documented as valid when the request's `prev_log_id` is `None`, but
//! `ReplicationHandler::update_matching()` asserts that a matching id is
//! always `Some`.
//!
//! Setup is deliberately non-blocking: a single-node leader is initialized
//! first, then a learner is added with the quota set to 0. The first
//! AppendEntries to that learner has `prev_log_id = None`, so the test network
//! returns `PartialSuccess(None)`.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use openraft::Config;
use openraft::ServerState;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn partial_success_none() -> Result<()> {
    let config = Arc::new(Config { ..Default::default() }.validate()?);

    let mut router = RaftRouter::new(config.clone());

    tracing::info!("--- single-node leader");
    router.new_raft_node(0).await;
    router.initialize(0).await?;
    router.wait(&0, Some(Duration::from_secs(2))).state(ServerState::Leader, "n0 leader").await?;

    tracing::info!("--- add learner 1 with zero AppendEntries quota");
    router.new_raft_node(1).await;
    router.set_append_entries_quota(Some(0));

    let n0 = router.get_raft_handle(&0)?;
    // Non-blocking: the membership add commits with the single voter while the
    // first replication to learner 1 produces PartialSuccess(None).
    let add_res = n0.add_learner(1, (), false).await;
    tracing::info!(?add_res, "non-blocking add_learner result");

    let stop = tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            match n0.with_raft_state(|_| ()).await {
                Ok(()) => tokio::time::sleep(Duration::from_millis(20)).await,
                Err(e) => return e,
            }
        }
    })
    .await;

    tracing::info!(?stop, "node 0 stop state");
    match stop {
        Ok(e) => {
            tracing::info!(error = %e, "node 0 stopped");
            Ok(())
        }
        Err(_) => anyhow::bail!("BUG NOT REPRODUCED: node 0 did not stop"),
    }
}
