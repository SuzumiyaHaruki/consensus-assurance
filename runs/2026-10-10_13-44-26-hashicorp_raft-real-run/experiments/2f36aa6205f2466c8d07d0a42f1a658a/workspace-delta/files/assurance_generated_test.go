package raft

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

type assuranceRecordingTransport struct {
	*InmemTransport

	mu            sync.Mutex
	confirmations map[ServerAddress]int
}

func (t *assuranceRecordingTransport) AppendEntries(id ServerID, target ServerAddress, args *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	err := t.InmemTransport.AppendEntries(id, target, args, resp)
	t.mu.Lock()
	if err == nil && resp.Success {
		t.confirmations[target]++
	}
	t.mu.Unlock()
	return err
}

// AppendEntriesPipeline deliberately declines the documented optional pipeline
// fast path so every AppendEntries result is visible to this observation.
func (t *assuranceRecordingTransport) AppendEntriesPipeline(id ServerID, target ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}

func (t *assuranceRecordingTransport) resetConfirmations() {
	t.mu.Lock()
	t.confirmations = make(map[ServerAddress]int)
	t.mu.Unlock()
}

func (t *assuranceRecordingTransport) confirmationCounts() map[ServerAddress]int {
	t.mu.Lock()
	defer t.mu.Unlock()
	copied := make(map[ServerAddress]int, len(t.confirmations))
	for address, count := range t.confirmations {
		copied[address] = count
	}
	return copied
}

type assuranceNode struct {
	id    ServerID
	addr  ServerAddress
	store *InmemStore
	snap  *InmemSnapshotStore
	trans *assuranceRecordingTransport
	raft  *Raft
}

func assuranceEmit(t *testing.T, value map[string]interface{}) {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(encoded))
}

func assuranceWaitForLeader(t *testing.T, nodes []*assuranceNode, timeout time.Duration) *assuranceNode {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		var found *assuranceNode
		count := 0
		for _, node := range nodes {
			if node.raft.State() == Leader {
				found = node
				count++
			}
		}
		if count == 1 {
			return found
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for one leader")
	return nil
}

func assuranceWaitForFollower(t *testing.T, nodes []*assuranceNode, leader *assuranceNode, timeout time.Duration) *assuranceNode {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		for _, node := range nodes {
			if node != leader && node.raft.State() == Follower {
				return node
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for a follower")
	return nil
}

func TestAssuranceNonVoterCannotCompleteVerifyLeaderQuorum(t *testing.T) {
	const nodeCount = 4
	base := DefaultConfig()
	base.ProtocolVersion = ProtocolVersionMax
	base.HeartbeatTimeout = 5 * time.Second
	base.ElectionTimeout = 5 * time.Second
	base.LeaderLeaseTimeout = 5 * time.Second
	base.CommitTimeout = 20 * time.Millisecond
	base.SnapshotInterval = time.Hour
	base.SnapshotThreshold = 1 << 20
	base.TrailingLogs = 1024

	nodes := make([]*assuranceNode, 0, nodeCount)
	var configuration Configuration
	for i := 0; i < nodeCount; i++ {
		address, transport := NewInmemTransport("")
		nodes = append(nodes, &assuranceNode{
			id:    ServerID(fmt.Sprintf("assurance-node-%d", i)),
			addr:  address,
			store: NewInmemStore(),
			snap:  NewInmemSnapshotStore(),
			trans: &assuranceRecordingTransport{
				InmemTransport: transport,
				confirmations:  make(map[ServerAddress]int),
			},
		})
		configuration.Servers = append(configuration.Servers, Server{
			Suffrage: Voter,
			ID:       nodes[i].id,
			Address:  nodes[i].addr,
		})
	}
	for _, source := range nodes {
		for _, target := range nodes {
			if source != target {
				source.trans.InmemTransport.Connect(target.addr, target.trans.InmemTransport)
			}
		}
	}
	for _, node := range nodes {
		conf := *base
		conf.LocalID = node.id
		conf.Logger = hclog.NewNullLogger()
		if err := BootstrapCluster(&conf, node.store, node.store, node.snap, node.trans, configuration); err != nil {
			t.Fatalf("bootstrap %s: %v", node.id, err)
		}
		raft, err := NewRaft(&conf, &MockFSM{}, node.store, node.store, node.snap, node.trans)
		if err != nil {
			t.Fatalf("start %s: %v", node.id, err)
		}
		node.raft = raft
	}
	defer func() {
		for _, node := range nodes {
			node.raft.Shutdown().Error()
		}
	}()

	leader := assuranceWaitForLeader(t, nodes, 20*time.Second)
	if err := leader.raft.Barrier(10 * time.Second).Error(); err != nil {
		t.Fatalf("initial barrier: %v", err)
	}

	demoted := assuranceWaitForFollower(t, nodes, leader, 5*time.Second)
	if err := leader.raft.DemoteVoter(demoted.id, 0, 10*time.Second).Error(); err != nil {
		t.Fatalf("demote %s: %v", demoted.id, err)
	}

	configurationFuture := leader.raft.GetConfiguration()
	if err := configurationFuture.Error(); err != nil {
		t.Fatalf("read configuration: %v", err)
	}
	current := configurationFuture.Configuration()
	voterAddresses := make(map[ServerAddress]ServerID)
	nonvoterAddresses := make(map[ServerAddress]ServerID)
	var isolated []ServerAddress
	for _, server := range current.Servers {
		if server.Suffrage == Voter {
			voterAddresses[server.Address] = server.ID
			if server.ID != leader.id {
				isolated = append(isolated, server.Address)
			}
		} else {
			nonvoterAddresses[server.Address] = server.ID
		}
	}
	if len(voterAddresses) != 3 || len(nonvoterAddresses) != 1 {
		t.Fatalf("unexpected configuration after demotion: %+v", current)
	}

	for _, source := range nodes {
		for _, target := range isolated {
			if source.addr == target {
				continue
			}
			source.trans.Disconnect(target)
			for _, peer := range nodes {
				if peer.addr == target {
					peer.trans.Disconnect(source.addr)
				}
			}
		}
	}

	leader.trans.resetConfirmations()
	assuranceEmit(t, map[string]interface{}{
		"event":                     "verify_setup",
		"leader_id":                 string(leader.id),
		"quorum_size":               len(voterAddresses)/2 + 1,
		"voter_count":               len(voterAddresses),
		"nonvoter_count":            len(nonvoterAddresses),
		"isolated_voter_count":      len(isolated),
		"nonvoter_connected":        true,
		"operation":                 "VerifyLeader",
		"observation_owner":         "leader transport",
		"pipeline_fastpath_enabled": false,
	})

	verifyResult := make(chan error, 1)
	go func() {
		verifyResult <- leader.raft.VerifyLeader().Error()
	}()

	var verifyErr error
	select {
	case verifyErr = <-verifyResult:
	case <-time.After(3 * time.Second):
		verifyErr = fmt.Errorf("VerifyLeader did not complete within 3s")
	}

	confirmations := leader.trans.confirmationCounts()
	voterConfirmations := 0
	nonvoterConfirmations := 0
	for address, count := range confirmations {
		if count == 0 {
			continue
		}
		if _, ok := voterAddresses[address]; ok {
			voterConfirmations++
		}
		if _, ok := nonvoterAddresses[address]; ok {
			nonvoterConfirmations++
		}
	}
	voterContactCount := 1 + voterConfirmations
	voterQuorumMet := voterContactCount >= len(voterAddresses)/2+1

	result := "denied"
	if verifyErr == nil {
		result = "confirmed"
	}
	errorText := ""
	if verifyErr != nil {
		errorText = verifyErr.Error()
	}
	assuranceEmit(t, map[string]interface{}{
		"event":                       "verify_outcome",
		"leader_id":                   string(leader.id),
		"operation":                   "VerifyLeader",
		"result":                      result,
		"error":                       errorText,
		"voter_contact_count":         voterContactCount,
		"voter_confirmation_count":    voterConfirmations,
		"nonvoter_confirmation_count": nonvoterConfirmations,
		"quorum_size":                 len(voterAddresses)/2 + 1,
		"voter_quorum_met":            voterQuorumMet,
	})
}
