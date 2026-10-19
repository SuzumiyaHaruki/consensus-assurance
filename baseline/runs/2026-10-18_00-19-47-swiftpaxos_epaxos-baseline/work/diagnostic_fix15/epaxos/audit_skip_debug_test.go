package epaxos

import (
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func TestInvestigationFirstSkip(t *testing.T) {
	chosen := state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")}
	for seed := int64(1); seed <= 500; seed++ {
		rng := rand.New(rand.NewSource(seed))
		c := newAuditCluster(5)
		c.drop = func(from, to int32, code uint8) bool { return rng.Intn(100) < 20 }
		c.propose(0, 1, chosen)
		if err := c.run(100000); err != nil {
			t.Fatal(err)
		}
		had := false
		for i := 0; i < 5; i++ {
			if randomFaultHasChosen(c.instance(i, 0, 0), chosen) {
				had = true
			}
		}
		if !had {
			continue
		}
		recoverer := -1
		for i := 1; i < 5; i++ {
			if !randomFaultHasChosen(c.instance(i, 0, 0), chosen) {
				recoverer = i
				break
			}
		}
		if recoverer == -1 {
			continue
		}
		c.drop = nil
		c.reps[recoverer].crtInstance[0] = 0
		c.reps[recoverer].startRecoveryForInstance(0, 0)
		if err := c.run(100000); err != nil {
			t.Fatal(err)
		}
		put, noop := 0, 0
		for i := 0; i < 5; i++ {
			inst := c.instance(i, 0, 0)
			if inst != nil && inst.Status == COMMITTED {
				if randomFaultHasChosen(inst, chosen) {
					put++
				} else if randomFaultIsNOOP(inst) {
					noop++
				}
			}
		}
		if put > 0 || noop > 0 {
			continue
		}
		t.Logf("first post-recovery skip seed=%d recoverer=%d", seed, recoverer)
		for i := 0; i < 5; i++ {
			inst := c.instance(i, 0, 0)
			if inst == nil {
				t.Logf("replica %d: no instance", i)
				continue
			}
			t.Logf("replica %d: status=%d seq=%d cmds=%v", i, inst.Status, inst.Seq, inst.Cmds)
		}
		return
	}
	t.Log("no post-recovery skip found")
}
