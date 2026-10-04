use std::{collections::VecDeque, future::Future, time::Duration};
use omnipaxos::{messages::Message, storage::{Entry, Snapshot}, util::LogEntry, ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, RuntimeConfig};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct Value(u64);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct Prefix(Vec<u64>);
impl Snapshot<Value> for Prefix {
    fn create(entries: &[Value]) -> Self { Self(entries.iter().map(|x| x.0).collect()) }
    fn merge(&mut self, delta: Self) { self.0.extend(delta.0); }
    fn use_snapshots() -> bool { true }
}
impl Entry for Value { type Snapshot = Prefix; }
type Node = OmniPaxos<Value, MemoryStorage<Value>>;
struct TestRuntime;
impl AsyncRuntime for TestRuntime {
    type JoinHandle = tokio::task::JoinHandle<()>;
    fn spawn<F: Future<Output=()> + Send + 'static>(future:F) -> Self::JoinHandle { tokio::spawn(future) }
    fn sleep(duration:Duration) -> impl Future<Output=()> + Send + 'static { tokio::time::sleep(duration) }
}
fn build(pid:u64) -> Node {
    OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id:1, nodes:vec![1,2,3], flexible_quorum:None },
        server_config: ServerConfig { pid, batch_size:1, election_tick_timeout:1000,
            resend_message_tick_timeout:1000, flush_batch_tick_timeout:1000, ..Default::default() },
    }.build(MemoryStorage::default()).unwrap()
}
fn take(node:&mut Node) -> Vec<Message<Value>> {
    let mut messages=Vec::new();node.take_outgoing_messages(&mut messages);messages
}
fn pump(nodes:&mut [Node]) {
    let mut queue=VecDeque::new();for node in nodes.iter_mut() { queue.extend(take(node)); }
    let mut count=0;
    while let Some(message)=queue.pop_front() {
        count+=1;assert!(count<1000,"transport did not quiesce");
        let index=message.get_receiver() as usize-1;
        nodes[index].handle_incoming(message);queue.extend(take(&mut nodes[index]));
    }
}
fn observe(entry:LogEntry<Value>, original:&[u64], positions:&mut Vec<usize>, ordinal:usize) {
    match entry {
        LogEntry::Decided(Value(value)) => {
            // Infer rank from a separately read, unique-value original decided log.
            // Numeric payload magnitude is not the ordering oracle.
            let position=original.iter().position(|x| *x==value).expect("unknown entry: cannot correlate");
            positions.push(position);
            println!("CA_EVENT {{\"event\":\"stream_item\",\"subscription\":\"from-zero\",\"ordinal\":{},\"kind\":\"decided\",\"value\":{},\"position\":{}}}",ordinal,value,position);
        }
        LogEntry::Snapshotted(s) => {
            println!("CA_EVENT {{\"event\":\"stream_item\",\"subscription\":\"from-zero\",\"ordinal\":{},\"kind\":\"snapshot\",\"boundary\":{},\"values\":{:?}}}",ordinal,s.trimmed_idx,s.snapshot.0);
        }
        other => panic!("unexpected representation; observation unknown: {:?}",other),
    }
}
#[tokio::test(flavor="current_thread")]
async fn snapshot_subscription_order() {
    tokio::time::timeout(Duration::from_secs(10),scenario()).await.expect("scenario timeout");
}
async fn scenario() {
    let mut nodes=vec![build(1),build(2),build(3)];
    nodes[0].try_become_leader();pump(&mut nodes);
    assert_eq!(nodes[0].get_current_leader(),Some((1,true)));
    // Deliberately nonmonotonic payloads ensure the oracle uses source positions.
    for value in [81,23,67,42,19] { nodes[0].append(Value(value)).unwrap();pump(&mut nodes); }
    assert!(nodes.iter().all(|n|n.get_decided_idx()==5));
    let original:Vec<u64>=nodes[0].read_decided_suffix(0).unwrap().into_iter().map(|x|match x {
        LogEntry::Decided(Value(v))=>v,other=>panic!("invalid decided prefix {:?}",other)
    }).collect();
    assert_eq!(original.len(),5);
    for i in 0..original.len() { assert!(!original[..i].contains(&original[i])); }
    println!("CA_EVENT {{\"event\":\"original_history\",\"subscription\":\"from-zero\",\"values\":{:?},\"decided\":5}}",original);

    nodes[0].snapshot(Some(3),true).unwrap();
    assert_eq!(nodes[0].get_compacted_idx(),3);
    let compacted=nodes[0].read_decided_suffix(0).unwrap();
    assert_eq!(compacted.len(),3);
    assert!(matches!(&compacted[0],LogEntry::Snapshotted(s) if s.trimmed_idx==3 && s.snapshot.0==original[..3]));
    assert!(matches!(&compacted[1],LogEntry::Decided(Value(v)) if *v==original[3]));
    assert!(matches!(&compacted[2],LogEntry::Decided(Value(v)) if *v==original[4]));
    let expected_catchup_items=compacted.len();
    let mut n3=nodes.pop().unwrap();let mut n2=nodes.pop().unwrap();let n1=nodes.pop().unwrap();
    let actor=spawn_actor::<_,_,TestRuntime>(n1,RuntimeConfig {
        tick_period:Duration::from_millis(50),egress_period:Duration::from_millis(1),
        decided_channel_capacity:32,..Default::default()
    });
    let outgoing=actor.outgoing_messages();let events=actor.subscribe_events();
    let event_drain=tokio::spawn(async move {while events.recv().await.is_ok(){}});
    let router_handle=actor.clone();
    let router=tokio::spawn(async move {
        while let Ok(message)=outgoing.recv().await {
            let target=if message.get_receiver()==2 {&mut n2}else{&mut n3};
            target.handle_incoming(message);
            let mut queue=VecDeque::new();queue.extend(take(&mut n2));queue.extend(take(&mut n3));
            while let Some(message)=queue.pop_front() {
                match message.get_receiver() {
                    1=>router_handle.handle_incoming(message).await,
                    2=>{n2.handle_incoming(message);queue.extend(take(&mut n2));},
                    3=>{n3.handle_incoming(message);queue.extend(take(&mut n3));},
                    _=>panic!("unknown receiver"),
                }
            }
        }
    });
    let stream=actor.subscribe_decided(0).await;
    // A read command behind SubscribeDecided confirms command processing without
    // interpreting a completed subscriber result as its own admission condition.
    assert_eq!(actor.decided_idx().await,5);
    println!("CA_EVENT {{\"event\":\"subscribed\",\"subscription\":\"from-zero\",\"from\":0,\"compacted\":3,\"decided\":5,\"retained_count\":2,\"history_ready\":true}}");
    let mut positions=Vec::new();let mut ordinal=0;
    // Observe the catch-up output, without asserting the stream's order.
    for _ in 0..expected_catchup_items {
        let entry=tokio::time::timeout(Duration::from_secs(1),stream.recv()).await.expect("catch-up missing").unwrap();
        observe(entry,&original,&mut positions,ordinal);ordinal+=1;
    }
    // End the window by elapsed time, independently of whether a reversal appears.
    let end=tokio::time::Instant::now()+Duration::from_millis(250);
    loop {
        match tokio::time::timeout_at(end,stream.recv()).await {
            Ok(Ok(entry))=>{observe(entry,&original,&mut positions,ordinal);ordinal+=1;},
            Ok(Err(_))=>panic!("subscription closed during observation"),
            Err(_)=>break,
        }
    }
    assert_eq!(actor.decided_idx().await,5);
    let final_suffix=actor.read_decided_suffix(3).await.unwrap();
    assert!(matches!(final_suffix.as_slice(),[LogEntry::Decided(Value(a)),LogEntry::Decided(Value(b))] if *a==original[3] && *b==original[4]));
    assert!(positions.len()>=2,"not enough output for order comparison");
    let order_preserved=positions.windows(2).all(|pair|pair[0]<=pair[1]);
    println!("CA_EVENT {{\"event\":\"stream_window\",\"subscription\":\"from-zero\",\"order_preserved\":{},\"positions\":{:?},\"observed_items\":{},\"stable_decided\":5,\"window_complete\":true}}",order_preserved,positions,ordinal);
    drop(stream);router.abort();let _=router.await;drop(actor);event_drain.abort();let _=event_drain.await;
}
