package dragonboat

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/lni/goutils/syncutil"
)

const assurancePanicChildEnv = "CA_WORKER_PANIC_CHILD"

// TestAssuranceWorkerPanicOutcome runs the same stopper launch the engine's
// snapshot workers use, with a worker function that panics, in a child process
// so that the parent can report what happened to the process as a whole.
func TestAssuranceWorkerPanicOutcome(t *testing.T) {
	if os.Getenv(assurancePanicChildEnv) == "1" {
		stopper := syncutil.NewStopper()
		stopper.RunWorker(func() {
			fmt.Println("CA_EVENT {\"event\":\"child_worker_started\"}")
			panic("assurance worker panic")
		})
		time.Sleep(500 * time.Millisecond)
		fmt.Println("CA_EVENT {\"event\":\"child_survived\"}")
		stopper.Stop()
		return
	}

	cmd := exec.Command(os.Args[0],
		"-test.run", "TestAssuranceWorkerPanicOutcome", "-test.v")
	cmd.Env = append(os.Environ(), assurancePanicChildEnv+"=1")
	out, err := cmd.CombinedOutput()
	text := string(out)
	started := strings.Contains(text, "child_worker_started")
	survived := strings.Contains(text, "child_survived")
	panicked := strings.Contains(text, "panic: assurance worker panic")
	exitCode := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			exitCode = ee.ExitCode()
		} else {
			fmt.Printf("CA_EVENT {\"event\":\"spawn_failed\",\"error\":%q}\n", err.Error())
			return
		}
	}
	fmt.Printf("CA_EVENT {\"event\":\"child_result\",\"worker_started\":%t,\"survived\":%t,\"panicked\":%t,\"exit_code\":%d}\n",
		started, survived, panicked, exitCode)
}
