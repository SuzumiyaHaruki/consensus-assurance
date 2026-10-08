// Audit diagnostic test (added for the consensus-assurance audit; NOT part of
// the captured implementation). The shipped NetworkTransport tests require TCP,
// which the sandbox forbids, so this exercises net_transport.go through a
// net.Pipe-backed StreamLayer (no sockets needed).
package raft

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

type pipeAddr string

func (a pipeAddr) Network() string { return "pipe" }
func (a pipeAddr) String() string  { return string(a) }

// pipeStream implements StreamLayer over in-memory net.Pipe connections.
type pipeStream struct {
	addr   ServerAddress
	ch     chan net.Conn
	closed chan struct{}
	once   sync.Once
}

func newPipeStream(addr ServerAddress) *pipeStream {
	return &pipeStream{addr: addr, ch: make(chan net.Conn, 16), closed: make(chan struct{})}
}

func (l *pipeStream) Accept() (net.Conn, error) {
	select {
	case c := <-l.ch:
		return c, nil
	case <-l.closed:
		return nil, errors.New("pipe stream closed")
	}
}

func (l *pipeStream) Close() error {
	l.once.Do(func() { close(l.closed) })
	return nil
}

func (l *pipeStream) Addr() net.Addr { return pipeAddr(l.addr) }

var pipeRegistry sync.Map // ServerAddress -> *pipeStream

func (l *pipeStream) Dial(address ServerAddress, timeout time.Duration) (net.Conn, error) {
	v, ok := pipeRegistry.Load(address)
	if !ok {
		return nil, fmt.Errorf("unknown target %s", address)
	}
	peer := v.(*pipeStream)
	c1, c2 := net.Pipe()
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case peer.ch <- c2:
		return c1, nil
	case <-timer.C:
		c1.Close()
		c2.Close()
		return nil, fmt.Errorf("dial timeout to %s", address)
	case <-peer.closed:
		c1.Close()
		c2.Close()
		return nil, errors.New("peer closed")
	}
}

// TestAudit_NetTransportPipe exercises the core NetworkTransport RPC paths
// (generic request/response, InstallSnapshot streaming, and the AppendEntries
// pipeline) without AF_INET.
func TestAudit_NetTransportPipe(t *testing.T) {
	if os.Getenv("AUDIT_PIPE_TRANSPORT") == "" {
		t.Skip("experimental net.Pipe transport harness; set AUDIT_PIPE_TRANSPORT=1 to run")
	}
	addrA := ServerAddress("pipe-a")
	addrB := ServerAddress("pipe-b")
	sA := newPipeStream(addrA)
	sB := newPipeStream(addrB)
	pipeRegistry.Store(addrA, sA)
	pipeRegistry.Store(addrB, sB)
	defer pipeRegistry.Delete(addrA)
	defer pipeRegistry.Delete(addrB)

	logger := hclog.NewNullLogger()
	tA := NewNetworkTransportWithLogger(sA, 4, 5*time.Second, logger)
	tB := NewNetworkTransportWithLogger(sB, 4, 5*time.Second, logger)
	defer tA.Close()
	defer tB.Close()

	// Node B answers RPCs.
	go func() {
		for rpc := range tB.Consumer() {
			switch cmd := rpc.Command.(type) {
			case *AppendEntriesRequest:
				rpc.Respond(&AppendEntriesResponse{
					RPCHeader: cmd.RPCHeader,
					Term:      cmd.Term,
					Success:   true,
					LastLog:   cmd.PrevLogEntry + uint64(len(cmd.Entries)),
				}, nil)
			case *RequestVoteRequest:
				rpc.Respond(&RequestVoteResponse{Term: cmd.Term, Granted: true}, nil)
			case *RequestPreVoteRequest:
				rpc.Respond(&RequestPreVoteResponse{Term: cmd.Term, Granted: true}, nil)
			case *TimeoutNowRequest:
				rpc.Respond(&TimeoutNowResponse{}, nil)
			case *InstallSnapshotRequest:
				if _, err := io.Copy(io.Discard, rpc.Reader); err != nil {
					rpc.Respond(nil, err)
					continue
				}
				rpc.Respond(&InstallSnapshotResponse{Term: cmd.Term, Success: true}, nil)
			default:
				rpc.Respond(nil, fmt.Errorf("unexpected command %T", rpc.Command))
			}
		}
	}()

	// Generic RPC round-trip (AppendEntries).
	var aresp AppendEntriesResponse
	if err := tA.AppendEntries(ServerID("B"), addrB,
		&AppendEntriesRequest{Term: 7, PrevLogEntry: 0, LeaderCommitIndex: 0}, &aresp); err != nil {
		t.Fatalf("AppendEntries RPC failed: %v", err)
	}
	if !aresp.Success || aresp.Term != 7 {
		t.Fatalf("bad AppendEntriesResponse: %+v", aresp)
	}

	// RequestVote / PreVote / TimeoutNow.
	var vresp RequestVoteResponse
	if err := tA.RequestVote(ServerID("B"), addrB, &RequestVoteRequest{Term: 8}, &vresp); err != nil {
		t.Fatalf("RequestVote RPC failed: %v", err)
	}
	if !vresp.Granted {
		t.Fatalf("vote not granted: %+v", vresp)
	}
	var pvresp RequestPreVoteResponse
	if err := tA.RequestPreVote(ServerID("B"), addrB, &RequestPreVoteRequest{Term: 8}, &pvresp); err != nil {
		t.Fatalf("RequestPreVote RPC failed: %v", err)
	}
	if !pvresp.Granted {
		t.Fatalf("pre-vote not granted: %+v", pvresp)
	}
	var tresp TimeoutNowResponse
	if err := tA.TimeoutNow(ServerID("B"), addrB, &TimeoutNowRequest{}, &tresp); err != nil {
		t.Fatalf("TimeoutNow RPC failed: %v", err)
	}

	// InstallSnapshot with streamed payload.
	payload := []byte("snapshot-payload-0123456789")
	var isresp InstallSnapshotResponse
	if err := tA.InstallSnapshot(ServerID("B"), addrB,
		&InstallSnapshotRequest{Term: 9, Size: int64(len(payload))},
		&isresp, bytes.NewReader(payload)); err != nil {
		t.Fatalf("InstallSnapshot RPC failed: %v", err)
	}
	if !isresp.Success {
		t.Fatalf("snapshot not installed: %+v", isresp)
	}

	// Pipelined AppendEntries.
	p, err := tA.AppendEntriesPipeline(ServerID("B"), addrB)
	if err != nil {
		t.Fatalf("AppendEntriesPipeline failed: %v", err)
	}
	defer p.Close()
	for i := 0; i < 10; i++ {
		f, err := p.AppendEntries(&AppendEntriesRequest{Term: 10, PrevLogEntry: uint64(i)},
			&AppendEntriesResponse{})
		if err != nil {
			t.Fatalf("pipeline AppendEntries %d failed: %v", i, err)
		}
		if err := f.Error(); err != nil {
			t.Fatalf("pipeline future %d failed: %v", i, err)
		}
	}
}
