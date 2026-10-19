//! Audit-only reproduction: snapshot install purges logs before the state
//! machine install has completed, leaving an unrecoverable persisted state if
//! the node crashes in that window.
//!
//! The install is held pending with a test-only hook in `memstore`
//! (`BlockOperation::InstallSnapshot`). The log store and state machine use
//! separate adaptors/locks so the log store can be inspected while the state
//! machine install is blocked.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use openraft::storage::Adaptor;
use openraft::storage::RaftLogStorage;
use openraft::storage::RaftStateMachine;
use openraft::Config;
use openraft::LogIdOptionExt;
use openraft::RaftStorage;
use openraft::SnapshotPolicy;
use openraft_memstore::BlockOperation;
use openraft_memstore::MemStore;
use openraft_memstore::TypeConfig;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn snapshot_install_purges_before_install_completes() -> Result<()> {
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

    tracing::info!("--- single voter 0, produce a snapshot");
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
    let snapshot = snapshot.expect("node 0 did not build the expected snapshot");
    let snap_last = snapshot.meta.last_log_id.expect("snapshot must contain a last log id");
    tracing::info!(?snap_last, "got snapshot to install");

    let leader_vote = n0.with_raft_state(|st| *st.vote_ref()).await?;
    let persisted_vote = leader_vote;

    tracing::info!("--- empty node 3 with separate log-store and state-machine adaptors");
    let inner = Arc::new(MemStore::default());
    let (log_store, _unused_sm) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());
    let (sm, _unused_log) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());

    log_store
        .clone()
        .storage_mut()
        .await
        .set_blocking(BlockOperation::InstallSnapshot, Duration::from_secs(10));

    let n3 = openraft::Raft::new(3, config.clone(), router.clone(), log_store.clone(), sm.clone()).await?;

    let mut read_sm = sm.clone();
    let pre_install_applied = read_sm.applied_state().await?.0;
    tracing::info!(?pre_install_applied, "node 3 applied before install");

    let install = tokio::spawn(async move { n3.install_full_snapshot(leader_vote, snapshot).await });

    // The log purge is a RaftCore command; it does not wait for the state
    // machine install command to finish.
    let mut log_reader = log_store.clone();
    let mut purged = None;
    for _ in 0..500 {
        let st = log_reader.get_log_state().await?;
        if st.last_purged_log_id == Some(snap_last) {
            purged = st.last_purged_log_id;
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let purged = purged.expect("follower log was not purged");
    assert_eq!(snap_last, purged, "log purge should have reached the snapshot");

    // The SM install is still in progress: its adapter lock is held by the
    // blocked `install_snapshot()` call.
    let mut blocked_sm = sm.clone();
    let sm_read = tokio::time::timeout(Duration::from_millis(300), async move { blocked_sm.applied_state().await }).await;
    assert!(
        sm_read.is_err(),
        "install must still be pending when the log purge has already been persisted"
    );
    tracing::info!(?purged, ?pre_install_applied, "PURGE PERSISTED WHILE SM INSTALL IS PENDING");

    // The state left by a crash at this point: the log store is purged up to
    // the snapshot, while the state machine is still at its pre-install state
    // and does not yet have the new snapshot. Re-create that persisted state
    // in a fresh store and start a node from it.
    tracing::info!("--- restart from the mid-install persisted state");
    let crash_store = Arc::new(MemStore::default());
    let mut crash_log_store = crash_store.clone();
    crash_log_store.purge_logs_upto(snap_last).await?;
    // The follower persisted the leader's vote before starting the install.
    crash_log_store.save_vote(&persisted_vote).await?;

    let (crash_log, _unused_crash_sm) = Adaptor::<TypeConfig, Arc<MemStore>>::new(crash_store.clone());
    let (crash_sm, _unused_crash_log) = Adaptor::<TypeConfig, Arc<MemStore>>::new(crash_store.clone());

    let restarted = openraft::Raft::new(4, config, router.clone(), crash_log, crash_sm).await;
    tracing::info!(restart_ok = restarted.is_ok(), "restart with the mid-install state");
    let restarted = restarted?;

    let res = tokio::time::timeout(Duration::from_secs(3), restarted.with_raft_state(|_| ())).await;
    tracing::info!(?res, "restarted node state access");
    match res {
        Ok(Err(e)) => {
            tracing::info!(error = %e, "restarted node reported a fatal error");
        }
        Ok(Ok(())) => panic!("BUG NOT REPRODUCED: restarted node served state despite purge-before-install"),
        Err(_) => panic!("restarted node hung on state access"),
    }

    install.abort();
    Ok(())
}
