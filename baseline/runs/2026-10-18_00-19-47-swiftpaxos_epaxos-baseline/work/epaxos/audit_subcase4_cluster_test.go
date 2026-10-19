package epaxos

import (
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

// One replica holds a PREACCEPTED value; the others have no instance.  With
// the documented sub-case 4, recovery would use TryPreAccept.  The captured
// code falls through to sub-case 5 and restarts phase 1.  Determine whether
// the value still commits or recovery stalls.
func TestInvestigationSinglePreacceptedRecovery(t *testing.T) {
	c := newAuditCluster(5)
	chosen := []state.Command{{Op: state.PUT, K: 7, V: state.Value("chosen")}}
	deps := auditDeps(5)
	inst := c.reps[0].newInstance(0, 0, chosen, 0, 0, PREACCEPTED, 0, deps)
	inst.lb = c.reps[0].newLeaderBookkeeping(nil, deps, deps, deps, 0, chosen, PREACCEPTED, 0)
	c.reps[0].InstanceSpace[0][0] = inst
	c.reps[0].crtInstance[0] = 0
	c.reps[0].updateConflicts(chosen, 0, 0, 0)
	c.reps[4].crtInstance[0] = 0
	c.reps[4].startRecoveryForInstance(0, 0)
	if err := c.run(100000); err != nil {
		t.Fatal(err)
	}
	put, noop := 0, 0
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("replica %d: no instance", i)
			continue
		}
		t.Logf("replica %d: status=%d cmds=%v", i, inst.Status, inst.Cmds)
		if inst.Status == COMMITTED {
			if len(inst.Cmds) == 1 && string(inst.Cmds[0].V) == "chosen" {
				put++
			} else if len(inst.Cmds) == 1 && inst.Cmds[0].Op == state.NONE {
				noop++
			}
		}
	}
	t.Logf("final: put=%d noop=%d", put, noop)
}
