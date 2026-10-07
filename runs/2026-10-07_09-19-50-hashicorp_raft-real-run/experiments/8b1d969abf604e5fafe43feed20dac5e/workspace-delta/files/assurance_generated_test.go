package raft

import (
    "encoding/json"
    "fmt"
    "sync"
    "testing"
    "time"

    "github.com/hashicorp/go-hclog"
)

// The policy substitutes only transport loss. Vote RPCs and delivered append
// RPCs use the existing in-memory transport and the target's real RPC handler.
type assuranceVerifyTransport struct {
    *InmemTransport
    denyVoterAppend bool
    voters map[ServerID]bool
    mu sync.Mutex
    voterSuccess int
    nonvoterSuccess int
    voterDropped int
}
func (x *assuranceVerifyTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
    return nil, ErrPipelineReplicationNotSupported
}
func (x *assuranceVerifyTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
    if x.denyVoterAppend && x.voters[id] {
        x.mu.Lock(); x.voterDropped++; x.mu.Unlock()
        return fmt.Errorf("exploration policy drops AppendEntries to voter %s", id)
    }
    err := x.InmemTransport.AppendEntries(id, addr, req, resp)
    if err == nil && resp.Success {
        x.mu.Lock()
        if x.voters[id] { x.voterSuccess++ } else { x.nonvoterSuccess++ }
        x.mu.Unlock()
    }
    return err
}
func (x *assuranceVerifyTransport) counts() (int,int,int) {
    x.mu.Lock(); defer x.mu.Unlock()
    return x.voterSuccess,x.nonvoterSuccess,x.voterDropped
}
func assuranceVerifyEvent(v map[string]interface{}) {
    b, err := json.Marshal(v); if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(b))
}
func TestAssuranceVerifyExplore(t *testing.T) {
    for _, deny := range []bool{false,true} {
        name := "connected_control"; if deny { name="voter_append_loss" }
        t.Run(name,func(t *testing.T) {
            configuration := Configuration{}
            voters := map[ServerID]bool{}
            transports := make([]*assuranceVerifyTransport,4)
            for i:=0;i<4;i++ {
                id:=ServerID(fmt.Sprintf("node-%d",i)); addr:=ServerAddress(id)
                suffrage:=Voter; if i==3 { suffrage=Nonvoter } else { voters[id]=true }
                configuration.Servers=append(configuration.Servers,Server{ID:id,Address:addr,Suffrage:suffrage})
                _, base:=NewInmemTransportWithTimeout(addr,100*time.Millisecond)
                transports[i]=&assuranceVerifyTransport{InmemTransport:base,denyVoterAppend:deny,voters:voters}
            }
            for i:=range transports { for j:=range transports { if i!=j {
                transports[i].Connect(transports[j].LocalAddr(),transports[j].InmemTransport)
            } } }
            nodes:=make([]*Raft,0,4)
            defer func() {
                shutdowns:=make([]Future,0,len(nodes))
                for _,r:=range nodes { shutdowns=append(shutdowns,r.Shutdown()) }
                for _,f:=range shutdowns { if err:=f.Error();err!=nil { t.Errorf("shutdown: %v",err) } }
                for _,tr:=range transports { if err:=tr.Close();err!=nil {t.Errorf("transport close: %v",err)} }
                assuranceVerifyEvent(map[string]interface{}{"event":"cleanup","scenario":name,"nodes":len(nodes)})
            }()
            for i:=range transports {
                cfg:=DefaultConfig();cfg.LocalID=configuration.Servers[i].ID
                cfg.HeartbeatTimeout=300*time.Millisecond;cfg.ElectionTimeout=300*time.Millisecond
                cfg.LeaderLeaseTimeout=300*time.Millisecond;cfg.CommitTimeout=20*time.Millisecond
                cfg.Logger=hclog.NewNullLogger()
                store:=NewInmemStore();snaps:=NewInmemSnapshotStore()
                if err:=BootstrapCluster(cfg,store,store,snaps,transports[i],configuration);err!=nil { t.Fatal(err) }
                r,err:=NewRaft(cfg,&MockFSM{},store,store,snaps,transports[i]);if err!=nil {t.Fatal(err)}
                nodes=append(nodes,r)
            }
            leaderIndex:=-1
            deadline:=time.Now().Add(5*time.Second)
            for time.Now().Before(deadline) && leaderIndex<0 {
                for i,r:=range nodes { if r.State()==Leader {leaderIndex=i;break} }
                if leaderIndex<0 {time.Sleep(time.Millisecond)}
            }
            if leaderIndex<0 {t.Fatal("no elected leader reached")}
            leader:=nodes[leaderIndex];tr:=transports[leaderIndex]
            term:=leader.CurrentTerm()
            v0,n0,d0:=tr.counts()
            assuranceVerifyEvent(map[string]interface{}{"event":"admission","scenario":name,"leader":string(leader.localID),"term":term,"voters":3,"nonvoters":1,"deny_voter_append":deny,"voter_success_before":v0,"nonvoter_success_before":n0,"dropped_before":d0})
            f:=leader.VerifyLeader()
            result:=make(chan error,1)
            go func(){result<-f.Error()}()
            var err error
            select {
            case err=<-result:
                v,n,d:=tr.counts()
                errorText:="";if err!=nil {errorText=err.Error()}
                assuranceVerifyEvent(map[string]interface{}{"event":"result","scenario":name,"leader":string(leader.localID),"admission_term":term,"current_term":leader.CurrentTerm(),"state":leader.State().String(),"success":err==nil,"error":errorText,"voter_success_total":v,"nonvoter_success_total":n,"dropped_total":d})
            case <-time.After(3*time.Second):
                // Timeout is a diagnostic, not evidence of a protocol deadline.
                assuranceVerifyEvent(map[string]interface{}{"event":"observation_timeout","scenario":name})
                shutdown:=leader.Shutdown();if e:=shutdown.Error();e!=nil {t.Error(e)}
                <-result
            }
        })
    }
}
