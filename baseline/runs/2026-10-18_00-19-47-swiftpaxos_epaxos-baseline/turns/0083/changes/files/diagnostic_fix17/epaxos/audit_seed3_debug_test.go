package epaxos

import (
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func TestInvestigationFix17Seed3(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	c := newAuditCluster(5)
	c.drop = func(from, to int32, code uint8) bool { return rng.Intn(100) < 20 }
	chosen := state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")}
	c.propose(0, 1, chosen)
	if err := c.run(100000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("pre replica %d: no instance", i)
			continue
		}
		t.Logf("pre replica %d: status=%d bal=%d vbal=%d cmds=%v", i, inst.Status, inst.bal, inst.vbal, inst.Cmds)
	}
	recoverer := -1
	for i := 1; i < 5; i++ {
		if !randomFaultHasChosen(c.instance(i, 0, 0), chosen) {
			recoverer = i
			break
		}
	}
	if recoverer == -1 {
		t.Fatal("no recoverer for seed 3")
	}
	t.Logf("recoverer=%d", recoverer)
	c.drop = nil
	c.reps[recoverer].crtInstance[0] = 0
	c.reps[recoverer].startRecoveryForInstance(0, 0)
	if err := c.run(100000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("replica %d: no instance", i)
			continue
		}
		if inst.lb == nil {
			t.Logf("replica %d: status=%d seq=%d cmds=%v lb=nil", i, inst.Status, inst.Seq, inst.Cmds)
			continue
		}
		lb := inst.lb
		t.Logf("replica %d: status=%d seq=%d cmds=%v lb{status=%d preparing=%t trying=%t tpaReps=%d tpaOK=%d nacks=%d lastTried=%d ballot=%d cmds=%v}",
			i, inst.Status, inst.Seq, inst.Cmds, lb.status, lb.preparing, lb.tryingToPreAccept,
			lb.tpaReps, lb.preAcceptOKs, lb.nacks, lb.lastTriedBallot, lb.ballot, lb.cmds)
	}
}
