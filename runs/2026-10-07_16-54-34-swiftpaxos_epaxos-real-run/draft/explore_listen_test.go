package epaxos

// Exploration harness: checks what the execution environment permits for listening, which
// decides whether the replica loop's startup phase can be measured here.

import (
	"fmt"
	"net"
	"testing"
)

func TestAssuranceListenPermissions(t *testing.T) {
	l1, err1 := net.Listen("tcp", "127.0.0.1:0")
	fmt.Println("CA_EVENT {\"event\":\"listen_loopback\",\"ok\":", err1 == nil, ",\"err\":\"", err1, "\"}")
	if l1 != nil {
		defer l1.Close()
	}
	l2, err2 := net.Listen("tcp", "0.0.0.0:39451")
	fmt.Println("CA_EVENT {\"event\":\"listen_any\",\"ok\":", err2 == nil, ",\"err\":\"", err2, "\"}")
	if l2 != nil {
		defer l2.Close()
	}
}
