package epaxos

// Exploration harness: the local-address helper that replica construction evaluates is also
// evaluated by the client constructor. This asks whether a client can be created in an
// environment where socket operations are not permitted, so the startup finding's scope can
// be stated with the entry points it actually affects.

import (
	"encoding/json"
	"fmt"
	"testing"

	"github.com/imdea-software/swiftpaxos/client"
	"github.com/imdea-software/swiftpaxos/dlog"
)

func cev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceClientConstructionProbe(t *testing.T) {
	panicked := false
	panicValue := ""
	created := false
	func() {
		defer func() {
			if v := recover(); v != nil {
				panicked = true
				panicValue = fmt.Sprint(v)
			}
		}()
		c := client.NewClientLog("127.0.0.1:39452", "127.0.0.1", 7087, false, true, false, dlog.New("", false))
		created = c != nil
	}()
	cev(map[string]any{"event": "client_construction", "panicked": panicked,
		"panic_value": panicValue, "created": created})
}
