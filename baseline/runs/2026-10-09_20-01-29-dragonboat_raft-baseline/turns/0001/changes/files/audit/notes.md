# Investigation notes

- Confirmed remote ReadIndex batch response context mixup; see report.
- Ruled out normal observer heartbeat responses contributing to ReadIndex quorum: nonzero-context heartbeats are only broadcast to voting members (`broadcastHeartbeatMessageWithHint`). The shared response handler alone is insufficient evidence of a defect.
- Read initial Raft election, membership, replication, ReadIndex, remote progress, and in-memory log paths.
- Next targets: membership changes and pending ReadIndex quorum semantics; snapshot/observer promotion and election state; witness behavior; persistence/update ordering.
- Test-only source additions are named `audit_*_test.go`; no production or dependency edits.
- Confirmed snapshot GC stale tracked-pointer race; valid checksummed snapshot reproduction and successful retry control saved. See report.
- Rejected alternate GC tick-underflow idea for normal use: transport drives Tick synchronously from one goroutine, so the tick does not advance during GC. Stale pointer replacement remains reachable without advancing the tick.
- Checked snapshot metadata capture: uses s.index/s.term under state-machine mutex, not potentially lagging externally visible lastApplied; no mismatch finding.
- Checked LRU session checkpoint iteration: dependency OrderedDo iterates oldest-first, so getSession touches restore the same complete order. No successful-checkpoint recency defect found.
- Periodic state-machine sync tasks can execute before queued batched updates, but syncedIndex reflects actual prior applied state. No persistence safety finding from this alone.
