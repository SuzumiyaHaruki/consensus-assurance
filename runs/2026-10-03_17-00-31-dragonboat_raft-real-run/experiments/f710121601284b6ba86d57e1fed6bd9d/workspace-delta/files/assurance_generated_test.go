package dragonboat

import (
    "os"
    "os/exec"
    "path/filepath"
    "runtime"
    "testing"
)

// The configured runner targets the module root. The protocol check itself
// belongs to internal/raft so that it can inspect admission without changing
// or exporting implementation internals.
func TestAssuranceForwardedReadLauncher(t *testing.T) {
    cmd := exec.Command(filepath.Join(runtime.GOROOT(), "bin", "go"),
        "test", "-v", "-count=1", "-timeout=300s",
        "-run", "^TestAssuranceForwardedReadContexts$", "./internal/raft")
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    if err := cmd.Run(); err != nil {
        t.Fatalf("internal/raft check did not complete successfully: %v", err)
    }
}
