package epaxos

import (
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func TestInvestigationFix5Seed6(t *testing.T) {
	const seed = int64(6)
	rng := rand.New(rand.NewSource(seed))
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
			t.Logf("pre-recovery replica %d: no instance", i)
			continue
		}
		t.Logf("pre-recovery replica %d: status=%d bal=%d vbal=%d cmds=%v",
			i, inst.Status, inst.bal, inst.vbal, inst.Cmds)
	}
	c.drop = nil
	c.reps[2].crtInstance[0] = 0
	c.reps[2].startRecoveryForInstance(0, 0)
	if err := c.run(100000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("post-recovery replica %d: no instance", i)
			continue
		}
		t.Logf("post-recovery replica %d: status=%d execedUpTo=%d cmds=%v",
			i, inst.Status, c.reps[i].ExecedUpTo[0], inst.Cmds)
	}
}
