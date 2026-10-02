from pathlib import Path
s=Path('quorum_storage_test.go').read_text().replace('    "bytes"\n','');s=s[:s.index('func TestAssuranceDelayedLeaderStorageQuorum')]
s=s.replace('    phase string\n','    phase string\n    heldVotes []pb.Message\n    currentTerm uint64\n    delivered map[uint64]bool\n')
needle='            if err := c.nodes[msg.To-1].Step(msg); err != nil { c.t.Fatal(err) }'
s=s.replace(needle,'''            if msg.Type==pb.MsgVoteResp && msg.To==1 {
                hs,_,err:=c.stores[msg.From-1].InitialState();if err!=nil {c.t.Fatal(err)}
                if msg.Reject || hs.Term!=msg.Term || hs.Vote!=1 {c.t.Fatal("grant lacks matching completed vote at capture")}
                c.heldVotes=append(c.heldVotes,msg)
                assuranceEmit(map[string]interface{}{"event":"grant_captured","request":c.request,"from":msg.From,"term":msg.Term,"stored_term":hs.Term,"stored_vote":hs.Vote})
            } else {c.deliver(msg)}''')
s+='''
func (c *assuranceStorageCluster) deliver(msg pb.Message) {
    if msg.Type==pb.MsgVoteResp && msg.To==1 && !msg.Reject && msg.Term==c.currentTerm {c.delivered[msg.From]=true}
    assuranceEmit(map[string]interface{}{"event":"actual_delivery","request":c.request,"phase":c.phase,"from":msg.From,"to":msg.To,"type":msg.Type.String(),"term":msg.Term})
    if err:=c.nodes[msg.To-1].Step(msg);err!=nil {c.t.Fatal(err)}
}
func (c *assuranceStorageCluster) release(term,from uint64) {
    for i,m:=range c.heldVotes {
        if m.Term==term && m.From==from {
            c.heldVotes=append(c.heldVotes[:i],c.heldVotes[i+1:]...)
            c.deliver(m)
            return
        }
    }
    c.t.Fatalf("missing actual grant term=%d from=%d",term,from)
}
func TestAssuranceDelayedElectionGrants(t *testing.T) {
    c:=&assuranceStorageCluster{t:t,request:"consecutive-campaigns-1",phase:"bootstrap",delivered:map[uint64]bool{}}
    all:=[3]bool{true,true,true}
    peers:=[]Peer{{ID:1},{ID:2},{ID:3}}
    for i:=0;i<3;i++ {
        c.stores[i]=NewMemoryStorage()
        n,err:=NewRawNode(&Config{ID:uint64(i+1),Storage:c.stores[i],ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:1<<20,MaxInflightMsgs:8,AsyncStorageWrites:true,Logger:discardLogger})
        if err!=nil {t.Fatal(err)}
        c.nodes[i]=n
        if err=n.Bootstrap(peers);err!=nil {t.Fatal(err)}
    }
    c.drain(all)
    c.phase="first_campaign"
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    oldTerm:=c.nodes[0].BasicStatus().Term
    c.drain(all)
    if len(c.heldVotes)!=3 || c.nodes[0].BasicStatus().RaftState!=StateCandidate {t.Fatal("first campaign prefix missing")}
    c.phase="second_campaign"
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.currentTerm=c.nodes[0].BasicStatus().Term
    c.drain(all)
    if len(c.heldVotes)!=6 || c.currentTerm!=oldTerm+1 || c.nodes[0].BasicStatus().RaftState!=StateCandidate {t.Fatal("second campaign prefix missing")}
    phases:=[]struct{name string;term,from uint64}{
        {"old_self",oldTerm,1},{"old_peer_2",oldTerm,2},{"old_peer_3",oldTerm,3},
        {"current_self",c.currentTerm,1},{"current_peer_2",c.currentTerm,2},{"current_peer_3",c.currentTerm,3},
    }
    for _,p:=range phases {
        c.phase=p.name
        assuranceEmit(map[string]interface{}{"event":"vote_phase_admitted","request":c.request,"phase":p.name,"node":1,"campaign_term":c.currentTerm,"prefix_ready":true,"released_term":p.term,"released_sender":p.from})
        c.release(p.term,p.from)
        c.drain(all)
        st:=c.nodes[0].BasicStatus()
        assuranceEmit(map[string]interface{}{"event":"election_observed","request":c.request,"phase":p.name,"node":1,"campaign_term":c.currentTerm,"actual_term":st.Term,"role":st.RaftState.String(),"leader":st.RaftState==StateLeader,"current_grants":len(c.delivered),"current_majority":len(c.delivered)>=2,"senders":c.delivered,"held_grants":len(c.heldVotes),"schedule_complete":true})
    }
    assuranceEmit(map[string]interface{}{"event":"history_finished","request":c.request,"campaign_term":c.currentTerm,"held_grants":len(c.heldVotes)})
}
'''
# A popped item is not yet delivered when it will enter the holding queue.
s=s.replace('"event":"message_delivered"','"event":"message_dequeued"')
Path('delayed_vote_test.go').write_text(s)
