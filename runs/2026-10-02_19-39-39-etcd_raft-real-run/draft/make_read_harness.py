p=open('quorum_storage_test.go').read()
p=p[:p.index('func TestAssuranceDelayedLeaderStorageQuorum')]
p=p.replace('    "bytes"\n','').replace('[3]','[5]').replace('i<3','i<5').replace('msg.To>3','msg.To>5')
p=p.replace('    phase string\n','''    phase string
    held map[uint64][]pb.Message
    delivered map[uint64]bool
    outputs []ReadState
''')
p=p.replace('    rd := n.Ready()','''    rd := n.Ready()
    for _, rs := range rd.ReadStates {
        if i == 0 && string(rs.RequestCtx) == c.request {
            c.outputs = append(c.outputs, rs)
            assuranceEmit(map[string]interface{}{"event":"read_output", "request":c.request,"phase":c.phase,"index":rs.Index,"context":string(rs.RequestCtx),"incoming_count":c.count([]uint64{1,4,5}),"outgoing_count":c.count([]uint64{1,2,3,4,5})})
        }
    }''')
p=p.replace('            if msg.To<1', '''            if msg.Type == pb.MsgHeartbeatResp && msg.To == 1 && string(msg.Context) == c.request {
                c.held[msg.From] = append(c.held[msg.From], msg)
                assuranceEmit(map[string]interface{}{"event":"reply_held","request":c.request,"phase":c.phase,"from":msg.From,"term":msg.Term,"context":string(msg.Context)})
                work=true
                continue
            }
            if msg.To<1''')
p+='''
func (c *assuranceStorageCluster) count(ids []uint64) int {
    n:=0
    for _,id:=range ids { if c.delivered[id] {n++} }
    return n
}

func (c *assuranceStorageCluster) release(id uint64) {
    msgs:=c.held[id]
    if len(msgs)==0 {c.t.Fatalf("missing produced reply from %d",id)}
    delete(c.held,id)
    for _,msg:=range msgs {
        c.delivered[id]=true
        assuranceEmit(map[string]interface{}{"event":"reply_released","request":c.request,"phase":c.phase,"from":id,"term":msg.Term,"context":string(msg.Context)})
        if err:=c.nodes[0].Step(msg);err!=nil {c.t.Fatal(err)}
    }
}

func TestAssuranceReadSupportAcrossJointChange(t *testing.T) {
    c:=&assuranceStorageCluster{t:t,request:"unique-read-joint-1",phase:"prefix",held:map[uint64][]pb.Message{},delivered:map[uint64]bool{}}
    peers:=[]Peer{{ID:1},{ID:2},{ID:3},{ID:4},{ID:5}}
    all:=[5]bool{true,true,true,true,true}
    for i:=0;i<5;i++ {
        c.stores[i]=NewMemoryStorage()
        n,err:=NewRawNode(&Config{ID:uint64(i+1),Storage:c.stores[i],ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:1<<20,MaxInflightMsgs:8,AsyncStorageWrites:true,ReadOnlyOption:ReadOnlySafe,Logger:discardLogger})
        if err!=nil {t.Fatal(err)}
        c.nodes[i]=n
        if err=n.Bootstrap(peers);err!=nil {t.Fatal(err)}
    }
    c.drain(all)
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.drain(all)
    r:=c.nodes[0].raft
    prefix:=r.raftLog.lastIndex()
    if r.state!=StateLeader || !r.committedEntryInCurrentTerm() {t.Fatal("election/current-term prefix missing")}
    for i:=0;i<5;i++ {
        last,err:=c.stores[i].LastIndex();if err!=nil {t.Fatal(err)}
        if last!=prefix || c.nodes[i].raft.raftLog.committed!=prefix || c.applied[i]!=prefix {t.Fatalf("prefix incomplete at node %d",i+1)}
    }
    originalTerm:=r.Term
    c.phase="read_requested"
    // Local dispatch supplies self participation. Remote participation is recorded
    // only at actual delivery below, independently from readOnly.acks.
    c.nodes[0].ReadIndex([]byte(c.request))
    c.delivered[1]=true
    c.drain(all)
    for id:=uint64(2);id<=5;id++ {if len(c.held[id])!=1 {t.Fatalf("expected one produced response from %d",id)}}
    c.phase="configuration_applied"
    cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointExplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:2},{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
    if err:=c.nodes[0].ProposeConfChange(cc);err!=nil {t.Fatal(err)}
    changeIndex:=r.raftLog.lastIndex()
    c.drain(all)
    cs:=r.trk.ConfState()
    has:=func(ids []uint64,id uint64)bool{for _,x:=range ids {if x==id{return true}};return false}
    if len(cs.Voters)!=3 || !has(cs.Voters,1) || !has(cs.Voters,4) || !has(cs.Voters,5) || len(cs.VotersOutgoing)!=5 || cs.AutoLeave {t.Fatalf("joint configuration prerequisite not reached: %+v",cs)}
    if r.Term!=originalTerm || r.state!=StateLeader || c.applied[0]!=changeIndex {t.Fatal("authority/configuration prefix not reached")}
    assuranceEmit(map[string]interface{}{"event":"joint_prefix","request":c.request,"term":r.Term,"change_index":changeIndex,"voters":cs.Voters,"outgoing":cs.VotersOutgoing,"pre_joint_outputs":len(c.outputs),"applied":c.applied[0]})
    phases:=[]struct{name string;release uint64}{
        {"self_only",0},
        {"one_outgoing_reply",2},
        {"outgoing_majority_only",3},
        {"both_majorities",4},
        {"remaining_reply",5},
    }
    for _,p:=range phases {
        c.phase=p.name
        assuranceEmit(map[string]interface{}{"event":"read_phase_admitted","request":c.request,"phase":p.name,"joint_applied":true,"term":r.Term,"change_index":changeIndex})
        if p.release!=0 {c.release(p.release)}
        c.drain(all)
        in,out:=c.count([]uint64{1,4,5}),c.count([]uint64{1,2,3,4,5})
        var index uint64
        if len(c.outputs)>0 {index=c.outputs[0].Index}
        assuranceEmit(map[string]interface{}{"event":"read_support_observed","request":c.request,"phase":p.name,"read_emitted":len(c.outputs)>0,"read_count":len(c.outputs),"read_index":index,"incoming_count":in,"outgoing_count":out,"both_majorities":in>=2 && out>=3,"leader_term":r.Term,"leader_role":r.state.String(),"leader_commit":r.raftLog.committed,"leader_applied":c.applied[0],"schedule_complete":true})
    }
    assuranceEmit(map[string]interface{}{"event":"read_history_finished","request":c.request,"read_count":len(c.outputs),"held_replies":len(c.held)})
}
'''
open('read_joint_test.go','w').write(p)
