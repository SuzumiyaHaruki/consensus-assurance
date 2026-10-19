package epaxos

import (
	"io"
	"net"
	"testing"
	"time"
)

// Environment check for the real-process cluster investigation.
func TestInvestigationLoopbackTCP(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skipf("loopback TCP unavailable: %v", err)
	}
	defer l.Close()
	done := make(chan error, 1)
	go func() {
		c, err := l.Accept()
		if err != nil {
			done <- err
			return
		}
		defer c.Close()
		buf := make([]byte, 4)
		_, err = io.ReadFull(c, buf)
		done <- err
	}()
	c, err := net.DialTimeout("tcp", l.Addr().String(), 2*time.Second)
	if err != nil {
		t.Fatalf("dial loopback: %v", err)
	}
	if _, err := c.Write([]byte("ping")); err != nil {
		t.Fatalf("write loopback: %v", err)
	}
	c.Close()
	if err := <-done; err != nil {
		t.Fatalf("read loopback: %v", err)
	}
}
