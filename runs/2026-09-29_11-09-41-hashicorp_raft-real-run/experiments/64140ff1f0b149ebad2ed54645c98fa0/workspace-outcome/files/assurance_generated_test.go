package raft

import (
    "encoding/json"
    "fmt"
    "io"
    "sync"
    "testing"
    "time"
)

// The transport retains the real in-memory RPC producer/receiver paths. The
// optional pipeline is disabled so a partition cuts the same routes for every
// AppendEntries call; successful responses are never synthesized.
type assuranceTransport struct {
    *InmemTransport
    mu sync.Mutex
    replies map[ServerID]int
}

func (a *assuranceTransport) AppendEntriesPipeline(id ServerID, addr ServerAddress) (AppendPipeline, error) {
    return nil, ErrPipelineReplicationNotSupported
}

func (a *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
    err := a.InmemTransport.AppendEntries(id, addr, req, resp)
    if err == nil && resp.Success {
        a.mu.Lock()
        a.replies[id]++
        a.mu.Unlock()
    }
    return err
}

func (a *assuranceTransport) counts() map[string]int {
    a.mu.Lock()
    defer a.mu.Unlock()
    c := make(map[string]int)
    for k, v := range a.replies { c[string(k)] = v }
    return c
}

type assuranceNode struct {
    r *Raft
    tr *assuranceTransport
    fsm *MockFSM
    id ServerID
    addr ServerAddress
}

func assuranceEmit(event string, fields map[string]interface{}) {
    fields["event"] = event
    b, err := json.Marshal(fields)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func assuranceAwait(t *testing.T, f Future, d time.Duration) error {
    t.Helper()
    ch := make(chan error, 1)
    go func() { ch <- f.Error() }()
    select {
    case err := <-ch: return err
    case <-time.After(d): t.Fatal("future completion deadline: observation is incomplete"); return nil
    }
}

func assuranceUntil(t *testing.T, d time.Duration, what string, pred func() bool) {
    t.Helper()
    stop := time.Now().Add(d)
    for time.Now().Before(stop) {
        if pred() { return }
        time.Sleep(2*time.Millisecond)
    }
    t.Fatalf("unreached prerequisite: %s", what)
}

func assuranceLast(n *assuranceNode) string {
    n.fsm.Lock()
    defer n.fsm.Unlock()
    if len(n.fsm.logs)==0 { return "" }
    return string(n.fsm.logs[len(n.fsm.logs)-1])
}

func TestAssuranceVerifyAuthorityHistory(t *testing.T) {
    for _, keepNonvoter := range []bool{true, false} {
        name := "with_nonvoter"
        if !keepNonvoter { name = "without_nonvoter_contact" }
        t.Run(name, func(t *testing.T) {
            nodes := make([]*assuranceNode, 4)
            for i := range nodes {
                id := ServerID(fmt.Sprintf("%s_node_%d", name, i))
                addr, base := NewInmemTransportWithTimeout(ServerAddress(id), 40*time.Millisecond)
                nodes[i] = &assuranceNode{id:id, addr:addr, tr:&assuranceTransport{InmemTransport:base, replies:make(map[ServerID]int)}, fsm:&MockFSM{}}
            }
            for i,n := range nodes {
                for j,p := range nodes {
                    if i!=j { n.tr.Connect(p.addr, p.tr.InmemTransport) }
                }
            }
            defer func() {
                // Initiate shutdown for all nodes before waiting for any one.
                var fs []Future
                for _,n := range nodes { if n.r!=nil { fs=append(fs,n.r.Shutdown()) } }
                for _,n := range nodes { n.tr.Close() }
                for _,f := range fs { assuranceAwait(t,f,3*time.Second) }
            }()
            for i,n := range nodes {
                cfg := DefaultConfig()
                cfg.ProtocolVersion = 3
                cfg.LocalID = n.id
                cfg.LogOutput = io.Discard
                cfg.CommitTimeout = 5*time.Millisecond
                cfg.HeartbeatTimeout = 100*time.Millisecond
                cfg.ElectionTimeout = 150*time.Millisecond
                cfg.LeaderLeaseTimeout = 80*time.Millisecond
                if i==0 {
                    // A longer local lease leaves an observable interval after
                    // the remote voters elect. All safety/lease workers still run.
                    cfg.HeartbeatTimeout = 2*time.Second
                    cfg.ElectionTimeout = 2*time.Second
                    cfg.LeaderLeaseTimeout = 2*time.Second
                }
                store := NewInmemStore()
                r,err := NewRaft(cfg,n.fsm,store,store,NewInmemSnapshotStore(),n.tr)
                if err!=nil { t.Fatal(err) }
                n.r=r
            }
            old := nodes[0]
            if err:=assuranceAwait(t,old.r.BootstrapCluster(Configuration{Servers:[]Server{{ID:old.id,Address:old.addr,Suffrage:Voter}}}),time.Second); err!=nil { t.Fatal(err) }
            assuranceUntil(t,6*time.Second,"initial real single-voter election",func()bool{return old.r.State()==Leader})
            for _,n:=range nodes[1:3] {
                if err:=assuranceAwait(t,old.r.AddVoter(n.id,n.addr,0,time.Second),2*time.Second); err!=nil { t.Fatal(err) }
            }
            nv:=nodes[3]
            cf:=old.r.AddNonvoter(nv.id,nv.addr,0,time.Second)
            if err:=assuranceAwait(t,cf,2*time.Second); err!=nil { t.Fatal(err) }
            configIndex:=cf.Index()
            before:=old.r.Apply([]byte("before"),time.Second)
            if err:=assuranceAwait(t,before,2*time.Second); err!=nil { t.Fatal(err) }
            assuranceUntil(t,2*time.Second,"all peers consume initial committed command",func()bool{
                for _,n:=range nodes { if assuranceLast(n)!="before" || n.r.CommitIndex()<configIndex {return false} }
                return true
            })
            for _,n:=range nodes {
                f:=n.r.GetConfiguration()
                if err:=assuranceAwait(t,f,time.Second); err!=nil {t.Fatal(err)}
                cfg:=f.Configuration()
                if len(cfg.Servers)!=4 {t.Fatalf("configuration prefix mismatch node=%s servers=%+v",n.id,cfg.Servers)}
                voters:=0
                for _,s:=range cfg.Servers {
                    if s.Suffrage==Voter {voters++}
                    if s.ID==nv.id && s.Suffrage!=Nonvoter {t.Fatal("nonvoter prefix mismatch")}
                }
                if voters!=3 {t.Fatal("voter count mismatch")}
            }
            oldTerm:=old.r.CurrentTerm()
            assuranceEmit("prefix",map[string]interface{}{"run":name,"old_id":string(old.id),"old_term":oldTerm,"configuration_index":configIndex,"voters":3,"nonvoters":1,"initial_apply_index":before.Index(),"old_value":assuranceLast(old)})
            healthyErr:=assuranceAwait(t,old.r.VerifyLeader(),time.Second)
            assuranceEmit("healthy_control",map[string]interface{}{"run":name,"ok":healthyErr==nil,"error":fmt.Sprint(healthyErr)})
            if healthyErr!=nil {t.Fatal(healthyErr)}

            // Separate {old, nonvoter} from the other two voters in both
            // directions. In the control, also separate old from nonvoter.
            cutStart:=time.Now()
            for _,i:=range []int{0,3} {
                for _,j:=range []int{1,2} {
                    nodes[i].tr.Disconnect(nodes[j].addr)
                    nodes[j].tr.Disconnect(nodes[i].addr)
                }
            }
            if !keepNonvoter {
                old.tr.Disconnect(nv.addr)
                nv.tr.Disconnect(old.addr)
            }
            assuranceEmit("partition",map[string]interface{}{"run":name,"nonvoter_connected":keepNonvoter})
            var successor *assuranceNode
            assuranceUntil(t,1500*time.Millisecond,"actual replacement voter election",func()bool{
                for _,n:=range nodes[1:3] {
                    if n.r.State()==Leader && n.r.CurrentTerm()>oldTerm {successor=n;return true}
                }
                return false
            })
            after:=successor.r.Apply([]byte("after"),time.Second)
            if err:=assuranceAwait(t,after,time.Second); err!=nil {t.Fatal(err)}
            newTerm:=successor.r.CurrentTerm()
            if successor.r.State()!=Leader || newTerm<=oldTerm || assuranceLast(successor)!="after" {t.Fatal("replacement authority prerequisite changed")}
            op:=name+"_verify_after_new_write"
            assuranceEmit("replacement_write",map[string]interface{}{"run":name,"op":op,"old_id":string(old.id),"new_id":string(successor.id),"old_term":oldTerm,"new_term":newTerm,"term_advanced":newTerm>oldTerm,"write_ok":true,"new_value":assuranceLast(successor),"write_index":after.Index()})
            preCounts:=old.tr.counts()
            assuranceEmit("verify_invocation",map[string]interface{}{"run":name,"op":op,"old_id":string(old.id),"old_term":old.r.CurrentTerm(),"old_state":old.r.State().String(),"new_term":newTerm,"new_id":string(successor.id),"old_value":assuranceLast(old),"partition_elapsed_ms":time.Since(cutStart).Milliseconds()})
            err:=assuranceAwait(t,old.r.VerifyLeader(),4*time.Second)
            // Record public result without asserting the disputed requirement.
            // The controller compares it with the fixed property independently.
            assuranceEmit("verify_result",map[string]interface{}{"run":name,"op":op,"ok":err==nil,"error":fmt.Sprint(err),"old_id":string(old.id),"old_term":old.r.CurrentTerm(),"old_state":old.r.State().String(),"new_id":string(successor.id),"new_term":successor.r.CurrentTerm(),"new_state":successor.r.State().String(),"old_value":assuranceLast(old),"new_value":assuranceLast(successor),"before_replies":preCounts,"after_replies":old.tr.counts(),"partition_elapsed_ms":time.Since(cutStart).Milliseconds()})
        })
    }
}
