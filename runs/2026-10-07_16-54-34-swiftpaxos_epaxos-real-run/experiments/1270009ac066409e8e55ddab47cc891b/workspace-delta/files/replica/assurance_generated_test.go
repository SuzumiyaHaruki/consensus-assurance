package replica

// Exploration harness: the peer reader is driven directly with a stream whose first byte is
// not a registered message id, which is what a displaced stream produces after a truncated
// command value. Both logger configurations are exercised: the one production uses
// (verbose) and the one that does not print, so the reader's actual reaction is observed
// rather than inferred from its source.

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
)

// readerStub is a minimal serializable object so the table has one registered id; the
// observation is about the reader's reaction to an id that is not registered.
type readerStub struct{}

func (s *readerStub) New() fastrpc.Serializable { return &readerStub{} }
func (s *readerStub) Marshal(w io.Writer)       { w.Write([]byte{0}) }
func (s *readerStub) Unmarshal(r io.Reader) error {
	_, err := io.ReadFull(r, make([]byte, 1))
	return err
}

func readerNode(verbose bool) *Replica {
	r := &Replica{
		Logger:       dlog.New("", verbose),
		N:            3,
		F:            1,
		Id:           0,
		Alias:        "r0",
		PeerAddrList: []string{"a", "b", "c"},
		Alive:        make([]bool, 3),
		RPC:          fastrpc.NewTableId(defs.RPC_TABLE),
	}
	// Register one object so a valid id exists and the table is not empty.
	r.RPC.Register(new(readerStub), make(chan fastrpc.Serializable, 1))
	return r
}

func TestAssurancePeerReaderUnknownMessage(t *testing.T) {
	// Non-verbose logger: the fatal path is silent and does not exit.
	r := readerNode(false)
	fmt.Println("CA_EVENT {\"event\":\"reader_prepared\",\"verbose\":false,\"first_byte\":200}")
	r.replicaListener(1, bufio.NewReader(bytes.NewBuffer([]byte{200, 0, 0, 0, 0, 0, 0, 0, 0, 0})))
	fmt.Println("CA_EVENT {\"event\":\"reader_returned\",\"verbose\":false,\"alive_after\":", r.Alive[1], "}")

	// Verbose logger, which is what the launcher passes: the fatal path ends the process.
	r2 := readerNode(true)
	fmt.Println("CA_EVENT {\"event\":\"reader_prepared\",\"verbose\":true,\"first_byte\":200}")
	r2.replicaListener(1, bufio.NewReader(bytes.NewBuffer([]byte{200})))
	fmt.Println("CA_EVENT {\"event\":\"reader_returned\",\"verbose\":true,\"alive_after\":", r2.Alive[1], "}")
}
