use std::{future::Future, time::{Duration, Instant}};
use omnipaxos::{ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig};
use omnipaxos::messages::{Message, sequence_paxos::PaxosMsg};
use omnipaxos::storage::{Entry, Snapshot};
use omnipaxos::util::LogEntry;
use omnipaxos_storage::memory_storage::MemoryStorage;
use omnipaxos_runtime::{spawn_actor, AsyncRuntime, RuntimeConfig};
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)] struct V(u64);
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)] struct NoSnap(Vec<u64>);
impl Entry for V {type Snapshot=NoSnap;}
impl Snapshot<V> for NoSnap {
 fn create(e: &[V])->Self{NoSnap(e.iter().map(|v|v.0).collect())} fn merge(&mut self,d:Self){self.0.extend(d.0)} fn use_snapshots()->bool{true}
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
async fn subscription_preserves_compacted_cursor(){
 let mut nodes:Vec<N>=(1..=3).map(|pid|OmniPaxosConfig{
 cluster_config:ClusterConfig{configuration_id:1,nodes:vec![1,2,3],..Default::default()},server_config:ServerConfig{pid,batch_size:1,..Default::default()}
 }.build(MemoryStorage::default()).unwrap()).collect();
 nodes[0].try_become_leader();pump(&mut nodes,false);
 for v in 1..=4{nodes[0].append(V(v)).unwrap();pump(&mut nodes,false);}
 for n in &nodes{assert_eq!(n.get_decided_idx(),4);}
 nodes[0].snapshot(Some(3),true).unwrap();
 assert_eq!(nodes[0].get_compacted_idx(),3);
 let expected=nodes[0].read_decided_suffix(0).unwrap();assert_eq!(expected.len(),2);
 match &expected[0]{LogEntry::Snapshotted(s)=>{assert_eq!(s.trimmed_idx,3);assert_eq!(s.snapshot.0,vec![1,2,3]);},_=>panic!("snapshot needed")}
 match &expected[1]{LogEntry::Decided(v)=>assert_eq!(v.0,4),_=>panic!("tail needed")}
 let core=nodes.remove(0);
 let h=spawn_actor::<V,MemoryStorage<V>,Rt>(core,RuntimeConfig{tick_period:Duration::from_millis(20),..Default::default()});
 let rx=h.subscribe_decided(0).await;
 let first=tokio::time::timeout(Duration::from_secs(1),rx.recv()).await.unwrap().unwrap();
 let second=tokio::time::timeout(Duration::from_secs(1),rx.recv()).await.unwrap().unwrap();
 match first{LogEntry::Snapshotted(s)=>{assert_eq!(s.trimmed_idx,3);assert_eq!(s.snapshot.0,vec![1,2,3]);},_=>panic!("first item")}
 match second{LogEntry::Decided(v)=>assert_eq!(v.0,4),_=>panic!("second item")}
 println!("CA_EVENT {{\"event\":\"backlog_consumed\",\"subscription\":1,\"decided\":4,\"prefix_end\":3,\"logical_end\":4}}");
 let extra=tokio::time::timeout(Duration::from_millis(200),rx.recv()).await;
 let extra_delivered=match extra{Ok(Ok(item))=>{println!("TRACE extra item {:?}",item);true},Ok(Err(_))=>panic!("unexpected closure"),Err(_)=>false};
 let final_decided=h.decided_idx().await;assert_eq!(final_decided,4);
 println!("CA_EVENT {{\"event\":\"stream_sample\",\"subscription\":1,\"completed\":true,\"extra_delivered\":{},\"final_decided\":{}}}",extra_delivered,final_decided);
 drop(rx);drop(h);
}
