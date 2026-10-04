use std::{future::Future, time::Duration};
use omnipaxos::{
    messages::{Message, async_runtime::AsyncRuntimeMsg},
    storage::{Entry, Snapshot}, util::LogEntry,
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, OmniPaxosHandle, RuntimeConfig};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct Value(u64);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct NoSnap;
impl Snapshot<Value> for NoSnap {
    fn create(_: &[Value]) -> Self { Self }
    fn merge(&mut self, _: Self) {}
    fn use_snapshots() -> bool { false }
}
impl Entry for Value { type Snapshot = NoSnap; }

// Executor adapter only: the selected crate does not enable its optional TokioRuntime.
struct Executor;
impl AsyncRuntime for Executor {
    type JoinHandle = tokio::task::JoinHandle<()>;
    fn spawn<F: Future<Output=()> + Send + 'static>(f: F) -> Self::JoinHandle { tokio::spawn(f) }
    fn sleep(d: Duration) -> impl Future<Output=()> + Send + 'static { tokio::time::sleep(d) }
}
type Handle = OmniPaxosHandle<Value>;

fn node(pid: u64) -> Handle {
    let cfg = OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], ..Default::default() },
        server_config: ServerConfig {
            pid, batch_size: 1, election_tick_timeout: 100_000,
            resend_message_tick_timeout: 100_000, flush_batch_tick_timeout: 100_000,
            ..Default::default()
        },
    };
    let op = cfg.build(MemoryStorage::<Value>::default()).expect("valid cluster");
    spawn_actor::<_,_,Executor>(op, RuntimeConfig {
        tick_period: Duration::from_millis(1), egress_period: Duration::from_millis(1),
        append_notify_timeout: Duration::from_secs(5), ..Default::default()
    })
}

// Each outgoing queue is drained in order. Partitioned traffic is retained unchanged.
async fn pump(nodes: &[Handle], isolate_one: bool, held: &mut Vec<Message<Value>>) {
    for n in nodes {
        let out = n.outgoing_messages();
        while let Ok(m) = out.try_recv() {
            if isolate_one && (m.get_sender() == 1 || m.get_receiver() == 1) {
                held.push(m);
            } else {
                nodes[(m.get_receiver()-1) as usize].handle_incoming(m).await;
            }
        }
        let events = n.subscribe_events();
        while events.try_recv().is_ok() {}
    }
    tokio::time::sleep(Duration::from_millis(2)).await;
}
async fn stable(nodes: &[Handle], ids: &[usize], leader: u64, isolated: bool, held: &mut Vec<Message<Value>>) {
    for _ in 0..500 {
        pump(nodes, isolated, held).await;
        let mut ready = true;
        for &i in ids { ready &= nodes[i].current_leader().await == Some((leader,true)); }
        if ready { return; }
    }
    panic!("leader preparation prerequisite not reached");
}
fn payload(entries: Option<Vec<LogEntry<Value>>>) -> Option<u64> {
    match entries?.first()? { LogEntry::Decided(v) => Some(v.0), _ => None }
}

#[test]
fn delayed_assignment_identity() {
    let rt = tokio::runtime::Builder::new_current_thread().enable_time().build().unwrap();
    rt.block_on(async {
        tokio::time::timeout(Duration::from_secs(20), async {
            let nodes = vec![node(1),node(2),node(3)];
            let mut held = Vec::new();
            nodes[0].try_become_leader().await;
            stable(&nodes, &[0,1,2], 1, false, &mut held).await;
            assert_eq!(nodes[2].decided_idx().await,0);
            println!("CA_EVENT {{\"event\":\"setup\",\"operation\":\"old-write\",\"old_leader\":1,\"empty\":true}}");
            let origin = nodes[2].clone();
            let pending = tokio::spawn(async move { origin.append_notify(Value(101)).await });
            // Pull the real TaggedProposal from origin and hand it to old leader.
            // All old-leader outbound messages are retained from this point onward.
            let mut tag = None;
            for _ in 0..500 {
                for (i,n) in nodes.iter().enumerate() {
                    let out = n.outgoing_messages();
                    while let Ok(m) = out.try_recv() {
                        if i == 2 {
                            if let Message::AsyncRuntime(a) = &m {
                                if let AsyncRuntimeMsg::TaggedProposal { entries } = &a.msg {
                                    assert_eq!(a.to,1);
                                    assert_eq!(entries.len(),1);
                                    assert_eq!(entries[0].1,Value(101));
                                    tag = Some(entries[0].0);
                                    println!("CA_EVENT {{\"event\":\"admitted\",\"operation\":\"old-write\",\"entry_id\":\"{}\",\"input\":{},\"old_leader\":1}}",entries[0].0.0,entries[0].1.0);
                                    nodes[0].handle_incoming(m).await;
                                    continue;
                                }
                            }
                        }
                        held.push(m);
                    }
                }
                if tag.is_some() { break; }
                tokio::time::sleep(Duration::from_millis(2)).await;
            }
            let tag = tag.expect("real tagged invocation");
            let mut assignment = None;
            for _ in 0..500 {
                let out = nodes[0].outgoing_messages();
                while let Ok(m) = out.try_recv() {
                    if let Message::AsyncRuntime(a) = &m {
                        if let AsyncRuntimeMsg::Assigned { ballot, entries } = &a.msg {
                            assert_eq!(a.to,3);
                            assert_eq!(entries.len(),1);
                            assert_eq!(entries[0].0,tag);
                            assignment = Some((entries[0].1,*ballot));
                        }
                    }
                    held.push(m);
                }
                if assignment.is_some() { break; }
                tokio::time::sleep(Duration::from_millis(2)).await;
            }
            let (assigned_idx, old_ballot) = assignment.expect("real old leader assignment");
            assert_eq!(assigned_idx,1);
            assert_eq!(nodes[0].decided_idx().await,0);
            println!("CA_EVENT {{\"event\":\"assigned\",\"operation\":\"old-write\",\"entry_id\":\"{}\",\"assigned_idx\":{},\"ballot_n\":{},\"old_decided\":0}}",tag.0,assigned_idx,old_ballot.n);
            // Node 1 remains isolated; only 2 and 3 supply the new preparation quorum.
            nodes[1].try_become_leader().await;
            stable(&nodes, &[1,2], 2, true, &mut held).await;
            assert_eq!(nodes[1].decided_idx().await,0);
            nodes[1].append(Value(202)).await.expect("replacement admitted");
            for _ in 0..500 {
                pump(&nodes,true,&mut held).await;
                if nodes[2].decided_idx().await >= assigned_idx { break; }
            }
            let replacement = payload(nodes[2].read_decided_suffix(assigned_idx-1).await).expect("replacement decided at origin");
            assert_eq!(replacement,202);
            assert!(!pending.is_finished(),"old request must still be pending before delayed assignment");
            println!("CA_EVENT {{\"event\":\"replacement\",\"operation\":\"old-write\",\"entry_id\":\"{}\",\"assigned_idx\":{},\"value\":{},\"new_leader\":2,\"pending\":true}}",tag.0,assigned_idx,replacement);
            // Release the old 1->3 stream in its original order, including the Assigned.
            // Other partitioned directions remain withheld. No message contents are edited.
            for m in held.drain(..) {
                if m.get_sender()==1 && m.get_receiver()==3 { nodes[2].handle_incoming(m).await; }
            }
            let result = tokio::time::timeout(Duration::from_secs(6),pending).await.expect("notification result available").expect("caller task");
            let (success,index,status) = match result {
                Ok(i) => (true,i,"ok"),
                Err(omnipaxos_runtime::AppendError::Superseded{log_entry_idx}) => (false,log_entry_idx,"superseded"),
                Err(omnipaxos_runtime::AppendError::Timeout) => (false,assigned_idx,"timeout"),
                Err(_) => (false,assigned_idx,"other_error"),
            };
            let value = if index > 0 { payload(nodes[2].read_decided_suffix(index-1).await) } else { None };
            let json_value = value.map(|v|v.to_string()).unwrap_or_else(||"null".into());
            println!("CA_EVENT {{\"event\":\"notification\",\"operation\":\"old-write\",\"entry_id\":\"{}\",\"case\":\"delayed_assignment\",\"success\":{},\"status\":\"{}\",\"returned_idx\":{},\"actual_value\":{},\"decided_idx\":{}}}",tag.0,success,status,index,json_value,nodes[2].decided_idx().await);
            drop(nodes);
            tokio::task::yield_now().await;
        }).await.expect("controlled history finished within harness bound");
    });
}
