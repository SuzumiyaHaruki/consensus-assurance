package epaxos

import (
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func randomFaultHasChosen(inst *Instance, cmd state.Command) bool {
	return inst != nil && len(inst.Cmds) == 1 &&
		inst.Cmds[0].K == cmd.K && string(inst.Cmds[0].V) == string(cmd.V)
}

func randomFaultIsNOOP(inst *Instance) bool {
	return inst != nil && len(inst.Cmds) == 1 && inst.Cmds[0].Op == state.NONE
}

// Investigation, excluded from TestAudit: randomized initial message drops,
// then recovery from a replica that lacks the proposed value.  Classify the
// result as PASS, SKIP (no value chosen), LOSS, or DIVERGENCE.
func TestInvestigationRandomFaultCampaign(t *testing.T) {
	chosen := state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")}
	passed, skipped, lost, diverged := 0, 0, 0, 0
	for seed := int64(1); seed <= 100; seed++ {
		rng := rand.New(rand.NewSource(seed))
		c := newAuditCluster(5)
		c.drop = func(from, to int32, code uint8) bool { return rng.Intn(100) < 20 }
		c.propose(0, 1, chosen)
		if err := c.run(100000); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}

		hadChosen := false
		for i := 0; i < 5; i++ {
			if randomFaultHasChosen(c.instance(i, 0, 0), chosen) {
				hadChosen = true
			}
		}
		if !hadChosen {
			skipped++
			t.Logf("seed %d: SKIP (no replica has the proposed value)", seed)
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
			passed++
			t.Logf("seed %d: PASS (all replicas already hold the value)", seed)
			continue
		}

		c.drop = nil
		c.reps[recoverer].crtInstance[0] = 0
		c.reps[recoverer].startRecoveryForInstance(0, 0)
		if err := c.run(100000); err != nil {
			t.Fatalf("seed %d recovery: %v", seed, err)
		}

		putCount, noopCount, otherCount := 0, 0, 0
		for i := 0; i < 5; i++ {
			inst := c.instance(i, 0, 0)
			if inst == nil || inst.Status != COMMITTED {
				continue
			}
			switch {
			case randomFaultHasChosen(inst, chosen):
				putCount++
			case randomFaultIsNOOP(inst):
				noopCount++
			default:
				otherCount++
			}
		}
		t.Logf("seed %d recoverer %d: put=%d noop=%d other=%d", seed, recoverer, putCount, noopCount, otherCount)
		if otherCount > 0 || (putCount > 0 && noopCount > 0) {
			for i := 0; i < 5; i++ {
				inst := c.instance(i, 0, 0)
				if inst != nil {
					t.Logf("seed %d replica %d: status=%d cmds=%v", seed, i, inst.Status, inst.Cmds)
				}
			}
			diverged++
			t.Errorf("seed %d: DIVERGENCE (put=%d noop=%d other=%d)", seed, putCount, noopCount, otherCount)
		} else if putCount == 0 && noopCount > 0 {
			lost++
			t.Errorf("seed %d: LOSS (chosen value replaced by NOOP on all committed replicas)", seed)
		} else if putCount > 0 {
			passed++
		} else {
			skipped++
		}
	}
	t.Logf("random fault campaign summary: pass=%d skip=%d loss=%d divergence=%d", passed, skipped, lost, diverged)
}
