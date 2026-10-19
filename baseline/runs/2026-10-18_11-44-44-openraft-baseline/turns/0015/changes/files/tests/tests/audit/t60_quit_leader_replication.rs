//! Audit-only probe: `Command::QuitLeader` is documented as "No longer a
//! leader. Clean up leader's data.", but the runtime only clears
//! `leader_data`; the replication handles in `self.replications` remain.
//!
//! To observe it externally, keep a chunked snapshot from the old leader to a
//! learner in flight, force a leadership change, and count InstallSnapshot
//! RPCs sent by the deposed leader after it stepped down.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use anyhow::Result;
use anyerror::AnyError;
use maplit::btreeset;
use openraft::Config;
use openraft::error::NetworkError;
use openraft::ServerState;
use openraft::SnapshotPolicy;

use crate::fixtures::init_default_ut_tracing;
use crate::fixtures::RaftRouter;
use openraft::RPCTypes;

#[async_entry::test(worker_threads = 8, init = "init_default_ut_tracing()", tracing_span = "debug")]
async fn quit_leader_keeps_snapshot_replication() -> Result<()> {
    let config = Arc::new(
        Config {
            snapshot_policy: SnapshotPolicy::LogsSinceLast(1),
            max_in_snapshot_log_to_keep: 0,
            purge_batch_size: 1,
            snapshot_max_chunk_size: 1,
            max_payload_entries: 3,
            heartbeat_interval: 50,
            election_timeout_min: 300,
            election_timeout_max: 400,
            ..Default::default()
        }
        .validate()?,
    );

    let mut router = RaftRouter::new(config.clone());

    tracing::info!("--- 2 voters, 0 is leader");
    let log_index = router.new_cluster(btreeset! {0, 1}, btreeset! {}).await?;

    tracing::info!(log_index, "--- write logs, snapshot and purge the leader log");
    let log_index = router.client_request_many(0, "audit", 200).await?;
    let n0 = router.get_raft_handle(&0)?;
    n0.trigger().snapshot().await?;

    for _ in 0..200 {
        let m = n0.metrics().borrow().clone();
        if m.snapshot.as_ref().map(|x| x.index).unwrap_or(0) >= log_index
            && m.purged.as_ref().map(|x| x.index).unwrap_or(0) >= log_index
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let m0 = n0.metrics().borrow().clone();
    tracing::info!(snapshot = ?m0.snapshot, purged = ?m0.purged, log_index, "leader snapshot/purge state");
    assert!(m0.purged.as_ref().map(|x| x.index).unwrap_or(0) >= log_index, "leader log was not purged");

    // Record every InstallSnapshot RPC by (from, target) and slow each chunk so
    // the snapshot is still in flight when leadership changes.
    //
    // Partition the new leader (1) from learner 2 so the learner keeps the old
    // vote and the deposed leader's in-flight snapshot can keep making
    // progress. The old leader (0) can still reach learner 2.
    router.set_rpc_pre_hook(RPCTypes::AppendEntries, move |_router, _req, from_id, target| {
        if from_id == 1 && target == 2 {
            return Err(NetworkError::new(&AnyError::error("new leader cannot reach learner 2")).into());
        }
        Ok(())
    });

    let calls = Arc::new(Mutex::new(Vec::<(u64, u64)>::new()));
    let calls_hook = calls.clone();
    router.set_rpc_pre_hook(RPCTypes::InstallSnapshot, move |_router, _req, from_id, target| {
        if from_id == 1 && target == 2 {
            return Err(
                NetworkError::new(&AnyError::error("new leader cannot send snapshot to learner 2")).into(),
            );
        }
        calls_hook.lock().unwrap().push((from_id, target));
        std::thread::sleep(Duration::from_millis(1));
        Ok(())
    });

    tracing::info!("--- add learner 2 behind the purged log; it must receive a snapshot");
    router.new_raft_node(2).await;
    n0.add_learner(2, (), false).await?;

    for _ in 0..200 {
        if calls.lock().unwrap().iter().any(|(from, to)| *from == 0 && *to == 2) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let first = calls.lock().unwrap().iter().any(|(from, to)| *from == 0 && *to == 2);
    assert!(first, "leader 0 did not start sending a snapshot to learner 2");

    // Let node 0's own vote lease expire, then force node 1 to campaign.
    tokio::time::sleep(Duration::from_millis(600)).await;
    let n1 = router.get_raft_handle(&1)?;
    n1.trigger().elect().await?;
    router.wait(&1, Some(Duration::from_secs(2))).state(ServerState::Leader, "n1 leader").await?;
    router.wait(&0, Some(Duration::from_secs(2))).state(ServerState::Follower, "n0 follower").await?;

    let before = calls.lock().unwrap().len();
    tokio::time::sleep(Duration::from_millis(2_000)).await;
    let post: Vec<(u64, u64)> = calls.lock().unwrap()[before..].to_vec();
    let post_old: Vec<(u64, u64)> = post.into_iter().filter(|(from, to)| *from == 0 && *to == 2).collect();
    tracing::info!(?post_old, "InstallSnapshot RPCs from deposed leader 0 after step-down");
    eprintln!(
        "deposed leader 0 sent {} InstallSnapshot chunks after step-down; sample={:?}",
        post_old.len(),
        &post_old[..post_old.len().min(8)]
    );
    assert!(
        !post_old.is_empty(),
        "deposed leader 0 sent no snapshot chunks after stepping down"
    );

    Ok(())
}
