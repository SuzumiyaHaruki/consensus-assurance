use std::{collections::VecDeque, time::Duration};
use omnipaxos::{OmniPaxos, OmniPaxosConfig, ClusterConfig, ServerConfig, messages::{Message, sequence_paxos::PaxosMsg}, storage::{Entry, Snapshot}, util::LogEntry};
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, RuntimeConfig};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct Value(u64);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct NoSnapshot;
impl Snapshot<Value> for NoSnapshot {
    fn create(_: &[Value]) -> Self { Self }
    fn merge(&mut self, _: Self) {}
    fn use_snapshots() -> bool { false }
}
impl Entry for Value { type Snapshot = NoSnapshot; }
struct Runtime;
impl AsyncRuntime for Runtime {
    type JoinHandle = tokio::task::JoinHandle<()>;
    fn spawn<F>(f: F) -> Self::JoinHandle where F: std::future::Future<Output=()> + Send + 'static { tokio::spawn(f) }
    fn sleep(d: Duration) -> impl std::future::Future<Output=()> + Send + 'static { tokio::time::sleep(d) }
}
type Op = OmniPaxos<Value, MemoryStorage<Value>>;
fn node(pid: u64) -> Op {
    OmniPaxosConfig {
        cluster_config: ClusterConfig {configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None},
        server_config: ServerConfig {pid, election_tick_timeout: 100, resend_message_tick_timeout: 100, flush_batch_tick_timeout: 100, batch_size: 1, ..Default::default()},
    }.build(MemoryStorage::default()).unwrap()
}
fn take_raw(nodes: &mut [Option<Op>], q: &mut VecDeque<Message<Value>>) {
    for node in nodes.iter_mut().flatten() { let mut v=Vec::new(); node.take_outgoing_messages(&mut v); q.extend(v); }
}
fn initial_pump(nodes: &mut [Option<Op>]) {
    let mut q=VecDeque::new();
    for _ in 0..100 {
        take_raw(nodes, &mut q);
        if q.is_empty() {return;}
        while let Some(m)=q.pop_front() {let to=m.get_receiver() as usize-1; nodes[to].as_mut().unwrap().handle_incoming(m);}
    }
    panic!("initial network failed to quiesce");
}
#[tokio::test(flavor="current_thread")]
async fn investigate_notification_after_replacement() {
    let mut nodes=vec![Some(node(1)),Some(node(2)),Some(node(3))];
    nodes[0].as_mut().unwrap().try_become_leader();
    initial_pump(&mut nodes);
    assert_eq!(nodes[0].as_ref().unwrap().get_current_leader(),Some((1,true)));
    assert!(nodes.iter().flatten().all(|n|n.get_decided_idx()==0 && n.get_accepted_idx()==0));
    println!("CA_EVENT {{\"event\":\"initial\",\"leader\":1,\"accepted\":0,\"decided\":0}}");
    // A long but finite actor tick allows real protocol messages to be handled
    // between notification evaluations. No actor internals or timer flags are changed.
    let cfg=RuntimeConfig {tick_period:Duration::from_secs(10),egress_period:Duration::from_millis(1),append_notify_timeout:Duration::from_secs(25),..Default::default()};
    let h=spawn_actor::<_,_,Runtime>(nodes[0].take().unwrap(),cfg);
    let out=h.outgoing_messages();
    let hc=h.clone();
    let call=tokio::spawn(async move {hc.append_notify(Value(101)).await});
    let mut dropped=0;
    tokio::time::timeout(Duration::from_secs(2), async {
        while dropped < 2 {
            let m=out.recv().await.unwrap();
            if let Message::SequencePaxos(p)=&m {
                if let PaxosMsg::AcceptDecide(a)=&p.msg {
                    assert_eq!(a.entries,vec![Value(101)]);
                    dropped+=1;
                    println!("CA_EVENT {{\"event\":\"isolated_accept\",\"from\":{},\"to\":{},\"value\":101,\"ballot_n\":{}}}",p.from,p.to,a.n.n);
                }
            }
            // Partition node 1: no outgoing packet is delivered to nodes 2/3.
        }
    }).await.expect("original proposal must produce actual acceptance messages");
    assert!(!call.is_finished());
    assert_eq!(h.decided_idx().await,0);
    // Nodes 2 and 3 form a new quorum without the isolated node's unchosen A.
    nodes[1].as_mut().unwrap().try_become_leader();
    let mut q=VecDeque::new();
    for _ in 0..50 {
        take_raw(&mut nodes,&mut q);
        if q.is_empty(){break;}
        while let Some(m)=q.pop_front(){let to=m.get_receiver() as usize-1;if to!=0 {nodes[to].as_mut().unwrap().handle_incoming(m);}}
    }
    assert_eq!(nodes[1].as_ref().unwrap().get_current_leader(),Some((2,true)));
    nodes[1].as_mut().unwrap().append(Value(202)).unwrap();
    for _ in 0..50 {
        take_raw(&mut nodes,&mut q);
        if q.is_empty(){break;}
        while let Some(m)=q.pop_front(){let to=m.get_receiver() as usize-1;if to!=0 {nodes[to].as_mut().unwrap().handle_incoming(m);}}
    }
    assert_eq!(nodes[1].as_ref().unwrap().get_decided_idx(),1);
    assert_eq!(nodes[2].as_ref().unwrap().get_decided_idx(),1);
    println!("CA_EVENT {{\"event\":\"replacement_decided\",\"leader\":2,\"value\":202,\"decided\":1}}");
    // Heal links with the documented reconnect callbacks. Drain and dispatch
    // each sender's emitted stream in order; every delivered packet is genuine.
    h.reconnected(2).await;
    h.reconnected(3).await;
    nodes[1].as_mut().unwrap().reconnected(1);
    nodes[2].as_mut().unwrap().reconnected(1);
    let mut sync_seen=false;
    tokio::time::timeout(Duration::from_secs(2),async {
        loop {
            while let Ok(m)=out.try_recv(){q.push_back(m);}
            take_raw(&mut nodes,&mut q);
            while let Some(m)=q.pop_front(){
                let to=m.get_receiver() as usize-1;
                if to==0 {
                    if let Message::SequencePaxos(p)=&m {if let PaxosMsg::AcceptSync(a)=&p.msg {
                        sync_seen=true;
                        println!("CA_EVENT {{\"event\":\"sync_delivered\",\"ballot_n\":{},\"decided\":{},\"suffix\":{:?}}}",a.n.n,a.decided_idx,a.log_sync.suffix.iter().map(|v|v.0).collect::<Vec<_>>());
                    }}
                    h.handle_incoming(m).await;
                } else {nodes[to].as_mut().unwrap().handle_incoming(m);}
            }
            if h.decided_idx().await==1 {break;}
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    }).await.expect("origin must install replacement before notifier tick");
    assert!(sync_seen);
    let read=h.read_decided_suffix(0).await.unwrap();
    let values:Vec<u64>=read.iter().filter_map(|e|match e{LogEntry::Decided(v)=>Some(v.0),_=>None}).collect();
    assert_eq!(values,vec![202]);
    println!("CA_EVENT {{\"event\":\"origin_read\",\"values\":{:?},\"call_finished_before_tick\":{}}}",values,call.is_finished());
    let result=tokio::time::timeout(Duration::from_secs(15),call).await.expect("notification completion").unwrap();
    match result {
        Ok(idx)=>println!("CA_EVENT {{\"event\":\"notification\",\"ok\":true,\"index\":{},\"requested_value\":101,\"decided_values\":{:?}}}",idx,values),
        Err(e)=>println!("Notification error: {:?}",e),
    }
    drop(h);
    drop(out);
    tokio::task::yield_now().await;
}
