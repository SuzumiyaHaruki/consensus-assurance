package dragonboat

import (
 "encoding/json"
 "fmt"
 "runtime"
 "testing"
 "time"

 "github.com/lni/dragonboat/v3/internal/rsm"
 "github.com/lni/dragonboat/v3/internal/tests"
 "github.com/lni/dragonboat/v3/internal/vfs"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

// Conditional exploration only: the snapshot metadata and successful payload
// load are substituted. This does not prove a legal membership-change history.
type assuranceSnapshotInput struct {
 rsm.ISnapshotter
 snapshot pb.Snapshot
}
func (s *assuranceSnapshotInput) GetMostRecentSnapshot() (pb.Snapshot,error) { return pb.Snapshot{},nil }
func (s *assuranceSnapshotInput) GetSnapshot(index uint64) (pb.Snapshot,error) { return s.snapshot,nil }
func (s *assuranceSnapshotInput) Load(pb.Snapshot,rsm.ILoadable,rsm.IRecoverable) error { return nil }

func TestAssuranceRecoveryPublicationOverlap(t *testing.T) {
 emit:=func(e map[string]interface{}) { b,err:=json.Marshal(e);if err!=nil {t.Fatal(err)};fmt.Println("CA_EVENT "+string(b)) }
 fs:=vfs.GetTestFS()
 nodes,_,_,ldb:=getTestRaftNodes(3,false,fs)
 defer cleanupTestDir(fs)
 defer ldb.Close()
 defer stopNodes(nodes)
 n:=nodes[0]
 original:=n.sm
 input:=&assuranceSnapshotInput{ISnapshotter:n.snapshotter}
 n.sm=rsm.NewStateMachine(rsm.NewNativeSM(n.config,rsm.NewInMemStateMachine(&tests.NoOP{}),n.stopC),input,n.config,n,fs)
 defer n.sm.Close()
 defer original.Close()
 // Use real bootstrap entries and callbacks to establish old membership.
 for i:=0;i<4;i++ { step(nodes) }
 if !n.initialized() || n.sm.GetLastApplied()!=3 || len(n.sm.GetMembership().Addresses)!=3 {t.Fatal("bootstrap not established")}
 ss:=pb.Snapshot{Index:100,Term:2,Membership:pb.Membership{ConfigChangeId:99,Addresses:map[uint64]string{1:"peer:12346",2:"peer:12347",3:"peer:12348",4:"peer:12349",5:"peer:12350"},Observers:map[uint64]string{},Witnesses:map[uint64]string{},Removed:map[uint64]bool{}}}
 input.snapshot=ss
 // The snapshot producer and transfer/payload pipeline are not executed.
 // Drive the actual snapshot consumer at the Peer boundary, then acknowledge
 // its log update as a caller would, without claiming durable crash behavior.
 n.p.Handle(pb.Message{Type:pb.InstallSnapshot,From:2,To:1,Term:2,Snapshot:ss})
 ud:=n.p.GetUpdate(true,n.sm.GetLastApplied())
 if pb.IsEmptySnapshot(ud.Snapshot) {t.Fatal("snapshot was not accepted")}
 if err:=n.logReader.ApplySnapshot(ss);err!=nil {t.Fatal(err)}
 n.p.Commit(ud)
 n.ss.setRecovering()
 n.raftMu.Lock()
 locked:=true
 defer func(){if locked {n.raftMu.Unlock()}}()
 // Before publication the actual campaign guard should still see a gap.
 for i:=0;i<45;i++ {n.tick(uint64(i+1))}
 before:=n.p.GetUpdate(true,n.sm.GetLastApplied())
 beforeVotes:=0
 for _,msg:=range before.Messages {if msg.Type==pb.RequestVote {beforeVotes++}}
 n.p.Commit(before)
 emit(map[string]interface{}{"event":"before_publication","applied":n.sm.GetLastApplied(),"vote_requests":beforeVotes,"recovering":n.ss.recovering()})
 done:=make(chan error,1)
 go func(){_,err:=n.sm.Recover(rsm.Task{Recover:true,Index:ss.Index});done<-err}()
 deadline:=time.Now().Add(5*time.Second)
 for n.sm.GetLastApplied()!=ss.Index && time.Now().Before(deadline) {runtime.Gosched()}
 if n.sm.GetLastApplied()!=ss.Index {t.Fatal("snapshot publication not reached")}
 // GetMembership also waits for the recovery body to release its RSM mutex.
 // RestoreRemotes still cannot take raftMu, which the step-side owns here.
 restoredRSM:=n.sm.GetMembership()
 n.updateAppliedIndex()
 for i:=0;i<45;i++ {n.tick(uint64(46+i))}
 after:=n.p.GetUpdate(true,n.appliedIndex)
 targets:=[]uint64{}
 for _,msg:=range after.Messages {if msg.Type==pb.RequestVote {targets=append(targets,msg.To)}}
 emit(map[string]interface{}{"event":"overlap","published_applied":n.sm.GetLastApplied(),"node_applied":n.appliedIndex,"rsm_members":len(restoredRSM.Addresses),"snapshot_index":ss.Index,"vote_targets":targets,"recovering":n.ss.recovering(),"snapshot_history_executed":false,"payload_load_substituted":true})
 n.p.Commit(after)
 n.raftMu.Unlock()
 locked=false
 select {case err:=<-done:if err!=nil {t.Fatal(err)};case <-time.After(5*time.Second):t.Fatal("recovery callback did not finish")}
 emit(map[string]interface{}{"event":"recovery_returned","published_applied":n.sm.GetLastApplied(),"config_index":n.sm.GetMembership().ConfigChangeId})
}
