use std::{collections::VecDeque, future::Future, time::Duration};
use omnipaxos::{messages::{Message, sequence_paxos::PaxosMsg}, storage::{Entry, Snapshot}, util::LogEntry, ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, AppendError, RuntimeConfig};
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
type Node = OmniPaxos<Value, MemoryStorage<Value>>;

// The public executor adapter uses real Tokio timers, without changing actor logic.
struct TestRuntime;
impl AsyncRuntime for TestRuntime {
    type JoinHandle = tokio::task::JoinHandle<()>;
    fn spawn<F: Future<Output = ()> + Send + 'static>(future: F) -> Self::JoinHandle { tokio::spawn(future) }
    fn sleep(duration: Duration) -> impl Future<Output = ()> + Send + 'static { tokio::time::sleep(duration) }
}
fn build(pid: u64) -> Node {
    OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None },
        server_config: ServerConfig { pid, batch_size: 1, election_tick_timeout: 1000,
            resend_message_tick_timeout: 1000, flush_batch_tick_timeout: 1000, ..Default::default() },
    }.build(MemoryStorage::default()).unwrap()
}
fn take(node: &mut Node) -> Vec<Message<Value>> {
    let mut messages = Vec::new(); node.take_outgoing_messages(&mut messages); messages
}
fn trace(message: &Message<Value>, action: &str) {
    let (kind, round) = match message {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::Prepare(x) => ("prepare", x.n.n),
            PaxosMsg::Promise(x) => ("promise", x.n.n),
            PaxosMsg::AcceptSync(x) => ("sync", x.n.n),
            PaxosMsg::AcceptDecide(x) => ("accept", x.n.n),
            PaxosMsg::Accepted(x) => ("accepted", x.n.n),
            PaxosMsg::Decide(x) => ("decide", x.n.n),
            _ => ("other_paxos", 0),
        },
        _ => ("other", 0),
    };
    println!("CA_EVENT {{\"event\":\"transport\",\"operation\":\"notify-original\",\"action\":\"{}\",\"from\":{},\"to\":{},\"kind\":\"{}\",\"round\":{}}}", action, message.get_sender(), message.get_receiver(), kind, round);
}
// Each producer's outgoing order is preserved; traffic to the isolated actor is
// deferred without modifying bytes. Core peers 2 and 3 continue normally.
fn pump_pair(n2: &mut Node, n3: &mut Node, deferred: &mut Vec<Message<Value>>) {
    let mut queue = VecDeque::new();
    queue.extend(take(n2)); queue.extend(take(n3));
    let mut steps = 0;
    while let Some(message) = queue.pop_front() {
        steps += 1; assert!(steps < 1000, "peer pump failed to quiesce");
        if message.get_receiver() == 1 {
            trace(&message, "defer"); deferred.push(message); continue;
        }
        trace(&message, "deliver");
        let target = if message.get_receiver() == 2 { &mut *n2 } else { &mut *n3 };
        target.handle_incoming(message); queue.extend(take(target));
    }
}
fn decided_value(node: &Node) -> Option<u64> {
    match node.read(0) { Some(LogEntry::Decided(Value(x))) => Some(x), _ => None }
}

#[tokio::test(flavor = "current_thread")]
async fn notify_after_replacement() {
    tokio::time::timeout(Duration::from_secs(20), scenario()).await.expect("scenario timeout");
}
async fn scenario() {
    // Prepare a real empty cluster. No storage state or protocol message is invented.
    let mut nodes = vec![build(1), build(2), build(3)];
    nodes[0].try_become_leader();
    let mut queue = VecDeque::new();
    for node in &mut nodes { queue.extend(take(node)); }
    let mut steps = 0;
    while let Some(message) = queue.pop_front() {
        steps += 1; assert!(steps < 1000);
        trace(&message, "deliver");
        let receiver = message.get_receiver() as usize - 1;
        nodes[receiver].handle_incoming(message);
        queue.extend(take(&mut nodes[receiver]));
    }
    assert_eq!(nodes[0].get_current_leader(), Some((1,true)));
    assert!(nodes.iter().all(|n| n.get_accepted_idx() == 0 && n.get_decided_idx() == 0));
    let old_ballot = nodes[0].get_promise();
    let mut n3 = nodes.pop().unwrap(); let mut n2 = nodes.pop().unwrap(); let n1 = nodes.pop().unwrap();
    let actor = spawn_actor::<_,_,TestRuntime>(n1, RuntimeConfig {
        tick_period: Duration::from_secs(5), egress_period: Duration::from_millis(1),
        append_notify_timeout: Duration::from_secs(15), ..Default::default()
    });
    let outgoing = actor.outgoing_messages();
    let events = actor.subscribe_events();
    let event_drain = tokio::spawn(async move { while events.recv().await.is_ok() {} });
    let call_handle = actor.clone();
    let call = tokio::spawn(async move { call_handle.append_notify(Value(101)).await });

    // While isolated, drain and discard the old leader's proposals. Wait for both
    // actual AcceptDecide messages containing the original value as admission evidence.
    let mut sent_to = Vec::new();
    while sent_to.len() < 2 {
        let message = outgoing.recv().await.unwrap();
        if let Message::SequencePaxos(p) = &message {
            if let PaxosMsg::AcceptDecide(a) = &p.msg {
                assert_eq!(a.n, old_ballot);
                assert_eq!(a.entries, vec![Value(101)]);
                assert!(!sent_to.contains(&p.to)); sent_to.push(p.to);
            }
        }
        trace(&message, "drop_isolated");
    }
    assert_eq!(actor.decided_idx().await, 0);
    assert_eq!(n2.get_accepted_idx(),0); assert_eq!(n3.get_accepted_idx(),0);
    println!("CA_EVENT {{\"event\":\"admitted\",\"operation\":\"notify-original\",\"payload\":101,\"old_round\":{},\"old_pid\":{},\"peers_empty\":true,\"origin_decided\":0,\"producer_observed\":true}}",old_ballot.n,old_ballot.pid);

    // A disjoint-from-origin majority elects a new leader and decides a replacement.
    let mut deferred = Vec::new();
    n2.try_become_leader(); pump_pair(&mut n2,&mut n3,&mut deferred);
    assert_eq!(n2.get_current_leader(),Some((2,true)));
    assert!(n2.get_promise() > old_ballot);
    assert_eq!(n2.get_accepted_idx(),0);
    n2.append(Value(202)).unwrap(); pump_pair(&mut n2,&mut n3,&mut deferred);
    assert_eq!(decided_value(&n2),Some(202)); assert_eq!(decided_value(&n3),Some(202));
    println!("CA_EVENT {{\"event\":\"replacement_chosen\",\"operation\":\"notify-original\",\"value\":202,\"round\":{},\"leader\":2,\"decided\":{}}}", n2.get_promise().n,n2.get_decided_idx());

    // Heal delivery to the actor. These are original queued messages. It processes
    // the new Prepare, emits Promise, then receives the leader's actual AcceptSync.
    for message in deferred.drain(..) { trace(&message,"deliver"); actor.handle_incoming(message).await; }
    let mut delivered_sync = false;
    while !delivered_sync {
        let message = outgoing.recv().await.unwrap();
        trace(&message,"deliver");
        match message.get_receiver() { 2 => n2.handle_incoming(message), 3 => n3.handle_incoming(message), _ => panic!("unexpected receiver") }
        pump_pair(&mut n2,&mut n3,&mut deferred);
        for message in deferred.drain(..) {
            if let Message::SequencePaxos(p) = &message {
                if let PaxosMsg::AcceptSync(s) = &p.msg {
                    assert_eq!(s.n,n2.get_promise()); assert_eq!(s.decided_idx,1);
                    assert_eq!(s.log_sync.suffix,vec![Value(202)]);
                    delivered_sync = true;
                }
            }
            trace(&message,"deliver"); actor.handle_incoming(message).await;
        }
    }
    // Read commands are serviced after the incoming queue is drained by the actor.
    let replacement = actor.read_decided_suffix(0).await.unwrap();
    assert!(matches!(replacement.as_slice(),[LogEntry::Decided(Value(202))]));
    println!("CA_EVENT {{\"event\":\"origin_replaced\",\"operation\":\"notify-original\",\"value\":202,\"decided\":{},\"pending_at_observation\":{}}}",actor.decided_idx().await,!call.is_finished());

    // Keep consuming all available outgoing messages and events while waiting for
    // the real periodic timer. No additional append or artificial tick is used.
    let route_actor = actor.clone();
    let route = tokio::spawn(async move {
        while let Ok(message) = outgoing.recv().await {
            trace(&message,"deliver");
            match message.get_receiver() { 2 => n2.handle_incoming(message), 3 => n3.handle_incoming(message), _ => panic!("unexpected receiver") }
            pump_pair(&mut n2,&mut n3,&mut deferred);
            for message in deferred.drain(..) { trace(&message,"deliver"); route_actor.handle_incoming(message).await; }
        }
    });
    let completion = call.await.unwrap();
    let (success,index,error_kind) = match completion {
        Ok(k) => (true,k,"none"),
        Err(AppendError::Superseded { log_entry_idx }) => (false,log_entry_idx,"superseded"),
        Err(AppendError::Timeout) => (false,0,"timeout"),
        Err(_) => (false,0,"other"),
    };
    let observed = actor.read_decided_suffix(index.saturating_sub(1)).await;
    let value = match observed.as_ref().and_then(|v| v.first()) {
        Some(LogEntry::Decided(Value(v))) => *v as i64, _ => -1,
    };
    println!("CA_EVENT {{\"event\":\"completion\",\"operation\":\"notify-original\",\"success\":{},\"returned_index\":{},\"decided_value\":{},\"error_kind\":\"{}\"}}",success,index,value,error_kind);
    route.abort(); let _ = route.await;
    drop(actor);
    event_drain.abort(); let _ = event_drain.await;
}
