package dragonboat

import (
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/rsm"
	"github.com/lni/dragonboat/v3/internal/vfs"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

type assuranceNoopPipeline struct{}

func (p *assuranceNoopPipeline) setCloseReady(*node)            {}
func (p *assuranceNoopPipeline) setStepReady(uint64)            {}
func (p *assuranceNoopPipeline) setCommitReady(uint64)          {}
func (p *assuranceNoopPipeline) setApplyReady(uint64)           {}
func (p *assuranceNoopPipeline) setStreamReady(uint64)          {}
func (p *assuranceNoopPipeline) setSaveReady(uint64)            {}
func (p *assuranceNoopPipeline) setRecoverReady(uint64)         {}

// TestAssuranceSnapshotInstallFrontier drives node.pushSnapshot and
// node.entriesToApply, then reads the first task the state machine reports to
// the apply loop, to see how a snapshot install moves the pushed/applied
// frontier and how committed entries around that frontier are treated.
func TestAssuranceSnapshotInstallFrontier(t *testing.T) {
	fs := vfs.GetTestFS()
	cfg := config.Config{ClusterID: 1, NodeID: 1}
	n := &node{
		clusterID:    1,
		nodeID:       1,
		config:       cfg,
		initializedC: make(chan struct{}),
		sysEvents:    &sysEventListener{},
		ss:           &snapshotState{},
		pipeline:     &assuranceNoopPipeline{},
	}
	n.sm = rsm.NewStateMachine(
		rsm.NewNativeSM(cfg, &rsm.InMemStateMachine{}, nil),
		nil, cfg, &testDummyNodeProxy{}, fs)
	n.toApplyQ = n.sm.TaskQ()

	ss := pb.Snapshot{Index: 5, Term: 2}
	n.pushSnapshot(ss, 0)
	fmt.Printf("CA_EVENT {\"event\":\"pushed\",\"pushed_index\":%d,\"ss_index\":%d}\n",
		n.pushedIndex, n.ss.getIndex())

	got := n.entriesToApply([]pb.Entry{
		{Index: 3, Term: 2},
		{Index: 4, Term: 2},
		{Index: 5, Term: 2},
		{Index: 6, Term: 2},
	})
	first := uint64(0)
	if len(got) > 0 {
		first = got[0].Index
	}
	fmt.Printf("CA_EVENT {\"event\":\"filtered\",\"count\":%d,\"first_index\":%d}\n",
		len(got), first)

	n.pushEntries(got)
	task, err := n.handleTask(nil, nil)
	if err != nil {
		t.Fatalf("handleTask returned %v", err)
	}
	fmt.Printf("CA_EVENT {\"event\":\"first_task\",\"recover\":%t,\"index\":%d}\n",
		task.Recover, task.Index)

	hole := func() (panicked bool) {
		defer func() {
			if r := recover(); r != nil {
				panicked = true
			}
		}()
		n.entriesToApply([]pb.Entry{{Index: 8, Term: 2}})
		return false
	}()
	fmt.Printf("CA_EVENT {\"event\":\"hole\",\"panicked\":%t}\n", hole)
}
