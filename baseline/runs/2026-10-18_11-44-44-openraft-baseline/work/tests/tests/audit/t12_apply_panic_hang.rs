//! Audit-only probe: a panic in `RaftStateMachine::apply()` kills the
//! state-machine worker, but RaftCore is not notified. The client responder
//! for the entry being applied is held in `client_resp_channels`, so
//! `client_write()` can wait forever while the core remains alive.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use maplit::btreeset;
use openraft::storage::Adaptor;
use openraft::Config;
use openraft::LogIdOptionExt;
use openraft::SnapshotPolicy;
use openraft_memstore::MemStore;
use openraft_memstore::TypeConfig;

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

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn install_panic_hangs_install_caller() -> Result<()> {
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
    router.wait(&0, Some(Duration::from_secs(2))).state(openraft::ServerState::Leader, "n0 leader").await?;

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
    let snapshot = snapshot.expect("snapshot missing");
    let leader_vote = n0.with_raft_state(|st| *st.vote_ref()).await?;

    let inner = Arc::new(MemStore::default());
    let (log_store, _unused_sm) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());
    let (sm, _unused_log) = Adaptor::<TypeConfig, Arc<MemStore>>::new(inner.clone());
    log_store.clone().storage_mut().await.set_panic_on_install_snapshot(true);

    let n3 = openraft::Raft::new(3, config, router.clone(), log_store, sm).await?;
    let install = tokio::time::timeout(Duration::from_secs(2), n3.install_full_snapshot(leader_vote, snapshot)).await;
    let core = tokio::time::timeout(Duration::from_secs(1), n3.with_raft_state(|_| ())).await;

    eprintln!(
        "install panic: install_caller={:?}, core={:?}",
        install.is_err(),
        core
    );
    assert!(install.is_err(), "expected install_full_snapshot to hang after the install panic");
    assert!(
        matches!(core, Ok(Ok(()))),
        "expected RaftCore to remain alive while the install responder is held"
    );
    Ok(())
}
