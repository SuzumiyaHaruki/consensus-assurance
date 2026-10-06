from pathlib import Path
p=Path('explore_notify.rs').read_text()
p=p.replace('struct Runtime;','struct Runtime;\nstatic ACTOR: std::sync::Mutex<Option<tokio::task::JoinHandle<()>>> = std::sync::Mutex::new(None);')
p=p.replace('type JoinHandle = tokio::task::JoinHandle<()>;','type JoinHandle = ();')
p=p.replace('{ tokio::spawn(f) }','{ *ACTOR.lock().unwrap() = Some(tokio::spawn(f)); }')
p=p.replace('q.extend(v);','for m in v { println!("TRACE emitted {:?}", m); q.push_back(m); }')
p=p.replace('let to=m.get_receiver() as usize-1;', 'println!("TRACE route {:?}",m);let to=m.get_receiver() as usize-1;')
p=p.replace('async fn investigate_notification_after_replacement()', 'async fn check_notification_identity_after_replacement()')
p=p.replace('    let mut dropped=0;', '''    let mut dropped=0;
    let requested_value=101u64;''')
p=p.replace('            let m=out.recv().await.unwrap();','            let m=out.recv().await.unwrap();\n            println!("TRACE partition_drop {:?}",m);')
p=p.replace('    // Nodes 2 and 3 form', '''    println!("CA_EVENT {{\\"event\\":\\"admitted\\",\\"scenario\\":\\"replacement\\",\\"operation\\":\\"notify-A\\",\\"requested_value\\":{},\\"origin\\":1,\\"admitted\\":true}}", requested_value);
    // Nodes 2 and 3 form''')
p=p.replace('while let Ok(m)=out.try_recv(){q.push_back(m);}','while let Ok(m)=out.try_recv(){println!("TRACE actor_emitted {:?}",m);q.push_back(m);}')
start=p.index('    let result=tokio::time::timeout(Duration::from_secs(15),call)')
p=p[:start]+'''    // Keep the healed transport and raw-node clocks serviced until the actor
    // returns. Completion is read before shutdown; a wait failure is not a result.
    let raw_clock=tokio::time::sleep(Duration::from_secs(10));
    tokio::pin!(raw_clock);
    tokio::time::timeout(Duration::from_secs(15),async {
        loop {
            while let Ok(m)=out.try_recv(){println!("TRACE actor_emitted {:?}",m);q.push_back(m);}
            take_raw(&mut nodes,&mut q);
            while let Some(m)=q.pop_front(){
                println!("TRACE route {:?}",m);
                let to=m.get_receiver() as usize-1;
                if to==0 {h.handle_incoming(m).await;} else {nodes[to].as_mut().unwrap().handle_incoming(m);}
            }
            if call.is_finished(){break;}
            tokio::select! {
                _=&mut raw_clock=>{
                    for n in nodes.iter_mut().flatten(){n.tick();}
                    raw_clock.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(10));
                }
                _=tokio::time::sleep(Duration::from_millis(1))=>{}
            }
        }
    }).await.expect("notification must return a result within observation bound");
    let result=call.await.unwrap();
    let (ok,returned_index,error)=match result {
        Ok(idx)=>(true,idx,"none"),
        Err(omnipaxos_runtime::AppendError::Superseded{..})=>(false,0,"superseded"),
        Err(omnipaxos_runtime::AppendError::Timeout)=>(false,0,"timeout"),
        Err(omnipaxos_runtime::AppendError::Shutdown)=>(false,0,"shutdown"),
        Err(_)=>(false,0,"other"),
    };
    // All state reads are actor commands. No caller writes log values, injects
    // ballots/messages, or samples mutable protocol fields concurrently.
    let final_decided=h.decided_idx().await;
    let final_read=h.read_decided_suffix(0).await.unwrap();
    let final_values:Vec<u64>=final_read.iter().filter_map(|e|match e{LogEntry::Decided(v)=>Some(v.0),_=>None}).collect();
    // accepted_idx/decided_idx and runtime assignments are exclusive boundaries:
    // the assigned first entry has return value 1 and core read position 0.
    let actual_value=returned_index.checked_sub(1).and_then(|i|final_values.get(i)).map(|v|*v as i64).unwrap_or(-1);
    println!("CA_EVENT {{\\"event\\":\\"result\\",\\"scenario\\":\\"replacement\\",\\"operation\\":\\"notify-A\\",\\"completed\\":true,\\"ok\\":{},\\"returned_index\\":{},\\"error\\":\\"{}\\",\\"actual_value\\":{},\\"decided_idx\\":{},\\"decided_values\\":{:?}}}",ok,returned_index,error,actual_value,final_decided,final_values);
    drop(h);
    drop(out);
    let join=ACTOR.lock().unwrap().take().unwrap();
    tokio::time::timeout(Duration::from_secs(2),join).await.expect("actor shutdown").expect("actor did not panic");
    println!("CA_EVENT {{\\"event\\":\\"cleanup\\",\\"actor_joined\\":true}}");
}
'''
Path('check_notify.rs').write_text(p)
