package epaxos

import (
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func TestInvestigationSeed4Loss(t *testing.T) {
	rng := rand.New(rand.NewSource(4))
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
		t.Logf("pre-recovery replica %d: status=%d bal=%d vbal=%d seq=%d deps=%v cmds=%v",
			i, inst.Status, inst.bal, inst.vbal, inst.Seq, inst.Deps, inst.Cmds)
	}
}
