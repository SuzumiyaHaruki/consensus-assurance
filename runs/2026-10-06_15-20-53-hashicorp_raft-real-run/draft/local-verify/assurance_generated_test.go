package raft

import (
    "encoding/json"
    "fmt"
    "io"
    "sync"
    "sync/atomic"
    "testing"
    "time"
)

const assuranceOperation = "verify-after-competing-commit"

func assuranceEmit(event string, fields map[string]interface{}) {
    fields["event"] = event
    fields["operation"] = assuranceOperation
    b, err := json.Marshal(fields)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(b))
}

type assuranceNetwork struct {
    sync.RWMutex
    partitioned bool
    countersMu sync.Mutex
    blocked map[string]int
    next atomic.Uint64
}

func (n *assuranceNetwork) cut(from, to ServerID) bool {
    left := func(id ServerID) bool { return id == "a" || id == "n" }
    return n.partitioned && left(from) != left(to)
}

// All ordinary RPC calls hold this policy read lock through their return.
// The partition acquires its write lock; it never changes any Raft state.
type assuranceTransport struct {
    *InmemTransport
    network *assuranceNetwork
    id ServerID
}

func (x *assuranceTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
    return nil, ErrPipelineReplicationNotSupported
}

func (x *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
    n := x.network
    n.RLock()
    defer n.RUnlock()
    heartbeat := req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && req.LeaderCommitIndex == 0 && len(req.Entries) == 0
    kind := "append"
    if heartbeat { kind = "heartbeat" }
    serial := n.next.Add(1)
    if n.cut(x.id, id) {
        key := string(x.id) + ":" + string(id) + ":" + kind
        n.countersMu.Lock()
        n.blocked[key]++
        first := n.blocked[key] == 1
        n.countersMu.Unlock()
        if first {
            assuranceEmit("blocked_path", map[string]interface{}{"from":x.id,"to":id,"kind":kind,"request":serial,"term":req.Term})
        }
        return fmt.Errorf("assurance partition %s to %s", x.id, id)
    }
    err := x.InmemTransport.AppendEntries(id, addr, req, resp)
    if n.partitioned && x.id == "a" && id == "n" {
        assuranceEmit("nonvoter_response", map[string]interface{}{"request":serial,"kind":kind,"request_term":req.Term,"response_term":resp.Term,"success":err == nil && resp.Success})
    }
    return err
}

func (x *assuranceTransport) RequestVote(id ServerID, addr ServerAddress, req *RequestVoteRequest, resp *RequestVoteResponse) error {
    x.network.RLock(); defer x.network.RUnlock()
    if x.network.cut(x.id,id) { return fmt.Errorf("assurance partition") }
    err := x.InmemTransport.RequestVote(id,addr,req,resp)
    if x.network.partitioned {
        assuranceEmit("election_response",map[string]interface{}{"from":x.id,"to":id,"term":req.Term,"granted":err == nil && resp.Granted})
    }
    return err
}
func (x *assuranceTransport) RequestPreVote(id ServerID, addr ServerAddress, req *RequestPreVoteRequest, resp *RequestPreVoteResponse) error {
    x.network.RLock(); defer x.network.RUnlock()
    if x.network.cut(x.id,id) { return fmt.Errorf("assurance partition") }
    return x.InmemTransport.RequestPreVote(id,addr,req,resp)
}
func (x *assuranceTransport) InstallSnapshot(id ServerID, addr ServerAddress, req *InstallSnapshotRequest, resp *InstallSnapshotResponse, data io.Reader) error {
    x.network.RLock(); defer x.network.RUnlock()
    if x.network.cut(x.id,id) { return fmt.Errorf("assurance partition") }
    return x.InmemTransport.InstallSnapshot(id,addr,req,resp,data)
}
func (x *assuranceTransport) TimeoutNow(id ServerID, addr ServerAddress, req *TimeoutNowRequest, resp *TimeoutNowResponse) error {
    x.network.RLock(); defer x.network.RUnlock()
    if x.network.cut(x.id,id) { return fmt.Errorf("assurance partition") }
    return x.InmemTransport.TimeoutNow(id,addr,req,resp)
}

func assuranceWait(t *testing.T, label string, timeout time.Duration, condition func() bool) {
    t.Helper()
    end := time.Now().Add(timeout)
    for time.Now().Before(end) {
        if condition() { return }
        time.Sleep(time.Millisecond)
    }
    assuranceEmit("setup_failure", map[string]interface{}{"stage":label})
    t.Fatalf("prerequisite not attained: %s",label)
}
func assuranceFuture(t *testing.T, label string, f Future) {
    t.Helper()
    done := make(chan error,1)
    go func(){ done <- f.Error() }()
    select {
    case err := <-done:
        if err != nil { t.Fatalf("%s: %v",label,err) }
    case <-time.After(3*time.Second):
        t.Fatalf("future not completed during setup: %s",label)
    }
}
func assuranceHas(f *MockFSM, value string) bool {
    f.Lock(); defer f.Unlock()
    for _, v := range f.logs { if string(v) == value { return true } }
    return false
}

func TestAssuranceVerifyAfterCompetingCommit(t *testing.T) {
    network := &assuranceNetwork{blocked:make(map[string]int)}
    nodes := make(map[ServerID]*Raft)
    transports := make(map[ServerID]*assuranceTransport)
    fsms := make(map[ServerID]*MockFSM)
    stores := make(map[ServerID]*InmemStore)
    ids := []ServerID{"a","b","c","n"}
    for _, id := range ids {
        _, base := NewInmemTransportWithTimeout(ServerAddress(id),30*time.Millisecond)
        transports[id] = &assuranceTransport{InmemTransport:base, network:network, id:id}
    }
    for _, from := range ids { for _, to := range ids {
        if from != to { transports[from].Connect(ServerAddress(to),transports[to].InmemTransport) }
    } }
    defer func(){
        pending := make([]Future,0,len(nodes))
        for _, id := range ids { if nodes[id] != nil { pending=append(pending,nodes[id].Shutdown()) } }
        for _, f := range pending { if err := f.Error(); err != nil { t.Errorf("shutdown: %v",err) } }
        for _, tr := range transports { _ = tr.Close() }
    }()
    for _, id := range ids {
        config := DefaultConfig()
        config.LocalID=id
        config.LogOutput=io.Discard
        config.HeartbeatTimeout=50*time.Millisecond
        config.ElectionTimeout=50*time.Millisecond
        config.LeaderLeaseTimeout=50*time.Millisecond
        config.CommitTimeout=5*time.Millisecond
        if id == "a" || id == "n" {
            config.HeartbeatTimeout=1500*time.Millisecond
            config.ElectionTimeout=1500*time.Millisecond
            config.LeaderLeaseTimeout=1500*time.Millisecond
        }
        if err := ValidateConfig(config); err != nil { t.Fatal(err) }
        store := NewInmemStore()
        fsm := &MockFSM{}
        node,err := NewRaft(config,fsm,store,store,NewInmemSnapshotStore(),transports[id])
        if err != nil { t.Fatal(err) }
        nodes[id]=node; fsms[id]=fsm; stores[id]=store
    }
    a := nodes["a"]
    assuranceFuture(t,"bootstrap",a.BootstrapCluster(Configuration{Servers:[]Server{{ID:"a",Address:"a",Suffrage:Voter}}}))
    assuranceWait(t,"initial leader",4*time.Second,func()bool{return a.State()==Leader})
    assuranceFuture(t,"add b",a.AddVoter("b","b",0,time.Second))
    assuranceFuture(t,"add c",a.AddVoter("c","c",0,time.Second))
    assuranceFuture(t,"add n",a.AddNonvoter("n","n",0,time.Second))
    before := a.Apply([]byte("before-partition"),time.Second)
    assuranceFuture(t,"before command",before)
    beforeIndex := before.Index()
    assuranceWait(t,"all FSMs before command",time.Second,func()bool{
        for _, id := range ids { if !assuranceHas(fsms[id],"before-partition") {return false} }; return true
    })
    for _, id := range ids {
        cf := nodes[id].GetConfiguration()
        assuranceFuture(t,"configuration",cf)
        conf := cf.Configuration()
        if len(conf.Servers)!=4 {t.Fatalf("%s configuration size",id)}
        for _, server := range conf.Servers {
            expected := Voter
            if server.ID=="n" {expected=Nonvoter}
            if server.Suffrage!=expected {t.Fatalf("%s unexpected suffrage",id)}
        }
        if nodes[id].CommitIndex()<beforeIndex {t.Fatalf("%s lacks committed prefix",id)}
    }
    oldTerm := a.CurrentTerm()
    assuranceEmit("prepared",map[string]interface{}{"old_term":oldTerm,"configuration_stable":true,"voters":3,"nonvoters":1,"before_index":beforeIndex,"old_lease_ms":1500,"other_election_ms":50})
    network.Lock()
    network.partitioned=true
    network.Unlock()
    partitionStart := time.Now()
    assuranceEmit("partition",map[string]interface{}{"left":"a,n","right":"b,c"})

    // Each of the two serial sending paths must enter a new blocked call.
    // This proves its previous pre-partition reply processing has returned;
    // no pipeline can supply an extra old reply because it is unsupported.
    assuranceWait(t,"old voter reply paths drained",700*time.Millisecond,func()bool{
        network.countersMu.Lock(); defer network.countersMu.Unlock()
        for _, peer := range []string{"b","c"} { for _, kind := range []string{"append","heartbeat"} {
            if network.blocked["a:"+peer+":"+kind]==0 {return false}
        } }; return true
    })
    assuranceEmit("reply_paths_drained",map[string]interface{}{"voter_paths":4,"elapsed_ms":time.Since(partitionStart).Milliseconds()})
    var winner ServerID
    assuranceWait(t,"competing leader",700*time.Millisecond,func()bool{
        for _, id := range []ServerID{"b","c"} {
            if nodes[id].State()==Leader && nodes[id].CurrentTerm()>oldTerm {winner=id;return true}
        }; return false
    })
    fresh := nodes[winner].Apply([]byte("after-partition"),time.Second)
    assuranceFuture(t,"competing command",fresh)
    newIndex := fresh.Index()
    assuranceWait(t,"both majority FSMs applied",500*time.Millisecond,func()bool{
        return assuranceHas(fsms["b"],"after-partition") && assuranceHas(fsms["c"],"after-partition")
    })
    var entryB,entryC Log
    if err := stores["b"].GetLog(newIndex,&entryB); err != nil {t.Fatal(err)}
    if err := stores["c"].GetLog(newIndex,&entryC); err != nil {t.Fatal(err)}
    if entryB.Term<=oldTerm || entryC.Term!=entryB.Term || string(entryB.Data)!="after-partition" || string(entryC.Data)!="after-partition" {
        t.Fatal("competing commit witness inconsistent")
    }
    assuranceEmit("competing_commit",map[string]interface{}{"leader":winner,"new_term":entryB.Term,"old_term":oldTerm,"index":newIndex,"voter_copies":2,"both_applied":true,"elapsed_ms":time.Since(partitionStart).Milliseconds()})
    // This event admits one operation independently of its subsequent result.
    assuranceEmit("verify_admitted",map[string]interface{}{"scenario":"nonvoter_partition","new_term":entryB.Term,"prior_commit_index":newIndex,"old_term":a.CurrentTerm(),"old_role":a.State().String(),"old_has_new_command":assuranceHas(fsms["a"],"after-partition")})
    verify := a.VerifyLeader()
    done := make(chan error,1)
    go func(){done<-verify.Error()}()
    select {
    case err := <-done:
        errorText := ""
        if err!=nil {errorText=err.Error()}
        assuranceEmit("verify_result",map[string]interface{}{"scenario":"nonvoter_partition","completed":true,"success":err==nil,"error":errorText,"old_role":a.State().String(),"old_term":a.CurrentTerm(),"new_term":entryB.Term,"old_has_new_command":assuranceHas(fsms["a"],"after-partition"),"elapsed_ms":time.Since(partitionStart).Milliseconds()})
    case <-time.After(3*time.Second):
        assuranceEmit("observation_timeout",map[string]interface{}{"stage":"verify result"})
    }
}
