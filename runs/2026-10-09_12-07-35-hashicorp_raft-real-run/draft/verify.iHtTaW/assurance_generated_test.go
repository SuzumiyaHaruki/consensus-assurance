package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type tnFSM struct{}

func (f *tnFSM) Apply(l *Log) interface{}       { return nil }
func (f *tnFSM) Snapshot() (FSMSnapshot, error) { return &tnSnapshot{}, nil }
func (f *tnFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type tnSnapshot struct{}

func (s *tnSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *tnSnapshot) Release()                        {}

func tnEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// tnNode builds one Raft node with background goroutines disabled and a
// bootstrapped configuration of the given voters, and gives it a known leader
// so a TimeoutNow effect (losing that leader) is observable.
func tnNode(t *testing.T, localID ServerID, voters []ServerID) *Raft {
	t.Helper()
	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = localID
	_, trans := NewInmemTransport(ServerAddress(localID))
	logs, stable, snaps := NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore()
	configuration := Configuration{}
	for _, v := range voters {
		configuration.Servers = append(configuration.Servers, Server{
			Suffrage: Voter, ID: v, Address: ServerAddress(v),
		})
	}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("BootstrapCluster(%s): %v", localID, err)
	}
	r, err := NewRaft(conf, &tnFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft(%s): %v", localID, err)
	}
	// The node currently has a known leader, as it would between heartbeats.
	r.setState(Follower)
	r.setLeader(ServerAddress(voters[1]), voters[1])
	return r
}

func tnProbe(r *Raft) (ServerAddress, ServerID, RaftState, bool) {
	addr, id := r.LeaderWithID()
	return addr, id, r.getState(), r.candidateFromLeadershipTransfer.Load()
}

func tnSendTimeoutNow(r *Raft, sender ServerID, proto ProtocolVersion) RPCResponse {
	ch := make(chan RPCResponse, 1)
	req := &TimeoutNowRequest{RPCHeader: RPCHeader{
		ProtocolVersion: proto,
		ID:              []byte(sender),
		Addr:            r.trans.EncodePeer(sender, ServerAddress(sender)),
	}}
	r.processRPC(RPC{Command: req, RespChan: ch})
	return <-ch
}

// TestAssuranceTimeoutNowSenderAttribution observes whether a TimeoutNow whose
// sender is not a voter of the receiver's latest configuration is honoured
// identically to one from a configured voter, and whether the only guard on
// this path is the RPC-header version window.
func TestAssuranceTimeoutNowSenderAttribution(t *testing.T) {
	const intruder = ServerID("intruder")
	const configured = ServerID("node2")
	voters := []ServerID{"node1", configured}

	// Case: sender is not a voter of the receiver's configuration.
	unattributed := tnNode(t, "node1", voters)
	tnEmit(t, map[string]interface{}{
		"event":                      "sender_scope_declared",
		"op_id":                      "tn-1",
		"sender_id":                  string(intruder),
		"sender_is_configured_voter": false,
		"configuration_nonempty":     true,
		"configured_voters":          []string{string(voters[0]), string(voters[1])},
	})
	uLeaderBefore, _, uStateBefore, uFlagBefore := tnProbe(unattributed)
	uResp := tnSendTimeoutNow(unattributed, intruder, ProtocolVersionMax)
	uLeaderAfter, _, uStateAfter, uFlagAfter := tnProbe(unattributed)
	uGranted := uStateAfter == Candidate && uFlagAfter
	tnEmit(t, map[string]interface{}{
		"event":                      "timeout_now_result",
		"op_id":                      "tn-1",
		"sender_id":                  string(intruder),
		"sender_is_configured_voter": false,
		"rpc_header_in_window":       true,
		"rejected":                   uResp.Error != nil,
		"error":                      fmt.Sprintf("%v", uResp.Error),
		"leader_before":              string(uLeaderBefore),
		"leader_after":               string(uLeaderAfter),
		"state_before":               uStateBefore.String(),
		"state_after":                uStateAfter.String(),
		"privilege_before":           uFlagBefore,
		"privilege_after":            uFlagAfter,
		"transfer_privilege_granted": uGranted,
	})

	// Control: sender is a voter of the receiver's configuration.
	attributed := tnNode(t, "node1", voters)
	tnEmit(t, map[string]interface{}{
		"event":                      "configured_sender_declared",
		"op_id":                      "tn-2",
		"sender_id":                  string(configured),
		"sender_is_configured_voter": true,
		"configuration_nonempty":     true,
	})
	aLeaderBefore, _, _, _ := tnProbe(attributed)
	aResp := tnSendTimeoutNow(attributed, configured, ProtocolVersionMax)
	aLeaderAfter, _, aStateAfter, aFlagAfter := tnProbe(attributed)
	tnEmit(t, map[string]interface{}{
		"event":                      "control_configured_sender_result",
		"op_id":                      "tn-2",
		"sender_id":                  string(configured),
		"sender_is_configured_voter": true,
		"rpc_header_in_window":       true,
		"rejected":                   aResp.Error != nil,
		"leader_before":              string(aLeaderBefore),
		"leader_after":               string(aLeaderAfter),
		"state_after":                aStateAfter.String(),
		"transfer_privilege_granted": aStateAfter == Candidate && aFlagAfter,
	})

	// Control: the only guard on this path is the RPC-header version window.
	outOfWindow := tnNode(t, "node1", voters)
	oLeaderBefore, _, _, _ := tnProbe(outOfWindow)
	oResp := tnSendTimeoutNow(outOfWindow, intruder, ProtocolVersion(0))
	oLeaderAfter, _, oStateAfter, oFlagAfter := tnProbe(outOfWindow)
	tnEmit(t, map[string]interface{}{
		"event":                      "control_out_of_window_result",
		"op_id":                      "tn-3",
		"sender_id":                  string(intruder),
		"sender_is_configured_voter": false,
		"rpc_header_in_window":       false,
		"rejected":                   oResp.Error != nil,
		"error":                      fmt.Sprintf("%v", oResp.Error),
		"leader_before":              string(oLeaderBefore),
		"leader_after":               string(oLeaderAfter),
		"state_after":                oStateAfter.String(),
		"transfer_privilege_granted": oStateAfter == Candidate && oFlagAfter,
	})
}
