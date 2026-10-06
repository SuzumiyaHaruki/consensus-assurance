use std::{future::Future, time::{Duration, Instant}};
use omnipaxos::{ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::storage::{Entry, Snapshot};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, RuntimeConfig};
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)] struct V(u64);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)] struct NoSnap;
impl Entry for V {type Snapshot=NoSnap;}
impl Snapshot<V> for NoSnap {
 fn create(_: &[V])->Self{NoSnap} fn merge(&mut self,_:Self){} fn use_snapshots()->bool{false}
}
struct Rt;
impl AsyncRuntime for Rt {
 type JoinHandle=tokio::task::JoinHandle<()>;
 fn spawn<F:Future<Output=()>+Send+'static>(f:F)->Self::JoinHandle{tokio::spawn(f)}
 fn sleep(d:Duration)->impl Future<Output=()>+Send+'static{tokio::time::sleep(d)}
}
type N=OmniPaxos<V,MemoryStorage<V>>;
fn pump(nodes:&mut [N], isolate_one:bool){
 for _ in 0..100 {
  let mut messages=vec![];
  for n in nodes.iter_mut(){n.take_outgoing_messages(&mut messages);}
  if messages.is_empty(){return;}
  for m in messages {
   let from=m.get_sender();let to=m.get_receiver();
   let drop=isolate_one&&(from==1||to==1);
   println!("TRACE from={} to={} dropped={} {:?}",from,to,drop,m);
   if !drop {nodes[(to-1)as usize].handle_incoming(m);}
  }
 }
 panic!("delivery bound");
}
#[tokio::test(flavor="current_thread")]
async fn notify_does_not_confirm_replacement(){
 let mut nodes:Vec<N>=(1..=3).map(|pid|OmniPaxosConfig{
  cluster_config:ClusterConfig{configuration_id:1,nodes:vec![1,2,3],..Default::default()},
  server_config:ServerConfig{pid,batch_size:1,..Default::default()},
 }.build(MemoryStorage::default()).unwrap()).collect();
 nodes[0].try_become_leader();pump(&mut nodes,false);
 for n in &nodes{assert_eq!(n.get_current_leader(),Some((1,true)));assert_eq!(n.get_decided_idx(),0);}
 // Keep the vector indexed by node id while moving the real node 1 into its actor.
 let placeholder=OmniPaxosConfig{cluster_config:ClusterConfig{configuration_id:1,nodes:vec![1,2,3],..Default::default()},server_config:ServerConfig{pid:1,..Default::default()}}.build(MemoryStorage::default()).unwrap();
 let old=std::mem::replace(&mut nodes[0],placeholder);
 // The unused placeholder is never delivered protocol traffic; discard its startup output.
 let mut discard=vec![];nodes[0].take_outgoing_messages(&mut discard);
 let old_ballot=old.get_promise();
 let start=Instant::now();
 let h=spawn_actor::<V,MemoryStorage<V>,Rt>(old,RuntimeConfig{tick_period:Duration::from_secs(5),egress_period:Duration::from_millis(1),append_notify_timeout:Duration::from_secs(20),..Default::default()});
 let out=h.outgoing_messages();
 let nh=h.clone();let notify=tokio::spawn(async move{nh.append_notify(V(42)).await});
 // Isolate old leader's outgoing acceptance. Its two real messages establish admission.
 let mut rejected=0;
 while rejected<2 {
  let m=tokio::time::timeout(Duration::from_secs(2),out.recv()).await.unwrap().unwrap();
  println!("TRACE isolated {:?}",m);
  if let Message::SequencePaxos(p)=&m {if let PaxosMsg::AcceptDecide(a)=&p.msg {assert_eq!(a.entries.len(),1);assert_eq!(a.entries[0].0,42);rejected+=1;}}
 }
 assert!(!notify.is_finished());
 println!("CA_EVENT {{\"event\":\"notify_admitted\",\"case\":\"replacement_before_drain\",\"operation\":1,\"proposed\":42,\"old_ballot_n\":{},\"isolated_accept_messages\":{}}}",old_ballot.n,rejected);
 // Nodes 2 and 3 have never received 42. Form a new quorum and decide 99 at slot 1.
 nodes[1].try_become_leader();pump(&mut nodes,true);
 assert_eq!(nodes[1].get_current_leader(),Some((2,true)));
 nodes[1].append(V(99)).unwrap();pump(&mut nodes,true);
 assert_eq!(nodes[1].get_decided_idx(),1);assert_eq!(nodes[2].get_decided_idx(),1);
 let new_ballot=nodes[1].get_promise();assert!(new_ballot>old_ballot);
 // Restore the connection. Core 2 and actor 1 each receive the appropriate callback.
 nodes[1].reconnected(1);h.reconnected(2).await;
 let mut synced=false;
 for _ in 0..20 {
  let mut messages=vec![];
  nodes[1].take_outgoing_messages(&mut messages);nodes[2].take_outgoing_messages(&mut messages);
  for m in messages {
   let to=m.get_receiver();println!("TRACE restored {:?}",m);
   if to==1 {h.handle_incoming(m).await;}else{nodes[(to-1)as usize].handle_incoming(m);}
  }
  // This command is processed after the already-enqueued incoming messages.
  if h.decided_idx().await==1 {synced=true;break;}
  let m=tokio::time::timeout(Duration::from_secs(2),out.recv()).await.unwrap().unwrap();
  println!("TRACE actor {:?}",m);
  let to=m.get_receiver();nodes[(to-1)as usize].handle_incoming(m);
 }
 assert!(synced);assert_eq!(h.current_leader().await,Some((2,true)));
 let read=h.read_decided_suffix(0).await.unwrap();
 assert_eq!(read.len(),1);let replacement=match &read[0]{LogEntry::Decided(v)=>v.0,_=>panic!("expected decided replacement")};assert_eq!(replacement,99);
 assert!(start.elapsed()<Duration::from_secs(4),"Setup must complete before first five-second tick");
 println!("CA_EVENT {{\"event\":\"replacement_observed\",\"case\":\"replacement_before_drain\",\"operation\":1,\"new_ballot_n\":{},\"decided\":1,\"replacement\":{},\"setup_ms\":{}}}",new_ballot.n,replacement,start.elapsed().as_millis());
 let result=tokio::time::timeout(Duration::from_secs(7),notify).await.expect("missing operation completion").unwrap();
 let (success,idx)=match &result{Ok(idx)=>(true,*idx),Err(_)=>(false,0)};
 let final_read=h.read_decided_suffix(0).await.unwrap();
 let at_slot=if success {match final_read.get(idx-1){Some(LogEntry::Decided(v))=>v.0,_=>panic!("successful index has no decided content")}}else{replacement};
 println!("CA_EVENT {{\"event\":\"notify_result\",\"case\":\"replacement_before_drain\",\"operation\":1,\"completed\":true,\"success\":{},\"index\":{},\"content_at_index\":{}}}",success,idx,at_slot);
 println!("TRACE notification {:?}",result);
 drop(out);drop(h);
}
