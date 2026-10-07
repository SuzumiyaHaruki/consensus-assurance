package epaxos

import (
	"bufio"
	"bytes"
	"encoding/json"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
)

// TestAssuranceRecoverySubcaseDispatch drives the captured recovery dispatch
// (startRecoveryForInstance + handlePrepareReply) for the family of slow-quorum
// prepare answers in which the instance owner is silent and the pre-accepted
// replies agree. It records, for each scenario, which message the recovering
// replica actually broadcasts and which internal sub-case state it ends in.
//
// The harness only observes the target implementation; it asserts nothing about
// the expected dispatch (the checker evaluates that).
func TestAssuranceRecoverySubcaseDispatch(t *testing.T) {
	const (
		n         = 5
		recovering = int32(0)
		owner      = int32(1)
	)

	for scenario, peerPreaccepts := range []int{2, 1, 0} {
		instance := int32(scenario)
		r, buffers := assuranceReplica(n, recovering)
		cmds := []state.Command{{Op: state.PUT, K: state.Key(int64(100 + scenario)), V: state.Value([]byte("value"))}}

		// The recovering replica already holds its own candidate for (owner, instance):
		// an earlier recovery round re-proposed it (startPhase1 at ballot 5) and pre-accepted
		// it locally, while the instance owner never answered.
		r.InstanceSpace[owner][instance] = r.newInstance(owner, instance, cmds, 5, 5, PREACCEPTED, 1, assuranceDeps(n))
		r.crtInstance[owner] = instance
		r.startRecoveryForInstance(owner, instance)
		assuranceDrain(buffers) // the Prepare broadcast of this attempt

		lb := r.InstanceSpace[owner][instance].lb
		ballot := lb.lastTriedBallot

		// Owner (replica 1) stays silent. Two further prepare replies complete the
		// slow quorum: peer 2 and peer 3, of which the first peerPreaccepts carry an
		// equal pre-accept of the candidate at the same ballot and the rest report no
		// record for the instance.
		for i := 0; i < 2; i++ {
			reply := &PrepareReply{
				AcceptorId: int32(2 + i),
				Replica:    owner,
				Instance:   instance,
				Ballot:     ballot,
				VBallot:    -1,
				Status:     NONE,
				Seq:        -1,
				Deps:       assuranceDeps(n),
			}
			if i < peerPreaccepts {
				reply.VBallot = ballot
				reply.Status = PREACCEPTED_EQ
				reply.Seq = 1
				reply.Command = cmds
			}
			r.handlePrepareReply(reply)
		}

		dispatch, code := assuranceDispatch(r, assuranceDrain(buffers))
		replyCount := 1 + peerPreaccepts // the pre-seeded own reply plus the peers above
		evidence := "partial_preaccepted_owner_silent"
		if replyCount >= r.Replica.SlowQuorumSize() {
			evidence = "full_preaccepted_owner_silent"
		}
		held := r.InstanceSpace[owner][instance]
		trying := held.lb != nil && held.lb.tryingToPreAccept

		assuranceLog(t, map[string]interface{}{
			"event":              "recovery_quorum_gathered",
			"instance_replica":   owner,
			"instance_id":        instance,
			"ballot":             ballot,
			"quorum_size":        r.Replica.SlowQuorumSize(),
			"preaccepted_count":  replyCount,
			"evidence_class":     evidence,
			"owner_replied":      false,
			"peer_replies":       2,
		})
		assuranceLog(t, map[string]interface{}{
			"event":               "recovery_dispatch",
			"instance_replica":    owner,
			"instance_id":         instance,
			"ballot":              ballot,
			"quorum_size":         r.Replica.SlowQuorumSize(),
			"preaccepted_count":   replyCount,
			"evidence_class":      evidence,
			"owner_replied":       false,
			"dispatch":            dispatch,
			"rpc_code":            int(code),
			"instance_status":     int(held.Status),
			"trying_to_preaccept": trying,
		})
	}
}

// assuranceReplica builds an in-process epaxos.Replica that never touches the
// network: handlers are called directly and peer writes are captured in memory.
func assuranceReplica(n int, id int32) (*Replica, []*bytes.Buffer) {
	buffers := make([]*bytes.Buffer, n)
	writers := make([]*bufio.Writer, n)
	for i := 0; i < n; i++ {
		buffers[i] = new(bytes.Buffer)
		writers[i] = bufio.NewWriter(buffers[i])
	}
	r := &Replica{
		Replica: &replica.Replica{
			Logger:             dlog.New("", false),
			M:                  sync.Mutex{},
			N:                  n,
			F:                  (n - 1) / 2,
			Id:                 id,
			Alias:              "assurance",
			State:              state.InitState(),
			Stats:              &defs.Stats{M: map[string]int{}},
			Alive:              make([]bool, n),
			PreferredPeerOrder: make([]int32, n),
			PeerWriters:        writers,
			Thrifty:            true,
			Exec:               false,
			LRead:              false,
			Dreply:             true,
			Beacon:             false,
			Durable:            false,
		},
		prepareChan:           make(chan fastrpc.Serializable, 1),
		preAcceptChan:         make(chan fastrpc.Serializable, 1),
		acceptChan:            make(chan fastrpc.Serializable, 1),
		commitChan:            make(chan fastrpc.Serializable, 1),
		prepareReplyChan:      make(chan fastrpc.Serializable, 1),
		preAcceptReplyChan:    make(chan fastrpc.Serializable, 1),
		preAcceptOKChan:       make(chan fastrpc.Serializable, 1),
		acceptReplyChan:       make(chan fastrpc.Serializable, 1),
		tryPreAcceptChan:      make(chan fastrpc.Serializable, 1),
		tryPreAcceptReplyChan: make(chan fastrpc.Serializable, 1),
		InstanceSpace:         make([][]*Instance, n),
		crtInstance:           make([]int32, n),
		CommittedUpTo:         make([]int32, n),
		ExecedUpTo:            make([]int32, n),
		conflicts:             make([]map[state.Key]*InstPair, n),
		maxSeqPerKey:          make(map[state.Key]int32),
		clientMutex:           new(sync.Mutex),
		instancesToRecover:    make(chan *instanceId, 4),
		maxRecvBallot:         -1,
	}
	for i := 0; i < n; i++ {
		r.Alive[i] = true
		r.PreferredPeerOrder[i] = int32((int(id) + 1 + i) % n)
		r.InstanceSpace[i] = make([]*Instance, 64)
		r.crtInstance[i] = -1
		r.ExecedUpTo[i] = -1
		r.CommittedUpTo[i] = -1
		r.conflicts[i] = make(map[state.Key]*InstPair)
	}
	r.exec = &Exec{r}
	// Register the same message table order as epaxos.New so the RPC codes match.
	r.RPC = fastrpc.NewTableId(defs.RPC_TABLE)
	r.prepareRPC = r.RPC.Register(new(Prepare), r.prepareChan)
	r.prepareReplyRPC = r.RPC.Register(new(PrepareReply), r.prepareReplyChan)
	r.preAcceptRPC = r.RPC.Register(new(PreAccept), r.preAcceptChan)
	r.preAcceptReplyRPC = r.RPC.Register(new(PreAcceptReply), r.preAcceptReplyChan)
	r.acceptRPC = r.RPC.Register(new(Accept), r.acceptChan)
	r.acceptReplyRPC = r.RPC.Register(new(AcceptReply), r.acceptReplyChan)
	r.commitRPC = r.RPC.Register(new(Commit), r.commitChan)
	r.tryPreAcceptRPC = r.RPC.Register(new(TryPreAccept), r.tryPreAcceptChan)
	r.tryPreAcceptReplyRPC = r.RPC.Register(new(TryPreAcceptReply), r.tryPreAcceptReplyChan)
	return r, buffers
}

func assuranceDeps(n int) []int32 {
	deps := make([]int32, n)
	for i := range deps {
		deps[i] = -1
	}
	return deps
}

func assuranceDrain(buffers []*bytes.Buffer) [][]byte {
	written := make([][]byte, 0, len(buffers))
	for _, buffer := range buffers {
		if buffer.Len() == 0 {
			continue
		}
		written = append(written, append([]byte(nil), buffer.Bytes()...))
		buffer.Reset()
	}
	return written
}

func assuranceDispatch(r *Replica, written [][]byte) (string, uint8) {
	for _, message := range written {
		if len(message) == 0 {
			continue
		}
		switch message[0] {
		case r.acceptRPC:
			return "accept", message[0]
		case r.tryPreAcceptRPC:
			return "try_preaccept", message[0]
		case r.preAcceptRPC:
			return "phase1_restart", message[0]
		case r.commitRPC:
			return "commit_recovery", message[0]
		}
	}
	return "none", 0
}

func assuranceLog(t *testing.T, event map[string]interface{}) {
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("cannot encode observation: %v", err)
	}
	t.Log("CA_EVENT " + string(raw))
}
