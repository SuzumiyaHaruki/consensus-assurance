use std::{collections::VecDeque, future::Future, time::{Duration, Instant}};
use omnipaxos::{OmniPaxos, OmniPaxosConfig, ClusterConfig, ServerConfig,
    storage::{Entry, NoSnapshot}, util::LogEntry,
    messages::{Message, async_runtime::AsyncRuntimeMsg, sequence_paxos::PaxosMsg}};
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, OmniPaxosHandle, RuntimeConfig};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct Value(u64);
impl Entry for Value { type Snapshot = NoSnapshot; }
struct Runtime;
impl AsyncRuntime for Runtime {
    type JoinHandle = tokio::task::JoinHandle<()>;
    fn spawn<F: Future<Output=()> + Send + 'static>(f: F) -> Self::JoinHandle { tokio::spawn(f) }
    fn sleep(d: Duration) -> impl Future<Output=()> + Send + 'static { tokio::time::sleep(d) }
}
type Core = OmniPaxos<Value, MemoryStorage<Value>>;
type Handle = OmniPaxosHandle<Value>;

fn build(pid: u64) -> Core {
    OmniPaxosConfig {
        cluster_config: ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], ..Default::default() },
        server_config: ServerConfig { pid, batch_size: 1, election_tick_timeout: 100_000,
            resend_message_tick_timeout: 100_000, flush_batch_tick_timeout: 10,
            ..Default::default() },
    }.build(MemoryStorage::default()).unwrap()
}

// One caller-owned FIFO per directed link, shared by setup and the actor phase.
struct Network {
    queues: Vec<VecDeque<Message<Value>>>,
    old_links_open: bool,
    proposal_route_open: bool,
    release_to_origin: bool,
    entry_id: Option<String>,
    assignment: Option<(String, usize, u32)>,
    old_value_emitted: bool,
    replacement_ballot: Option<u32>,
}
impl Network {
    fn new() -> Self { Self { queues: (0..9).map(|_|VecDeque::new()).collect(),
        old_links_open:true, proposal_route_open:true, release_to_origin:false,
        entry_id:None,assignment:None,old_value_emitted:false,replacement_ballot:None } }
    fn enqueue(&mut self, m: Message<Value>) {
        let from=m.get_sender(); let to=m.get_receiver();
        if let Message::AsyncRuntime(a)=&m {
            match &a.msg {
                AsyncRuntimeMsg::TaggedProposal{entries} if from==2 && to==1 => {
                    assert_eq!(entries.len(),1);
                    assert_eq!(entries[0].1,Value(101));
                    let id=entries[0].0.0.to_string();
                    assert!(self.entry_id.is_none());
                    println!("CA_EVENT {{\"event\":\"admitted\",\"op_id\":\"old-request\",\"entry_id\":\"{}\",\"proposed\":101,\"origin\":2,\"old_leader\":1}}",id);
                    self.entry_id=Some(id);
                }
                AsyncRuntimeMsg::Assigned{ballot,entries} if from==1 && to==2 => {
                    assert_eq!(entries.len(),1);
                    let id=entries[0].0.0.to_string();
                    assert_eq!(Some(&id),self.entry_id.as_ref());
                    self.assignment=Some((id.clone(),entries[0].1,ballot.n));
                    println!("CA_EVENT {{\"event\":\"assigned_held\",\"op_id\":\"old-request\",\"entry_id\":\"{}\",\"assigned_idx\":{},\"old_ballot\":{}}}",id,entries[0].1,ballot.n);
                }
                _=>{}
            }
        }
        if let Message::SequencePaxos(p)=&m {
            match &p.msg {
                PaxosMsg::AcceptDecide(a) if from==1 => {
                    if a.entries.iter().any(|v|v.0==101) { self.old_value_emitted=true; }
                }
                PaxosMsg::AcceptDecide(a) if from==3 => {
                    if a.entries.iter().any(|v|v.0==202) { self.replacement_ballot=Some(a.n.n); }
                }
                _=>{}
            }
        }
        self.queues[((from-1)*3+to-1) as usize].push_back(m);
    }
    fn allowed(&self, from:u64,to:u64)->bool {
        self.old_links_open || (from!=1 && to!=1) ||
        (self.proposal_route_open && from==2 && to==1) ||
        (self.release_to_origin && from==1 && to==2)
    }
    fn ready(&mut self)->Vec<Message<Value>> {
        let mut out=Vec::new();
        for from in 1..=3 { for to in 1..=3 {
            if self.allowed(from,to) { out.extend(self.queues[((from-1)*3+to-1) as usize].drain(..)); }
        }}
        out
    }
    async fn pump(&mut self, h:&[Handle]) {
        for handle in h {
            let out=handle.outgoing_messages();
            while let Ok(m)=out.try_recv() { self.enqueue(m); }
            let events=handle.subscribe_events();
            while events.try_recv().is_ok() {}
        }
        for m in self.ready() { h[(m.get_receiver()-1) as usize].handle_incoming(m).await; }
        tokio::time::sleep(Duration::from_millis(2)).await;
    }
}

#[tokio::test(flavor="current_thread")]
async fn genuine_delayed_assignment_after_replacement() {
    let mut core:Vec<Core>=(1..=3).map(build).collect();
    let mut net=Network::new();
    core[0].try_become_leader();
    // No proposals yet. Fully drain this fault-free initialization prefix.
    for _ in 0..100 {
        for c in &mut core {
            let mut out=Vec::new(); c.take_outgoing_messages(&mut out);
            for m in out { net.enqueue(m); }
        }
        let ready=net.ready();
        if ready.is_empty() { break; }
        for m in ready { core[(m.get_receiver()-1) as usize].handle_incoming(m); }
    }
    assert!(net.queues.iter().all(|q|q.is_empty()));
    for c in &core {
        assert_eq!(c.get_current_leader(),Some((1,true)));
        assert_eq!(c.get_decided_idx(),0); assert_eq!(c.get_accepted_idx(),0);
    }
    println!("CA_EVENT {{\"event\":\"setup\",\"op_id\":\"old-request\",\"leader\":1,\"empty\":true,\"nodes\":3}}");
    let cfg=RuntimeConfig { tick_period:Duration::from_millis(10),
        egress_period:Duration::from_millis(1), append_notify_timeout:Duration::from_secs(20),
        ..Default::default() };
    let h:Vec<Handle>=core.into_iter().map(|c|spawn_actor::<_,_,Runtime>(c,cfg.clone())).collect();
    net.old_links_open=false;
    let origin=h[1].clone();
    let pending=tokio::spawn(async move {origin.append_notify(Value(101)).await});
    let start=Instant::now();
    while net.assignment.is_none() || !net.old_value_emitted {
        assert!(start.elapsed()<Duration::from_secs(3),"old assignment/append prerequisite missing");
        net.pump(&h).await;
    }
    net.proposal_route_open=false;
    let (id,assigned_idx,old_ballot)=net.assignment.clone().unwrap();
    assert_eq!(assigned_idx,1);
    assert!(!pending.is_finished(),"request completed before assignment delivery");
    assert_eq!(h[1].decided_idx().await,0);
    assert_eq!(h[2].decided_idx().await,0);
    println!("CA_EVENT {{\"event\":\"old_unreplicated\",\"op_id\":\"old-request\",\"entry_id\":\"{}\",\"accepted_message_observed\":true,\"old_outbound_delivered\":0}}",id);
    h[2].try_become_leader().await;
    let start=Instant::now();
    loop {
        net.pump(&h).await;
        if h[2].current_leader().await==Some((3,true)) && h[1].current_leader().await==Some((3,true)) { break; }
        assert!(start.elapsed()<Duration::from_secs(3),"new leader prerequisite missing");
    }
    h[2].append(Value(202)).await.unwrap();
    let start=Instant::now();
    while h[1].decided_idx().await<1 || h[2].decided_idx().await<1 {
        assert!(start.elapsed()<Duration::from_secs(3),"replacement decision prerequisite missing");
        net.pump(&h).await;
    }
    let replacement=h[1].read_decided_suffix(0).await.unwrap();
    assert!(matches!(&replacement[0],LogEntry::Decided(Value(202))));
    let new_ballot=net.replacement_ballot.expect("replacement producer not observed");
    assert!(new_ballot>old_ballot);
    assert!(!pending.is_finished(),"unassigned pending call did not survive transition");
    println!("CA_EVENT {{\"event\":\"replacement_decided\",\"op_id\":\"old-request\",\"entry_id\":\"{}\",\"assigned_idx\":{},\"observed\":202,\"new_ballot\":{},\"old_ballot\":{},\"pending\":true}}",id,assigned_idx,new_ballot,old_ballot);
    // Release the whole old-leader -> origin FIFO, including any preceding messages.
    net.release_to_origin=true;
    let start=Instant::now();
    while !pending.is_finished() && start.elapsed()<Duration::from_secs(2) { net.pump(&h).await; }
    if pending.is_finished() {
        let result=pending.await.unwrap();
        let (success,returned_idx,status)=match result {
            Ok(i)=>(true,i,"ok"),
            Err(omnipaxos_runtime::AppendError::Superseded{log_entry_idx})=>(false,log_entry_idx,"superseded"),
            Err(omnipaxos_runtime::AppendError::Timeout)=>(false,0,"timeout"),
            Err(_)=>(false,0,"other_error"),
        };
        let index=if success {returned_idx.checked_sub(1).expect("invalid returned position")} else {assigned_idx-1};
        let observed=h[1].read_decided_suffix(index).await.unwrap();
        let observed_value=match &observed[0] {LogEntry::Decided(v)=>v.0,_=>panic!("result log entry not decided")};
        println!("CA_EVENT {{\"event\":\"completion\",\"op_id\":\"old-request\",\"entry_id\":\"{}\",\"success\":{},\"returned_idx\":{},\"status\":\"{}\",\"observed_value\":{},\"decided_idx\":{}}}",id,success,returned_idx,status,observed_value,h[1].decided_idx().await);
    } else {
        println!("CA_EVENT {{\"event\":\"bounded_pending\",\"op_id\":\"old-request\",\"entry_id\":\"{}\"}}",id);
        pending.abort();
        let _=pending.await;
    }
    drop(h); // Runtime shutdown also cancels any actor still blocked in its select loop.
}
