# 共识审计研究报告

方法 `audit-products-v62`；模式 `real/autonomous`；持续 30.14 分钟。
停止原因：Agent stopped: Action timeout exceeded; process group killed

## 问题与证据

### 追随者安装快照后仍上报快照索引以上的旧日志导致无法追上：单调与非单调日志存储均受影响

当前处置：已有源码解释。
问题 `b02f82dfc4024a638ae4ecbdcb18b1fc-question-0` v4；来源：install_snapshot, get_last_entry, append_prev_check, set_previous_log, replicate_to, send_latest_snapshot（[完整引用](state.json)）。
原命题：When a follower installs a snapshot while its persisted log already ends above the snapshot's LastLogIndex, does the follower's last-log report allow the leader's next AppendEntries (PrevLogEntry = snapshot index) to be accepted, or does the leader loop re-transferring the same snapshot with no follower progress?
假设：installSnapshot restores the FSM, sets lastApplied/lastSnapshot/configuration and compacts logs at or below req.LastLogIndex, but never truncates log entries above req.LastLogIndex and never calls setLastLog. The cached lastLogIndex/lastLogTerm therefore keep the stale suffix, so getLastEntry reports (staleLast, staleTerm) instead of (snapshotIndex, snapshotTerm) whenever lastLogIndex > lastSnapshotIndex. appendEntries then fails the PrevLogEntry==lastIdx branch and either logs.GetLog errors (entries compacted) or returns the stale term, so it rejects with NoRetryBackoff. The leader lowers nextIndex by one (resp.LastLog+1 is above nextIndex-1, so min picks nextIndex-1), and once nextIndex-1 falls below the leader's compacted first index setupAppendEntries returns ErrLogNotFound and the leader re-sends the identical snapshot.
下一判别条件：Run the same 3-node in-memory scenario twice: with the isolated node's pre-reconnect last log index below the replacement leader's snapshot index (control, no stale suffix) and above it (case, stale suffix). If the explanation holds the control converges after one install, while the case leaves the isolated node stuck at the snapshot index with leader commit index above it and repeated identical snapshot installs. If the case also converges, the stale-suffix explanation is refuted and the harness or predicate must be revisited.
问题反证：The control branch (follower log at or below the snapshot index) reaches the leader commit index, so ordinary snapshot catch-up works; the violation is specific to a follower whose persisted log extends above the snapshot index.；The predecessor experiment's comparisons were unusable (all unknown) because its two mutually exclusive scenario_setup admissions could not both correlate to one result event; that encoding defect is corrected here and is not evidence about the target.
问题边界：Single-process in-memory InmemTransport, FileSnapshotStore and InmemStore/MockMonotonicLogStore; network/TCP transports and disk-backed stores were not exercised.；Only live catch-up was observed; restart/recovery of a node left holding an above-snapshot suffix, and any consequence for committed entries or safety (as opposed to progress), were not tested.；TrailingLogs=0 forces compaction; with larger TrailingLogs the follower must be correspondingly further behind for the leader to send a snapshot, but the follower-side last-log state that causes the stall is unchanged.

固定实验 `b02f82dfc4024a638ae4ecbdcb18b1fc-experiment` v1：[原始依据](fixed-experiments/b02f82dfc4024a638ae4ecbdcb18b1fc-experiment/basis.json)。
范围：One process, three real Raft instances over InmemTransport with InmemStore and FileSnapshotStore, built with the upstream MakeCluster test helper. The replacement leader compacts its log at or below its snapshot index (TrailingLogs=0) so it can no longer serve the isolated node's match point from the log store.
前史／供给条件：Bootstrap a 3-node cluster; commit a 20-command prefix to all nodes; isolate the current leader; append 200 (case) or 2 (control) uncommitted tail commands on the isolated node; let the remaining two nodes elect a replacement leader; commit 20 more commands and take a snapshot at index S on the replacement leader; commit 10 post entries above S; reconnect and observe for about 4.5s.
假设：Config: ProtocolVersion=3, HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms, CommitTimeout=10ms, TrailingLogs=0, SnapshotThreshold disabled, SnapshotInterval=1h.；The isolated node's uncommitted suffix is produced by real Apply calls on the old leader during its pre-step-down lease window; no state is injected.；The replacement leader commits post-snapshot entries with the third node so leader_commit_index rises above the snapshot index.
范围外：Network and TCP transports; mixed-version rolling upgrades.；Monotonic log stores; the non-monotonic InmemStore path is exercised.；Any restart or recovery of the isolated node; only live catch-up is measured.
书面要求：After a follower installs a snapshot at index S and the follower's durable log ends at index L with S >= L, the follower must report its last log entry as (S, snapshotTerm) so the leader's PrevLogEntry=S consistency check succeeds and later entries commit on the follower. Anchored in state.go:167-174 (getLastEntry) and raft.go:1475-1502 (appendEntries PrevLogEntry check); installSnapshot at raft.go:1814-1953 with the post-restore block at raft.go:1930-1948 is the producer that must establish that condition.
执行 `61befa27ce114c8097c8bdfa597e9ee5`：completed，退出码 0；[回执](logs/61befa27ce114c8097c8bdfa597e9ee5/check.json)、[stdout](logs/61befa27ce114c8097c8bdfa597e9ee5/stdout.log)、[stderr](logs/61befa27ce114c8097c8bdfa597e9ee5/stderr.log)。
机械比较：unknown；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "scenario_setup",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 139,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "control_catchup",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "old_last_after": 55,
    "old_applied_after": 55,
    "old_commit_after": 55,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": false,
    "isolated_caught_up": true,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 140,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "scenario_setup",
    "scenario": "case_no_progress",
    "stale_suffix": true,
    "snapshot_index": 45,
    "old_last_before": 222,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 61628,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "case_no_progress",
    "scenario": "case_no_progress",
    "stale_suffix": true,
    "snapshot_index": 45,
    "old_last_before": 222,
    "old_last_after": 223,
    "old_applied_after": 45,
    "old_commit_after": 23,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": true,
    "isolated_caught_up": false,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 61629,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved
观测缺口：Event 1 {'scenario': 'control_catchup', 'snapshot_index': 45}: No corresponding prerequisite events reached: control_admission/scenario_setup, case_admission/scenario_setup；Event 0 {'scenario': 'control_catchup', 'snapshot_index': 45}: Admitted operation has no complete applicable result observation
观测缺口：Event 3 {'scenario': 'case_no_progress', 'snapshot_index': 45, 'old_last_before': 222}: No corresponding prerequisite events reached: control_admission/scenario_setup, case_admission/scenario_setup；Event 2 {'scenario': 'case_no_progress', 'snapshot_index': 45, 'old_last_before': 222}: Admitted operation has no complete applicable result observation
观测缺口：Event 3 {'scenario': 'case_no_progress', 'old_last_after': 223}: No corresponding prerequisite events reached: control_admission/scenario_setup, case_admission/scenario_setup；Event 2 {'scenario': 'case_no_progress'}: Missing operation admission fields or identity

固定实验 `e3d6dc035d0e4e3d8f25950dd3698fdf-experiment` v2：[原始依据](fixed-experiments/e3d6dc035d0e4e3d8f25950dd3698fdf-experiment/basis.json)。
范围：One process, three real Raft instances over InmemTransport with InmemStore and FileSnapshotStore, built with the upstream MakeCluster test helper. The replacement leader compacts its log at or below its snapshot index (TrailingLogs=0) so it can no longer serve the isolated node's match point from the log store.
前史／供给条件：Bootstrap a 3-node cluster; commit a 20-command prefix to all nodes; isolate the current leader; append 200 (case) or 2 (control) uncommitted tail commands on the isolated node; let the remaining two nodes elect a replacement leader; commit 20 more commands and take a snapshot at index S on the replacement leader; commit 10 post entries above S; reconnect and observe for about 4.5s; in one execution emit a scenario_setup admission event and a snapshot_catchup_result event for each of the two scenarios.
假设：Config: ProtocolVersion=3, HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms, CommitTimeout=10ms, TrailingLogs=0, SnapshotThreshold disabled, SnapshotInterval=1h.；The isolated node's above-snapshot suffix is produced by real Apply calls on the old leader during its pre-step-down lease window; no state is injected.；The replacement leader commits post-snapshot entries with the third node so leader_commit_index rises above the snapshot index.
范围外：Network and TCP transports; mixed-version rolling upgrades.；Monotonic log stores; the non-monotonic InmemStore path is exercised.；Restart or recovery of the isolated node; only live catch-up is measured.
前驱 `b02f82dfc4024a638ae4ecbdcb18b1fc-experiment`；修订原因：Corrected event and comparison encoding: the predecessor's comparisons required two mutually exclusive scenario_setup prerequisites to correlate to each result event, so all comparisons evaluated unknown. The successor emits one shared scenario_setup admission event and one shared snapshot_catchup_result event name per scenario, selects the scenario by a stale_suffix applicability condition, and asserts the required healthy property (isolated_caught_up true, stalled false) so a stalled case is a violating witness. The executed scenarios, prefix, requirement and observations are unchanged.；实际变化：harness, scope, prefix, requirement, comparisons
书面要求：After a follower installs a snapshot at index S, a persisted log suffix above S that the leader does not share must not keep the follower from accepting the leader's AppendEntries with PrevLogEntry=S: the follower must stop reporting a stale above-snapshot last entry and converge to the leader's log. Anchored in state.go:167-174 (getLastEntry returns the cached log index/term whenever it is at or above the snapshot index) and raft.go:1475-1502 (appendEntries rejects on a missing or term-mismatched PrevLogEntry); installSnapshot at raft.go:1814-1953 with the post-restore block at raft.go:1930-1948 is the producer responsible for establishing that state.
执行 `2322bd7884b749f89c3101f04bc82e78`：completed，退出码 0；[回执](logs/2322bd7884b749f89c3101f04bc82e78/check.json)、[stdout](logs/2322bd7884b749f89c3101f04bc82e78/stdout.log)、[stderr](logs/2322bd7884b749f89c3101f04bc82e78/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "scenario_setup",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 141,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "old_last_after": 55,
    "old_applied_after": 55,
    "old_commit_after": 55,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": false,
    "isolated_caught_up": true,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 142,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "scenario_setup",
    "scenario": "case_no_progress",
    "stale_suffix": true,
    "snapshot_index": 45,
    "old_last_before": 222,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 59415,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "case_no_progress",
    "stale_suffix": true,
    "snapshot_index": 45,
    "old_last_before": 222,
    "old_last_after": 223,
    "old_applied_after": 45,
    "old_commit_after": 23,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": true,
    "isolated_caught_up": false,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]",
      "location": {
        "line": 59416,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffix\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved

固定实验 `5af7bfdd43694974b1a9aa24d559df0f-experiment` v3：[原始依据](fixed-experiments/5af7bfdd43694974b1a9aa24d559df0f-experiment/basis.json)。
范围：One process, three real Raft instances over InmemTransport with FileSnapshotStore; each scenario selects InmemStore either directly (non-monotonic) or wrapped in MockMonotonicLogStore (monotonic) via MakeClusterCustom. The replacement leader compacts at or below its snapshot index (TrailingLogs=0).
前史／供给条件：For each of three scenarios: bootstrap a 3-node cluster, commit a 20-command prefix, isolate the current leader, append 2 (control) or 200 (both stall cases) uncommitted tail commands on the isolated node, let the remaining two nodes elect a replacement leader, commit 20 more commands and take a snapshot at index S, commit 10 post entries above S, reconnect, and observe for about 4.5s. The two stall scenarios differ only in the isolated node's log store (non-monotonic vs MockMonotonicLogStore).
假设：Config: ProtocolVersion=3, HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms, CommitTimeout=10ms, TrailingLogs=0, SnapshotThreshold disabled, SnapshotInterval=1h.；The isolated node's above-snapshot suffix is produced by real uncommitted Apply calls on the old leader before it steps down; no state is injected.；MockMonotonicLogStore returns IsMonotonic()==true, so installSnapshot takes the removeOldLogs branch.
范围外：Network and TCP transports; mixed-version rolling upgrades.；Restart or recovery of the isolated node; only live catch-up is measured.；Disk-backed stores (the in-memory stores share the same LogStore contract).
前驱 `e3d6dc035d0e4e3d8f25950dd3698fdf-experiment`；修订原因：Adds a third scenario using MakeClusterCustom with MonotonicLogs=true so installSnapshot takes the removeOldLogs branch, plus a store_monotonic field and a corresponding comparison. The control and the non-monotonic stall scenario are unchanged. This isolates whether the stall is caused by retained above-snapshot log bytes or by the cached last-log index/term.；实际变化：harness, anchors, scope, prefix, requirement, responsibility, comparisons
书面要求：After a follower installs a snapshot at index S, catch-up must not depend on whether the above-S bytes survive: regardless of the LogStore's monotonicity, a follower whose persisted log ended above S must stop reporting a last log entry above S and accept the leader's AppendEntries with PrevLogEntry=S so it converges to the leader's log. Anchored in state.go:167-174 (getLastEntry) and raft.go:1475-1502 (appendEntries PrevLogEntry check); installSnapshot at raft.go:1814-1953 chooses removeOldLogs for a MonotonicLogStore and compactLogs otherwise, and is the producer responsible for the post-install last-log state.
执行 `b7a3841507c14bbba992965686f5ee54`：completed，退出码 1；[回执](logs/b7a3841507c14bbba992965686f5ee54/check.json)、[stdout](logs/b7a3841507c14bbba992965686f5ee54/stdout.log)、[stderr](logs/b7a3841507c14bbba992965686f5ee54/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "scenario_setup",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 157,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "old_last_after": 55,
    "old_applied_after": 55,
    "old_commit_after": 55,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": false,
    "isolated_caught_up": true,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 158,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "scenario_setup",
    "scenario": "case_nonmonotonic_stall",
    "stale_suffix": true,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 223,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 61296,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "case_nonmonotonic_stall",
    "stale_suffix": true,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 223,
    "old_last_after": 223,
    "old_applied_after": 45,
    "old_commit_after": 23,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": true,
    "isolated_caught_up": false,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 61297,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved；Does the post-snapshot catch-up stall also occur with a MonotonicLogStore, where installSnapshot's removeOldLogs deletes the above-snapshot log bytes and only the cached lastLogIndex/lastLogTerm remain to be reported by getLastEntry?；Nonzero exit has no valid independent-failure attribution
观测缺口：No applicable completed result event was reached

固定实验 `58b739baeea14b0a8ff27e6cfab5c1c3-experiment` v4：[原始依据](fixed-experiments/58b739baeea14b0a8ff27e6cfab5c1c3-experiment/basis.json)。
范围：One process, three real Raft instances over InmemTransport with FileSnapshotStore; each scenario selects InmemStore directly (non-monotonic) or wrapped in MockMonotonicLogStore (monotonic) via MakeClusterCustom with LongstopTimeout=60s. The replacement leader compacts at or below its snapshot index (TrailingLogs=0).
前史／供给条件：For each of three scenarios: bootstrap a 3-node cluster, commit a 20-command prefix, isolate the current leader, append 2 (control) or 200 (both stall cases) uncommitted tail commands on the isolated node, let the remaining two nodes elect a replacement leader, commit 20 more commands and take a snapshot at index S, commit 10 post entries above S, reconnect, observe for about 4.5s, and emit the scenario's setup and result events before helper cleanup. The two stall scenarios differ only in the isolated node's log store (non-monotonic vs MockMonotonicLogStore).
假设：Config: ProtocolVersion=3, HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms, CommitTimeout=10ms, TrailingLogs=0, SnapshotThreshold disabled, SnapshotInterval=1h.；The isolated node's above-snapshot suffix is produced by real uncommitted Apply calls on the old leader before it steps down; no state is injected.；MockMonotonicLogStore returns IsMonotonic()==true, so installSnapshot takes the removeOldLogs branch.
范围外：Network and TCP transports; mixed-version rolling upgrades.；Restart or recovery of the isolated node; only live catch-up is measured.；Disk-backed stores.
前驱 `5af7bfdd43694974b1a9aa24d559df0f-experiment`；修订原因：Harness-only change to fix the predecessor's independent cleanup failure: MakeClusterOpts.LongstopTimeout is raised from the helper default 5s to 60s, and each scenario's CA_EVENT pair is now printed inside the scenario function before the deferred cluster.Close. No scenario, app, source, requirement or comparison changed.；实际变化：harness, source_ids, scope, prefix, responsibility, comparisons
书面要求：After a follower installs a snapshot at index S, catch-up must not depend on whether the above-S bytes survive: regardless of the LogStore's monotonicity, a follower whose persisted log ended above S must stop reporting a last log entry above S and accept the leader's AppendEntries with PrevLogEntry=S so it converges to the leader's log. Anchored in state.go:167-174 (getLastEntry) and raft.go:1475-1502 (appendEntries PrevLogEntry check); installSnapshot at raft.go:1814-1953 chooses removeOldLogs for a MonotonicLogStore and compactLogs otherwise, and is the producer responsible for the post-install last-log state.
执行 `ed8023e758ae49bc93676179f4ae489c`：completed，退出码 0；[回执](logs/ed8023e758ae49bc93676179f4ae489c/check.json)、[stdout](logs/ed8023e758ae49bc93676179f4ae489c/stdout.log)、[stderr](logs/ed8023e758ae49bc93676179f4ae489c/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "scenario_setup",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 140,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "control_catchup",
    "stale_suffix": false,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 25,
    "old_last_after": 55,
    "old_applied_after": 55,
    "old_commit_after": 55,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": false,
    "isolated_caught_up": true,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 141,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "scenario_setup",
    "scenario": "case_nonmonotonic_stall",
    "stale_suffix": true,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 223,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 59910,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "case_nonmonotonic_stall",
    "stale_suffix": true,
    "store_monotonic": false,
    "snapshot_index": 45,
    "old_last_before": 223,
    "old_last_after": 223,
    "old_applied_after": 45,
    "old_commit_after": 23,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": true,
    "isolated_caught_up": false,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 59911,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "scenario_setup",
    "scenario": "case_monotonic_stall",
    "stale_suffix": true,
    "store_monotonic": true,
    "snapshot_index": 45,
    "old_last_before": 223,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 119936,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  },
  {
    "event": "snapshot_catchup_result",
    "scenario": "case_monotonic_stall",
    "stale_suffix": true,
    "store_monotonic": true,
    "snapshot_index": 45,
    "old_last_before": 223,
    "old_last_after": 223,
    "old_applied_after": 45,
    "old_commit_after": 23,
    "leader_last_after": 55,
    "leader_commit_index": 55,
    "stalled": true,
    "isolated_caught_up": false,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]",
      "location": {
        "line": 119937,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotStaleSuffixMonotonic\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved

归属解释历史：

- `e3d6dc035d0e4e3d8f25950dd3698fdf-interpretation-0` · 违反判断：追随者安装快照时只压缩快照索引及以下的日志，既不截断索引以上的旧日志、也不更新缓存的最后日志索引/任期；因此当本机日志长于快照索引时，getLastEntry 仍返回旧的 (lastLogIndex,lastLogTerm)，AppendEntries 的 PrevLogEntry 校验被拒绝，leader 逐次下调 nextIndex 直到 ErrLogNotFound 并反复重发同一快照，追随者停在快照索引不再前进（保留执行事件 1 与 3 支持该结论；对照事件显示日志未超出快照索引时可正常追上）。；依据来源 install_snapshot, get_last_entry, append_prev_check, set_previous_log, replicate_to, send_latest_snapshot，执行 61befa27ce114c8097c8bdfa597e9ee5。
  反证：The three comparisons declared in this experiment's basis evaluated as unknown, not violated: each declared prerequisite had to correlate to every result event, but the two scenario_setup admissions carry mutually exclusive scenario values, so match_prerequisites could not build one chain (observations.json comparisons[0..2] reason 'No corresponding prerequisite events reached'). This is a defect in the comparison admission encoding, not in the cited event facts.；The control event (index 1) is consistent with the ordinary snapshot install path working when the follower's log ends at or below the snapshot index, so the stall is not a blanket snapshot failure.
  限制：Single-process in-memory transport and the non-monotonic InmemStore path; network/TCP transports and MonotonicLogStore were not exercised.；Only live catch-up was observed; restart/recovery of the stalled node and any committed-entry or safety consequence were not tested.；The declared requirement text conditioned on S >= L (log at or below the snapshot index), which describes the control; the violation is observed in the opposite branch (L > S), where the follower keeps a stale suffix.；The submitted successor experiment corrects the admission/comparison encoding and needs its own receipt before it can carry an interpretation.
- `582acedf6e86477a92ab474a241721b7-interpretation-0` · 违反判断：在保留的 3 节点内存执行中（CheckRun 2322bd7884b749f89c3101f04bc82e78）：对照场景（本机日志末索引 25 低于快照索引 45）比较成立，追随者 applied=55 达到 leader commit=55；缺陷场景（本机日志末索引 222 高于快照索引 45）两条比较被判 violated，witness 为事件 3，追随者 applied 冻结在 45、leader commit=55、stalled=true。原因链：installSnapshot 只清理快照索引及以下的日志、不截断以上后缀也不更新 setLastLog，getLastEntry 继续返回旧的 (lastLogIndex,lastLogTerm)，AppendEntries 的 PrevLogEntry 校验被拒，leader 逐次下调 nextIndex 直至 ErrLogNotFound 并重发同一快照。范围限于单进程内存、非单调存储；未测试重启恢复与安全性，不主张已提交日志丢失。；依据来源 install_snapshot, get_last_entry, append_prev_check, set_previous_log, replicate_to, send_latest_snapshot，执行 2322bd7884b749f89c3101f04bc82e78。
  反证：The control comparison holds in the same execution, so the stall is not a general failure of snapshot installation.；The stalled follower reports old_last_after=223 (unchanged stale suffix) while old_commit_after=23, i.e. its local log/commit view remains inconsistent with the restored FSM at index 45; this is consistent with the defect but also means the exact number of re-sent snapshots is timing dependent and was not counted in this run.
  限制：Only progress/liveness is established. The retained events do not show a committed entry lost or overwritten, so no safety violation is claimed.；Transport, store and restart coverage is limited to the in-memory, non-monotonic single-process configuration described in the experiment scope.；The successor fixes the predecessor's comparison encoding; the predecessor's raw event indices 1 and 3 remain valid observations and its interpretation is preserved.
- `1b24d155db77414b9490619c49f7a51f-interpretation-0` · 未解决：CheckRun b7a3841507c14bbba992965686f5ee54 has status completed but exit_code 1 (outcome tests_failed), so it cannot support the monotonic conclusion. What did complete, before the failure, are two parsed events on the same operation stream: event 1 (control_catchup) with stale_suffix=false, old_last_after=55, applied 55 = leader commit 55 (comparison 0 outcome holds), and event 3 (case_nonmonotonic_stall) with snapshot_index=45 < old_last_before=223, applied frozen at 45 while leader commit 55, stalled=true, isolated_caught_up=false (comparison 1 outcome violated, valid witness index 3). That re-confirms the already-established non-monotonic defect and is retained here only as partial output. The monotonic scenario ran (its [CA] log line reports snapshot_index=45, oldLastBefore=222, leaderCommit=55) but emitted no CA_EVENT before the test panicked in the harness helper cluster.Close() after its shutdown-timeout timer fired (testing.go:307), i.e. a harness cleanup timeout, not a target assertion. No monotonic endpoint was measured, so the discriminator between retained above-snapshot bytes and the cached last-log state is not decided by this run.；依据来源 install_snapshot, get_last_entry, append_prev_check, replicate_to，执行 b7a3841507c14bbba992965686f5ee54。
  反证：Native local runs of the same harness (before submission, not a formal receipt) showed the monotonic scenario stalling identically (old_last_after=223, applied=45, stalled=true). This is why the question is worth resuming, but it is not retained execution evidence and is not used as a conclusion.；The panic occurred in the test helper's cluster.Close(), so it also does not indicate any target behavior failure.
  限制：Concrete resume condition: emit the monotonic scenario's result event (or explicitly Shutdown and await each Raft before cluster.Close) so the measurement precedes cleanup, then re-run this exact harness as a fresh successor; a completed receipt with the monotonic comparison then decides the gap.；Until that receipt exists, the monotonic branch is unestablished and the recorded defect conclusion rests only on the non-monotonic receipt 2322bd7884b749f89c3101f04bc82e78.
- `b8ec90938f1346649533b743268e42fc-interpretation-0` · 违反判断：在保留执行 CheckRun ed8023e758ae49bc93676179f4ae489c（completed，exit 0）中：对照场景比较成立（applied 55 = leader commit 55）；非单调存储对比 violated，witness 为事件 3（applied 冻结 45，leader commit 55，stalled=true）；单调存储（removeOldLogs 已删除快照索引以上的日志字节）对比同样 violated，witness 为事件 5（snapshot_index 45、old_last_before 223、old_last_after 223、applied 45、stalled=true）。因此问题不取决于日志字节是否保留，而在于 installSnapshot 未重置缓存的 lastLogIndex/lastLogTerm（未调用 setLastLog），getLastEntry 继续返回快照索引以上的旧项，AppendEntries 的 PrevLogEntry 校验被拒，leader 逐次下调 nextIndex 直至 ErrLogNotFound 并反复重发同一快照。范围限于单进程内存、3 节点；未测试重启恢复，也不主张已提交日志丢失。；依据来源 install_snapshot, get_last_entry, append_prev_check, replicate_to，执行 ed8023e758ae49bc93676179f4ae489c。
  反证：The monotonic branch confirms rather than refutes the explanation: deleting the above-snapshot bytes (removeOldLogs) did not restore catch-up, which rules out retained bytes as the necessary cause.；The control comparison still holds, so ordinary snapshot catch-up is unaffected.；The predecessor run's nonzero exit was an upstream helper shutdown timeout (testing.go:307) and is preserved as counterevidence for that failed attempt; it carried no target-behavior claim.
  限制：Only progress/liveness is established; no committed entry was observed to be lost or overwritten, so no safety violation is claimed.；Coverage is limited to the in-memory, single-process, 3-node configuration described in the experiment scope; network transports, disk-backed stores and restarts were not exercised.
  缺口答复：1b24d155db77414b9490619c49f7a51f-gap-0: Yes. CheckRun ed8023e758ae49bc93676179f4ae489c (completed, exit_code 0, no parsing errors, prerequisites matched) shows the monotonic store stalling exactly like the non-monotonic one. Comparison 2 (applicability stale_suffix=true, store_monotonic=true, assertion stalled==false) is violated with valid witness index 5: scenario case_monotonic_stall reports snapshot_index=45 < old_last_before=223, old_last_after=223, old_applied_after=45 while leader_commit_index=55, stalled=true, isolated_caught_up=false. Because MockMonotonicLogStore makes installSnapshot take the removeOldLogs branch, the above-snapshot bytes are already deleted, so what survives is the cached lastLogIndex/lastLogTerm, which is not reset (no setLastLog call) and is still reported by getLastEntry (state.go:167-174). The stall is therefore caused by the cached last-log state, not by retained log bytes.

## 共享理解与修订

- `b02f82dfc4024a638ae4ecbdcb18b1fc-knowledge-0` r1 · behavior：(*Raft).installSnapshot restores the received snapshot into the FSM, sets lastApplied=req.LastLogIndex, sets lastSnapshot=(req.LastLogIndex,req.LastLogTerm), overwrites the latest and committed configuration, then removes or compacts only logs at or below req.LastLogIndex (removeOldLogs for a MonotonicLogStore, otherwise compactLogs). It never calls setLastLog and never truncates log entries above req.LastLogIndex, so the cached lastLogIndex/lastLogTerm retain any pre-existing suffix.；条件：A follower handles an InstallSnapshotRequest and its persisted log already contains entries at indices greater than req.LastLogIndex, for example an uncommitted suffix written by an earlier leader term.。
- `b02f82dfc4024a638ae4ecbdcb18b1fc-knowledge-1` r1 · behavior：(*raftState).getLastEntry returns (lastLogIndex,lastLogTerm) whenever lastLogIndex >= lastSnapshotIndex, and returns (lastSnapshotIndex,lastSnapshotTerm) only when the cached log index is below the snapshot index. After a snapshot install that leaves a longer persisted log, the follower therefore reports the stale tail index and term rather than the snapshot index and term.；条件：lastLogIndex > lastSnapshotIndex on the local raftState, which holds after installSnapshot when the log was not truncated above the snapshot index.。
- `b02f82dfc4024a638ae4ecbdcb18b1fc-knowledge-2` r1 · behavior：(*Raft).appendEntries verifies a.PrevLogEntry by comparing it to getLastEntry; if they differ it reads logs.GetLog(a.PrevLogEntry). A missing entry or a differing term sets resp.NoRetryBackoff=true and rejects the request without truncating the local log.；条件：A follower receives an AppendEntriesRequest with a.PrevLogEntry > 0.。
- `b02f82dfc4024a638ae4ecbdcb18b1fc-knowledge-3` r1 · behavior：(*Raft).replicateTo advances s.nextIndex to max(min(s.nextIndex-1, resp.LastLog+1), 1) on a rejected AppendEntries, so a follower that reports a higher LastLog than the leader's nextIndex causes nextIndex to decrease by one; when setupAppendEntries returns ErrLogNotFound it goes to SEND_SNAP and sendLatestSnapshot re-sends the newest snapshot and sets nextIndex=meta.Index+1 on success.；条件：The follower keeps rejecting AppendEntries and its reported LastLog stays above the leader's nextIndex.。
- `e3d6dc035d0e4e3d8f25950dd3698fdf-knowledge-0` r1 · fact：In the retained 3-node in-memory execution, when the isolated node reconnected with its persisted log ending above the replacement leader's snapshot index (case: old_last_before=222 vs snapshot_index=45), the node's applied index stayed at the snapshot index 45 across the observation window while the leader's commit index was 55 (stalled=true, isolated_caught_up=false); in the same execution the control with the node's log ending below the snapshot index (old_last_before=25) reached applied index 55 and caught up (stalled=false, isolated_caught_up=true).；条件：Single process, three real Raft instances over InmemTransport with InmemStore and FileSnapshotStore, ProtocolVersion=3, HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms, TrailingLogs=0, replacement leader compacted at or below its snapshot index; the isolated node's above-snapshot suffix was produced by real uncommitted Apply calls on the old leader before it stepped down.。
- `aec582f7b2ee436a9a667699fffce95a-knowledge-0` r1 · fact：In the retained 3-node in-memory execution (CheckRun ed8023e758ae49bc93676179f4ae489c), the post-snapshot catch-up stall occurred for both log-store monotonicity branches: with a non-monotonic InmemStore the isolated follower stayed at applied index 45 while the leader commit index was 55 (event 3, stalled=true, isolated_caught_up=false), and with MockMonotonicLogStore, whose removeOldLogs deletes the above-snapshot log bytes during installSnapshot, it still stayed at applied index 45 with old_last_after=223 (event 5, stalled=true, isolated_caught_up=false). The control whose log ended at or below the snapshot index reached applied index 55 (event 1, isolated_caught_up=true).；条件：Single process, three real Raft instances over InmemTransport with FileSnapshotStore; ProtocolVersion=3; HeartbeatTimeout=ElectionTimeout=LeaderLeaseTimeout=300ms; TrailingLogs=0; the isolated node's above-snapshot suffix was produced by real uncommitted Apply calls on the old leader before it stepped down; only live catch-up was measured.。

## 执行成本与原始记录

Agent 调用 14 次；控制器目标执行 4 次。
目标进程累计秒数：122.783782；含准备的动作秒数：141.63263991900067；两者不相加。
请求模型：`deepseek-flash` / `high`；服务端模型版本仅以回执为准。
[完整状态与历史](state.json)、[当前工作索引](research.json)、[实际配置](config.json)、[事件](events.jsonl)。
源码身份、工具成功及模型解释各有边界；脚本化产品仅验证框架，不作为自主发现证据。
