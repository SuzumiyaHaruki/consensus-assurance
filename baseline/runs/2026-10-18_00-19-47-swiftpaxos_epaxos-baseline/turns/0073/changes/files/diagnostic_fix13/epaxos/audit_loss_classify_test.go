package epaxos

import (
	"fmt"
	"math/rand"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

// Classify all-NOOP outcomes in the fixed stack by how many replicas held the
// proposed command before recovery.  Three or more holders would be a likely
// chosen-value loss and needs review.
func TestInvestigationLossClassifier(t *testing.T) {
	chosen := state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")}
	buckets := make(map[int]int)
	chosenLikely := 0
	for seed := int64(1); seed <= 1000; seed++ {
		rng := rand.New(rand.NewSource(seed))
		c := newAuditCluster(5)
		c.drop = func(from, to int32, code uint8) bool { return rng.Intn(100) < 20 }
		c.propose(0, 1, chosen)
		if err := c.run(100000); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}

		holders := 0
		committed := 0
		leaderHolds := false
		attrs := make(map[string]int)
		for i := 0; i < 5; i++ {
			inst := c.instance(i, 0, 0)
			if randomFaultHasChosen(inst, chosen) {
				holders++
				if i == 0 {
					leaderHolds = true
				}
				attrs[fmt.Sprintf("seq=%d deps=%v", inst.Seq, inst.Deps)]++
				if inst.Status == COMMITTED {
					committed++
				}
			}
		}
		if holders == 0 {
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
			t.Fatalf("seed %d recovery: %v", seed, err)
		}

		put, noop, other := 0, 0, 0
		for i := 0; i < 5; i++ {
			inst := c.instance(i, 0, 0)
			if inst == nil || inst.Status != COMMITTED {
				continue
			}
			switch {
			case randomFaultHasChosen(inst, chosen):
				put++
			case randomFaultIsNOOP(inst):
				noop++
			default:
				other++
			}
		}
		if put == 0 && other == 0 && noop == 5 {
			buckets[holders]++
			t.Logf("seed %d: all-NOOP loss, pre-holders=%d (committed=%d leader=%t attrs=%v)",
				seed, holders, committed, leaderHolds, attrs)
			if holders >= 3 && leaderHolds && len(attrs) == 1 {
				chosenLikely++
				t.Logf("seed %d: fast-path chosen candidate (3 identical holders including leader)", seed)
				t.Errorf("seed %d: a fast-path chosen value was lost on all five replicas", seed)
			}
		}
		if put > 0 && noop > 0 {
			t.Errorf("seed %d: mixed committed values put=%d noop=%d", seed, put, noop)
		}
	}
	t.Logf("all-NOOP loss holders distribution: %v; fast-path chosen candidates=%d", buckets, chosenLikely)
}
