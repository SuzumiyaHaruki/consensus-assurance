package epaxos

// Exploration harness: the latency helper resolves the local address by dialling a fixed
// probe address. The harness calls it and reports whether it returns or panics; the helper
// is unmodified.

import (
	"encoding/json"
	"fmt"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica/defs"
)

func iev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceLocalAddressProbe(t *testing.T) {
	iev(map[string]any{"event": "probe_request", "subject": "local-address"})
	panicked := false
	panicValue := ""
	value := ""
	func() {
		defer func() {
			if v := recover(); v != nil {
				panicked = true
				panicValue = fmt.Sprint(v)
			}
		}()
		value = defs.IP()
	}()
	iev(map[string]any{"event": "local_address_probe", "subject": "local-address", "panicked": panicked,
		"panic_value": panicValue, "value_nonempty": value != "", "value_len": len(value)})
}
