//go:build dragonboat_audit

// Audit-only check of the exported channel-based transport plugin. The
// upstream tests define their own factory with a real Validate; the shipped
// ChanTransportFactory panics from Validate, which NodeHost calls during
// config validation.

package dragonboat

import (
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	chantrans "github.com/lni/dragonboat/v3/plugin/chan"
)

func TestAuditChanTransportFactoryIsUsable(t *testing.T) {
	fs := vfs.GetTestFS()
	dir := singleNodeHostTestDir
	if err := fs.RemoveAll(dir); err != nil {
		t.Fatalf("%v", err)
	}
	defer func() {
		if err := fs.RemoveAll(dir); err != nil {
			t.Fatalf("%v", err)
		}
	}()
	nhc := config.NodeHostConfig{
		WALDir:         dir,
		NodeHostDir:    dir,
		RTTMillisecond: 2,
		RaftAddress:    "localhost:12345",
		Expert: config.ExpertConfig{
			FS:               fs,
			TransportFactory: &chantrans.ChanTransportFactory{},
		},
	}
	var recovered interface{}
	func() {
		defer func() {
			recovered = recover()
		}()
		nh, err := NewNodeHost(nhc)
		if err == nil {
			nh.Stop()
		}
	}()
	if recovered != nil {
		t.Fatalf("NewNodeHost with the exported ChanTransportFactory panicked: %v", recovered)
	}
}
