//! Audit-only probe: `add_learner(blocking=true)` is documented to block
//! until the learner is up to date. Its wait predicate treats a leadership
//! change (metrics.replication becomes None) as a successful stop, so it may
//! return Ok while the learner has not received any logs.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use maplit::btreeset;
use openraft::Config;
use openraft::LogIdOptionExt;
use openraft::ServerState;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn add_learner_blocking_leader_change() -> Result<()> {
    let config = Arc::new(
        Config {
            election_timeout_min: 300,
            election_timeout_max: 400,
            heartbeat_interval: 50,
            ..Default::default()
        }
        .validate()?,
    );

    let mut router = RaftRouter::new(config.clone());

    let log_index = router.new_cluster(btreeset! {0, 1}, btreeset! {}).await?;
    tracing::info!(log_index, "cluster created");

    // Learner 2 never answers AppendEntries; it cannot catch up.
    router.set_rpc_blocked(2, true);

    // Let node 0's own vote lease expire so it will grant node 1's campaign.
    tokio::time::sleep(Duration::from_millis(600)).await;

    let n0 = router.get_raft_handle(&0)?;
    let add = tokio::spawn(async move { n0.add_learner(2, (), true).await });

    // Wait for the add-membership log to commit before changing leadership.
    for _ in 0..100 {
        let m = router.get_raft_handle(&0)?.metrics().borrow().clone();
        if m.membership_config.membership().get_node(&2).is_some() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    {
        let m = router.get_raft_handle(&0)?.metrics().borrow().clone();
        assert!(m.membership_config.membership().get_node(&2).is_some(), "learner 2 was not added");
    }

    tracing::info!("--- force node 1 to campaign while add_learner is waiting");
    let n1 = router.get_raft_handle(&1)?;
    n1.trigger().elect().await?;
    router.wait(&1, Some(Duration::from_secs(2))).state(ServerState::Leader, "n1 leader").await?;

    let res = tokio::time::timeout(Duration::from_millis(500), add).await;
    tracing::info!(?res, "add_learner result after leadership change");

    let add_res = res.expect("add_learner should have stopped")?;
    assert!(add_res.is_ok(), "add_learner returned an error: {:?}", add_res);

    // The learner is still blocked and has not received the cluster log.
    let m1 = router.get_raft_handle(&1)?.metrics().borrow().clone();
    let matching = m1.replication.as_ref().and_then(|r| r.get(&2)).cloned();
    tracing::info!(?matching, ?log_index, "learner 2 replication state at add_learner return");
    eprintln!(
        "add_learner returned Ok after leadership change; learner-2 matching={:?}, cluster log_index={}",
        matching, log_index
    );
    assert!(
        matching.map(|x| x.index().unwrap_or(0)).unwrap_or(0) < log_index,
        "learner 2 unexpectedly caught up"
    );

    Ok(())
}
