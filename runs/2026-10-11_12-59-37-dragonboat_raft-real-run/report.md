# 共识审计研究报告

方法 `audit-products-v62`；模式 `real/autonomous`；持续 11.66 分钟。
停止原因：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via https://platform.openai.com/settings/organization/status-and-access before retrying.
This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via https://platform.openai.com/settings/organization/status-and-access before retrying.

## 问题与证据

### When one follower read is still pending and a later read from another follower obtains a quorum confirmation, does the leader return each original request context to the correct origin?

当前处置：调查中。
问题 `1c2b73044acc4708a34462dbff273d3d-question-0` v1；来源：read_api, bootstrap, bootstrap_entries, read_admission, read_batch, read_reply, read_follower, read_heartbeat, read_consumer, read_client_completion, read_node_producer, read_node_consumer, read_expected_context（[完整引用](state.json)）。
假设：readIndex.confirm returns and removes a prefix of readStatus objects, preserving each original ctx and from. handleReadIndexLeaderConfirmation uses s.from and s.index but m.Hint/m.HintHigh on remote replies, apparently replacing earlier contexts with the latest confirmation context. The follower exposes that context in ReadyToRead, and pendingReadIndex.addReady only recognizes its own batches by exact SystemCtx.
下一判别条件：Launch three real Peers from empty TestLogDB stores and bootstrap addresses; elect normally with logical ticks and commit the current-term no-op. Submit one unique context from each follower. Compare normal first-round delivery with loss of only the first request heartbeat round, followed by reliable delivery for the second request and twelve heartbeat rounds. Identify each operation by scenario and origin, never returned context. Inspect producer messages, pending statuses, consumer ReadyToReads and missing outcomes. A preserved original context or an enclosing rule preventing overlapping remote requests would refute the suspicion.
问题反证：The local-leader completion branch uses s.ctx correctly.；The first read cannot be served before a current-term entry commits in a multi-voter cluster.；Nonzero-context heartbeat broadcasts target voting members, not observers.；Existing TestReadOnlyOptionSafe checks returned context equality for serial reads; it does not establish overlapping-request behavior.
问题边界：No retained execution has been reviewed yet.；The proposed endpoint is the Peer ReadyToRead interface. Client RequestState timeout, FSM read contents and any linearizability consequence are not measured.

固定实验 `1c2b73044acc4708a34462dbff273d3d-experiment` v1：[原始依据](fixed-experiments/1c2b73044acc4708a34462dbff273d3d-experiment/basis.json)。
范围：Three normal bootstrapped voting Peers in one synchronously owned memory transport. Compare the same two follower ReadIndex inputs under two delivery schedules. The only fault is losing the two initial context-bearing heartbeat messages in the treatment; later communication is reliable.
前史／供给条件：For each independent scenario, Launch all three peers with empty TestLogDB and the same three bootstrap addresses. Save each update; apply actual committed configurations and notify applied indices. Tick node 1 until its election and current-term no-op are committed, routing every real message. Submit context (1001,31) at follower 2; either deliver its complete round or discard only generated Heartbeat messages. Submit context (2002,32) at follower 3 and deliver all traffic. Then tick and deliver twelve normal rounds. The test never injects term, leader, commit, pending-read, membership or reply state. Every returned ReadyToRead is emitted with origin identity regardless of context; endpoint counts retain missing or duplicate results.
假设：No crashes, membership changes or persistence failures. The existing TestLogDB models successful storage; updates are appended and state saved before messages are delivered.；The harness applies actual committed bootstrap configuration entries and acknowledges committed indices through Peer.NotifyRaftLastApplied. There is no application command/FSM read in this local interface probe.；Each follower submits exactly one distinct, nonzero opaque SystemCtx via the real Peer.ReadIndex producer. Contexts are supplied instead of executing the node-level random generator; Peer.ReadIndex and the existing context-equality test independently establish that this argument must be preserved.；Logical time is controlled. Node 1 alone ticks until election; after requests, all three nodes receive twelve ticks with each message queue fully drained.
范围外：Public NodeHost futures and timeout completion；FSM-value linearizability；Crash recovery and disk durability；Any universal progress guarantee inferred from twelve ticks
书面要求：A ReadIndex result returned at the originating Peer must preserve both fields of the SystemCtx supplied for that read. Batched confirmation may raise the read index, but cannot substitute a different operation context.
执行 `43bee6f879b143c9a47818c3473eb286`：completed，退出码 0；[回执](logs/43bee6f879b143c9a47818c3473eb286/check.json)、[stdout](logs/43bee6f879b143c9a47818c3473eb286/stdout.log)、[stderr](logs/43bee6f879b143c9a47818c3473eb286/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "applied": 4,
    "committed": 4,
    "event": "prefix",
    "leader": 1,
    "node": 1,
    "scenario": "deliver_first_round",
    "term": 2,
    "voters": 3,
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 42,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "applied": 4,
    "committed": 4,
    "event": "prefix",
    "leader": 1,
    "node": 2,
    "scenario": "deliver_first_round",
    "term": 2,
    "voters": 3,
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "applied": 4,
    "committed": 4,
    "event": "prefix",
    "leader": 1,
    "node": 3,
    "scenario": "deliver_first_round",
    "term": 2,
    "voters": 3,
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "event": "admitted",
    "input_high": 31,
    "input_low": 1001,
    "leader": 1,
    "origin": 2,
    "scenario": "deliver_first_round",
    "term": 2,
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 45,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "commit": 0,
    "event": "produced",
    "from": 2,
    "high": 31,
    "index": 0,
    "low": 1001,
    "scenario": "deliver_first_round",
    "term": 0,
    "to": 1,
    "type": "ReadIndex",
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "commit": 4,
    "event": "produced",
    "from": 1,
    "high": 31,
    "index": 0,
    "low": 1001,
    "scenario": "deliver_first_round",
    "term": 2,
    "to": 2,
    "type": "Heartbeat",
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 47,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "commit": 4,
    "event": "produced",
    "from": 1,
    "high": 31,
    "index": 0,
    "low": 1001,
    "scenario": "deliver_first_round",
    "term": 2,
    "to": 3,
    "type": "Heartbeat",
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 48,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  },
  {
    "commit": 0,
    "event": "produced",
    "from": 2,
    "high": 31,
    "index": 0,
    "low": 1001,
    "scenario": "deliver_first_round",
    "term": 2,
    "to": 1,
    "type": "HeartbeatResp",
    "_ca_stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
    "_ca_observation": {
      "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]",
      "location": {
        "line": 49,
        "stream": "[\"github.com/lni/dragonboat/v3/internal/raft\",\"TestAssuranceReadIndexContext/deliver_first_round\"]"
      }
    }
  }
]
```
待解决：Execution has no attributed interpretation

## 共享理解与修订


## 执行成本与原始记录

Agent 调用 2 次；控制器目标执行 1 次。
目标进程累计秒数：15.035343；含准备的动作秒数：16.328860050999992；两者不相加。
请求模型：`gpt-6-astra` / `low`；服务端模型版本仅以回执为准。
[完整状态与历史](state.json)、[当前工作索引](research.json)、[实际配置](config.json)、[事件](events.jsonl)。
源码身份、工具成功及模型解释各有边界；脚本化产品仅验证框架，不作为自主发现证据。
