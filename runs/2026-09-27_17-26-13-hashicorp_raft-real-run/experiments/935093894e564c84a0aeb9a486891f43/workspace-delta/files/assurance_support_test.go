package raft

import (
	"encoding/json"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// AssuranceMessage identifies one actual RPC and its delivery boundary.
// Payload records actual input/output; callers supply their own discriminator.
type AssuranceMessage struct {
	ID       uint64 `json:"message_id"`
	Sender   string `json:"sender"`
	Receiver string `json:"receiver"`
	Kind     string `json:"kind"`
	Phase    string `json:"event"`
	Payload  string `json:"payload"`
	Error    string `json:"error,omitempty"`
}

type AssuranceCluster struct {
	Nodes      []*Raft
	Transports []*InmemTransport
	done       chan struct{}
	workers    sync.WaitGroup
	sequence   uint64
	emit       sync.Mutex
	gate       func(AssuranceMessage) <-chan struct{}
}

type assuranceTransport struct {
	*InmemTransport
	inbox chan RPC
}

func (t *assuranceTransport) Consumer() <-chan RPC { return t.inbox }

func (c *AssuranceCluster) record(m AssuranceMessage) {
	c.emit.Lock()
	raw, err := json.Marshal(m)
	if err != nil {
		c.emit.Unlock()
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(raw))
	c.emit.Unlock()
}

func (c *AssuranceCluster) boundary(m AssuranceMessage) bool {
	c.record(m)
	var release <-chan struct{}
	if c.gate != nil {
		release = c.gate(m)
	}
	if release != nil {
		select {
		case <-release:
		case <-c.done:
			return false
		}
	}
	select {
	case <-c.done:
		return false
	default:
		return true
	}
}

func (c *AssuranceCluster) forward(t *assuranceTransport, receiver ServerID, rpc RPC) {
	defer c.workers.Done()
	data, err := json.Marshal(rpc.Command)
	if err != nil {
		panic(err)
	}
	m := AssuranceMessage{ID: atomic.AddUint64(&c.sequence, 1), Receiver: string(receiver),
		Kind: fmt.Sprintf("%T", rpc.Command), Phase: "request_delivery", Payload: string(data)}
	if h, ok := rpc.Command.(WithRPCHeader); ok {
		m.Sender = string(h.GetRPCHeader().ID)
	}
	if !c.boundary(m) {
		return
	}
	response := make(chan RPCResponse, 1)
	actual := rpc
	actual.RespChan = response
	select {
	case t.inbox <- actual:
	case <-c.done:
		return
	}
	m.Phase = "request_handoff"
	c.record(m)
	var result RPCResponse
	select {
	case result = <-response:
	case <-c.done:
		return
	}
	data, err = json.Marshal(result.Response)
	if err != nil {
		panic(err)
	}
	m.Phase, m.Payload = "reply_delivery", string(data)
	if result.Error != nil {
		m.Error = result.Error.Error()
	}
	if !c.boundary(m) {
		return
	}
	select {
	case rpc.RespChan <- result:
		m.Phase = "reply_handoff"
		c.record(m)
	case <-c.done:
	}
}

// Configurations, FSMs and timeouts are experiment inputs, never hidden answers.
// Bootstrap uses the public API; every election and reply comes from real workers.
func NewAssuranceCluster(t *testing.T, configs []*Config, fsm func(int) FSM,
	rpcTimeout time.Duration, gate func(AssuranceMessage) <-chan struct{}) *AssuranceCluster {
	return NewAssuranceClusterWithSuffrage(t, configs, nil, fsm, rpcTimeout, gate)
}

// Explicit initial membership is passed unchanged to the public bootstrap API.
// A nil list retains the all-voter convenience entry point.
func NewAssuranceClusterWithSuffrage(t *testing.T, configs []*Config, suffrage []ServerSuffrage,
	fsm func(int) FSM, rpcTimeout time.Duration, gate func(AssuranceMessage) <-chan struct{}) *AssuranceCluster {
	t.Helper()
	if len(suffrage) != 0 && len(suffrage) != len(configs) {
		t.Fatal("suffrage must name every configured member")
	}
	c := &AssuranceCluster{done: make(chan struct{}), gate: gate}
	t.Cleanup(func() {
		close(c.done)
		futures := make([]Future, 0, len(c.Nodes))
		for _, node := range c.Nodes {
			futures = append(futures, node.Shutdown())
		}
		for _, transport := range c.Transports {
			transport.Close()
		}
		finished := make(chan struct{})
		go func() {
			for _, future := range futures {
				future.Error()
			}
			c.workers.Wait()
			close(finished)
		}()
		select {
		case <-finished:
		case <-time.After(5 * time.Second):
			t.Error("Raft helper cleanup timed out")
		}
	})
	configuration := Configuration{}
	for index, conf := range configs {
		_, transport := NewInmemTransportWithTimeout(ServerAddress(conf.LocalID), rpcTimeout)
		c.Transports = append(c.Transports, transport)
		role := Voter
		if len(suffrage) != 0 {
			role = suffrage[index]
		}
		configuration.Servers = append(configuration.Servers, Server{ID: conf.LocalID,
			Address: transport.LocalAddr(), Suffrage: role})
	}
	for i, transport := range c.Transports {
		for j, peer := range c.Transports {
			if i != j {
				transport.Connect(peer.LocalAddr(), peer)
			}
		}
	}
	for i, transport := range c.Transports {
		conf := *configs[i]
		store, snapshots := NewInmemStore(), NewInmemSnapshotStore()
		proxy := &assuranceTransport{InmemTransport: transport, inbox: make(chan RPC)}
		if err := BootstrapCluster(&conf, store, store, snapshots, proxy, configuration); err != nil {
			t.Fatal(err)
		}
		c.workers.Add(1)
		go func(receiver ServerID, tr *assuranceTransport) {
			defer c.workers.Done()
			for {
				select {
				case rpc := <-tr.InmemTransport.Consumer():
					c.workers.Add(1)
					go c.forward(tr, receiver, rpc)
				case <-c.done:
					return
				}
			}
		}(conf.LocalID, proxy)
		node, err := NewRaft(&conf, fsm(i), store, store, snapshots, proxy)
		if err != nil {
			t.Fatal(err)
		}
		c.Nodes = append(c.Nodes, node)
	}
	return c
}
