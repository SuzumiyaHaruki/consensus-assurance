package raft

import (
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// These controlled developer fixtures are not native discovery or a stored bug answer.
func assuranceDiscriminator(t *testing.T, phase string) (*AssuranceCluster, int, chan struct{}, <-chan AssuranceMessage, *int32) {
	release, entered := make(chan struct{}), make(chan AssuranceMessage, 1)
	armed := new(int32)
	configs := make([]*Config, 3)
	for i := range configs {
		conf := DefaultConfig()
		conf.LocalID = ServerID(fmt.Sprintf("node-%d", i))
		conf.HeartbeatTimeout, conf.ElectionTimeout, conf.LeaderLeaseTimeout = 200*time.Millisecond, 200*time.Millisecond, 100*time.Millisecond
		configs[i] = conf
	}
	cluster := NewAssuranceCluster(t, configs, func(int) FSM { return &MockFSM{} }, 500*time.Millisecond,
		func(message AssuranceMessage) <-chan struct{} {
			if message.Phase == phase && message.Kind == "*raft.AppendEntriesRequest" && atomic.CompareAndSwapInt32(armed, 1, 0) {
				entered <- message
				return release
			}
			return nil
		})
	deadline := time.After(4 * time.Second)
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-deadline:
			t.Fatal("No actual election observed")
		case <-ticker.C:
			for i, node := range cluster.Nodes {
				if node.State() == Leader {
					return cluster, i, release, entered, armed
				}
			}
		}
	}
}

func TestAssuranceVerificationBoundary(t *testing.T) {
	cluster, leader, release, entered, armed := assuranceDiscriminator(t, "reply_delivery")
	atomic.StoreInt32(armed, 1)
	future := cluster.Nodes[leader].VerifyLeader()
	select {
	case <-entered:
		close(release)
	case <-time.After(2 * time.Second):
		t.Fatal("No actual reply reached selected boundary")
	}
	err := future.Error()
	fmt.Printf("CA_EVENT {\"event\":\"verification_complete\",\"success\":%t}\n", err == nil)
	if err != nil {
		t.Fatal(err)
	}
}

func TestAssuranceApplicationBoundary(t *testing.T) {
	cluster, leader, release, entered, armed := assuranceDiscriminator(t, "request_delivery")
	atomic.StoreInt32(armed, 1)
	future := cluster.Nodes[leader].Apply([]byte("fixture-operation"), 2*time.Second)
	select {
	case <-entered:
		close(release)
	case <-time.After(2 * time.Second):
		t.Fatal("No actual request reached selected boundary")
	}
	if err := future.Error(); err != nil {
		t.Fatal(err)
	}
	fmt.Printf("CA_EVENT {\"event\":\"application_complete\",\"index\":%d}\n", future.Index())
}
