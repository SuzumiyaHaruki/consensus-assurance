//! Audit-only probe: `Raft::shutdown()` waits for RaftCore, but RaftCore owns
//! the state-machine worker only through a detached JoinHandle. If the worker
//! is in the middle of an install/apply, it can finish after `shutdown()`
//! returns and modify the store.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use openraft::storage::Adaptor;
use openraft::storage::RaftStateMachine;
use openraft::Config;
use openraft::LogIdOptionExt;
use openraft::SnapshotPolicy;
use openraft_memstore::BlockOperation;
use openraft_memstore::MemStore;
use openraft_memstore::TypeConfig;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn shutdown_does_not_wait_for_sm_worker() -> Result<()> {
    let config = Arc::new(
        Config {
            snapshot_policy: SnapshotPolicy::LogsSinceLast(1),
            max_in_snapshot_log_to_keep: 0,
            purge_batch_size: 1,
            enable_heartbeat: false,
            election_timeout_min: 3_000,
            election_timeout_max: 4_000,
            ..Default::default()
        }
        .validate()?,
    );

    let mut router = RaftRouter::new(config.clone());
    router.new_raft_node(0).await;
    router.initialize(0).await?;
    router.wait(&0, Some(Duration::from_secs(3))).state(openraft::ServerState::Leader, "n0 leader").await?;

    let log_index = router.client_request_many(0, "audit", 5).await?;
    let n0 = router.get_raft_handle(&0)?;
    n0.trigger().snapshot().await?;

    let mut snapshot = None;
    for _ in 0..200 {
        if let Some(s) = n0.get_snapshot().await? {
            if s.meta.last_log_id.index() >= Some(log_index) {
                snapshot = Some(s);
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let snapshot = snapshot.expect("node 0 did not build the snapshot");
    let snap_last = snapshot.meta.last_log_id.expect("snapshot last log id");
    let leader_vote = n0.with_raft_state(|st| *st.vote_ref()).await?;

    let inner = Arc::new(MemStore::default());
    let (log_store, _unused_sm) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());
    let (sm, _unused_log) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());
    let mut read_sm = sm.clone();
    let before = read_sm.applied_state().await?.0;

    log_store
        .clone()
        .storage_mut()
        .await
        .set_blocking(BlockOperation::InstallSnapshot, Duration::from_secs(1));

    let n3 = openraft::Raft::new(3, config.clone(), router.clone(), log_store, sm.clone()).await?;
    let n3_shutdown = n3.clone();
    let install = tokio::spawn(async move { n3.install_full_snapshot(leader_vote, snapshot).await });

    // Let the worker enter the delayed install.
    tokio::time::sleep(Duration::from_millis(100)).await;
    n3_shutdown.shutdown().await?;
    tracing::info!("shutdown returned");

    // The worker was still sleeping; it now completes the install.
    tokio::time::sleep(Duration::from_millis(1_200)).await;
    let after = sm.clone().applied_state().await?.0;
    tracing::info!(?before, ?after, ?snap_last, "SM state after shutdown");
    eprintln!("SM applied after shutdown: before={:?}, after={:?}, snapshot={:?}", before, after, snap_last);
    assert_eq!(None, before, "precondition: empty state machine");
    assert_eq!(
        Some(snap_last),
        after,
        "the state-machine worker completed install after shutdown returned"
    );

    install.abort();
    Ok(())
}
