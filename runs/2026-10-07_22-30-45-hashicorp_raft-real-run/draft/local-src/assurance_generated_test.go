package raft

import (
    "encoding/json"
    "fmt"
    "io"
    "sync"
    "testing"
    "time"
)

// This transport retains real in-memory RPC dispatch and disables the optional
// pipeline. Its partition policy returns errors, never synthesized successes.
type assuranceTransport struct {
    *InmemTransport
    mu sync.Mutex
    cut map[ServerID]bool
    failed map[string]int
    success map[ServerID]int
}
func (x *assuranceTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
    return nil, ErrPipelineReplicationNotSupported
}
func assuranceLane(id ServerID, a *AppendEntriesRequest) string {
    lane := "append"
    if a.PrevLogEntry == 0 && a.PrevLogTerm == 0 && len(a.Entries) == 0 && a.LeaderCommitIndex == 0 {
        lane = "heartbeat"
    }
    return string(id)+"/"+lane
}
func (x *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, a *AppendEntriesRequest, r *AppendEntriesResponse) error {
    x.mu.Lock()
    blocked := x.cut[id]
    if blocked { x.failed[assuranceLane(id,a)]++ }
    x.mu.Unlock()
    if blocked { return fmt.Errorf("assurance partition to %s", id) }
    err := x.InmemTransport.AppendEntries(id,addr,a,r)
    x.mu.Lock()
    if err == nil && r.Success { x.success[id]++ }
    x.mu.Unlock()
    return err
}
func (x *assuranceTransport) stats() (map[string]int,map[ServerID]int) {
    x.mu.Lock(); defer x.mu.Unlock()
    f:=map[string]int{}; s:=map[ServerID]int{}
    for k,v:=range x.failed { f[k]=v }; for k,v:=range x.success { s[k]=v }
    return f,s
}
type assuranceFSM struct { mu sync.Mutex; value string }
func (f *assuranceFSM) Apply(l *Log) interface{} { f.mu.Lock(); defer f.mu.Unlock(); f.value=string(l.Data); return f.value }
func (f *assuranceFSM) read() string { f.mu.Lock(); defer f.mu.Unlock(); return f.value }
func (f *assuranceFSM) Snapshot() (FSMSnapshot,error) { return nil,fmt.Errorf("snapshot outside scenario") }
func (f *assuranceFSM) Restore(io.ReadCloser) error { return fmt.Errorf("restore outside scenario") }
func assuranceEmit(m map[string]interface{}) { b,e:=json.Marshal(m); if e!=nil { panic(e) }; fmt.Println("CA_EVENT "+string(b)) }
func assuranceWait(t *testing.T, name string, d time.Duration, f func() bool) {
    t.Helper(); deadline:=time.Now().Add(d)
    for time.Now().Before(deadline) { if f(){return}; time.Sleep(time.Millisecond) }
    t.Fatalf("prerequisite not reached: %s",name)
}
func assuranceFuture(t *testing.T, name string, f Future) error {
    t.Helper(); done:=make(chan error,1); go func(){done<-f.Error()}()
    select { case e:=<-done:return e; case <-time.After(10*time.Second):t.Fatalf("future not complete: %s",name);return nil }
}
func TestAssuranceVerifyNonvoterAfterNewLeader(t *testing.T) {
    ids:=[]ServerID{"A","B","C","D"}
    cfg:=Configuration{Servers:[]Server{{Voter,"A","A"},{Voter,"B","B"},{Voter,"C","C"},{Nonvoter,"D","D"}}}
    trs:=make([]*assuranceTransport,4); stores:=make([]*InmemStore,4); snaps:=make([]*InmemSnapshotStore,4)
    fsms:=make([]*assuranceFSM,4); confs:=make([]*Config,4); nodes:=make([]*Raft,4)
    for i,id:=range ids {
        _,raw:=NewInmemTransportWithTimeout(ServerAddress(id),500*time.Millisecond)
        trs[i]=&assuranceTransport{InmemTransport:raw,cut:map[ServerID]bool{},failed:map[string]int{},success:map[ServerID]int{}}
        stores[i]=NewInmemStore();snaps[i]=NewInmemSnapshotStore();fsms[i]=&assuranceFSM{}
        c:=DefaultConfig();c.LocalID=id;c.PreVoteDisabled=true;c.CommitTimeout=10*time.Millisecond
        c.HeartbeatTimeout=100*time.Millisecond;c.ElectionTimeout=100*time.Millisecond;c.LeaderLeaseTimeout=50*time.Millisecond
        if i==0 { c.HeartbeatTimeout=3*time.Second;c.ElectionTimeout=3*time.Second;c.LeaderLeaseTimeout=3*time.Second }
        c.SnapshotInterval=time.Hour;c.SnapshotThreshold=1000000;c.LogOutput=io.Discard
        if e:=ValidateConfig(c);e!=nil { t.Fatal(e) };confs[i]=c
    }
    for i:=range trs { for j:=range trs { if i!=j { trs[i].Connect(ServerAddress(ids[j]),trs[j].InmemTransport) } } }
    defer func(){
        futures:=[]Future{}
        for _,r:=range nodes {if r!=nil {futures=append(futures,r.Shutdown())}}
        for _,f:=range futures {if e:=f.Error();e!=nil {t.Errorf("shutdown: %v",e)}}
        for _,tr:=range trs {if e:=tr.Close();e!=nil {t.Errorf("transport close: %v",e)}}
        assuranceEmit(map[string]interface{}{"event":"cleanup","scenario":"nonvoter-partition","joined":true})
    }()
    // Bootstrap exactly one voter. Other empty nodes obtain the configuration
    // from real replication; their empty membership permits the initial vote.
    if e:=BootstrapCluster(confs[0],stores[0],stores[0],snaps[0],trs[0],cfg);e!=nil {t.Fatal(e)}
    start:=func(i int){var e error;nodes[i],e=NewRaft(confs[i],fsms[i],stores[i],stores[i],snaps[i],trs[i]);if e!=nil {t.Fatal(e)}}
    start(0)
    // The initial campaign is automatic. Starting the other processes when A
    // campaigns avoids fabricating TimeoutNow or setting internal leader state.
    assuranceWait(t,"A automatic campaign",8*time.Second,func()bool{return nodes[0].State()==Candidate})
    for i:=1;i<4;i++ {start(i)}
    assuranceWait(t,"A elected",3*time.Second,func()bool{return nodes[0].State()==Leader})
    initial:=nodes[0].Apply([]byte("before-partition"),time.Second)
    if e:=assuranceFuture(t,"initial apply",initial);e!=nil {t.Fatal(e)}
    assuranceWait(t,"baseline applied on every node",2*time.Second,func()bool{
        for _,f:=range fsms {if f.read()!="before-partition" {return false}};return true
    })
    oldTerm:=nodes[0].getCurrentTerm()
    for _,r:=range nodes {f:=r.GetConfiguration();if e:=f.Error();e!=nil {t.Fatal(e)};if !assuranceSameConfig(f.Configuration(),cfg){t.Fatal("configuration mismatch")}}
    assuranceEmit(map[string]interface{}{"event":"baseline","scenario":"nonvoter-partition","old_id":"A","old_term":oldTerm,"value":fsms[0].read(),"voters":3,"nonvoters":1})
    // Split {A,D} from {B,C} in both directions. Existing synchronous requests
    // may finish, so their callbacks are accounted for by the lane drain below.
    for _,i:=range []int{0,3} {for _,j:=range []int{1,2} {trs[i].Disconnect(ServerAddress(ids[j]));trs[j].Disconnect(ServerAddress(ids[i]))}}
    for _,i:=range []int{0,3} {trs[i].mu.Lock();trs[i].cut["B"]=true;trs[i].cut["C"]=true;trs[i].mu.Unlock()}
    for _,i:=range []int{1,2} {trs[i].mu.Lock();trs[i].cut["A"]=true;trs[i].cut["D"]=true;trs[i].mu.Unlock()}
    var newer int
    assuranceWait(t,"majority-side leader",2*time.Second,func()bool{
        for _,i:=range []int{1,2} {if nodes[i].State()==Leader && nodes[i].getCurrentTerm()>oldTerm {newer=i;return true}};return false
    })
    applied:=nodes[newer].Apply([]byte("after-majority-election"),time.Second)
    if e:=assuranceFuture(t,"new leader apply",applied);e!=nil {t.Fatal(e)}
    newTerm:=nodes[newer].getCurrentTerm()
    if newTerm<=oldTerm || fsms[newer].read()!="after-majority-election" {t.Fatal("new authority/write premise missing")}
    // Each peer has one ordinary replication worker and one heartbeat worker.
    // Entering a failed post-cut call in both lanes proves any prior success in
    // that lane has already returned through notifyAll before verification.
    assuranceWait(t,"old voter callback paths drained",2*time.Second,func()bool{
        f,_:=trs[0].stats();return f["B/append"]>0&&f["B/heartbeat"]>0&&f["C/append"]>0&&f["C/heartbeat"]>0
    })
    if nodes[0].State()!=Leader || nodes[0].getCurrentTerm()!=oldTerm {t.Fatal("old leader already stepped down before verification")}
    failed,before:=trs[0].stats()
    assuranceEmit(map[string]interface{}{"event":"admission","scenario":"nonvoter-partition","op":"verify-A-1","node":"A","new_leader":string(ids[newer]),"old_term":oldTerm,"new_term":newTerm,"new_write_index":applied.Index(),"new_value":fsms[newer].read(),"old_value":fsms[0].read(),"stable_config":true,"voter_lanes_drained":true,"failed_lanes":failed,"new_write_completed":true})
    // Future identity is fixed here; Error is called exactly once and awaited.
    verification:=nodes[0].VerifyLeader()
    err:=assuranceFuture(t,"old VerifyLeader",verification)
    _,after:=trs[0].stats()
    errText:="";if err!=nil {errText=err.Error()}
    assuranceEmit(map[string]interface{}{"event":"result","scenario":"nonvoter-partition","op":"verify-A-1","node":"A","success":err==nil,"error":errText,"old_value":fsms[0].read(),"new_value":fsms[newer].read(),"old_term":nodes[0].getCurrentTerm(),"new_term":newTerm,"A_state":nodes[0].State().String(),"B_success_delta":after["B"]-before["B"],"C_success_delta":after["C"]-before["C"],"D_success_delta":after["D"]-before["D"]})
}
func assuranceSameConfig(a,b Configuration)bool {
    if len(a.Servers)!=len(b.Servers){return false}
    for i,s:=range a.Servers {if s!=b.Servers[i]{return false}};return true
}
