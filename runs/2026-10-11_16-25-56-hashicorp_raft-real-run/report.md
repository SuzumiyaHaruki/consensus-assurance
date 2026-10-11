# 共识审计研究报告

方法 `audit-products-v63`；模式 `real/autonomous`；持续 60.01 分钟。
停止原因：Agent stopped: Action timeout exceeded; process group killed

## 问题与证据

### Leadership transfer 的接收端权威校验缺失

当前处置：局部问题已回答。
问题 `ce1a7dcb68b449448fdee06b3eb7737e-question-0` v2；来源：s_timeoutnow_handler, s_timeoutnow_msg, s_prevote_gate, s_vote_known_leader, s_sender_precondition（[完整引用](state.json)）。
原命题：In the captured snapshot, is a leadership-transfer order (TimeoutNow) bound at the receiver to the current leader's authority, or can a delivered order that carries no term and whose claimed sender is not the current leader (and not a configuration member) drive a stable follower out of Follower and depose the serving leader?
假设：Raft.timeoutNow is the only RPC handler that changes authority without consulting any term: it does setLeader("",""), setState(Candidate) and candidateFromLeadershipTransfer.Store(true) and responds, ignoring RPCHeader.ID/Addr and the configuration. TimeoutNowRequest embeds only RPCHeader, so no term/freshness value exists to check, while the producer only sends it after it has caught the target up (nextIndex beyond the leader's last index) - a precondition the receiver cannot verify. The Candidate run skips pre-vote (raft.go:294-298) and voters skip the known-leader rejection for LeadershipTransfer candidates (raft.go:1645-1656), so the order withdraws both disruption guards at once.
下一判别条件：In one fault-free, normally bootstrapped 3-node in-memory cluster with a stable leader at a known term, deliver a single TimeoutNow to a follower using a transport RPC header whose ID is not a configuration member (and which necessarily carries no term), then observe the target's state/term and the previous leader's state/term for a bounded interval. Control: the same non-member sender with a RequestVoteRequest that does carry a term, but an older one, must leave the target unchanged. If the TimeoutNow leaves the target in Follower at the same term and the leader in place, the hypothesis is refuted; if the target leaves Follower at a higher term while the leader steps down, the receiver-side authority gap is observed.
问题边界：The witness is one execution of one fault-free in-process cluster; it establishes the receiver-side transition, not how long clients stayed without a leader afterwards.；Safety was not violated in this execution and is not claimed to be: term/vote rules still select the leader. The defect is the acceptance of a leadership-transfer order that is bound neither to the sender's identity/term nor to its configuration membership.；Because the order carries no term, a replayed or delayed order from a legitimate former leader is indistinguishable from the witness message at the receiver; the witness does not separate those two producers.

固定实验 `ce1a7dcb68b449448fdee06b3eb7737e-experiment` v1：[原始依据](fixed-experiments/ce1a7dcb68b449448fdee06b3eb7737e-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster; one control RPC (stale-term RequestVote from a non-member claimed sender) followed by one TimeoutNow from the same claimed sender to a follower, with bounded observation of target and leader state/term.
前史／供给条件：The harness builds the prefix itself with the captured test facilities: MakeCluster(3, t, nil) bootstraps a three-voter configuration through the in-memory transport, waits for a stable leader (c.Leader()), and records the leader id/address/term and the chosen follower's state/term as CA_EVENT steady_state. It then selects the follower's transport peer as sender and emits CA_EVENT control_stale_request_vote after delivering a RequestVoteRequest with Term = targetTerm-1 and RPCHeader.ID = 'ghost-not-in-config'. Only then does it deliver the single TimeoutNowRequest with the same RPC header (no term field exists) and emit CA_EVENT after_timeout_now after a bounded 2s observation of the target and the previous leader. No state is injected and no storage is pre-filled.
假设：MakeCluster(3) performs real bootstrap: initial configuration entry, leader election and log replication through the in-memory transport.；Both RPCs are delivered over the in-memory transport with no packet loss, reordering or delay, so any observed transition is caused by the delivered request itself.；The sender identity in the RPC header ('ghost-not-in-config') is deliberately not a configuration member; the probe does not rely on the sender being reachable or registered.；The cluster is healthy before the probe: a leader is serving at a known term, which the harness records as steady_state.
范围外：Network-transport authentication, TLS and peer-identity properties outside the Raft layer.；State-machine safety (log matching, single vote per term) and any claim that the newly elected leader violates it.；Behaviour after the observation interval, further elections, and client-visible unavailability.
书面要求：A delivered leadership-transfer order is processed as authority to depose the known leader even though the message carries no term and its claimed sender is not the serving leader or a configuration member; the receiver performs no term, identity or membership check before clearing the leader and starting an election.
执行 `8248101f2e7e47ecae3104f94cd0357b`：completed，退出码 0；[回执](logs/8248101f2e7e47ecae3104f94cd0357b/check.json)、[stdout](logs/8248101f2e7e47ecae3104f94cd0357b/stdout.log)、[stderr](logs/8248101f2e7e47ecae3104f94cd0357b/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `5a436a477b8e4920bbcd4123e81f07fa-interpretation-0`：有限范围未见违反；已确认的缺陷：TimeoutNow 请求只带 RPCHeader、没有任何 term，接收端 timeoutNow 也不检查发送方身份、term 或是否属于当前配置，就直接清除已知 leader、进入 Candidate，并置位 candidateFromLeadershipTransfer。该标志同时关闭两道扰动防护：候选者跳过 pre-vote，投票者跳过“已有 leader 时拒绝投票”。固定输入执行（receipt 8248101f2e7e47ecae3104f94cd0357b，exit 0）中，健康三节点集群里一次来自“非配置成员”声称发送方的 TimeoutNow 使 Follower(term 2) 变为 Leader(term 3)，并迫使原 leader 下台（Follower, term 3）；同一发送方携带旧 term 的 RequestVote 对照未产生任何状态变化。属权威接纳缺陷，不主张状态机安全性被破坏。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "claimed_sender_id": "ghost-not-in-config",
    "cluster_size": 3,
    "event": "steady_state",
    "leader_addr": "server-a6e1bccd-5b6d-e70d-19dd-541899a9209f",
    "leader_id": "a6e1bccd-5b6d-e70d-19dd-541899a9209f",
    "leader_state": "Leader",
    "leader_term": 2,
    "target_id": "server-0967aefd-b333-78d5-19ad-b0f17187c583",
    "target_protocol": 3,
    "target_state": "Follower",
    "target_term": 2,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]"
      }
    }
  },
  {
    "claimed_sender_id": "ghost-not-in-config",
    "event": "control_vote_sent",
    "request_term": 1,
    "target_id": "server-0967aefd-b333-78d5-19ad-b0f17187c583",
    "target_state": "Follower",
    "target_term": 2,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]"
      }
    }
  },
  {
    "claimed_sender_id": "ghost-not-in-config",
    "event": "control_stale_request_vote",
    "granted": false,
    "request_term": 1,
    "rpc_error": "",
    "target_moved": false,
    "target_state_after": "Follower",
    "target_term_after": 2,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]"
      }
    }
  },
  {
    "claimed_sender_id": "ghost-not-in-config",
    "event": "authority_probe_sent",
    "leader_id": "a6e1bccd-5b6d-e70d-19dd-541899a9209f",
    "leader_state": "Leader",
    "leader_term": 2,
    "target_id": "server-0967aefd-b333-78d5-19ad-b0f17187c583",
    "target_state": "Follower",
    "target_term": 2,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
      "location": {
        "line": 47,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]"
      }
    }
  },
  {
    "claimed_sender_id": "ghost-not-in-config",
    "event": "after_timeout_now",
    "leader_deposed": true,
    "leader_id": "a6e1bccd-5b6d-e70d-19dd-541899a9209f",
    "leader_state_after": "Follower",
    "leader_state_before": "Leader",
    "leader_term_after": 3,
    "leader_term_before": 2,
    "observation_interval_s": 2,
    "rpc_error": "",
    "target_id": "server-0967aefd-b333-78d5-19ad-b0f17187c583",
    "target_moved": true,
    "target_state_after": "Leader",
    "target_state_before": "Follower",
    "target_term_after": 3,
    "target_term_before": 2,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]",
      "location": {
        "line": 66,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceTimeoutNowNonLeaderAuthority\"]"
      }
    }
  }
]
```

归属解释历史：

- `5a436a477b8e4920bbcd4123e81f07fa-interpretation-0` · 有限范围未见违反：已确认的缺陷：TimeoutNow 请求只带 RPCHeader、没有任何 term，接收端 timeoutNow 也不检查发送方身份、term 或是否属于当前配置，就直接清除已知 leader、进入 Candidate，并置位 candidateFromLeadershipTransfer。该标志同时关闭两道扰动防护：候选者跳过 pre-vote，投票者跳过“已有 leader 时拒绝投票”。固定输入执行（receipt 8248101f2e7e47ecae3104f94cd0357b，exit 0）中，健康三节点集群里一次来自“非配置成员”声称发送方的 TimeoutNow 使 Follower(term 2) 变为 Leader(term 3)，并迫使原 leader 下台（Follower, term 3）；同一发送方携带旧 term 的 RequestVote 对照未产生任何状态变化。属权威接纳缺陷，不主张状态机安全性被破坏。；依据来源 s_timeoutnow_handler, s_timeoutnow_msg, s_prevote_gate, s_vote_known_leader, s_sender_precondition，执行 8248101f2e7e47ecae3104f94cd0357b。
  反证：The control shows the term checks used by the vote path do work: the same claimed sender with an older term was refused and changed nothing, so the observed transition is attributable to the TimeoutNow admission path and not to a generally permissive RPC layer.；No safety violation appeared: the target was elected through the normal term/vote exchange, and the previous leader stepped down on the higher term.
  限制：One execution, one fault-free 3-node in-process cluster, in-memory transport; no network-transport authentication, clock or partition conditions are covered.；The deposed leader's client-visible unavailability after the transition is not measured.；The witness does not distinguish a non-member claimed sender from a replayed or delayed order of a legitimate former leader, because the message carries no term to separate them.
  缺口答复：ce1a7dcb68b449448fdee06b3eb7737e-gap-0: Yes, within the executed conditions. In receipt 8248101f2e7e47ecae3104f94cd0357b (exit 0) event index 4 after_timeout_now reports target_moved true with target_state_after Leader / target_term_after 3 (from Follower term 2) and leader_deposed true with the previous leader in state Follower at term 3, after the index 3 authority_probe_sent admission whose claimed sender is not a configuration member; the control event index 2 from the same claimed sender, which does carry an older term, reports granted false and target_moved false. One received TimeoutNow therefore moved a stable follower out of Follower at a higher term and deposed the serving leader, while the stale-term RequestVote left the target unchanged.
### 配置条目在 25 轮复现中即时可见，未观察到发布配置滞后于自身日志

当前处置：局部问题已回答。
问题 `ce1a7dcb68b449448fdee06b3eb7737e-question-1` v5；来源：s_get_configuration, s_ensure_same_peers（[完整引用](state.json)）。
原命题：Can a server in the captured snapshot hold a configurations.latest (and hence GetConfiguration) that is older than its own committed log, and how is that state produced?
假设：Re-scoped after reading the FSM apply path: configuration entries never reach FSM.Apply (fsm.go:105-118), so the captured helper's FSM comparison cannot show that a peer holds a configuration entry. The remaining question is whether the >5s 'peer mismatch' seen locally in TestRaft_ProtocolVersion_Upgrade_2_3 came from a peer not having appended the configuration entry within the EnsureSamePeers window (replication lag), or from a server whose configurations.latest/atomic latestConfiguration was reset behind an entry it already holds.
下一判别条件：Replay the captured upgrade scenario with per-node instrumentation that records, each 100ms, whether the configuration entry is present in each log store, each node's latestIndex/latestConfiguration, and the leader's per-peer replication nextIndex/lastContact. Lag shows as the entry absent from that peer's log store (with the leader committing via another peer); an internal reset shows as the entry present while latestIndex/latestConfiguration stay below it. A decisive witness needs the entry present and latest still behind after the leader's replication has advanced past it.
问题边界：Answered for the reproduced scenario: with a valid predicate (published configuration content plus log store contents, never the index accessor that returns a constant zero), every node reached the new membership and no node showed the old membership while its log held the configuration entry.；Twenty-five rounds of the captured upgrade scenario converged with a per-round maximum wait of 0-6ms and any_lag_with_entry false in all rounds; all 75 per-node results reported the joiner visible and the entry present in the log store.；Not explained and not attributed: the earlier local observation that the captured TestRaft_ProtocolVersion_Upgrade_2_3 failed with a peer mismatch in about two of three isolated runs. Under instrumentation the same scenario converges in milliseconds, so the cause remains unknown and no claim is made about it.；An asymmetry was observed but is expected: in one round a node published the three-server membership while its committed configuration index was still behind, because appending a configuration entry updates the published latest configuration while the committed configuration advances only when the leader's commit index reaches it.；The probe uses the in-memory transport and one cluster shape (protocol-2 pair plus protocol-3 joiner); other shapes were not exercised.

固定实验 `446bc215583d49f8aa9b6cbfabbef334-experiment` v1：[原始依据](fixed-experiments/446bc215583d49f8aa9b6cbfabbef334-experiment/basis.json)。
范围：Twenty-five repetitions of the captured upgrade scenario (protocol-2 pair plus a protocol-3 joiner) on in-memory clusters, each round following one AddVoter of the joiner and polling every 5ms for up to 3s for the published configuration content to include the joiner, then recording per node whether the entry is in its log store while its published content is still old.
前史／供给条件：Built with captured test facilities and real producers only: per round a protocol-2 pair is bootstrapped, a protocol-3 single node is created without bootstrap, merged and fully connected, and the leader adds that node through AddVoter, whose future index identifies the configuration entry. The harness emits one config_round_probe_start per round with the iteration, entry index and cluster size, then one config_round_start per node with the starting published content and log store last index. It polls the atomically published content of every node every 5ms for up to 3s, records when each node first shows the joiner, and finally emits per-node config_node_result events carrying whether the entry is present in that node's log store together with its published content, log store last index, applied index and commit index, plus one config_round_end carrying all_converged, any_lag_with_entry, the maximum wait and the window. No storage is pre-filled and no production code is modified.
假设：MakeCluster(2, protocol 2) plus a merged MakeClusterNoBootstrap(1, protocol 3) and AddVoter of the joiner reproduce the captured scenario, with the future's index identifying the configuration entry.；The atomically published configuration content is what GetConfiguration returns and what the captured cluster assertion compares; the configuration index accessor is excluded because it returns a constant zero.；Five-millisecond polling with a 3s window is dense enough to distinguish prompt propagation from a multi-second stall.；Every round is a fresh cluster, so rounds do not share state.
范围外：The configuration index accessor, which is covered by a separate finding.；Network transport behaviour, crashes and restarts.；Any claim about the captured test's earlier local failures, which this probe does not reproduce.
书面要求：探索尚未固定要求，不产生正式确认。
执行 `38d727906cc1458b9dfdcd9e337fc5a2`：completed，退出码 0；[回执](logs/38d727906cc1458b9dfdcd9e337fc5a2/check.json)、[stdout](logs/38d727906cc1458b9dfdcd9e337fc5a2/stdout.log)、[stderr](logs/38d727906cc1458b9dfdcd9e337fc5a2/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `3e1c60d4f59d4003a5efce001e1e4374-interpretation-0`：有限范围未见违反；本场景下保护成立（固定输入执行 receipt 38d727906cc1458b9dfdcd9e337fc5a2，exit 0，两条比较在全部 25 轮成立）：25 轮协议 2 双节点 + 协议 3 加入者的升级场景中，发布配置内容在各节点于 0-6ms（中位数 0ms）内包含新成员，且没有任何节点在自身日志已含配置条目的情况下仍发布旧成员（any_lag_with_entry 全为 false，75/75 节点结果收敛）。此前该问题探针使用恒为 0 的配置索引访问器作为判据，其读数无效，已被本次测量取代。仍未解释且不作归因：先前本地捕获测试 TestRaft_ProtocolVersion_Upgrade_2_3 在约 2/3 次隔离运行中出现 peer mismatch，插桩后同一场景毫秒级收敛，本执行未复现该现象。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "cluster_size": 3,
    "entry_index": 3,
    "event": "config_round_probe_start",
    "iteration": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "content_servers_start": 3,
    "entry_index": 3,
    "event": "config_round_start",
    "iteration": 0,
    "log_store_last_start": 3,
    "node": "dc4223e7-57ac-a8e6-1259-1f47b15dd5cb",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 45,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "content_servers_start": 2,
    "entry_index": 3,
    "event": "config_round_start",
    "iteration": 0,
    "log_store_last_start": 2,
    "node": "b48c0d87-e243-0f5f-20f0-a8c43a117338",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "content_servers_start": 3,
    "entry_index": 3,
    "event": "config_round_start",
    "iteration": 0,
    "log_store_last_start": 3,
    "node": "server-baa59969-7263-b408-0bed-60cb2269756a",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 47,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "applied_index": 3,
    "commit_index": 3,
    "content_servers": 3,
    "converged": true,
    "entry_present_in_log": true,
    "event": "config_node_result",
    "iteration": 0,
    "log_store_last": 3,
    "node": "dc4223e7-57ac-a8e6-1259-1f47b15dd5cb",
    "wait_ms": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 48,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "applied_index": 3,
    "commit_index": 3,
    "content_servers": 3,
    "converged": true,
    "entry_present_in_log": true,
    "event": "config_node_result",
    "iteration": 0,
    "log_store_last": 3,
    "node": "b48c0d87-e243-0f5f-20f0-a8c43a117338",
    "wait_ms": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 49,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "applied_index": 2,
    "commit_index": 2,
    "content_servers": 3,
    "converged": true,
    "entry_present_in_log": true,
    "event": "config_node_result",
    "iteration": 0,
    "log_store_last": 3,
    "node": "server-baa59969-7263-b408-0bed-60cb2269756a",
    "wait_ms": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 50,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  },
  {
    "all_converged": true,
    "any_lag_with_entry": false,
    "entry_index": 3,
    "event": "config_round_end",
    "iteration": 0,
    "lagging_nodes": 0,
    "max_wait_ms": 0,
    "window_ms": 3000,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]",
      "location": {
        "line": 51,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceConfigurationContentConvergence\"]"
      }
    }
  }
]
```
待解决：Exploratory basis has no fixed requirement and comparison

归属解释历史：

- `5a436a477b8e4920bbcd4123e81f07fa-interpretation-1` · 未解决：No sourced mechanism was established for configurations.latest or the atomically published latestConfiguration being older than a configuration entry the server itself has committed, and the inference that produced the earlier suspicion was corrected by source reading. Configuration entries never reach FSM.Apply (fsm.go:105-118: only LogCommand goes to r.fsm.Apply; LogConfiguration only calls ConfigurationStore.StoreConfiguration when the FSM implements ConfigurationStore), and MockFSM records only LogCommand payloads (testing.go:76-81), so the captured helper's EnsureSame comparison (testing.go:614-676) is vacuous for a cluster whose only entries are configuration and noop entries and cannot show that a peer holds the configuration entry - my earlier claim that the lagging follower had applied the entry while reporting old membership was therefore unfounded. The helper does poll until its limit, which defaults to 5s (testing.go:733-752), so the captured 'peer mismatch' means one node's GetConfiguration read stayed at the 2-server bootstrap configuration for at least the full window while another node reported 3 servers; that is consistent with the entry not having been appended on that node yet, and my instrumented replay of the same scenario (AddVoter of a protocol-3 node into a protocol-2 pair, 250ms polling of configurations.latest/latestIndex and the atomic copy) showed every node converging within 250ms on every run, so no persistent internal divergence was observed. The candidate path named in the earlier hypothesis is also refuted: on a suffix-truncating appendEntries the conflicting entry is included in newEntries and processConfigurationLogEntry is re-run for it in the same call (raft.go:1504-1560), and rolling latest back to the committed configuration after a real truncation is the intended semantics rather than a stale read. The question is left unresolved and paused: the >5s lag itself was not reproduced under instrumentation and its cause (replication scheduling, pipeline state, or something else) is unverified.；依据来源 s_get_configuration, s_fsm_apply_switch, s_mockfsm_apply, s_ensure_same, s_ensure_same_peers, s_makecluster_defaults, s_truncation_rollback，执行 无（源码解释）。
  反证：Local replay of the captured failing scenario converged on every run, so the observed mismatch did not reproduce under instrumentation; it is retained as an unexplained observation rather than as evidence of a defect.；The appendEntries rollback that the earlier hypothesis named is not a stale-latest mechanism: the conflicting entry is re-appended and re-processed in the same call (raft.go:1504-1560).
  限制：No controller execution receipt backs this interpretation; the negative replay result came from a scratch copy of the captured package during exploration.；The captured failing test was observed to fail 2 of 3 isolated local runs before instrumentation; that count is a local observation and not a retained receipt.；Nothing here establishes that a stale configuration state is impossible; it establishes that the specific inference and the specific candidate path were not supported.
  缺口答复：ce1a7dcb68b449448fdee06b3eb7737e-gap-1: Not established, with a correction. Source reading shows configuration entries never reach FSM.Apply (fsm.go:105-118) and MockFSM records only LogCommand payloads (testing.go:76-81), so the captured EnsureSame comparison (testing.go:614-676) cannot demonstrate that a peer holds a configuration entry; the earlier inference that a stale-latest node had applied the entry was unfounded. Instrumented replay of the same scenario (protocol-2 pair plus an AddVoter of a protocol-3 node, reading configurations.latest/latestIndex, the atomic latestConfiguration and the log store every 250ms) converged within 250ms on every run, and the appendEntries truncation path re-applies configuration entries in the same call (raft.go:1504-1560), so neither a persistent stale configuration state nor an internal reset behind an appended entry was observed. What remains supported is the weaker observation that in the captured test runs one node's GetConfiguration read stayed at the 2-server bootstrap configuration for the whole 5s EnsureSamePeers window (testing.go:733-752) while another reported 3 servers; whether that was replication lag to that node or a reset was not determined, and no execution was requested for this question.
- `3e1c60d4f59d4003a5efce001e1e4374-interpretation-0` · 有限范围未见违反：本场景下保护成立（固定输入执行 receipt 38d727906cc1458b9dfdcd9e337fc5a2，exit 0，两条比较在全部 25 轮成立）：25 轮协议 2 双节点 + 协议 3 加入者的升级场景中，发布配置内容在各节点于 0-6ms（中位数 0ms）内包含新成员，且没有任何节点在自身日志已含配置条目的情况下仍发布旧成员（any_lag_with_entry 全为 false，75/75 节点结果收敛）。此前该问题探针使用恒为 0 的配置索引访问器作为判据，其读数无效，已被本次测量取代。仍未解释且不作归因：先前本地捕获测试 TestRaft_ProtocolVersion_Upgrade_2_3 在约 2/3 次隔离运行中出现 peer mismatch，插桩后同一场景毫秒级收敛，本执行未复现该现象。；依据来源 s_set_latest_configuration, s_get_latest_configuration, s_process_configuration_entry, s_get_configuration_api，执行 38d727906cc1458b9dfdcd9e337fc5a2。
  反证：The earlier probe for this question reported twenty consecutive non-converged readings, but that predicate was the configuration index accessor, which returns a constant zero; those readings are invalid and are superseded rather than averaged with this result.；One round shows a node with the new membership published while its committed configuration index is still behind, which is the documented latest-versus-committed distinction and not evidence of the lag this question asks about.
  限制：Twenty-five rounds of a single scenario shape through the in-memory transport; other shapes and larger clusters were not exercised.；The measurement reads published configuration content and the log store at the end of each window; a transient internal state between those reads is not excluded, only the persistent form the question asks about.；The captured test's earlier local failure is not reproduced here and remains unexplained; this interpretation does not attribute it.；No claim is made about networks with loss, partitions or slow disks.
### Does nextConfiguration's AddNonvoter branch silently keep an existing voter's vote (or drop an address update), contradicting the documented contract for AddNonvoter and DemoteVoter, in a way that could let a membership change fail to remove voting authority?

当前处置：局部问题已回答。
问题 `5a436a477b8e4920bbcd4123e81f07fa-question-2` v1；来源：s_addnonvoter_doc, s_addnonvoter_branch, s_addnonvoter_tests（[完整引用](state.json)）。
假设：The branch is asymmetric with AddVoter: when the target server currently has Suffrage != Nonvoter (a voter or staging server) it writes only the address and keeps the existing suffrage, whereas AddVoter replaces the entry when the server is not already a voter. Read alone this looks like a membership change that cannot take authority away.
下一判别条件：Compare the branch against the documented contract for AddNonvoter and DemoteVoter and against the captured table expectations for each initial suffrage. A defect requires either a documented promise that AddNonvoter demotes, or a captured expectation showing Voter/Staging becoming Nonvoter; if the documentation assigns demotion to DemoteVoter and the expectations keep Voter/Staging unchanged, the asymmetry is intended behaviour and no authority-loss claim is supported.
问题边界：Source-only answer: no execution was requested, so this settles the contract question rather than any live membership-change behaviour.；The captured table expectations cannot distinguish 'address rewritten with the same value' from 'address untouched', so the exact address-update effect on an existing voter was not exercised.

归属解释历史：

- `5a436a477b8e4920bbcd4123e81f07fa-interpretation-2` · 源码解释：The apparent asymmetry is the documented contract rather than a missed demotion. The AddNonvoter documentation (api.go:959-963) states that a server already in the cluster has its address updated, and assigns vote removal to DemoteVoter (api.go:992-996); the AddNonvoter branch (configuration.go:256-276) therefore appends a Nonvoter only when the entry is absent and otherwise rewrites the address while preserving the existing suffrage, and the branch still rejects a configuration with no voters through checkConfiguration. The captured table expectations agree for every initial suffrage: with an existing Voter the expected configuration keeps Voter id1 (configuration_test.go:197-198), with an existing Staging server it keeps Staging (configuration_test.go:199-200), and DemoteVoter on a Voter produces Nonvoter (configuration_test.go:206-207). An operator who wants to take a vote away must call DemoteVoter, so no membership change silently loses or retains authority against the documented contract. Recorded as a source-answered negative result so the asymmetry is not later reported as a defect.；依据来源 s_addnonvoter_doc, s_addnonvoter_branch, s_addnonvoter_tests，执行 无（源码解释）。
  限制：Source-only: the documentation, branch and captured expectations agree, but no execution was requested and the exact address-rewrite effect was not exercised.；This says nothing about what happens if a DemoteVoter request is accepted while the demoted server is the leader; that path was not investigated.
### After a configuration entry is committed, can the FSM thread's own applied index lag behind the committed configuration index in a way that makes a snapshot claim an index/configuration combination the FSM does not represent, or that silently mislabels snapshot metadata?

当前处置：局部问题已回答。
问题 `e2a8cfd757e74ee4965e45968de09795-question-0` v1；来源：s_fsm_apply_single, s_prepare_log, s_process_logs, s_fsm_snapshot_req, s_take_snapshot, s_compact_trailing（[完整引用](state.json)）。
假设：The FSM thread tracks the index it has accounted for locally and advances it only for entries that actually reach it; configuration entries are dropped before dispatch in protocol <= 2 and, when they do arrive without a ConfigurationStore, return early without advancing the index. That lag is then contained by takeSnapshot, which refuses to snapshot when the FSM index is below the committed configuration index instead of labelling a snapshot with a configuration the FSM never reached.
下一判别条件：Trace which log types survive prepareLog into the FSM batch, whether the apply handler advances its local index for each of them, and what takeSnapshot does with the FSM-reported index versus the committed configuration index read afterwards. A defect would require either an entry type that reaches the FSM but silently skips the index bookkeeping without a stated reason, or a snapshot that is created with a configuration index beyond the FSM index.
问题边界：Source-only: no execution was requested, so this is a reading of the routing, index and guard code rather than an observed snapshot sequence.；The behaviour is described for the single-apply path; the batching path tracks the last entry in the batch instead (fsm.go:145-171) and was not differentially exercised.

归属解释历史：

- `e2a8cfd757e74ee4965e45968de09795-interpretation-0` · 源码解释：The lag is real but contained, and the containment is explicit rather than accidental. Committed entries reach the FSM thread only if prepareLog builds a tuple for them (raft.go:1362-1387): LogBarrier and LogCommand always, LogConfiguration only when protocolVersion > 2, while LogNoop and the deprecated peer entries return nil and are never dispatched; processLogs (raft.go:1292-1358) responds to their futures itself and then advances lastApplied. Inside the FSM thread (fsm.go:92-125) every received entry advances the local lastIndex/lastTerm except a LogConfiguration when the FSM does not implement ConfigurationStore, which returns early with the explicit reason that the index should not advance for an unimplemented operation. The snapshot request reports that local index (fsm.go:216-233), so after a committed configuration change with no later command or barrier the FSM index can sit below the committed configuration index. takeSnapshot (snapshot.go:125-211) reads the committed configuration from the main thread afterwards and refuses to snapshot when snapReq.index < committedIndex, with a comment naming exactly this case, so metadata is never labelled with a configuration the FSM has not reached; compaction is separately bounded by min(snapshot index, last log index - TrailingLogs) (snapshot.go:213-240), so nothing beyond the log's last index is trimmed. The observable boundary is that snapshot creation keeps failing with 'cannot take snapshot now, wait until the configuration entry at N has been applied' until an entry the FSM accounts for arrives - and the library's own client contract supplies one, since both a command and a Barrier traverse this path, so the condition is self-clearing under normal traffic rather than a stuck state. No defect is claimed here; the reading explains why the asymmetry between the log index and the FSM index is safe.；依据来源 s_fsm_apply_single, s_prepare_log, s_process_logs, s_fsm_snapshot_req, s_take_snapshot, s_compact_trailing，执行 无（源码解释）。
  反证：The early return would be a silent metadata mislabel if the guard were absent, but snapshot.go:165-176 refuses exactly that case and reports it to the caller, so the weak link identified in the hypothesis is enclosed by a source-visible protection.；Compaction cannot delete past the log head: maxLog is the minimum of the snapshot index and lastLogIdx-trailingLogs (snapshot.go:213-240).
  限制：Source-only: no execution was requested, so this explains the guard rather than observing a snapshot sequence or the error being returned to a client.；The batching FSM path tracks the last entry of the batch (fsm.go:145-171) rather than the last entry sent to ApplyBatch, which was read but not differentially exercised.；Nothing here measures how long a cluster would run without a snapshot in the no-traffic case; the claim is only that the condition is bounded by a legal client operation.
### 快照恢复节点的自动快照条件恒真（含对照确认）

当前处置：局部问题已回答。
问题 `e2a8cfd757e74ee4965e45968de09795-question-1` v3；来源：s_should_snapshot, s_take_snapshot, s_install_snapshot_tail, s_get_last_index, s_compact_trailing（[完整引用](state.json)）。
原命题：Can shouldSnapshot's unsigned delta between the log store's last index and the last snapshot index underflow, so that the automatic snapshot condition is permanently true on a node whose log store sits below its snapshot index, and what does such a node then do every SnapshotInterval?
假设：shouldSnapshot computes delta := lastIdx - lastSnap with unsigned integers and no ordering check, where lastIdx is the log store's LastIndex and lastSnap is the snapshot index kept separately. A node that recovered through InstallSnapshot sets its last snapshot index to the snapshot's index, while its log store may keep a lower index: installSnapshot compacts with min(snapIdx, lastLogIdx-trailingLogs), so a node whose log store is below the snapshot index keeps that lower index, and the node's snapshot-aware log index (getLastIndex = max(lastLogIndex, lastSnapshotIndex)) does not feed shouldSnapshot. If a run reaches that state, delta underflows and the node takes a fresh full-state snapshot every SnapshotInterval until its log store grows past the snapshot index.
下一判别条件：Build a cluster whose leader has compacted most of its log, let a fresh or lagging follower recover by InstallSnapshot, and then record, per SnapshotInterval: the follower's log store FirstIndex/LastIndex, its last snapshot index, whether shouldSnapshot returned true, whether takeSnapshot created a new snapshot at the same index and whether a repeat install happened. A confirmed defect needs the log store index below the snapshot index together with repeated snapshot creation on an otherwise idle node; if the log store index is always at or above the snapshot index after install, or if some other producer raises it, the hypothesis is refuted.
问题边界：The witness is one bounded window (900ms, SnapshotInterval 40ms, 22 samples) on one recovered node in one cluster; it establishes the condition and the repeated snapshot creation, not production SnapshotInterval cost or how long the condition persists in a busy cluster.；The observation is bounded to the automatic snapshot path on a node isolated from its leader during the window; the receipt does not separate snapshot creations caused by a further InstallSnapshot because isolation excludes that source by construction.；The control comparison in the retained receipt is structurally uncorrelated (both nodes shared one end-event name), so the control is supported by the operands recorded in the same receipt and by the requested successor rather than by a holds outcome.；No safety or availability failure is claimed; the effect is repeated snapshot work, and snapshot retention still bounds how many snapshot objects are kept.

固定实验 `0620c91eb9c641de9723369bd4729fd6-experiment` v1：[原始依据](fixed-experiments/0620c91eb9c641de9723369bd4729fd6-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster with a small SnapshotInterval/SnapshotThreshold/TrailingLogs: warm traffic, isolation of one follower, further traffic so the leader compacts, reconnection so the follower recovers by InstallSnapshot, then a bounded idle window on the recovered node (isolated again so no further InstallSnapshot can occur) with the leader observed over the same window as control.
前史／供给条件：The harness builds the prefix with the captured test facilities and real producers only: MakeCluster(3, conf) with SnapshotInterval=40ms, SnapshotThreshold=20 and TrailingLogs=5 bootstraps the cluster; leader.Apply() commits 60 warm commands so every node snapshots; the chosen follower is cut off with c.Disconnect and 140 further commands are committed by the remaining quorum so the leader's log compacts; c.FullyConnect reconnects and the follower recovers through the InstallSnapshot handler. The harness then emits recovery_state (snapshot index 202 above log store last index 62 in the local run) and disconnects the recovered node again before the observation window. window_start carries each node's snapshot index, newest snapshot ID, log store last index, last snapshot index, should_snapshot() and applied index; during the window the harness samples each node's snapshot list every 40ms counting distinct IDs; window_end reports distinct_snapshot_ids, snapshot_created_without_new_entries (derived as distinct>=2 and applied index unchanged, with both operands emitted), newest snapshot ID and index, log store last index, should_snapshot() and applied_delta. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) with SnapshotInterval=40ms, SnapshotThreshold=20, TrailingLogs=5 performs real bootstrap, replication, snapshots and log compaction through the in-memory transport.；Disconnecting only the chosen follower leaves the leader with a quorum (itself plus the other follower), so the cluster keeps committing and the leader's log compacts past the isolated follower's next index.；The isolated follower does not raise its term while isolated because pre-vote is active by default, so reconnecting lets the leader complete the recovery without a spurious election.；Isolating the recovered node again before the window removes the leader as a source of further snapshots, so any new snapshot in that node's store must be produced by its own snapshot goroutine.；Both observed nodes run the same configuration; the leader is idle in the window except for heartbeats.
范围外：Safety claims: no state-machine divergence, lost entry or double application is asserted.；Cost measurement: bytes written, disk wear and FSM Snapshot() latency are not measured.；Behaviour with MonotonicLogStore implementations, which take the removeOldLogs branch instead of compactLogs.；Duration of the condition under production SnapshotInterval values.
书面要求：On a server whose log store last index sits below its last snapshot index, the automatic snapshot condition computes the delta between the log store index and the snapshot index as an unsigned subtraction without an ordering guard, so the condition stays true while the server is idle and its snapshot goroutine keeps creating fresh snapshots at the same index.
执行 `dd59f37872d240548eff168eb821901f`：completed，退出码 0；[回执](logs/dd59f37872d240548eff168eb821901f/check.json)、[stdout](logs/dd59f37872d240548eff168eb821901f/stdout.log)、[stderr](logs/dd59f37872d240548eff168eb821901f/stderr.log)。
机械比较：unknown；当前确认：未确认违反
当前归属解释 `1bb3635ce65244c5ac3c439ab505451e-interpretation-0`：有限范围未见违反；已确认的缺陷：经 InstallSnapshot 恢复的节点，其日志存储 LastIndex 可能停留在低于已安装快照索引的位置（installSnapshot 设置快照索引并按 min(snapIdx, lastLogIdx-trailingLogs) 压缩，state.go:159-163 的快照感知索引不参与该判断）。shouldSnapshot（snapshot.go:106-120）用无符号减法比较日志存储索引与快照索引且无大小保护，于是条件恒为真，runSnapshots（snapshot.go:72-102）每个 SnapshotInterval 都会触发一次 takeSnapshot。固定输入执行（receipt dd59f37872d240548eff168eb821901f，exit 0）中：恢复节点快照索引 62→202 而日志存储索引保持 62；在 900ms 窗口、applied_delta 为 0 的情况下产生 15 个不同快照 ID，最新快照索引始终为 202；同一窗口内 leader 的 should_snapshot 为 false 且只有 1 个快照 ID。后果是空闲恢复节点持续写出等价的全量快照（可避免的 IO/快照开销），不主张安全性或可用性被破坏。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "recovery_state",
    "log_store_below_snapshot_index": true,
    "log_store_last_after_reconnect": 62,
    "log_store_last_before_isolation": 62,
    "node": "server-9f900c62-8505-225c-ac98-3fad363c2403",
    "snapshot_advanced_over_log_store": true,
    "snapshot_index_after_reconnect": 202,
    "snapshot_index_before_isolation": 62,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
      "location": {
        "line": 248,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]"
      }
    }
  },
  {
    "applied_index": 202,
    "event": "window_start",
    "last_snapshot_index": 202,
    "log_store_last": 62,
    "newest_snapshot_id": "2-202-1791708222798",
    "node": "server-9f900c62-8505-225c-ac98-3fad363c2403",
    "role": "recovered-node",
    "should_snapshot": true,
    "snapshot_index": 202,
    "snapshot_interval_ms": 40,
    "snapshot_threshold": 20,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
      "location": {
        "line": 250,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]"
      }
    }
  },
  {
    "applied_index": 202,
    "event": "window_start",
    "last_snapshot_index": 202,
    "log_store_last": 202,
    "newest_snapshot_id": "2-202-1791708221790",
    "node": "server-73610073-b9c9-6888-3231-5b8b4d361e3a",
    "role": "leader-control",
    "should_snapshot": false,
    "snapshot_index": 202,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
      "location": {
        "line": 251,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]"
      }
    }
  },
  {
    "applied_delta": 0,
    "applied_index": 202,
    "distinct_snapshot_ids": 15,
    "event": "window_end",
    "last_snapshot_index": 202,
    "log_store_last": 62,
    "newest_snapshot_id": "2-202-1791708223751",
    "newest_snapshot_index": 202,
    "node": "server-9f900c62-8505-225c-ac98-3fad363c2403",
    "role": "recovered-node",
    "should_snapshot": true,
    "snapshot_created_without_new_entries": true,
    "snapshot_index": 202,
    "ticks": 22,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
      "location": {
        "line": 566,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]"
      }
    }
  },
  {
    "applied_delta": 0,
    "applied_index": 202,
    "distinct_snapshot_ids": 1,
    "event": "window_end",
    "last_snapshot_index": 202,
    "log_store_last": 202,
    "newest_snapshot_id": "2-202-1791708221790",
    "newest_snapshot_index": 202,
    "node": "server-73610073-b9c9-6888-3231-5b8b4d361e3a",
    "role": "leader-control",
    "should_snapshot": false,
    "snapshot_created_without_new_entries": false,
    "snapshot_index": 202,
    "ticks": 22,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]",
      "location": {
        "line": 567,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflow\"]"
      }
    }
  }
]
```
观测缺口：Event 3 {'node': 'server-9f900c62-8505-225c-ac98-3fad363c2403'}: No corresponding prerequisite events reached: control_window/window_start

固定实验 `1bb3635ce65244c5ac3c439ab505451e-experiment` v2：[原始依据](fixed-experiments/1bb3635ce65244c5ac3c439ab505451e-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster with SnapshotInterval=40ms, SnapshotThreshold=20 and TrailingLogs=5: warm traffic, isolation of one follower, further traffic so the leader compacts, reconnection so the follower recovers by InstallSnapshot, then a bounded idle window on the recovered node (isolated again) with the leader observed over the same window as control. Identical to the predecessor except that the two nodes' window events carry distinct names.
前史／供给条件：Same prefix as the predecessor, built with captured test facilities and real producers only: MakeCluster(3, conf) with SnapshotInterval=40ms, SnapshotThreshold=20, TrailingLogs=5; 60 warm leader.Apply() commands so every node snapshots; c.Disconnect on the chosen follower plus 140 further commands committed by the remaining quorum so the leader compacts past the follower's next index; c.FullyConnect so the follower recovers through the real InstallSnapshot handler; then recovery_state, then c.Disconnect of the recovered node again before the window. The successor differs only in event naming: the recovered node emits window_start and recovered_window_end, the leader emits control_window_start and control_window_end, so each comparison's admission and result events correlate on the same node identity. Window sampling, operands and the derived snapshot_created_without_new_entries field are unchanged from the predecessor. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) with the settings above performs real bootstrap, replication, snapshotting and log compaction through the in-memory transport.；Disconnecting only the chosen follower leaves the leader with a quorum, so the cluster keeps committing and the leader's log compacts past the isolated follower's next index.；Pre-vote is active by default, so the isolated follower does not raise its term and reconnecting lets the leader complete recovery without a spurious election.；Isolating the recovered node again before the window removes the leader as a source of further snapshots, so any new snapshot in that node's store is produced by its own snapshot goroutine.；The leader is idle during the window apart from heartbeats and its log store index equals its snapshot index.
范围外：Safety claims: no state divergence, lost entry or double application is asserted.；Cost measurement: bytes written, disk wear and FSM Snapshot() latency are not measured.；Monotonic log store implementations, which take the removeOldLogs branch instead of compactLogs.；Production SnapshotInterval values and long-run persistence of the condition.
前驱 `0620c91eb9c641de9723369bd4729fd6-experiment`；修订原因：Only the event labelling and comparison wiring changed: the predecessor emitted one shared window_end event for both the recovered node and the leader, so the control comparison could not correlate an admission event to the compared event identity (receipt dd59f37872d240548eff168eb821901f reported comparison_index 1 as unknown with 'No corresponding prerequisite events reached: control_window/window_start'). The successor emits recovered_window_end for the recovered node and control_window_end for the leader with the leader admission renamed control_window_start, keeping the producers, configuration, command counts, isolation steps and window identical. Fresh execution is requested because the comparison basis changed.；实际变化：harness, scope, prefix, requirement, responsibility, comparisons
书面要求：On a server whose log store last index sits below its last snapshot index, the automatic snapshot condition stays true while the server is idle, and the server's snapshot goroutine keeps creating fresh snapshots at the same index; a server whose log store index equals its snapshot index does not.
执行 `c388285f090c4c1c85547bd6ddd9cd98`：completed，退出码 0；[回执](logs/c388285f090c4c1c85547bd6ddd9cd98/check.json)、[stdout](logs/c388285f090c4c1c85547bd6ddd9cd98/stdout.log)、[stderr](logs/c388285f090c4c1c85547bd6ddd9cd98/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `87206f99921a4f25986b0b6525d9d58c-interpretation-0`：有限范围未见违反；已确认的缺陷（含对照）：经 InstallSnapshot 恢复的节点，其日志存储 LastIndex 停留在低于已安装快照索引的位置，shouldSnapshot（snapshot.go:106-120）以无符号减法且无大小保护地比较日志存储索引与快照索引，使条件恒为真；runSnapshots（snapshot.go:72-102）因此每个 SnapshotInterval 都触发一次 takeSnapshot。后继固定输入执行（receipt c388285f090c4c1c85547bd6ddd9cd98，exit 0）中：恢复节点快照索引 62→202 而日志存储索引保持 62；900ms 窗口内 applied_delta 为 0、应产生 13 个不同快照 ID、最新快照索引始终为 202；同一窗口同一集群的 leader 对照 should_snapshot 为 false、日志存储索引 202 等于快照索引、只有 1 个快照 ID。两条比较均成立，与前一执行（dd59f37872d240548eff168eb821901f，15 个快照 ID，对照未关联）构成同一场景的兼容历史。后果是空闲恢复节点持续写出等价全量快照（可避免的 IO/快照开销），不主张安全性或可用性被破坏。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "recovery_state",
    "log_store_below_snapshot_index": true,
    "log_store_last_after_reconnect": 62,
    "log_store_last_before_isolation": 62,
    "node": "server-b5fbb977-7cbb-7907-4269-31faaa6a1c86",
    "snapshot_advanced_over_log_store": true,
    "snapshot_index_after_reconnect": 202,
    "snapshot_index_before_isolation": 62,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
      "location": {
        "line": 224,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]"
      }
    }
  },
  {
    "applied_index": 202,
    "event": "window_start",
    "last_snapshot_index": 202,
    "log_store_last": 62,
    "newest_snapshot_id": "2-202-1791708350452",
    "node": "server-b5fbb977-7cbb-7907-4269-31faaa6a1c86",
    "role": "recovered-node",
    "should_snapshot": true,
    "snapshot_index": 202,
    "snapshot_interval_ms": 40,
    "snapshot_threshold": 20,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
      "location": {
        "line": 226,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]"
      }
    }
  },
  {
    "applied_index": 202,
    "event": "control_window_start",
    "last_snapshot_index": 202,
    "log_store_last": 202,
    "newest_snapshot_id": "2-202-1791708349439",
    "node": "server-2f8f363d-165e-4ae3-ae7b-3a76d1079a93",
    "role": "leader-control",
    "should_snapshot": false,
    "snapshot_index": 202,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
      "location": {
        "line": 227,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]"
      }
    }
  },
  {
    "applied_delta": 0,
    "applied_index": 202,
    "distinct_snapshot_ids": 13,
    "event": "recovered_window_end",
    "last_snapshot_index": 202,
    "log_store_last": 62,
    "newest_snapshot_id": "2-202-1791708351357",
    "newest_snapshot_index": 202,
    "node": "server-b5fbb977-7cbb-7907-4269-31faaa6a1c86",
    "role": "recovered-node",
    "should_snapshot": true,
    "snapshot_created_without_new_entries": true,
    "snapshot_index": 202,
    "ticks": 22,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
      "location": {
        "line": 515,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]"
      }
    }
  },
  {
    "applied_delta": 0,
    "applied_index": 202,
    "distinct_snapshot_ids": 1,
    "event": "control_window_end",
    "last_snapshot_index": 202,
    "log_store_last": 202,
    "newest_snapshot_id": "2-202-1791708349439",
    "newest_snapshot_index": 202,
    "node": "server-2f8f363d-165e-4ae3-ae7b-3a76d1079a93",
    "role": "leader-control",
    "should_snapshot": false,
    "snapshot_created_without_new_entries": false,
    "snapshot_index": 202,
    "ticks": 22,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]",
      "location": {
        "line": 516,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceSnapshotIndexUnderflowControlCorrelated\"]"
      }
    }
  }
]
```

归属解释历史：

- `1bb3635ce65244c5ac3c439ab505451e-interpretation-0` · 有限范围未见违反：已确认的缺陷：经 InstallSnapshot 恢复的节点，其日志存储 LastIndex 可能停留在低于已安装快照索引的位置（installSnapshot 设置快照索引并按 min(snapIdx, lastLogIdx-trailingLogs) 压缩，state.go:159-163 的快照感知索引不参与该判断）。shouldSnapshot（snapshot.go:106-120）用无符号减法比较日志存储索引与快照索引且无大小保护，于是条件恒为真，runSnapshots（snapshot.go:72-102）每个 SnapshotInterval 都会触发一次 takeSnapshot。固定输入执行（receipt dd59f37872d240548eff168eb821901f，exit 0）中：恢复节点快照索引 62→202 而日志存储索引保持 62；在 900ms 窗口、applied_delta 为 0 的情况下产生 15 个不同快照 ID，最新快照索引始终为 202；同一窗口内 leader 的 should_snapshot 为 false 且只有 1 个快照 ID。后果是空闲恢复节点持续写出等价的全量快照（可避免的 IO/快照开销），不主张安全性或可用性被破坏。；依据来源 s_should_snapshot, s_run_snapshots, s_take_snapshot, s_install_snapshot_full, s_get_last_index, s_compact_trailing，执行 dd59f37872d240548eff168eb821901f。
  反证：The control operands recorded in the same receipt show the condition is not universal: the leader in the same window kept shouldSnapshot false, its log store index equal to its snapshot index, and a single snapshot ID at index 202 with applied_delta 0.；The retained receipt's control comparison outcome is unknown (no correlated prerequisite) because both nodes emitted one shared end-event name; this is a harness naming defect in my comparison setup, not a contrary observation, and it is why a successor is requested rather than treated as confirmation.；The node was isolated during the window by construction, so the repeated snapshots cannot be attributed to further InstallSnapshot traffic from a leader.
  限制：One execution, one bounded window; production SnapshotInterval values, larger state, and busy clusters were not exercised.；The measured effect is repeated snapshot creation on a recovered idle node; no state corruption, lost entry or availability failure is claimed, and snapshot retention bounds stored copies.；The witness does not measure the CPU, IO or FSM Snapshot() latency cost of the repeated snapshots.；Monotonic log stores take the removeOldLogs branch instead of compactLogs and were not exercised.
  缺口答复：e2a8cfd757e74ee4965e45968de09795-gap-2: Yes, and nothing in the observed path raises the log store index to prevent the repeat. In receipt dd59f37872d240548eff168eb821901f (exit 0) the recovered node's log store last index stayed 62 while its snapshot index was 202 (event index 0, log_store_below_snapshot_index true), shouldSnapshot reported true at window start (index 1) and still true at window end (index 3), and over the 900ms window with applied_delta 0 the node produced 15 distinct snapshot IDs whose newest index remained 202 - so a fresh snapshot at the same index was created roughly every SnapshotInterval. The leader observed in the same window kept shouldSnapshot false with 1 distinct snapshot ID at the same index 202 (indices 2 and 4). The mechanism is the unsigned delta in snapshot.go:106-120 measured against the log store's own LastIndex rather than the snapshot-aware index, combined with installSnapshot setting the snapshot index above the surviving log store index (raft.go:1814-1950, snapshot.go:216-240) and runSnapshots sampling the condition every SnapshotInterval (snapshot.go:72-102).
- `87206f99921a4f25986b0b6525d9d58c-interpretation-0` · 有限范围未见违反：已确认的缺陷（含对照）：经 InstallSnapshot 恢复的节点，其日志存储 LastIndex 停留在低于已安装快照索引的位置，shouldSnapshot（snapshot.go:106-120）以无符号减法且无大小保护地比较日志存储索引与快照索引，使条件恒为真；runSnapshots（snapshot.go:72-102）因此每个 SnapshotInterval 都触发一次 takeSnapshot。后继固定输入执行（receipt c388285f090c4c1c85547bd6ddd9cd98，exit 0）中：恢复节点快照索引 62→202 而日志存储索引保持 62；900ms 窗口内 applied_delta 为 0、应产生 13 个不同快照 ID、最新快照索引始终为 202；同一窗口同一集群的 leader 对照 should_snapshot 为 false、日志存储索引 202 等于快照索引、只有 1 个快照 ID。两条比较均成立，与前一执行（dd59f37872d240548eff168eb821901f，15 个快照 ID，对照未关联）构成同一场景的兼容历史。后果是空闲恢复节点持续写出等价全量快照（可避免的 IO/快照开销），不主张安全性或可用性被破坏。；依据来源 s_should_snapshot, s_run_snapshots, s_take_snapshot, s_install_snapshot_full, s_get_last_index, s_compact_trailing，执行 c388285f090c4c1c85547bd6ddd9cd98。
  反证：The control comparison now holds against the opposite value: the leader in the same cluster and window had shouldSnapshot false, its log store index equal to its snapshot index, and a single snapshot ID at index 202 with applied_delta 0, so the repeated snapshots are not a property of the configuration or of the window.；The number of distinct snapshot IDs differs between the two executions (15 and 13 over 22 samples at a 40ms interval), which is consistent with scheduling jitter rather than a different mechanism, and is retained here rather than smoothed.；The recovered node was isolated during the window by construction, so the repeats cannot be attributed to further InstallSnapshot traffic from the leader.
  限制：Two executions, both short windows (900ms) with a deliberately small SnapshotInterval; production SnapshotInterval behaviour and long-run persistence were not observed.；Only the in-memory log and snapshot stores with default (non-monotonic) log store behaviour were exercised; MonotonicLogStore takes the removeOldLogs branch instead.；The measured effect is repeated snapshot creation; its CPU, IO and FSM Snapshot() latency cost, and any interaction with slow snapshot persistence, were not measured.；No claim is made that the condition is unrecoverable: any traffic that raises the log store index above the snapshot index ends it, and it is not claimed to affect safety.
### When leadership is lost while a VerifyLeader request is outstanding, can the resulting future be completed twice or left permanently unanswered, given that replication goroutines still hold it and notify it onto the shared verify channel after the leader loop has already responded to the pending set?

当前处置：局部问题已回答。
问题 `87206f99921a4f25986b0b6525d9d58c-question-0` v1；来源：s_verify_future_vote, s_defer_error_respond, s_leader_cleanup_verify, s_verify_leader_dispatch, s_nonleader_verify_reject（[完整引用](state.json)）。
假设：A pending verify future lives in two owners at once: the leader loop's notify set (responded with ErrLeadershipLost by the step-down cleanup) and each replication goroutine's notify map (a separate map, cleared by notifyAll at the end of an RPC). A goroutine that notifies after the cleanup therefore pushes the same future back onto the shared verifyCh, where the follower or candidate loop will respond to it a second time.
下一判别条件：Trace who may call respond on a verifyFuture and with what synchronisation, and what happens to a future that a replication goroutine re-notifies after the step-down cleanup: a defect requires two concurrent responders (a data race on the responded flag or a double send on the error channel) or a future that is never completed. If respond is reachable only from the main goroutine holding the run loop, and the second arrival is answered under the same stateless reject rule, the sequence is ordered and idempotent, and the apparent double completion is refuted.
问题边界：Source-only: no execution and no race-detector run was requested, so this explains the ownership and ordering rather than observing a concurrent step-down.；The analysis covers verifyFuture completion paths in the captured revision; it says nothing about other future types or about respond callers added later.；The timing window in which a replication goroutine notifies after the cleanup was reasoned from the code, not measured.

归属解释历史：

- `87206f99921a4f25986b0b6525d9d58c-interpretation-1` · 源码解释：The apparent double completion is refuted by completion ownership and ordering. verifyLeader registers the future in the leader loop's notify set and in each replication goroutine's notify map, and the step-down cleanup responds ErrLeadershipLost to everything still in the leader's own set (raft.go:511-526). The replication maps are separate and are only cleared by notifyAll when an RPC finishes (replication.go:100-111), so a goroutine that finishes its heartbeat after the cleanup can still call vote on the same future; vote sends the future onto the shared verify channel and nils its notify channel under voteLock, so it wakes at most once (future.go:272-293). The critical point is who responds: respond is reachable only from the main run loop for this future type (the leader loop's verify branch, the follower and candidate reject branches, and the step-down cleanup), and all of those execute on the single main goroutine, so the cleanup's respond and any later rejection are sequentially ordered rather than concurrent. The second arrival is therefore a no-op: deferError.respond returns early once responded is set, and if it were reached first it would simply answer ErrNotLeader through the same idempotent path (future.go:94-131, raft.go:181-186). The result is that a VerifyLeader outstanding at leadership loss is answered exactly once - ErrLeadershipLost from the cleanup - and any late wake-up on the shared channel is swallowed by the responded flag instead of double-closing the error channel or blocking a sender. A worthwhile boundary follows from the same reading but is not a defect: because vote records a false reply immediately, the leader steps down and answers ErrNotLeader as soon as a single peer reports a new leader, and because votes are only counted from replies, a partition that silences peers leaves the request unanswered until a reply, shutdown or the caller's own timeout resolves it.；依据来源 s_verify_future_vote, s_defer_error_respond, s_leader_cleanup_verify, s_verify_leader_dispatch, s_nonleader_verify_reject，执行 无（源码解释）。
  反证：The strong form of the suspicion - two concurrent responders racing on the responded flag - requires a respond caller off the main goroutine, and the captured revision has none for verifyFuture: replication goroutines only call vote/notifyAll, which never respond.；The shared verify channel is buffered (api.go:568) so the late notification itself cannot block a replication goroutine.
  限制：Source-only: the ordering argument rests on respond being called exclusively from the main run loop in this revision; a race-detector execution of a concurrent step-down was not requested.；The unresolved-caller-timeout boundary (a verified request that never gets a peer reply) is described, not measured.；No behaviour of other future types or later revisions is claimed.
### 快照安装未回退已应用状态（含同执行对照）

当前处置：局部问题已回答。
问题 `3aab71eb943140cfa801c33349322eb2-question-0` v5；来源：s_install_snapshot_term_only, s_install_snapshot_apply, s_process_logs_replay, s_replicate_to_backoff, s_replicate_send_snapshot, s_get_last_index（[完整引用](state.json)）。
原命题：Can an InstallSnapshot whose term is current but whose snapshot index is older than the receiving node's applied state rewind that node's applied state, and is the rewind always covered by re-application from the surviving log so that no acknowledged applied entry is lost?
假设：installSnapshot performs no comparison between the request's LastLogIndex and the receiving node's own lastApplied, last snapshot index or log store range: it rejects only an older term, restores the FSM from the requested snapshot, sets lastApplied and the last snapshot index to the request's values (a decrease when the request is older by index), replaces both configurations from the request, and then compacts or removes old logs according to that index. Recovering from such a rewind therefore depends on processLogs replaying entries from lastApplied+1 out of the surviving log; if the node's log no longer covers (request index, previously applied index] - for example because it had already compacted past the older snapshot index - those already-applied entries cannot be re-applied and the rewound state persists.
下一判别条件：Two-sided. Sender side: determine whether a leader can be induced to send a snapshot whose index is below the follower's applied index, given that a snapshot is only opened when the leader cannot produce entries from its nextIndex (below its compacted first index) and that nextIndex only moves on follower responses. Receiver side: instrument a node whose log store first index is above the index of a delivered snapshot and record lastApplied, the FSM-visible applied index and the log first index immediately before and after the install, then whether a later commit advance re-applies the gap. A defect needs a delivered request with snapshot index below the receiver's applied index together with a log that does not cover the gap, so that the applied index is not re-reached; if every delivered request has an index at or above the receiver's applied index, or the surviving log always covers the gap, the concern is refuted.
问题边界：Answered for the driven scenario, not in general: the probe never constructs a leader whose latest snapshot index is below a follower's applied index, so unreachability of a rewinding install is not established.；Three probe executions were needed because of two comparison-wiring defects of mine (an admission without node identity, then one admission alias serving nodes that cannot produce the other result event); receipts 2ee538f299f344b098cc111a3b2cdd43 and 1ac934864b0f42fd9bb658662fd71274 therefore retain operands without a decided comparison, and only receipt 60a9c1c1920e4c7d9cd3b6c031613b69 carries complete comparisons.；All three executions show the same operand pattern: no applied-index decrease anywhere, and the recovered node's snapshot index equal to its applied index rather than below it.；Monotonic log store implementations, which take the removeOldLogs branch, were not exercised.

固定实验 `a70adeea31e04813a3ed4fce9c449729-experiment` v1：[原始依据](fixed-experiments/a70adeea31e04813a3ed4fce9c449729-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster with SnapshotInterval=30ms, SnapshotThreshold=10 and TrailingLogs=5, running three rounds of: 25 warm commands, isolate one follower, 60 further commands by the remaining quorum, reconnect, then 1.2s of polling every 2ms that records each node's applied index, snapshot index and log store last index.
前史／供给条件：The harness builds everything with captured test facilities and real producers: MakeCluster(3, conf) with SnapshotInterval=30ms, SnapshotThreshold=10, TrailingLogs=5 bootstraps the cluster and Elects a leader; each round applies 25 commands through leader.Apply, chooses the lexicographically first follower, records its applied index, snapshot index and log store last index, cuts it off with c.Disconnect, commits 60 further commands through the remaining quorum, reconnects with c.FullyConnect, and then polls all three nodes every 2ms for 1.2s. During polling the harness tracks each node's maximum applied index, any applied-index decrease with the snapshot index and log store last index at that moment, the number of snapshot-index changes, and how many poll ticks showed the snapshot index above the log store last index (the install signature). probe_start and one round_start per round record the scenario operands; per node the harness emits recovered_node_probe_end when the install signature was seen and steady_node_probe_end otherwise, carrying max_applied_seen, applied_at_end, observed_applied_decrease, decrease_count, the prior and new applied index and the snapshot/log index at the decrease, snapshot_index_changes, install_signature_ticks and the end state. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) with the settings above performs real bootstrap, replication, snapshotting and compaction through the in-memory transport.；Isolating one follower leaves the leader with a quorum, so commits continue and the leader's log compacts past that follower's next index, making the follower recover through the real InstallSnapshot handler on reconnect.；Polling every 2ms is dense enough to observe an applied-index decrease if one occurs, because an install sets lastApplied directly from the request.；The install signature (snapshot index above the log store last index) identifies a node that has been through InstallSnapshot or is in the post-install state; nodes without it are the steadier comparison within the same execution.
范围外：Configurations where the leader's latest snapshot index is below a follower's applied index, which the probe does not deliberately construct.；Monotonic log store implementations, which take the removeOldLogs branch.；Client-visible consequences of a hypothetical rewind and any performance measurement.
书面要求：No InstallSnapshot delivered in this scenario moves a receiver's applied index backwards: a request whose snapshot index is below the receiver's applied state would show up as an applied-index decrease with the snapshot index below the previously observed applied index, and the receiver's applied index must stay monotone across the isolation, compaction and recovery rounds.
执行 `2ee538f299f344b098cc111a3b2cdd43`：completed，退出码 0；[回执](logs/2ee538f299f344b098cc111a3b2cdd43/check.json)、[stdout](logs/2ee538f299f344b098cc111a3b2cdd43/stdout.log)、[stderr](logs/2ee538f299f344b098cc111a3b2cdd43/stderr.log)。
机械比较：unknown；当前确认：未确认违反
当前归属解释 `f96d0cb449034230970d0365462d8585-interpretation-0`：未解决；Receipt 2ee538f299f344b098cc111a3b2cdd43 (completed, exit 0, tests_passed) retained the operands but not a decidable comparison, so the account is recorded as unresolved rather than as confirmation. Event 0 probe_start records the scenario constants (3 nodes, SnapshotInterval 30ms, SnapshotThreshold 10, TrailingLogs 5) with leader server-8263015e.... Events 1-3 round_start for the isolated follower server-15768087... show the rounds advancing its applied index 27 -> 112 -> 197 with its log store last index tracking it. Event 6 recovered_node_probe_end for server-15768087... reports install_signature_seen true with install_signature_ticks 1361, snapshot index 257 above log store last index 197, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0 with the decrease operands left at zero. Events 4 and 5 steady_node_probe_end for the leader and the other follower report install_signature_seen false, snapshot index 257/253, log store last index 257 and the same monotone applied state. Taken as operands, this is a negative result for the concern in this scenario: the node that went through the install path never reported an applied index below its maximum, so no delivered request rewound it; the source-level reason is consistent with the term-only check plus the sender-side clamp analysed earlier, since every delivered request in these rounds carried the leader's current snapshot index rather than an older one. The decisive step is nonetheless missing: comparison_index 0 and 1 both came back unknown ('Ambiguous prerequisite association; missing probe.node' for events 6, 4 and 5, and 'Missing operation admission fields or identity' for event 0), because my admission event probe_start carried no node identity while the comparisons keyed on node. I therefore do not claim holds; the successor harness emits per-node admission events (probe_node_start) with the same producers, parameters and window, and the question stays paused until that execution is judged.

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "cluster_size": 3,
    "event": "probe_start",
    "leader_id": "server-8263015e-24bc-40fd-0e47-41fcb7d08cfb",
    "snapshot_interval_ms": 30,
    "snapshot_threshold": 10,
    "trailing_logs": 5,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 27,
    "event": "round_start",
    "log_store_last_before": 27,
    "node": "server-15768087-7040-b6a9-389c-058048342755",
    "round": 0,
    "snapshot_before": 27,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 134,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 112,
    "event": "round_start",
    "log_store_last_before": 112,
    "node": "server-15768087-7040-b6a9-389c-058048342755",
    "round": 1,
    "snapshot_before": 112,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 375,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 197,
    "event": "round_start",
    "log_store_last_before": 197,
    "node": "server-15768087-7040-b6a9-389c-058048342755",
    "round": 2,
    "snapshot_before": 197,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 611,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_end": 257,
    "decrease_count": 0,
    "event": "steady_node_probe_end",
    "install_signature_seen": false,
    "install_signature_ticks": 0,
    "log_store_last_at_decrease": 0,
    "log_store_last_at_end": 257,
    "max_applied_seen": 257,
    "new_applied_at_decrease": 0,
    "node": "server-8263015e-24bc-40fd-0e47-41fcb7d08cfb",
    "observed_applied_decrease": false,
    "prior_applied_at_decrease": 0,
    "snapshot_index_at_decrease": 0,
    "snapshot_index_at_end": 257,
    "snapshot_index_changes": 3,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 741,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_end": 257,
    "decrease_count": 0,
    "event": "steady_node_probe_end",
    "install_signature_seen": false,
    "install_signature_ticks": 0,
    "log_store_last_at_decrease": 0,
    "log_store_last_at_end": 257,
    "max_applied_seen": 257,
    "new_applied_at_decrease": 0,
    "node": "server-b0329767-58ac-02e7-2365-402565b09c37",
    "observed_applied_decrease": false,
    "prior_applied_at_decrease": 0,
    "snapshot_index_at_decrease": 0,
    "snapshot_index_at_end": 253,
    "snapshot_index_changes": 3,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 743,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_end": 257,
    "decrease_count": 0,
    "event": "recovered_node_probe_end",
    "install_signature_seen": true,
    "install_signature_ticks": 1361,
    "log_store_last_at_decrease": 0,
    "log_store_last_at_end": 197,
    "max_applied_seen": 257,
    "new_applied_at_decrease": 0,
    "node": "server-15768087-7040-b6a9-389c-058048342755",
    "observed_applied_decrease": false,
    "prior_applied_at_decrease": 0,
    "snapshot_index_at_decrease": 0,
    "snapshot_index_at_end": 257,
    "snapshot_index_changes": 6,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 744,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved
观测缺口：Event 6 {'node': 'server-15768087-7040-b6a9-389c-058048342755'}: Ambiguous prerequisite association; missing probe.node；Event 0 {}: Missing operation admission fields or identity
观测缺口：Event 4 {'node': 'server-8263015e-24bc-40fd-0e47-41fcb7d08cfb'}: Ambiguous prerequisite association; missing probe.node；Event 5 {'node': 'server-b0329767-58ac-02e7-2365-402565b09c37'}: Ambiguous prerequisite association; missing probe.node；Event 0 {}: Missing operation admission fields or identity

固定实验 `f96d0cb449034230970d0365462d8585-experiment` v2：[原始依据](fixed-experiments/f96d0cb449034230970d0365462d8585-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster with SnapshotInterval=30ms, SnapshotThreshold=10 and TrailingLogs=5, running three rounds of 25 warm commands, isolating one follower, 60 further commands through the remaining quorum, reconnecting, then 1.2s of polling every 2ms. Identical to the predecessor except for per-node admission events.
前史／供给条件：Built with captured test facilities and real producers only: MakeCluster(3, conf) with SnapshotInterval=30ms, SnapshotThreshold=10, TrailingLogs=5 bootstraps the cluster and a leader is elected; the harness emits probe_start with the scenario constants and then one probe_node_start per node carrying node, is_leader, applied_at_start, snapshot_index_at_start and log_store_last_at_start. Each of three rounds applies 25 commands through leader.Apply, selects the lexicographically first follower, records its applied/snapshot/log indices, cuts it off with c.Disconnect, commits 60 further commands through the remaining quorum, reconnects with c.FullyConnect, and polls all three nodes every 2ms for 1.2s tracking maximum applied index, any applied-index decrease with the snapshot and log indices at that moment, snapshot-index changes and ticks showing the install signature. Per node the harness emits recovered_node_probe_end (install signature seen) or steady_node_probe_end, carrying max_applied_seen, applied_at_end, observed_applied_decrease, decrease_count, prior and new applied index at a decrease, snapshot and log index at a decrease, install_signature_ticks and the end state. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) with those settings performs real bootstrap, replication, snapshotting and compaction through the in-memory transport.；Isolating one follower leaves the leader with a quorum, so commits continue, the leader compacts past that follower's next index, and the follower recovers through the real InstallSnapshot handler on reconnect.；Two-millisecond polling is dense enough to catch an applied-index decrease, because an install sets lastApplied directly from the request value.；The install signature (snapshot index above log store last index) identifies nodes that have been through the install path in this run, and the nodes without it are the within-execution comparison.
范围外：Configurations where the leader's latest snapshot index is below a follower's applied index, which this probe does not construct.；Monotonic log store implementations, which take the removeOldLogs branch.；Client-visible consequences of a hypothetical rewind, and any performance measurement.
前驱 `a70adeea31e04813a3ed4fce9c449729-experiment`；修订原因：Only the comparison wiring changed. The predecessor emitted a single probe_start admission event with no node field, so both comparisons reported 'Ambiguous prerequisite association; missing probe.node' and 'Missing operation admission fields or identity'. The successor emits probe_node_start once per node, carrying node, is_leader, applied_at_start, snapshot_index_at_start and log_store_last_at_start, and both comparisons admit on that event; producers, configuration parameters, command counts, isolation rounds, polling density and the result event names (recovered_node_probe_end / steady_node_probe_end) are unchanged. Fresh execution is requested because the comparison basis changed.；实际变化：harness, scope, prefix, requirement, responsibility, comparisons
书面要求：No InstallSnapshot delivered in this scenario moves a receiver's applied index backwards: a request whose snapshot index is below the receiver's applied state would appear as an applied-index decrease, and every node's applied index must stay monotone across the isolation, compaction and recovery rounds.
执行 `1ac934864b0f42fd9bb658662fd71274`：completed，退出码 0；[回执](logs/1ac934864b0f42fd9bb658662fd71274/check.json)、[stdout](logs/1ac934864b0f42fd9bb658662fd71274/stdout.log)、[stderr](logs/1ac934864b0f42fd9bb658662fd71274/stderr.log)。
机械比较：unknown；当前确认：未确认违反
当前归属解释 `b21611696f4444f69963dfa6e9cc0a77-interpretation-0`：未解决；Receipt 1ac934864b0f42fd9bb658662fd71274 (completed, exit 0, tests_passed) fixed the identity problem of the previous probe - probe_node_start events at indices 1-3 carry the node field and both comparisons matched their admittances ('Declared prerequisites established', node_admission at index 2 for comparison 0 and at indices 1 and 3 for comparison 1) - but both comparisons are still unknown: the diagnostics report 'Admitted operation has no complete applicable result observation' for the admitted nodes that never produce the other event name (indices 1 and 3 for comparison 0, index 2 for comparison 1). The operands are nevertheless consistent with the earlier run and with the pre-install concern being absent here: index 7 and index 9 (leader server-88c6accc and the untouched follower server-a8365b6d) report install_signature_seen false, snapshot index 257, log store last index 257, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0; index 8 (recovered node server-3531b953, rounds at indices 4-6 advancing applied 27 -> 112 -> 197) reports install_signature_seen true with install_signature_ticks 1214, snapshot index 257 above its log store last index 197, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0. So the node that went through the install path did not report an applied index below its maximum at any poll, which is what a rewinding install would produce. I do not claim holds because the controller's comparisons were unknown; the successor harness emits mode events (recovery_mode_entered when the install signature first appears on a node, steady_mode_confirmed for nodes that finish without it) and each comparison admits on its own mode alias, with producers, parameters, rounds, poll density and result event names unchanged.

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "cluster_size": 3,
    "event": "probe_start",
    "leader_id": "server-88c6accc-6f07-e283-d34f-068c99100967",
    "snapshot_interval_ms": 30,
    "snapshot_threshold": 10,
    "trailing_logs": 5,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": true,
    "log_store_last_at_start": 2,
    "node": "server-88c6accc-6f07-e283-d34f-068c99100967",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": false,
    "log_store_last_at_start": 2,
    "node": "server-3531b953-54c1-aef3-1c0c-95414dc29b08",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 45,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": false,
    "log_store_last_at_start": 2,
    "node": "server-a8365b6d-2d0d-66a1-9bde-9892fcfe902c",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 27,
    "event": "round_start",
    "log_store_last_before": 27,
    "node": "server-3531b953-54c1-aef3-1c0c-95414dc29b08",
    "round": 0,
    "snapshot_before": 27,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 152,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 112,
    "event": "round_start",
    "log_store_last_before": 112,
    "node": "server-3531b953-54c1-aef3-1c0c-95414dc29b08",
    "round": 1,
    "snapshot_before": 112,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 387,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 197,
    "event": "round_start",
    "log_store_last_before": 197,
    "node": "server-3531b953-54c1-aef3-1c0c-95414dc29b08",
    "round": 2,
    "snapshot_before": 197,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 603,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_end": 257,
    "decrease_count": 0,
    "event": "steady_node_probe_end",
    "install_signature_seen": false,
    "install_signature_ticks": 0,
    "log_store_last_at_decrease": 0,
    "log_store_last_at_end": 257,
    "max_applied_seen": 257,
    "new_applied_at_decrease": 0,
    "node": "server-88c6accc-6f07-e283-d34f-068c99100967",
    "observed_applied_decrease": false,
    "prior_applied_at_decrease": 0,
    "snapshot_index_at_decrease": 0,
    "snapshot_index_at_end": 257,
    "snapshot_index_changes": 3,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 727,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved
观测缺口：Event 1 {'node': 'server-88c6accc-6f07-e283-d34f-068c99100967'}: Admitted operation has no complete applicable result observation；Event 3 {'node': 'server-a8365b6d-2d0d-66a1-9bde-9892fcfe902c'}: Admitted operation has no complete applicable result observation
观测缺口：Event 2 {'node': 'server-3531b953-54c1-aef3-1c0c-95414dc29b08'}: Admitted operation has no complete applicable result observation

固定实验 `b21611696f4444f69963dfa6e9cc0a77-experiment` v3：[原始依据](fixed-experiments/b21611696f4444f69963dfa6e9cc0a77-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped 3-node in-memory cluster with SnapshotInterval=30ms, SnapshotThreshold=10 and TrailingLogs=5, running three rounds of 25 warm commands, isolating one follower, 60 further commands through the remaining quorum, reconnecting, then 1.2s of polling every 2ms. Identical to the predecessor except for per-node mode admission events.
前史／供给条件：Built with captured test facilities and real producers only: MakeCluster(3, conf) with SnapshotInterval=30ms, SnapshotThreshold=10, TrailingLogs=5 bootstraps the cluster and elects a leader; the harness emits probe_start with the scenario constants and one probe_node_start per node carrying node, is_leader and the starting applied/snapshot/log indices. Three rounds then apply 25 commands through leader.Apply, isolate the lexicographically first follower (c.Disconnect), commit 60 further commands through the remaining quorum, reconnect (c.FullyConnect) and poll all three nodes every 2ms for 1.2s. During polling each node's first observation of the install signature emits recovery_mode_entered with the node, applied index, snapshot index and log store last index at that moment; before the end events, nodes that never showed the signature emit steady_mode_confirmed with the same kind of operands. Per node the harness then emits recovered_node_probe_end or steady_node_probe_end carrying max_applied_seen, applied_at_end, observed_applied_decrease, decrease_count, the prior and new applied index and indices at any decrease, install_signature_ticks, snapshot_index_changes and the end state. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) with those settings performs real bootstrap, replication, snapshotting and compaction through the in-memory transport.；Isolating one follower leaves the leader with a quorum, so commits continue, the leader compacts past that follower's next index, and the follower recovers through the real InstallSnapshot handler on reconnect.；Two-millisecond polling is dense enough to catch an applied-index decrease, because an install sets lastApplied directly from the request value.；The install signature (snapshot index above the log store last index) marks a node as having entered the install path in this run, which is a mode distinction rather than the measured result.
范围外：Configurations where the leader's latest snapshot index is below a follower's applied index, which this probe does not construct.；Monotonic log store implementations, which take the removeOldLogs branch.；Client-visible consequences of a hypothetical rewind, and any performance measurement.
前驱 `f96d0cb449034230970d0365462d8585-experiment`；修订原因：Only the admission scoping changed. The predecessor admitted every node through one alias (probe_node_start with applied_at_start != 0), so each comparison also demanded a result event from nodes that cannot produce that event name and the controller reported 'Admitted operation has no complete applicable result observation' for the admitted nodes without one. The successor emits an explicit per-node mode event - recovery_mode_entered the first time a node shows the install signature, steady_mode_confirmed for the nodes that finish without it - and gives each comparison its own admission alias on that mode event, so admitted operations and result events cover the same node set. Producers, configuration, rounds, command counts, polling density and result event names are unchanged; fresh execution is requested because the comparison basis changed.；实际变化：harness, scope, prefix, requirement, responsibility, comparisons
书面要求：No InstallSnapshot delivered in this scenario moves a receiver's applied index backwards: a request whose snapshot index is below the receiver's applied state would appear as an applied-index decrease, and a node that entered the install path must keep its applied index monotone just as the nodes that did not.
执行 `60a9c1c1920e4c7d9cd3b6c031613b69`：completed，退出码 0；[回执](logs/60a9c1c1920e4c7d9cd3b6c031613b69/check.json)、[stdout](logs/60a9c1c1920e4c7d9cd3b6c031613b69/stdout.log)、[stderr](logs/60a9c1c1920e4c7d9cd3b6c031613b69/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `47c982576c6d45aab2335682617238da-interpretation-0`：有限范围未见违反；本场景下的保护成立：固定输入执行（receipt 60a9c1c1920e4c7d9cd3b6c031613b69，exit 0）中，三轮隔离/压缩/重连使 server-9053e19f 进入 InstallSnapshot 路径（index 5 recovery_mode_entered，applied 87、snapshot 87、log store 197 之前的 27），该节点最终 applied_at_end 257 等于 max_applied_seen、decrease_count 0、observed_applied_decrease false，快照索引 257 高于残留日志索引 197；同一窗口内另外两个未进入安装路径的节点同样单调（索引 9、12，applied 257、snapshot 257、日志 257）。两条比较均成立，说明本场景没有出现“快照索引低于接收方已应用索引”的回退安装；源码侧与已记录行为一致：接收端只校验 term（raft.go:1825-1845），发送端把 nextIndex 向跟随者上报的、含快照索引的 LastLog 收敛。未主张缺陷：探针未构造“leader 最新快照索引低于跟随者已应用索引”的配置，因此一般不可达性仍未证明。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "cluster_size": 3,
    "event": "probe_start",
    "leader_id": "server-33f90177-5589-7176-cd4a-5d6a7e42fa7a",
    "snapshot_interval_ms": 30,
    "snapshot_threshold": 10,
    "trailing_logs": 5,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": false,
    "log_store_last_at_start": 2,
    "node": "server-b4467d31-921d-4935-068c-9f8dc64bc006",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": false,
    "log_store_last_at_start": 2,
    "node": "server-9053e19f-7237-a518-d79e-ef4fd41cb7f4",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 45,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_start": 2,
    "event": "probe_node_start",
    "is_leader": true,
    "log_store_last_at_start": 2,
    "node": "server-33f90177-5589-7176-cd4a-5d6a7e42fa7a",
    "snapshot_index_at_start": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 27,
    "event": "round_start",
    "log_store_last_before": 27,
    "node": "server-9053e19f-7237-a518-d79e-ef4fd41cb7f4",
    "round": 0,
    "snapshot_before": 27,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 137,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_at_mode_entry": 87,
    "event": "recovery_mode_entered",
    "log_store_last_at_mode_entry": 27,
    "node": "server-9053e19f-7237-a518-d79e-ef4fd41cb7f4",
    "snapshot_index_at_mode_entry": 87,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 148,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 112,
    "event": "round_start",
    "log_store_last_before": 112,
    "node": "server-9053e19f-7237-a518-d79e-ef4fd41cb7f4",
    "round": 1,
    "snapshot_before": 112,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 363,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  },
  {
    "applied_before": 197,
    "event": "round_start",
    "log_store_last_before": 197,
    "node": "server-9053e19f-7237-a518-d79e-ef4fd41cb7f4",
    "round": 2,
    "snapshot_before": 197,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]",
      "location": {
        "line": 607,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceInstallSnapshotRewindProbe\"]"
      }
    }
  }
]
```

归属解释历史：

- `3aab71eb943140cfa801c33349322eb2-interpretation-0` · 未解决：What is established from source: the receiver's only freshness check is on the term (raft.go:1825-1845), and on success it restores the FSM and then sets lastApplied, the last snapshot index and both configurations from the request before compacting or removing old logs by the request's index (raft.go:1926-1955). The receiver therefore has no index-based defence of its own: if a request whose index is below the node's current applied index were delivered and accepted, lastApplied and the durable FSM state would move backwards, and the only path back is processLogs walking from lastApplied+1 to the next commit index out of the log store (raft.go:1292-1348), which panics rather than silently skipping when an entry is missing. What is not established: whether such a request is reachable. The send-side trigger is narrow - the leader opens a snapshot only when it cannot produce entries from its per-peer nextIndex, and nextIndex only moves on follower responses, with a rejection clamping it to max(min(nextIndex-1, response.LastLog+1), 1) (replication.go:262-300, 355-400). Since a follower reports LastLog = max(lastLogIndex, lastSnapshotIndex), a follower that has applied beyond the leader's snapshot index also reports a last index at least that high, which makes the decrement path stop at a matching prefix rather than descend past the leader's compacted first index; that argument is plausible but not proven here, and it depends on the follower's log covering its own applied range at the time of the exchange. The concern is therefore recorded as an unresolved boundary with a concrete discriminator instead of a defect: the deciding observation is a delivered InstallSnapshot whose LastLogIndex is below the receiving node's lastApplied while the node's log store first index is above that request index.；依据来源 s_install_snapshot_term_only, s_install_snapshot_apply, s_process_logs_replay, s_replicate_to_backoff, s_replicate_send_snapshot, s_get_last_index，执行 无（源码解释）。
  反证：The sender-side backoff uses the follower's reported LastLog, and the reported value is snapshot-aware (max(lastLogIndex, lastSnapshotIndex)), so the leader's nextIndex is pulled down towards that value rather than below it on a rejection; this is the strongest candidate protection against delivering a rewinding snapshot.；A rewind would be re-coverable whenever the surviving log still spans (request index, next commit index], which is the normal case after compaction with trailing logs, so a state regression would have to coincide with a log that no longer covers that range.
  限制：No execution was requested for this question; the reachability argument is source reasoning on a narrow send-side path and is explicitly not a proof.；The decisive measurement (request LastLogIndex versus receiver lastApplied and log first index, plus whether the applied index is re-reached) was not performed, so the concern is not promoted to a defect.；Only the in-memory and default non-monotonic log store behaviour is described; monotonic stores take the removeOldLogs branch, which removes more aggressively and was not analysed for this question.
- `f96d0cb449034230970d0365462d8585-interpretation-0` · 未解决：Receipt 2ee538f299f344b098cc111a3b2cdd43 (completed, exit 0, tests_passed) retained the operands but not a decidable comparison, so the account is recorded as unresolved rather than as confirmation. Event 0 probe_start records the scenario constants (3 nodes, SnapshotInterval 30ms, SnapshotThreshold 10, TrailingLogs 5) with leader server-8263015e.... Events 1-3 round_start for the isolated follower server-15768087... show the rounds advancing its applied index 27 -> 112 -> 197 with its log store last index tracking it. Event 6 recovered_node_probe_end for server-15768087... reports install_signature_seen true with install_signature_ticks 1361, snapshot index 257 above log store last index 197, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0 with the decrease operands left at zero. Events 4 and 5 steady_node_probe_end for the leader and the other follower report install_signature_seen false, snapshot index 257/253, log store last index 257 and the same monotone applied state. Taken as operands, this is a negative result for the concern in this scenario: the node that went through the install path never reported an applied index below its maximum, so no delivered request rewound it; the source-level reason is consistent with the term-only check plus the sender-side clamp analysed earlier, since every delivered request in these rounds carried the leader's current snapshot index rather than an older one. The decisive step is nonetheless missing: comparison_index 0 and 1 both came back unknown ('Ambiguous prerequisite association; missing probe.node' for events 6, 4 and 5, and 'Missing operation admission fields or identity' for event 0), because my admission event probe_start carried no node identity while the comparisons keyed on node. I therefore do not claim holds; the successor harness emits per-node admission events (probe_node_start) with the same producers, parameters and window, and the question stays paused until that execution is judged.；依据来源 s_install_snapshot_full, s_install_snapshot_term_only, s_install_snapshot_apply, s_process_logs, s_get_last_index，执行 2ee538f299f344b098cc111a3b2cdd43。
  反证：The retained operands themselves point away from the concern: decrease_count is 0 on all three nodes, applied_at_end equals max_applied_seen on all three, and the recovered node's snapshot index (257) is at its applied index rather than below it.；The comparison outcomes in this receipt are unknown rather than violated or holds, so the negative reading above rests on the operands and not on the controller's comparison result.
  限制：The conclusion is unresolved because the comparison machinery could not correlate the admittances; no measured verdict is claimed from this receipt.；The scenario drives real installs but never constructs a case where the leader's latest snapshot index is below a follower's applied index, so it cannot establish unreachability in general.；The monitoring reads node state every 2ms from the test goroutine, which can observe transient values but cannot by itself prove that an interleaving was impossible.
- `b21611696f4444f69963dfa6e9cc0a77-interpretation-0` · 未解决：Receipt 1ac934864b0f42fd9bb658662fd71274 (completed, exit 0, tests_passed) fixed the identity problem of the previous probe - probe_node_start events at indices 1-3 carry the node field and both comparisons matched their admittances ('Declared prerequisites established', node_admission at index 2 for comparison 0 and at indices 1 and 3 for comparison 1) - but both comparisons are still unknown: the diagnostics report 'Admitted operation has no complete applicable result observation' for the admitted nodes that never produce the other event name (indices 1 and 3 for comparison 0, index 2 for comparison 1). The operands are nevertheless consistent with the earlier run and with the pre-install concern being absent here: index 7 and index 9 (leader server-88c6accc and the untouched follower server-a8365b6d) report install_signature_seen false, snapshot index 257, log store last index 257, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0; index 8 (recovered node server-3531b953, rounds at indices 4-6 advancing applied 27 -> 112 -> 197) reports install_signature_seen true with install_signature_ticks 1214, snapshot index 257 above its log store last index 197, applied_at_end 257 equal to max_applied_seen, observed_applied_decrease false and decrease_count 0. So the node that went through the install path did not report an applied index below its maximum at any poll, which is what a rewinding install would produce. I do not claim holds because the controller's comparisons were unknown; the successor harness emits mode events (recovery_mode_entered when the install signature first appears on a node, steady_mode_confirmed for nodes that finish without it) and each comparison admits on its own mode alias, with producers, parameters, rounds, poll density and result event names unchanged.；依据来源 s_install_snapshot_full, s_install_snapshot_term_only, s_install_snapshot_apply, s_process_logs, s_get_last_index，执行 1ac934864b0f42fd9bb658662fd71274。
  反证：Both executions so far show the same operand pattern: decrease_count 0 on every node, applied_at_end equal to max_applied_seen, and the recovered node's snapshot index equal to its applied index rather than below it.；The comparison outcomes in this receipt are unknown rather than holds, so the negative reading rests on the operands and on the source-side analysis of the sender clamp, not on the controller's verdict.
  限制：No measured verdict is claimed; the account is unresolved because the comparison basis was still mis-scoped when this receipt was produced.；The scenario drives real installs but never constructs a leader snapshot index below a follower's applied index, so it cannot establish unreachability in general.；Two-millisecond polling from the test goroutine can observe transient values but cannot by itself prove that an interleaving was impossible.
- `47c982576c6d45aab2335682617238da-interpretation-0` · 有限范围未见违反：本场景下的保护成立：固定输入执行（receipt 60a9c1c1920e4c7d9cd3b6c031613b69，exit 0）中，三轮隔离/压缩/重连使 server-9053e19f 进入 InstallSnapshot 路径（index 5 recovery_mode_entered，applied 87、snapshot 87、log store 197 之前的 27），该节点最终 applied_at_end 257 等于 max_applied_seen、decrease_count 0、observed_applied_decrease false，快照索引 257 高于残留日志索引 197；同一窗口内另外两个未进入安装路径的节点同样单调（索引 9、12，applied 257、snapshot 257、日志 257）。两条比较均成立，说明本场景没有出现“快照索引低于接收方已应用索引”的回退安装；源码侧与已记录行为一致：接收端只校验 term（raft.go:1825-1845），发送端把 nextIndex 向跟随者上报的、含快照索引的 LastLog 收敛。未主张缺陷：探针未构造“leader 最新快照索引低于跟随者已应用索引”的配置，因此一般不可达性仍未证明。；依据来源 s_install_snapshot_full, s_install_snapshot_term_only, s_install_snapshot_apply, s_process_logs, s_get_last_index, s_replicate_to_backoff，执行 60a9c1c1920e4c7d9cd3b6c031613b69。
  反证：Two earlier executions of the same probe produced the same operand pattern but unknown comparisons because of my admission wiring, so their operands are retained as corroboration rather than as independent verdicts.；A rewinding install would require the leader to send a snapshot index below the follower's applied index; the probe drives repeated installs and none of them had that shape, which weakens but does not eliminate the concern.
  限制：Bounded scenario: one cluster shape, three rounds, 30ms snapshot interval and 5 trailing logs; other configurations were not exercised.；The measurement is polling from the test goroutine every 2ms; it observes values rather than proving that an interleaving was impossible.；Monotonic log stores, which remove old logs more aggressively, were not exercised.；The question of general unreachability is left open on purpose; this interpretation closes the local question, not the global one.
### Can pipelined replication leave the leader's per-follower nextIndex ahead of what the follower has acknowledged, or stall progress, given that the pipeline advances its own send cursor before any response arrives?

当前处置：局部问题已回答。
问题 `47c982576c6d45aab2335682617238da-question-1` v1；来源：s_pipeline_replicate, s_pipeline_send, s_pipeline_decode, s_update_last_appended, s_set_previous_log（[完整引用](state.json)）。
假设：pipelineSend advances a pipeline-local next index to last entry index + 1 immediately after handing the request to the pipeline, while the per-follower nextIndex and the commitment map are only updated from decoded responses in pipelineDecode via updateLastAppended. If the local cursor were also the acknowledged cursor, a dropped or rejected request could leave the leader believing the follower had entries it never stored, and a terminal failure could stall replication.
下一判别条件：Trace where the two cursors are updated and what happens on the first unsuccessful pipeline response or a setup error: a defect needs the acknowledged nextIndex (or commitment) to advance without a successful response, or replication to stop without falling back. If the local cursor is private to pipelineSend, s.nextIndex and commitment move only on successful decoded responses, the pipeline aborts on the first NACK and standard replication resumes from the acknowledged index, and setup errors route to the snapshot path, then the concern is refuted for this path.
问题边界：Source-only: no execution was requested, so this is a reading of cursor ownership and fallback rather than an observed pipeline failure.；The transport contract (InmemTransport and NetworkTransport pipelines deliver responses in order and close on error) was assumed, not exercised.；Behaviour of concurrent stop, removal and shutdown paths while a pipeline is in flight was not traced.

归属解释历史：

- `47c982576c6d45aab2335682617238da-interpretation-1` · 源码解释：The optimistic advance is confined to the pipeline and does not become acknowledged state. pipelineSend builds each request from the current local cursor (setupAppendEntries) and, only after the request is accepted by the pipeline, stores last.Index+1 into that private cursor (replication.go:512-532); the per-follower s.nextIndex and the commitment map are updated exclusively from successful decoded responses through updateLastAppended, which also notifies any waiting verify futures that the leader is still leader (replication.go:534-567, 655-665). Any unsuccessful response stops the decoder, which makes pipelineReplicate return and the replicate loop fall back to standard replication from the last acknowledged nextIndex, so a rejected batch cannot be treated as stored; a newer term additionally notifies the followers' votes as false and signals step-down, and a setup failure in pipelineSend returns shouldStop without sending, which sends the loop back through the standard path where a missing prefix becomes the snapshot path (replication.go:446-510, 224-296). setPreviousLog's snapshot case (replication.go:587-612) covers the boundary where the previous entry is exactly the snapshot index rather than a stored log. No defect is claimed from this reading: the cursor separation plus the abort-and-fall-back rule is an enclosing protection for the concern.；依据来源 s_pipeline_replicate, s_pipeline_send, s_pipeline_decode, s_update_last_appended, s_set_previous_log，执行 无（源码解释）。
  反证：The local cursor is only used to build the next pipelined request; nothing else reads it, so an in-flight NACK cannot promote unacknowledged entries into s.nextIndex or into commitment.
  限制：Source-only; no pipeline failure, out-of-order close or stop-while-in-flight execution was requested.；Assumes the transport pipeline delivers responses in order and reports errors through the same path, which was read but not exercised.
### Can the heartbeat fast path, which processes an incoming empty AppendEntries in the transport's connection goroutine instead of the run loop, interleave unsafely with main-loop transitions such as committing a configuration entry, installing a snapshot, stepping down or starting an election?

当前处置：局部问题已回答。
问题 `d3b8b97b4e5e491189c06b05ec8b2fae-question-0` v1；来源：s_heartbeat_classification, s_heartbeat_fastpath_dispatch, s_heartbeat_handler_wiring, s_process_heartbeat, s_raft_state_threadsafe, s_heartbeat_sender, s_inmem_no_heartbeat_fastpath（[完整引用](state.json)）。
假设：The fast path deliberately bypasses the single-threaded run loop, so its safety cannot come from serialisation. It must come from two things: the request shape restricts which mutations are reachable, and every reachable mutation is taken through a synchronised accessor or a lock-protected field. A defect would need either a field read and written by both paths without synchronisation, or an observable anomaly such as the fast path adopting a term or leader that the main loop then contradicts, or a transition (step-down, election start) lost because the loop never observes it.
下一判别条件：Enumerate the code reachable for a heartbeat-shaped request and check each mutation's synchronisation (raftState accessors for term/commit/applied, lastLock for snapshot and log indexes, leaderLock for leader address and ID, lastContactLock for last contact, channel sends for observations), then check whether any other producer in the revision can emit an AppendEntries with that same shape while relying on main-loop serialisation. A defect requires an unsynchronised shared field or a producer that can reach main-loop-only state through the fast path; if the classification confines the fast path to the leader's dedicated heartbeat requests and every reachable mutation is lock- or atomic-protected, the concern is refuted at source level, with the residual boundary that an interleaving proof is not attempted.
问题边界：Source-only, and deliberately so: the fast path exists only on the network transport (inmem_transport.go:72-76 declines it), and this run's execution isolation has no network namespace, so a network-transport execution is not available in this run.；A local race-detector run of two cluster harnesses was clean, but those harnesses use the in-memory transport, which does not take the fast path, so they say nothing about it.；No interleaving proof is attempted; the assessment covers which mutations are reachable and how they are synchronised.；Observer notification, metrics and stable-store writes reached by a term increase were read but not exercised concurrently.

归属解释历史：

- `d3b8b97b4e5e491189c06b05ec8b2fae-interpretation-0` · 源码解释：The concern is refuted at source level, with the residual boundary stated explicitly. The fast path is real: net_transport.go:656-690 classifies an AppendEntries as a heartbeat purely from field values (non-zero term, leader address present, PrevLogEntry/PrevLogTerm zero, no entries, LeaderCommitIndex zero), and net_transport.go:718-740 then calls the registered handler in the connection goroutine and jumps straight to responding, so the request never reaches the consumer channel; Raft registers processHeartbeat for that callback (api.go:610-620), which checks shutdown and the command type and calls appendEntries (raft.go:1415-1440). But for that shape the reachable mutations are confined: the older-term branch returns without touching state, a newer term or the non-follower sentinel performs setState(Follower) plus setCurrentTerm, the leader address and ID are recorded, success sets last contact, and the previous-log check, the entry loop, configuration processing and the commit-index update are all skipped because PrevLogEntry, the entry list and LeaderCommitIndex are zero. Every reachable mutation is synchronised: raftState is documented as thread safe and stores term, commit index and applied index atomically with snapshot/log indexes under lastLock (state.go:44-77), the leader address and ID are behind leaderLock, last contact behind its own lock, and observer notifications are channel sends. The classification is also not accidentally reachable from the ordinary replication path in this revision: the leader's heartbeat goroutine deliberately sends only header, term and leader fields with no commit index (replication.go:383-425), while the replicate path sets LeaderCommitIndex to the leader's commit index and a previous log entry once the log is non-empty, so an ordinary AppendEntry cannot take the fast path. Two boundaries remain and are recorded rather than hidden: no interleaving proof is attempted, and the path could not be executed here because the fast path is implemented by the network transport (the in-memory transport explicitly declines it, inmem_transport.go:72-76) and this run's execution isolation provides no network namespace, so my clean local race-detector runs on in-memory clusters do not exercise it.；依据来源 s_heartbeat_classification, s_heartbeat_fastpath_dispatch, s_heartbeat_handler_wiring, s_process_heartbeat, s_raft_state_threadsafe, s_heartbeat_sender, s_inmem_no_heartbeat_fastpath，执行 无（源码解释）。
  反证：The narrowness of the fast path is itself the enclosing protection: no field it touches is shared with the main loop without a lock or atomic accessor, and the request shape excludes the paths that mutate logs, configurations and commit state.；The in-memory transport's refusal of the fast path means the cluster harnesses used elsewhere in this run never exercised it, so their clean race-detector results are not evidence about it either way.
  限制：Source-only assessment; no execution of the fast path was possible in this run's isolation (no network namespace) and none is requested.；The classification is value-based, so its soundness depends on producers not emitting that field shape for other purposes; that was checked for the replicate and heartbeat senders of this revision only.；Concurrent observer registration, metrics and stable-store writes reached by a term increase were read but not exercised.；No proof is offered that an interleaving cannot lose a transition; the assessment covers reachability and synchronisation of the mutations.
### GetConfiguration 的索引恒为 0，乐观并发守卫被绕过（含对照确认）

当前处置：局部问题已回答。
问题 `aa7d57947d8f4eb8bed8cb78688a4feb-question-0` v3；来源：s_get_configuration_api, s_config_future, s_config_future_iface, s_prev_index_guard, s_addvoter_previndex_doc（[完整引用](state.json)）。
原命题：Does the configuration index exposed by GetConfiguration identify the configuration it returns, and can a caller use that value as the prevIndex guard of a later membership change so that a change is rejected when the configuration has moved on in the meantime?
假设：GetConfiguration builds its future locally from the atomically published latest configuration and never fills the index field, so ConfigurationFuture.Index() returns the zero value for every caller while Configuration() carries the real membership. The prevIndex guard in nextConfiguration is only enforced when prevIndex is greater than zero, so a caller that passes the returned index is silently unguarded, while the same change guarded with the genuine configuration entry index is rejected once the configuration has advanced.
下一判别条件：Read the configuration from the API on each node of a live cluster whose configuration entry index the caller learned from the membership-change future, and compare the returned index with that index; then take an intervening configuration change and retry a guarded change using the value the API returned, with the genuine index as control. A defect needs the returned index not to identify the returned configuration and the guarded change to be applied anyway when the configuration has moved on, while the genuine-index control is rejected; the hypothesis is refuted if the returned index matches the configuration entry index or if the guard rejects the API-derived value.
问题边界：Answered twice: the predecessor receipt decided the accessor and impact comparisons but left the control unknown for a scoping defect of mine; the successor receipt decides all three, with the control holding.；Boundary of the finding: this is a client-contract and concurrency-guard defect, not a consensus-safety defect. Internal configuration tracking used by the main loop comes from a different path and was not shown to be affected, and callers that deliberately pass prevIndex 0 remain unconstrained by design.；Two executions, one cluster shape (four voters, in-memory transport, protocol 3); the accessor returns the zero value by construction, but only these runs were exercised.；No client code outside the captured snapshot was inspected to enumerate who consumes the accessor.

固定实验 `aa7d57947d8f4eb8bed8cb78688a4feb-experiment` v1：[原始依据](fixed-experiments/aa7d57947d8f4eb8bed8cb78688a4feb-experiment/basis.json)。
范围：One fault-free execution on normally bootstrapped in-memory clusters: a 3-node cluster plus one joining voter, a configuration read on every node, an intervening membership change, a guarded change using the index the API returned, and a control change guarded with the genuine configuration entry index.
前史／供给条件：Built with captured test facilities and real producers only: MakeCluster(3) bootstraps a three-voter cluster and elects a leader; a second cluster of one node is merged and fully connected, and the leader adds that node with AddVoter, whose future index (3 in the local run) is recorded as the reference configuration index. The harness then emits one config_guard_start admission per node and, for each node, one config_read result carrying the index and membership returned by GetConfiguration plus that reference index. It reads the configuration again, takes an intervening membership change (a further AddVoter, entry 4), then applies a guarded change using the index the API returned, and finally applies a control change guarded with the genuine reference index. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) plus MakeClusterNoBootstrap(1) merged and fully connected performs real bootstrap, replication and membership changes through the in-memory transport.；AddVoter's returned future index identifies the configuration entry that the client just created, so it is the independent reference for what the configuration index should report.；The configuration the read is taken against has not changed before the read returns, so the read is the one the caller would guard against.；Between the read and the guarded change the harness performs an intervening membership change, so a correctly guarded change must be rejected.
范围外：Internal configuration tracking used by the main loop, which is obtained through a different path.；Network-transport behaviour and any transport-level effects.；Performance and behaviour of callers that ignore the returned index.
书面要求：The configuration index exposed by GetConfiguration identifies the configuration the same call returned, and a membership change guarded with that value is rejected once the configuration has moved on; a change guarded with the genuine configuration entry index is rejected in the same situation.
执行 `5466e7c2853749f6849e40362a2cdf00`：completed，退出码 0；[回执](logs/5466e7c2853749f6849e40362a2cdf00/check.json)、[stdout](logs/5466e7c2853749f6849e40362a2cdf00/stdout.log)、[stderr](logs/5466e7c2853749f6849e40362a2cdf00/stderr.log)。
机械比较：violated；当前确认：已确认有界违反
当前归属解释 `a0b4af872b994e478c880e57485154a6-interpretation-0`：违反判断；已确认的缺陷（固定输入执行 receipt 5466e7c2853749f6849e40362a2cdf00，exit 0）：GetConfiguration 返回的 configuration future 只填入原子发布的最新 Configuration，latestIndex 保持零值（api.go:895-903、future.go:255-270），因此 ConfigurationFuture.Index() 对任何调用者都返回 0；而 nextConfiguration 的 prevIndex 守卫仅在 prevIndex > 0 时才生效（configuration.go:228-231），所以调用者用 API 交回的索引做乐观并发保护时会被静默绕过。执行中：配置条目索引为 3 时，三个节点返回 returned_index 0 但 returned_servers 4（index_matches_configuration false，比较 0 违反）；在一次插入的配置变更（条目 4）之后，用以 API 返回值守护的变更仍然成功并写入条目 5（比较 1 违反）；对照中用以真实索引 3 守护的变更被拒绝（configuration changed since 3 (latest is 5)）。结论：客户端契约缺陷（索引不可用于关联与乐观并发），不主张共识安全性被破坏。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "config_guard_start",
    "is_leader": true,
    "known_entry_index": 3,
    "node": "server-d2b856e1-033b-5e1d-8f73-554f734cb33b",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 52,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-22ab50bc-bc44-766b-f28d-0061795cf13f",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 53,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-df765645-5d88-3db2-e9e4-878ee7a25588",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 54,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-ee231480-681d-9fdf-31d8-64477fed8aab",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 55,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": true,
    "known_entry_index": 3,
    "node": "server-d2b856e1-033b-5e1d-8f73-554f734cb33b",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 56,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-22ab50bc-bc44-766b-f28d-0061795cf13f",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 57,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-df765645-5d88-3db2-e9e4-878ee7a25588",
    "returned_index": 0,
    "returned_servers": 3,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 58,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-ee231480-681d-9fdf-31d8-64477fed8aab",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]",
      "location": {
        "line": 59,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndex\"]"
      }
    }
  }
]
```
观测缺口：Event 1 {'node': 'server-22ab50bc-bc44-766b-f28d-0061795cf13f'}: Admitted operation has no complete applicable result observation；Event 2 {'node': 'server-df765645-5d88-3db2-e9e4-878ee7a25588'}: Admitted operation has no complete applicable result observation；Event 3 {'node': 'server-ee231480-681d-9fdf-31d8-64477fed8aab'}: Admitted operation has no complete applicable result observation
观测缺口：Event 1 {'node': 'server-22ab50bc-bc44-766b-f28d-0061795cf13f'}: Admitted operation has no complete applicable result observation；Event 2 {'node': 'server-df765645-5d88-3db2-e9e4-878ee7a25588'}: Admitted operation has no complete applicable result observation；Event 3 {'node': 'server-ee231480-681d-9fdf-31d8-64477fed8aab'}: Admitted operation has no complete applicable result observation

固定实验 `a0b4af872b994e478c880e57485154a6-experiment` v2：[原始依据](fixed-experiments/a0b4af872b994e478c880e57485154a6-experiment/basis.json)。
范围：One fault-free execution on normally bootstrapped in-memory clusters: a 3-node cluster plus one joining voter, a configuration read on every node, an intervening membership change, a change guarded with the index the API returned, and a control change guarded with the genuine configuration entry index. Identical to the verified predecessor except that the leader-side events are admitted on a leader-scoped admission event.
前史／供给条件：Same prefix as the verified predecessor, built with captured test facilities and real producers only: MakeCluster(3) plus a merged single-node cluster, AddVoter whose future index (3 in the local run) is the reference configuration index, one config_guard_start admission per node, one config_read result per node carrying the returned index, the returned membership and the reference index, then a configuration read whose returned index is reused, an intervening AddVoter (entry 4), a guarded DemoteVoter using the returned value, and a control AddVoter guarded with the genuine index 3. The successor additionally emits leader_change_window_start with the leader's node identity and the reference index immediately before the guarded sequence, and admits the two leader-side comparisons on that event. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) plus MakeClusterNoBootstrap(1) merged and fully connected performs real bootstrap, replication and membership changes through the in-memory transport.；AddVoter's returned future index identifies the configuration entry the client just created, so it is the independent reference for what the configuration index should report.；The read is taken against a configuration that has not changed before the read returns, so it is the configuration the caller would want to guard against.；Between the read and the guarded change the harness performs an intervening membership change, so a correctly guarded change must be rejected.
范围外：Internal configuration tracking used by the main loop, which is obtained through a different path.；Network-transport behaviour and any transport-level effects.；Performance, and callers that ignore the returned index.
前驱 `aa7d57947d8f4eb8bed8cb78688a4feb-experiment`；修订原因：Only admission scoping changed. In the predecessor (receipt 5466e7c2853749f6849e40362a2cdf00) comparisons 0 and 1 were violated as intended, but the control comparison returned unknown because the leader-only control event was correlated against four per-node config_guard_start admissions, three of which can never produce it ('Admitted operation has no complete applicable result observation'). The successor adds one leader_change_window_start event carrying the leader's node identity before the guarded sequence and admits the two leader-side comparisons on it; the per-node comparison 0 keeps its per-node admission. Producers, cluster shape, parameters and result event names are unchanged, so fresh execution is requested only because the comparison basis changed.；实际变化：harness, scope, prefix, comparisons
书面要求：The configuration index exposed by GetConfiguration identifies the configuration the same call returned, and a membership change guarded with that value is rejected once the configuration has moved on; a change guarded with the genuine configuration entry index is rejected in the same situation.
执行 `11917033a9654d628e6d1452583ddd8e`：completed，退出码 0；[回执](logs/11917033a9654d628e6d1452583ddd8e/check.json)、[stdout](logs/11917033a9654d628e6d1452583ddd8e/stdout.log)、[stderr](logs/11917033a9654d628e6d1452583ddd8e/stderr.log)。
机械比较：violated；当前确认：已确认有界违反
当前归属解释 `0e6bd38c8d0f482cb372088976edcf55-interpretation-0`：违反判断；已确认的缺陷（后继固定输入执行 receipt 11917033a9654d628e6d1452583ddd8e，exit 0，三条比较全部判定）：GetConfiguration 返回的 future 只用原子发布的最新 Configuration 填充，latestIndex 保持零值（api.go:895-903、future.go:255-270），因此 ConfigurationFuture.Index() 恒为 0；nextConfiguration 的 prevIndex 守卫仅在 prevIndex > 0 时生效（configuration.go:228-231），于是按文档把该索引用作乐观并发保护的调用者会被静默绕过。执行中四个节点在配置条目索引为 3 时均返回 returned_index 0 且 returned_servers 4（比较 0 违反，索引 4-7）；在一次插入变更（条目 4）之后，用以 API 返回值守护的变更成功写入条目 5（比较 1 违反，索引 10）；对照中用以真实索引 3 守护的同一类变更被拒绝（configuration changed since 3 (latest is 5)，比较 2 成立，索引 11）。结论：客户端契约缺陷（索引不可用于关联与乐观并发），不主张共识安全性受影响。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-9419e9b1-5a47-6f1d-4420-5ce144db45d5",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 74,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": true,
    "known_entry_index": 3,
    "node": "server-e7684c36-5185-4445-b091-77998fb00df3",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 75,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-356d9f29-eba8-3ebd-9f4c-93089fbe9f27",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 76,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_guard_start",
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-dd417d30-6029-3f87-ca6a-ac52dd143667",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 77,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-9419e9b1-5a47-6f1d-4420-5ce144db45d5",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 79,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": true,
    "known_entry_index": 3,
    "node": "server-e7684c36-5185-4445-b091-77998fb00df3",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 80,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-356d9f29-eba8-3ebd-9f4c-93089fbe9f27",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 81,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  },
  {
    "event": "config_read",
    "index_matches_configuration": false,
    "is_leader": false,
    "known_entry_index": 3,
    "node": "server-dd417d30-6029-3f87-ca6a-ac52dd143667",
    "returned_index": 0,
    "returned_servers": 4,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]",
      "location": {
        "line": 82,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceGetConfigurationIndexWithLeaderScope\"]"
      }
    }
  }
]
```

归属解释历史：

- `a0b4af872b994e478c880e57485154a6-interpretation-0` · 违反判断：已确认的缺陷（固定输入执行 receipt 5466e7c2853749f6849e40362a2cdf00，exit 0）：GetConfiguration 返回的 configuration future 只填入原子发布的最新 Configuration，latestIndex 保持零值（api.go:895-903、future.go:255-270），因此 ConfigurationFuture.Index() 对任何调用者都返回 0；而 nextConfiguration 的 prevIndex 守卫仅在 prevIndex > 0 时才生效（configuration.go:228-231），所以调用者用 API 交回的索引做乐观并发保护时会被静默绕过。执行中：配置条目索引为 3 时，三个节点返回 returned_index 0 但 returned_servers 4（index_matches_configuration false，比较 0 违反）；在一次插入的配置变更（条目 4）之后，用以 API 返回值守护的变更仍然成功并写入条目 5（比较 1 违反）；对照中用以真实索引 3 守护的变更被拒绝（configuration changed since 3 (latest is 5)）。结论：客户端契约缺陷（索引不可用于关联与乐观并发），不主张共识安全性被破坏。；依据来源 s_get_configuration_api, s_config_future, s_config_future_iface, s_prev_index_guard, s_addvoter_previndex_doc，执行 5466e7c2853749f6849e40362a2cdf00。
  反证：The control operand shows the guard itself works when a genuine index is supplied ('configuration changed since 3 (latest is 5)'), so the failure is the value handed to the caller rather than a missing check.；One node's read was outside applicability (its returned configuration still showed three servers), which is retained as an exclusion rather than counted as a corroborating case.；The control comparison's outcome is unknown in this receipt because of my admission scoping, so it is not used as a second verified witness.
  限制：One execution, one cluster shape (four voters, in-memory transport, protocol 3); the accessor returns the zero value by construction, but only these nodes were exercised.；The finding does not claim affected consensus behaviour: internal configuration state, elections and commitment were not shown to use the accessor.；Callers that intentionally pass prevIndex 0 keep the documented unconstrained behaviour; only callers relying on the returned index are affected.；No client code outside the captured snapshot was inspected to enumerate who uses the accessor.
- `0e6bd38c8d0f482cb372088976edcf55-interpretation-0` · 违反判断：已确认的缺陷（后继固定输入执行 receipt 11917033a9654d628e6d1452583ddd8e，exit 0，三条比较全部判定）：GetConfiguration 返回的 future 只用原子发布的最新 Configuration 填充，latestIndex 保持零值（api.go:895-903、future.go:255-270），因此 ConfigurationFuture.Index() 恒为 0；nextConfiguration 的 prevIndex 守卫仅在 prevIndex > 0 时生效（configuration.go:228-231），于是按文档把该索引用作乐观并发保护的调用者会被静默绕过。执行中四个节点在配置条目索引为 3 时均返回 returned_index 0 且 returned_servers 4（比较 0 违反，索引 4-7）；在一次插入变更（条目 4）之后，用以 API 返回值守护的变更成功写入条目 5（比较 1 违反，索引 10）；对照中用以真实索引 3 守护的同一类变更被拒绝（configuration changed since 3 (latest is 5)，比较 2 成立，索引 11）。结论：客户端契约缺陷（索引不可用于关联与乐观并发），不主张共识安全性受影响。；依据来源 s_get_configuration_api, s_config_future, s_config_future_iface, s_prev_index_guard, s_addvoter_previndex_doc，执行 11917033a9654d628e6d1452583ddd8e。
  反证：The control comparison now holds against the opposite value, showing the guard is implemented and enforced for genuine indices; the failure is the value handed to callers, not a missing check.；In the predecessor receipt one node's read fell outside applicability (it still showed three servers), so this interpretation relies on the successor where all four nodes reported the four-server configuration with index 0.
  限制：Two executions of one cluster shape through the in-memory transport; the accessor is zero by construction, but wider configurations were not exercised.；No internal consumer or external client of the accessor was enumerated, so the practical blast radius is described but not measured.；No claim is made about elections, commitment or internal configuration state, which were not shown to use the accessor.
### 被隔离 leader 的 VerifyLeader 在租约量级内完成并报错

当前处置：局部问题已回答。
问题 `ab8ea0d2f60f422796f9d946edf40b48-question-0` v2；来源：s_verify_leader_api, s_check_leader_lease, s_leader_cleanup_verify, s_verify_future_vote, s_lease_config_validation（[完整引用](state.json)）。
原命题：When a leader that cannot reach a quorum issues VerifyLeader, does the request complete within a bound that the source supports, and does it fail rather than silently succeed, without the caller having to supply its own timeout?
假设：VerifyLeader counts the leader's own vote and then waits for peer replies; with the peers unreachable no reply arrives, so the request can only complete when the leader leaves the leader loop. The lease check is that path: the leader loop samples last contact periodically and steps down when fewer than quorumSize peers were contacted within LeaderLeaseTimeout, and the step-down cleanup responds ErrLeadershipLost to every pending verification. The request should therefore complete in the order of LeaderLeaseTimeout and report an error, while a healthy leader completes immediately.
下一判别条件：On a healthy three-node cluster call VerifyLeader on the leader (control: immediate success), then isolate the leader from both followers and call VerifyLeader again, measuring completion, elapsed time, the returned error and the leader's state against a client-side wait limit several times the lease. A defect needs the request to remain unanswered past the limit or to report success while the leader cannot contact a quorum; prompt failure with the leader stepping down refutes the concern for this configuration.
问题边界：Answered for the tested configuration only: heartbeat, election and leader-lease timeouts were all 300ms, and the configuration rules require the lease not to exceed the heartbeat timeout, so ratios far from 1:1 were not exercised.；The probe isolates the leader rather than crashing it, and the followers elect their own leader while the isolated node steps down; that concurrent election is outside the measured endpoint even though it happens in the same execution.；The measured bound is the lease check plus scheduling (306ms against a 300ms lease in the retained run); no upper bound for heavily loaded hosts is claimed.；Bounded completion was measured through the returned future with a client-side wait limit; the request was still outstanding at the moment of isolation by construction, which is the scenario of interest.

固定实验 `ab8ea0d2f60f422796f9d946edf40b48-experiment` v1：[原始依据](fixed-experiments/ab8ea0d2f60f422796f9d946edf40b48-experiment/basis.json)。
范围：One fault-free execution of a normally bootstrapped three-node in-memory cluster with heartbeat, election and leader-lease timeouts all set to 300ms: a control VerifyLeader on the healthy leader, then isolation of the leader from both followers and a second VerifyLeader measured against a 6s client-side wait limit.
前史／供给条件：Built with captured test facilities and real producers only: MakeCluster(3, conf) with HeartbeatTimeout, ElectionTimeout and LeaderLeaseTimeout all 300ms bootstraps the cluster and c.Leader() returns the leader; the harness emits verify_control_start with the node identity, its state and the lease, calls VerifyLeader and emits verify_healthy with the error, elapsed time and state. It then isolates the leader from its peers with c.Partition, emits verify_probe_start with the node identity, state, lease and connected-peer count, issues VerifyLeader again, waits on the returned future from a separate goroutine against a 6s limit, and emits verify_partitioned with completion, elapsed time, error text, state and the wait limit. No storage is pre-filled and no production code is modified.
假设：MakeCluster(3) performs real bootstrap, election and heartbeats through the in-memory transport, and c.Partition isolates the leader while leaving the other two connected to each other.；LeaderLeaseTimeout must not exceed HeartbeatTimeout, so all three timeouts are set to 300ms and the expected completion bound is a small multiple of that value.；The client-side wait limit of 6s is generous relative to the 300ms lease, so remaining unanswered past it would be a hang rather than an expected bound.；The leader is still in the Leader state when the isolated call is issued, so the measured path is the lease check and the step-down cleanup rather than a non-leader rejection.
范围外：Configurations with other lease, heartbeat or election ratios (for example a lease far below the heartbeat timeout).；Crash and restart scenarios, and any network transport behaviour.；The followers' own election while the leader is isolated.
书面要求：VerifyLeader issued by a leader that cannot contact a quorum completes within a bound set by the leader lease and reports an error instead of hanging or claiming success, while the same call on a healthy leader succeeds immediately.
执行 `32b2614b51cd4e06a91be66d8bed1c4b`：completed，退出码 0；[回执](logs/32b2614b51cd4e06a91be66d8bed1c4b/check.json)、[stdout](logs/32b2614b51cd4e06a91be66d8bed1c4b/stdout.log)、[stderr](logs/32b2614b51cd4e06a91be66d8bed1c4b/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `7823fda370ca4a11b3e4d0ad9908eb1b-interpretation-0`：有限范围未见违反；本场景下保护成立（固定输入执行 receipt 32b2614b51cd4e06a91be66d8bed1c4b，exit 0，三条比较全部判定成立）：健康 leader 的 VerifyLeader 立即返回成功（0ms，仍为 Leader，索引 1）；把 leader 与两个 follower 隔离后，同一调用在 306ms（租约 300ms）内完成并返回错误 “leadership lost while committing log”，节点状态变为 Follower（索引 3）。源码机制：VerifyLeader 只统计对端回应（api.go:883-893），无人回应时由 leader loop 的租约检查在 LeaderLeaseTimeout 内联系不到 quorum 时下台（raft.go:1036-1081），随后下台清理对未完成的验证 future 回应 ErrLeadershipLost。配置校验要求租约不高于心跳超时（config.go:333-376），因此探针把三个超时都设为 300ms。未主张缺陷；残余边界为只测了 1:1 的租约/心跳比、隔离期间 follower 自行选举不在测量端点内、以及单次、空载环境下的观测。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "verify_control_start",
    "leader_state": "Leader",
    "lease_ms": 300,
    "node": "server-ea62e7ff-86ed-d5c0-1f53-2d723c34d3f3",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
      "location": {
        "line": 43,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]"
      }
    }
  },
  {
    "elapsed_ms": 0,
    "error_empty": true,
    "error_text": "",
    "event": "verify_healthy",
    "leader_state": "Leader",
    "node": "server-ea62e7ff-86ed-d5c0-1f53-2d723c34d3f3",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
      "location": {
        "line": 44,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]"
      }
    }
  },
  {
    "event": "verify_probe_start",
    "leader_state": "Leader",
    "lease_ms": 300,
    "node": "server-ea62e7ff-86ed-d5c0-1f53-2d723c34d3f3",
    "peers_connected": 0,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
      "location": {
        "line": 46,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]"
      }
    }
  },
  {
    "completed": true,
    "elapsed_ms": 306,
    "error_empty": false,
    "error_text": "leadership lost while committing log",
    "event": "verify_partitioned",
    "leader_state": "Follower",
    "lease_ms": 300,
    "node": "server-ea62e7ff-86ed-d5c0-1f53-2d723c34d3f3",
    "wait_limit_ms": 6000,
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]",
      "location": {
        "line": 79,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceVerifyLeaderUnderPartition\"]"
      }
    }
  }
]
```

归属解释历史：

- `7823fda370ca4a11b3e4d0ad9908eb1b-interpretation-0` · 有限范围未见违反：本场景下保护成立（固定输入执行 receipt 32b2614b51cd4e06a91be66d8bed1c4b，exit 0，三条比较全部判定成立）：健康 leader 的 VerifyLeader 立即返回成功（0ms，仍为 Leader，索引 1）；把 leader 与两个 follower 隔离后，同一调用在 306ms（租约 300ms）内完成并返回错误 “leadership lost while committing log”，节点状态变为 Follower（索引 3）。源码机制：VerifyLeader 只统计对端回应（api.go:883-893），无人回应时由 leader loop 的租约检查在 LeaderLeaseTimeout 内联系不到 quorum 时下台（raft.go:1036-1081），随后下台清理对未完成的验证 future 回应 ErrLeadershipLost。配置校验要求租约不高于心跳超时（config.go:333-376），因此探针把三个超时都设为 300ms。未主张缺陷；残余边界为只测了 1:1 的租约/心跳比、隔离期间 follower 自行选举不在测量端点内、以及单次、空载环境下的观测。；依据来源 s_verify_leader_api, s_check_leader_lease, s_leader_cleanup_verify, s_verify_future_vote, s_lease_config_validation，执行 32b2614b51cd4e06a91be66d8bed1c4b。
  反证：The control in the same execution (index 1) shows verification succeeds normally, so the failure at index 3 is attributable to the isolation and not to a broken verification path.；The observed error is the leadership-lost path rather than a quorum rejection, which is consistent with the source: silence is resolved by the lease check, not by the request itself.
  限制：One configuration (lease equal to heartbeat and election timeout) and one execution; other ratios and loaded hosts were not exercised.；The probe isolates rather than crashes the leader, and the followers elect while the isolated node steps down; that is outside the measured endpoint.；The measured 306ms against a 300ms lease is a single observation, and no claim is made about the distribution of the completion time.
### 运行期配置重载拒绝违反不变量的配置且不改动现状

当前处置：局部问题已回答。
问题 `83e05a1268184d598ceffcdfe382b2d6-question-0` v2；来源：s_reload_config, s_reloadable_config, s_lease_config_validation（[完整引用](state.json)）。
原命题：Can ReloadConfig on a running node install a configuration that the same library would reject at construction (for example a leader lease longer than the heartbeat timeout), and is the running configuration left untouched when the merged configuration is invalid?
假设：ReloadConfig copies exactly the reloadable fields onto the current configuration under a reload lock, runs the same validation the constructor uses on the merged result, and stores the new configuration only when validation passes, so an invalid reload returns the validation error and leaves the running configuration and its timers unchanged. A shorter heartbeat additionally wakes the leader and follower loops so replication and heartbeat timers adopt it.
下一判别条件：On a live node read ReloadableConfig, attempt a reload that violates the lease-versus-heartbeat invariant, and compare the returned error and the reported configuration with the values read before; then attempt a valid relaxation and check that it is accepted and visible. A defect needs the invalid reload to be accepted, to change the configuration partially, or the valid one to be silently dropped; rejection with unchanged state and an applied valid reload refutes the concern.
问题边界：Answered for the tested invariant and value pair only: one node, one invalid combination (heartbeat and election below the non-reloadable leader lease) and one valid relaxation were exercised.；The probe observes the returned error and the reported reloadable configuration; it does not measure how quickly the heartbeat, replication or election timers adopt a reloaded value, nor multi-node behaviour.；One node was sufficient because the reload path does not depend on membership or leadership; that reasoning is source-based, not measured.

固定实验 `83e05a1268184d598ceffcdfe382b2d6-experiment` v1：[原始依据](fixed-experiments/83e05a1268184d598ceffcdfe382b2d6-experiment/basis.json)。
范围：One fault-free execution on a normally bootstrapped single-node in-memory cluster: read the reloadable configuration, attempt an invalid reload that lowers the heartbeat and election timeouts below the non-reloadable leader lease, then attempt a valid reload that raises both.
前史／供给条件：Built with captured test facilities and real producers only: MakeCluster(1) bootstraps a node; the harness emits reload_probe_start with the node identity and the heartbeat, election and leader-lease values in force, then calls ReloadConfig with the reloadable fields set to 10ms for heartbeat and election while the non-reloadable lease stays at 50ms and emits reload_invalid with the returned error, whether the reported configuration is unchanged and the heartbeat value reported afterwards. It then calls ReloadConfig with heartbeat and election raised to 100ms and emits reload_valid with the returned error, the reported heartbeat and election, the lease still in force and whether the new heartbeat was applied. No storage is pre-filled and no production code is modified.
假设：MakeCluster(1) with the captured in-memory configuration leaves heartbeat, election and leader lease at 50ms, so lowering heartbeat and election to 10ms violates the validated lease-versus-heartbeat invariant while raising them to 100ms keeps it.；ReloadableConfig reports the reloadable fields currently in force, which is the configuration the probe compares against.；A single node is sufficient because the reload path does not depend on cluster membership or leadership.
范围外：Timing behaviour of replication and heartbeat loops after a successful reload.；Other reloadable fields and other invalid combinations.；Multi-node behaviour, network transport and restarts.
书面要求：A reload whose merged configuration violates the validated invariants is rejected with the running configuration unchanged, and a valid reload is accepted and visible through ReloadableConfig.
执行 `ff7deec318f148dc93776cc8f5610136`：completed，退出码 0；[回执](logs/ff7deec318f148dc93776cc8f5610136/check.json)、[stdout](logs/ff7deec318f148dc93776cc8f5610136/stdout.log)、[stderr](logs/ff7deec318f148dc93776cc8f5610136/stderr.log)。
机械比较：holds；当前确认：未确认违反
当前归属解释 `50470719317e436ab8ffb5b992db7441-interpretation-0`：有限范围未见违反；本场景下保护成立（固定输入执行 receipt ff7deec318f148dc93776cc8f5610136，exit 0，三条比较全部成立）：在 heartbeat/election 50ms、leader lease 50ms 的运行节点上，把 heartbeat 与 election 降到 10ms 的重载被拒绝，错误为 “LeaderLeaseTimeout (50ms) cannot be larger than heartbeat timeout (10ms)”，且 ReloadableConfig 保持不变（config_unchanged true）；随后把 heartbeat 与 election 提升到 100ms 的重载被接受并生效（lease 仍为 50ms，heartbeat_applied true）。源码机制：ReloadConfig 在重载锁内把五个可重载字段合并到当前配置，用与构造相同的校验验证合并结果，只有成功才写入（api.go:713-741、config.go:267-313、config.go:366-371 的租约不高于心跳规则）。未主张缺陷；残余边界为单节点、单一不变量组合与单一合法变更，且未测量重载后计时器实际生效速度。

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "election_ms_before": 50,
    "event": "reload_probe_start",
    "heartbeat_ms_before": 50,
    "leader_lease_ms_before": 50,
    "node": "server-5a061d9e-f233-c9f6-0243-d905db8a2c4a",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
      "location": {
        "line": 6,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]"
      }
    }
  },
  {
    "config_unchanged": true,
    "error_empty": false,
    "error_text": "LeaderLeaseTimeout (50ms) cannot be larger than heartbeat timeout (10ms)",
    "event": "reload_invalid",
    "heartbeat_ms_after": 50,
    "heartbeat_ms_before": 50,
    "node": "server-5a061d9e-f233-c9f6-0243-d905db8a2c4a",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
      "location": {
        "line": 7,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]"
      }
    }
  },
  {
    "election_ms_after": 100,
    "error_empty": true,
    "error_text": "",
    "event": "reload_valid",
    "heartbeat_applied": true,
    "heartbeat_ms_after": 100,
    "lease_ms_after": 50,
    "node": "server-5a061d9e-f233-c9f6-0243-d905db8a2c4a",
    "_ca_stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
    "_ca_observation": {
      "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]",
      "location": {
        "line": 8,
        "stream": "[\"github.com/hashicorp/raft\",\"TestAssuranceReloadConfigValidation\"]"
      }
    }
  }
]
```

归属解释历史：

- `50470719317e436ab8ffb5b992db7441-interpretation-0` · 有限范围未见违反：本场景下保护成立（固定输入执行 receipt ff7deec318f148dc93776cc8f5610136，exit 0，三条比较全部成立）：在 heartbeat/election 50ms、leader lease 50ms 的运行节点上，把 heartbeat 与 election 降到 10ms 的重载被拒绝，错误为 “LeaderLeaseTimeout (50ms) cannot be larger than heartbeat timeout (10ms)”，且 ReloadableConfig 保持不变（config_unchanged true）；随后把 heartbeat 与 election 提升到 100ms 的重载被接受并生效（lease 仍为 50ms，heartbeat_applied true）。源码机制：ReloadConfig 在重载锁内把五个可重载字段合并到当前配置，用与构造相同的校验验证合并结果，只有成功才写入（api.go:713-741、config.go:267-313、config.go:366-371 的租约不高于心跳规则）。未主张缺陷；残余边界为单节点、单一不变量组合与单一合法变更，且未测量重载后计时器实际生效速度。；依据来源 s_reload_config, s_reloadable_config, s_lease_config_validation，执行 ff7deec318f148dc93776cc8f5610136。
  反证：The control in the same execution (index 2) shows the reload path works, so the rejection at index 1 is attributable to the values rather than to a non-functional reload.；config_unchanged being true is an explicit operand of the same result event, not an inference from the absence of an error.
  限制：One node, one invalid combination, one valid relaxation, one execution; other validated constraints and other reloadable fields were not exercised.；The probe reads the reported configuration, not the timers' actual behaviour after a successful reload.；Because the reload path is independent of membership and leadership, a single node was used; that reduction is source-justified but not executed at larger sizes.
### Do LastIndex, CommitIndex and AppliedIndex expose the same progress, and which value bounds what a snapshot may claim about the state machine?

当前处置：局部问题已回答。
问题 `246186dca08549b4a8535799f9742a99-question-0` v1；来源：s_progress_accessors, s_process_logs_dispatch_index, s_fsm_snapshot_req, s_take_snapshot, s_get_last_index（[完整引用](state.json)）。
假设：The three accessors are intentionally different views: LastIndex is stable storage including the snapshot index, CommitIndex is the committed index, and AppliedIndex reflects the last index handed to the FSM thread's apply channel rather than work the FSM has finished - its own documentation says the application's state may lag behind it. Snapshot metadata is a separate value that the FSM thread owns and reports, and takeSnapshot additionally refuses to use it when it is below the committed configuration index.
下一判别条件：Compare each accessor's implementation and documentation with when its backing field is written: a defect would need an accessor whose documentation promises FSM completion while the value is written at dispatch time, or snapshot metadata derived from an accessor rather than from the FSM thread's own index. If the documentation states the dispatch-time caveat and snapshot metadata comes from the FSM thread, the accessors are consistent views and the concern is refuted.
问题边界：Source-only: no execution was requested in this turn, so the different notions are established from the accessors, their write sites and their documentation rather than measured concurrently.；The turn did not measure how far AppliedIndex can lead the FSM in practice under a slow FSM; only the ordering of writes was established.；Nothing here changes earlier findings; it consolidates the vocabulary used to interpret them.

归属解释历史：

- `246186dca08549b4a8535799f9742a99-interpretation-0` · 源码解释：The accessors are consistent views rather than conflicting ones, and the mismatch that could mislead a client is documented at the accessor itself. LastIndex delegates to getLastIndex, which returns the maximum of the stored log index and the snapshot index under the last-index lock (state.go:159-163); CommitIndex returns the committed index; AppliedIndex returns the applied index whose documentation (api.go:1238-1244) states that it reflects the last index sent to the FSM over the apply channel and that the application's state may therefore lag behind it. That caveat matches the write site: processLogs advances the applied index after the batch has been queued to the FSM thread (raft.go:1352-1358), so a client that polls AppliedIndex to decide whether its own write is applied can be told the index before the FSM has processed it, exactly as documented; a client that waits on its own Apply or Barrier future instead is answered by the FSM thread. Snapshot metadata does not use any of these accessors: the FSM thread reports the index it has accounted for with the snapshot request (fsm.go:216-233), and takeSnapshot checks that value against the committed configuration index before creating a snapshot (snapshot.go:125-211), so the fourth value is the one that bounds what a snapshot may claim. Consequences for reading earlier work in this run: the applied index reported by a node is a dispatch watermark, the FSM thread's index is the one that produces snapshot indices, and configuration visibility depends on the append path rather than on either watermark. No defect is claimed.；依据来源 s_progress_accessors, s_process_logs_dispatch_index, s_fsm_snapshot_req, s_take_snapshot, s_get_last_index，执行 无（源码解释）。
  反证：The strongest candidate for a defect here - an accessor that claims more than it delivers - is explicitly disclaimed in the accessor's own documentation, so a client cannot be misled by the name alone.；Snapshot metadata being produced by the FSM thread rather than by an accessor removes the possibility of a snapshot claiming state the FSM has not reached, which was checked separately in an earlier question with its guard.
  限制：Source-only synthesis; no concurrent measurement of the four values was requested in this turn.；The distance by which AppliedIndex can lead the FSM under a slow application was not measured.；This consolidates vocabulary; it supersedes nothing and changes no earlier conclusion.
### What does HasExistingState count as existing state, and can a store be in a condition where the constructor restores state but the helper reports the node as new (or the reverse), so a caller might bootstrap over data it should have recovered?

当前处置：局部问题已回答。
问题 `46289ca57dde4a1181f22bd834b3523d-question-0` v1；来源：s_has_existing_state, s_new_raft_restores, s_has_existing_state_test, s_vote_write_order（[完整引用](state.json)）。
假设：The helper reports existing state when any of three independent conditions holds: a current term above zero in the stable store, a log store last index above zero, or at least one snapshot. That matches the constructor's documented behaviour of restoring old state, so the only way the two could disagree is a state component the helper never consults - most plausibly the persisted vote - being written without a current term.
下一判别条件：Enumerate the durable components the constructor reads (current term, log store, snapshot store, and the configuration entries inside the log) and compare them with the helper's three checks, then look for a write path that persists a component without any of the three triggers. A defect needs such a write path, for example a vote persisted before the term; if every such write is preceded by a term increase, the helper's term check covers it and the concern is refuted.
问题边界：Source-only: no execution was requested in this turn; the reasoning rests on the helper, the write paths and the captured test expectation.；The helper treats any last log index above zero as existing state even if the log is otherwise empty, which is a conservative direction (it can report existing state for a store that has been used and cleared) and was not exercised.；A custom store implementation that reports a non-zero last index or lists snapshots for a fresh node would make the helper conservative; the captured in-memory stores were not executed here.

归属解释历史：

- `46289ca57dde4a1181f22bd834b3523d-interpretation-0` · 源码解释：Detection and recovery agree in the captured revision. HasExistingState (api.go:460-494) is documented as reporting logs, knowledge of a current term or any snapshot, and the implementation checks exactly those three things in that order: a stable current term above zero returns true, a 'not found' error is ignored while other term errors are propagated, a log last index above zero returns true, and a non-empty snapshot list returns true. NewRaft's documentation (api.go:496-500) states that old state such as snapshots, logs and peers is restored when the node is constructed, so a caller that respects the helper will not bootstrap over data the constructor would recover. The captured test for this contract (raft_test.go:255-295) records the expected direction on both sides: a freshly created node in a merged cluster reports no existing state before it joins, and the same node reports existing state after joining, which matches the helper's use of the stable term and log index. The one durable component the helper does not consult directly is the persisted vote; in both write paths that persist one, the term is raised durably first - the election path raises the term before persisting the vote (raft.go:1983 and 2021), and the vote-handling path adopts a higher term before persisting the vote (raft.go:1668 and 1726) - so a stored vote cannot exist without a non-zero current term, and the first check covers it. The remaining asymmetry is conservative rather than unsafe: a used-but-cleared log store, or a custom store that reports a non-zero last index for a fresh node, makes the helper report existing state, which errs towards recovering rather than bootstrapping. No defect is claimed.；依据来源 s_has_existing_state, s_new_raft_restores, s_has_existing_state_test, s_vote_write_order，执行 无（源码解释）。
  反证：The candidate gap - a persisted vote that the helper ignores - is closed by the durable ordering of the two write paths, not merely by the absence of a counterexample.；The captured test expectation covers both directions (fresh node false, joined node true), so the helper's contract is not only documented but exercised by the package's own tests.
  限制：Source-only; no execution was requested for this question in this turn.；The conservative direction (existing state reported for a cleared but previously used store) was not exercised against a real store.；The vote-order argument covers the write paths present in this revision; it is not a statement about other revisions.
### Which duties does the captured LogStore interface impose on an implementation, and which of them does Raft rely on for correctness rather than for storage alone?

当前处置：局部问题已回答。
问题 `5f9e27a6f308417e8bf9ca4c60f970dc-question-0` v1；来源：s_log_store_contract, s_log_barrier_contract, s_log_appended_at, s_oldest_log_retry, s_inmem_store_logs（[完整引用](state.json)）。
假设：Beyond storing and retrieving entries, the interface grants a freedom that the library depends on: a stored batch may be non-contiguous with previous logs, and Raft uses that gap to resynchronise followers after a snapshot restore, offering the MonotonicLogStore opt-in for implementations that cannot tolerate gaps. A store that cannot tolerate gaps but does not declare the opt-in would silently change what Raft believes about discontinuity, which is the kind of consumer/producer mismatch worth stating. Timestamps in the log are explicitly operational only, and the barrier type carries a stronger completion contract than a no-op.
下一判别条件：Compare the interface documentation with the call sites that consume FirstIndex, LastIndex, StoreLogs and the barrier type: a defect on the library side would need a call site that assumes a property the interface does not promise, or a store property the library never reads. For a store implementation the question is whether it can tolerate gaps and, if not, whether it declares IsMonotonic; the captured in-memory store stores by index and does not implement the opt-in, so it relies on the documented gap freedom.
问题边界：Source-only: no execution was requested for this question in this turn; no custom log store was written or exercised.；The behaviour of third-party stores (for example a BoltDB-backed store) was not inspected; only the interface documentation and the captured in-memory store were read.；Whether any captured call site mis-uses a promised property was surveyed only for the paths already read in this run (replication, snapshot restore, install) rather than exhaustively.

归属解释历史：

- `5f9e27a6f308417e8bf9ca4c60f970dc-interpretation-0` · 源码解释：The duties are documented where they are consumed, and the two surprising ones are freedoms rather than obligations. FirstIndex and LastIndex are specified to return 0 when there are no entries, which is what the snapshot and replication code relies on when it decides whether a prefix is available (for example the last-index helper returning the maximum of log and snapshot index). StoreLogs is explicitly permitted to store a batch that is not contiguous with previous logs, and the library uses that gap to mark the discontinuity created by a snapshot restore; stores that cannot tolerate gaps must opt in through MonotonicLogStore.IsMonotonic, after which Raft removes all previous logs instead of relying on the gap. The captured in-memory store inserts entries by index and does not implement the opt-in, so it takes the gap branch - consistent with the fork in the install path that chooses between removing all old logs and compacting. The barrier type carries its own documented contract: it exists so that callers can be sure preceding operations reached the FSM, and it resolves only when the FSM manager acknowledges it, which is stronger than a committed no-op and matches the ordering observed earlier in the apply path. Finally, AppendedAt is disclaimed as a coordination input: it is operational information, followers may see a future timestamp from clock skew, and the leader is not required to persist before delivering log entries, so nothing may treat it as an ordering or freshness signal - a reading worth recording because age metrics are derived from it. No defect is claimed; the one consumer/producer mismatch that would matter belongs to a store implementation that needs monotonicity without declaring it, which is outside the captured snapshot.；依据来源 s_log_store_contract, s_log_barrier_contract, s_log_appended_at, s_oldest_log_retry, s_inmem_store_logs，执行 无（源码解释）。
  反证：The only mismatch found is on the implementation side (a store needing monotonicity without declaring it), and the captured in-memory store correctly takes the gap branch instead of claiming monotonicity.；The barrier contract explains why a Barrier is a stronger synchronisation point than a no-op, which is consistent with the apply-path ordering established separately in this run rather than contradicting it.
  限制：Source-only; no custom store was written and no gap-dependent resynchronisation was executed for this question.；Third-party stores shipped outside this snapshot were not inspected.；The call-site survey covers the paths read in this run (replication, snapshot restore, install, oldest-log metrics), not every use of the store interfaces.
### 降级到 protocol 1 的 leader 会以旧格式写配置条目，非投票成员被静默丢弃

当前处置：局部问题已回答。
问题 `6962a0dc36854f06b25086c2b0574c7c-question-0` v2；来源：s_encode_peers_legacy, s_append_config_legacy_branch, s_decode_peers_legacy, s_protocol_version_bounds（[完整引用](state.json)）。
原命题：Can a membership change silently drop non-voter or staging servers when it is written through the deprecated peer encoding, i.e. when the leader runs a protocol version below 2 while its configuration contains entries of those suffrages?
假设：A leader with protocolVersion below 2 encodes every membership change with the deprecated peer list, whose encoder gathers only voters and states that other suffrage types are not supported by the format; the decoder on the receiving side reconstructs voters only as well. A configuration that contained a non-voter or staging server would therefore be written back without it, and because nextConfiguration computed the full configuration (and only requires at least one voter), nothing on that path would report the loss.
下一判别条件：Establish whether a node with protocolVersion below 2 can be leader while configurations.latest contains a non-voter or staging entry: those entries can only enter through the versioned configuration format or through a snapshot, so the interesting cases are a deliberate downgrade of a running member, a mixed-version cluster where the older node wins an election, and a snapshot restored from a newer member. If such a state is reachable, a harness can drive one membership change on that leader and compare the entry's decoded configuration with the configuration the change requested; if the state is unreachable, or if the leader refuses or is replaced before appending, the concern is refuted. A defect requires a delivered entry whose decoded configuration is missing a server that the requested configuration contained.
问题边界：Conditional answer: the lossy encoding is real, and its precondition is reachable only through a downgrade-style deployment - a member restarted with a protocol version below 2 while its stores already contain versioned configuration entries that include non-voters - not in a cluster that has only ever run the newer format.；Whether such a downgrade is a supported operation for the library is a policy question the captured sources do not settle; the code permits the restart and rebuilds the configuration without consulting the node's protocol version.；No execution was requested, so no entry was appended and decoded; the conclusion rests on the constructor's replay, the encoding branch, the encoder/decoder asymmetry and the protocol gate on the membership API.；The failure would drop non-voting members from the written configuration, not break quorum, since checkConfiguration still requires at least one voter.

归属解释历史：

- `6962a0dc36854f06b25086c2b0574c7c-interpretation-0` · 未解决：The lossy encoding is established from source; its reachability is not. appendConfigurationEntry chooses the entry format from the leader's protocol version alone: below 2 it appends a deprecated remove-peer entry whose payload is encodePeers(configuration) (raft.go:1219-1233), and encodePeers iterates the configuration taking only servers with suffrage Voter, with the stated reason that other suffrage types are not supported by the data format (configuration.go:311-327). The receiving side is symmetric: the deprecated entry is decoded with decodePeers, which reconstructs every server as a voter (configuration.go:330-352), and the same encoder fills the peers field returned to protocol-version-below-2 voters (raft.go:1620-1622). nextConfiguration had computed the full configuration and checkConfiguration only requires at least one voter, so a non-voter or staging entry in the computed configuration would not stop the append - it would simply not be representable in the written entry. What that means depends entirely on whether the precondition is reachable, and this turn did not establish it: non-voter and staging entries enter only through the versioned configuration format or through a snapshot from a member that used it, so the candidate paths are a deliberate downgrade of a running member, a mixed-version cluster in which the older node becomes leader, and a snapshot restored from a newer member (the version bounds themselves allow protocol 0 and above, config.go:100-106, with the handler accepting one version back). Until one of those is shown to produce a below-2 leader holding such a configuration, this stays a sourced boundary rather than a defect; the decisive test is to append one membership change on such a leader and compare the decoded entry with the configuration the change requested.；依据来源 s_encode_peers_legacy, s_append_config_legacy_branch, s_decode_peers_legacy, s_protocol_version_bounds，执行 无（源码解释）。
  反证：A cluster that has only ever run protocol 1 cannot have non-voter or staging entries in its configuration, because the deprecated format cannot introduce them; the concern is confined to downgrade, mixed-version and snapshot-restore states.；checkConfiguration still guarantees at least one voter, so the lossy path cannot produce a configuration with no voters - the risk would be losing non-voting members in the written entry, not losing the quorum.
  限制：No execution: no entry was appended or decoded, and no downgrade or mixed-version cluster was constructed.；Reachability was not established, so no defect is claimed and the question stays paused with its discriminator.；The wider compatibility matrix (which version combinations the library promises to support during rolling upgrades) was not surveyed.
- `bc9aba4bf6654a5f91001cd1f0346a2b-interpretation-0` · 条件性结果：条件性确认的缺陷：当 leader 的 protocolVersion 低于 2 时，appendConfigurationEntry 使用旧格式（encodePeers）写成员变更（raft.go:1219-1233），而该编码只保留 Voter，注释明确说明其他 suffrage 不受支持（configuration.go:311-327）；接收端 decodePeers 也只会还原为 Voter（configuration.go:330-352），因此配置中的非投票成员会被静默丢弃，checkConfiguration 只要求至少一个 Voter，不会报错。触发条件：低于 2 的 leader 持有含非投票成员的配置。该前置状态可达：NewRaft 通过回放日志重建配置（api.go:593-607），解码只依赖条目类型、不看本节点协议版本，所以把成员以 protocol 1 重启后仍会保留版本化格式写入的非投票成员；而 protocol 1 下可用的成员变更 API 恰是旧格式的 AddPeer（API 在 protocolVersion > 2 时拒绝，api.go:905-919），RPC 头检查允许一个版本回退（raft.go:45-70），protocol 1 与 protocol 2 节点可以互通。影响范围：属于部署性条件（写出版本化配置后回退版本再重启），不会破坏 quorum，也只在曾使用版本化格式的集群中出现；库是否“支持”这种回退未在快照中说明。；依据来源 s_encode_peers_legacy, s_append_config_legacy_branch, s_decode_peers_legacy, s_new_raft_config_replay, s_add_peer_protocol_gate, s_check_rpc_header_version_window，执行 无（源码解释）。
  反证：A cluster that has only ever run protocol 1 cannot hold non-voter entries, because the deprecated format cannot introduce them, so the defect cannot arise there.；checkConfiguration still guarantees at least one voter, so the worst case is losing non-voting members, not losing the ability to commit.；The one-version-back RPC window means the mixed deployment is not obviously excluded by the protocol checks, which is what makes the precondition reachable rather than hypothetical.
  限制：No execution: the appended entry was not decoded and compared, and no downgraded node was constructed.；Whether the library supports rollback below the version that wrote versioned configuration entries is a policy question outside the captured sources.；The conclusion is scoped to a deliberate restart with a lower protocol version on stores that already contain versioned configuration entries.
### What exactly does Shutdown promise to a caller - when is the node considered shut down, when do in-flight operations finish, and when is the transport released?

当前处置：局部问题已回答。
问题 `8d8ffb8edcfb4ca79bfbcf1fb35683f3-question-0` v1；来源：s_shutdown_api, s_shutdown_future, s_process_logs_shutdown（[完整引用](state.json)）。
假设：Shutdown is idempotent: the first call closes the shutdown channel, records the node as shut down, moves it to the Shutdown state and returns a future bound to the node, while later calls return a future with no node so nothing is closed twice. The returned future's Error() is what waits for the background routines and, when the transport implements WithClose, closes it; operations still queued for the FSM thread are answered with the shutdown error by the dispatching code rather than being left pending.
下一判别条件：Compare the fields set by the first and later Shutdown calls with what the returned future's Error does, and trace what happens to work that is mid-flight when the shutdown channel closes. A defect needs a call that reports completion before the routines stop, a second call that closes something twice, or in-flight clients left unanswered; idempotent return values plus a future that waits and closes, with explicit shutdown responses on the dispatch paths, refute the concern.
问题边界：Source-only: no execution was requested in this turn; no shutdown was raced against in-flight operations.；The survey covers the processLogs dispatch path and the shutdown future; other paths that respond ErrRaftShutdown or ErrLeadershipLost were not enumerated exhaustively.；The behaviour of a transport that does not implement WithClose was not exercised; in that case only the routines are awaited.

归属解释历史：

- `8d8ffb8edcfb4ca79bfbcf1fb35683f3-interpretation-0` · 源码解释：The contract is coherent and the ordering is explicit. Shutdown takes a lock, and on the first call closes the shutdown channel, marks the node shut down, sets the Shutdown state and returns a future bound to the node; a later call returns a future whose raft pointer is nil precisely so that nothing is closed twice (api.go:1012-1025). Because the node is marked and moved to Shutdown before the future is returned, a caller that ignores the future still observes the state change, while a caller that waits obtains the stronger guarantee: the shutdown future's Error waits on the node's routine group and closes the transport when it implements WithClose (future.go:167-180), so the return value is the only thing that waits for background work rather than just requesting it. In-flight operations are not orphaned by the channel closing: the processLogs batch handoff selects on the shutdown channel and responds ErrRaftShutdown to every future in the batch it could not dispatch (raft.go:1300-1310), and the run loops return out of their select when the channel closes so their own pending futures are answered by the cleanup paths already recorded in this run (leadership-lost for the leader's inflight set). No defect is claimed: the two-phase shape, the idempotence and the explicit shutdown responses are consistent with each other, and the only boundary worth naming is that a caller who never waits on the future gets a request rather than a completed shutdown.；依据来源 s_shutdown_api, s_shutdown_future, s_process_logs_shutdown，执行 无（源码解释）。
  反证：The second-call future carries a nil node deliberately, which is what prevents a double transport close rather than being an oversight.；The ordering (mark and change state under the lock, then return the future) means an ignored future cannot leave the node looking healthy.
  限制：Source-only; no shutdown was raced against in-flight operations in this run.；Only the processLogs handoff was cited as an in-flight response path; other shutdown response sites were not enumerated.；Transports without WithClose are awaited but not closed, which was read but not exercised.
### What does an observer receive, and what happens to an observation when the observer cannot keep up?

当前处置：局部问题已回答。
问题 `04c20350eed842e49c7f1229f2968eba-question-0` v1；来源：s_observation_types, s_observer_registration, s_observe_delivery（[完整引用](state.json)）。
假设：Delivery is best-effort by default: for a non-blocking observer the library attempts a channel send and counts a dropped observation when the channel is full, without blocking the emitting goroutine, while a blocking observer performs a plain send and therefore applies backpressure to the caller. A filter can suppress delivery per observer, and registration and deregistration take a write lock while delivery takes the read lock, so a slow blocking observer holds a read lock for the duration of its send.
下一判别条件：Compare the delivery paths for blocking and non-blocking observers and the counters each maintains, and check which locks are held while sending. A defect would need the library to promise lossless delivery, to block an internal goroutine for a non-blocking observer, or to hold a lock across a send in a way that prevents registration; the documented best-effort path with explicit drop counting refutes the first two, and the read lock during a blocking send is the boundary worth stating.
问题边界：Source-only: no execution was requested in this turn; no observer was registered, dropped or blocked while observing.；The set of events that produce observations was read but not enumerated exhaustively; the observation data types listed in the interface were not traced to every producer.；The consequence of a blocking observer on a specific emitting goroutine (main loop, replication, FSM thread) was not measured.

归属解释历史：

- `04c20350eed842e49c7f1229f2968eba-interpretation-0` · 源码解释：The contrast between the two delivery modes is deliberate and visible in a few lines. observe builds one observation per registered observer, applies that observer's filter, skips observers with no channel, and then either sends unconditionally when the observer asked for blocking behaviour or attempts a non-blocking send and increments a dropped counter when the channel is full (observer.go:120-151). The counters are per observer and updated atomically, so a consumer can detect loss rather than infer it. Ordering of registration is guarded separately: RegisterObserver and DeregisterObserver take the observers write lock (observer.go:104-118) while delivery holds only the read lock, so a blocking observer does not prevent another observer from being visited, but a blocking observer does hold the read lock for the duration of its send and therefore blocks registration or deregistration until it returns. Consequences worth stating for a consumer: with the default non-blocking mode, losing observations under load is expected and the drop counter is the signal; with the opt-in blocking mode, the observer can stall whichever internal goroutine emitted the observation - main loop, replication or the FSM thread, depending on the event - and the observation stream must not be treated as a durable log. No defect is claimed: the interface documents that observations are sent when an event occurs and the implementation's drop counting makes the best-effort semantics observable.；依据来源 s_observation_types, s_observer_registration, s_observe_delivery，执行 无（源码解释）。
  反证：A blocking observer cannot cause an internal deadlock by itself: delivery holds only a read lock, so it cannot block another observer's delivery, and the counters let a consumer distinguish loss from silence.；Nothing in the interface promises lossless delivery, so the drop path is a documented-by-design consequence of the non-blocking default rather than an unstated violation.
  限制：Source-only; no observer was registered or saturated in this run.；The blast radius of a blocking observer was reasoned per emitting goroutine but not measured.；The full list of event producers was not enumerated; the observation payload types in the interface are the extent of what was read.
### What does a client get from Barrier, and what does its optional timeout bound?

当前处置：局部问题已回答。
问题 `71da525e349f4f9281515c56c0aeeff0-question-0` v1；来源：s_barrier_api, s_log_barrier_contract（[完整引用](state.json)）。
假设：Barrier appends a barrier log and answers the caller only once the FSM thread acknowledges it, so on success all preceding operations have been applied; it must be issued on the leader or the call fails, and a supplied timeout bounds how long the call waits to enqueue the command rather than how long the FSM takes to apply it.
下一判别条件：Compare the API documentation with the implementation's timeout handling and with the barrier type's documented completion contract: a defect would need the call to return before preceding operations are applied, to succeed on a non-leader, or for the timeout to be presented as an application deadline. Documentation that ties completion to the FSM acknowledgement, restricts the call to the leader and describes the timeout as bounding the start, together with the enqueue-time select in the implementation, refutes the concern.
问题边界：Source-only: no execution was requested in this turn; the timeout behaviour was read, not raced.；Only the leader-side enqueue path and the barrier log type were consulted; the follower rejection path is the same ErrNotLeader rule recorded elsewhere in this run.；The distinction between enqueue timeout and apply latency is documented and implemented, but no measurement of the latter was made.

归属解释历史：

- `71da525e349f4f9281515c56c0aeeff0-interpretation-0` · 源码解释：The two layers agree. The API documentation states that Barrier issues a command which blocks until all preceding operations have been applied to the FSM and that it must run on the leader or fail, and it describes the optional timeout as limiting how long we wait for the command to be started (api.go:854-858); the implementation creates a barrier log future with no index or term yet and then selects on the caller's timer while offering the future to the apply channel (api.go:859-880), which is exactly an enqueue bound. The log-level contract recorded earlier says the barrier type exists to ensure preceding operations reached the FSM and resolves only on the FSM manager's acknowledgement (log.go:33-38), which is what makes the successful completion meaningful. Consequences for a caller: a success means the FSM reflects all preceding writes; a timeout means the command was not started in time, so the caller must not read it as 'not yet applied' versus 'applied' - it simply does not know; and a non-leader returns the not-leader error rather than queueing the barrier. No defect is claimed; the only boundary worth naming is that the timeout is an enqueue deadline, which the documentation states explicitly.；依据来源 s_barrier_api, s_log_barrier_contract，执行 无（源码解释）。
  反证：The candidate confusion - treating the timeout as an application deadline - is explicitly excluded by the documentation's wording and by the implementation's enqueue-time select.；The completion semantics are anchored twice: at the API and at the log type, so a caller following either is not misled.
  限制：Source-only; no barrier timeout was raced against a slow FSM in this run.；Apply latency after a successful enqueue was not measured.；The follower rejection path was not re-read here; it follows the same not-leader rule recorded elsewhere in this run.

## 共享理解与修订

- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-0` r1 · behavior：Raft.timeoutNow performs an unconditional authority transition on the receiver: it clears the known leader, sets the state to Candidate, stores candidateFromLeadershipTransfer=true and responds with an empty TimeoutNowResponse. It never inspects the RPC header identity, the current configuration, or any term, and observes no election or heartbeat precondition before transitioning.；条件：Applies to every TimeoutNowRequest that passes checkRPCHeader, delivered to a server in any run state; the request carries only RPCHeader (ProtocolVersion, ID, Addr) and therefore cannot be evaluated for freshness.。
- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-1` r1 · behavior：While candidateFromLeadershipTransfer is set, runCandidate does not pre-vote: it calls electSelf directly, which increments the current term and sends RequestVote with LeadershipTransfer=true. The flag is cleared by a deferred store(false) when the candidate run ends.；条件：Set only by timeoutNow in the captured source; applies to a node that then enters/continues the candidate state.。
- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-2` r1 · behavior：requestVote rejects a vote request that arrives while a different leader is known, but skips that rejection when req.LeadershipTransfer is true; the older-term rejection and the log-suffix comparison still run before a vote is granted.；条件：Applies to RequestVoteRequest handling on any server that has a recorded leader whose address differs from the candidate and whose protocol version carries the LeadershipTransfer flag.。
- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-3` r1 · behavior：The other authority-bearing RPC handlers guard their state change with the sender's term: appendEntries returns early when a.Term is below the current term and only adopts/updates term and state when the request term is greater (or the receiver is not a follower), and installSnapshot ignores a snapshot whose request term is older than the current term.；条件：Applies to AppendEntriesRequest and InstallSnapshotRequest processing; this is the control contrast for the TimeoutNow handler, which has no term to compare.。
- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-4` r1 · behavior：The leader-side leadershipTransfer routine only issues the TimeoutNow RPC after it has driven the target's replication nextIndex past the leader's last log index, i.e. the producer establishes a caught-up target before transferring.；条件：Applies to the sender path invoked from leaderLoop; it is not verified by, nor visible to, the receiving timeoutNow handler.。
- `ce1a7dcb68b449448fdee06b3eb7737e-knowledge-5` r1 · behavior：GetConfiguration does not read main-thread membership state: it returns a configurationsFuture whose configurations field is filled from the atomically published latestConfiguration, which is written only by setLatestConfiguration (and cleared/initialised elsewhere), so the value a client sees is whatever that atomic last held.；条件：Applies to any caller of GetConfiguration on any server, including followers, independent of the main-thread run loop.。
- `5a436a477b8e4920bbcd4123e81f07fa-knowledge-0` r1 · behavior：Configuration log entries are not delivered to the FSM: the apply loop dispatches only LogCommand to r.fsm.Apply, and for LogConfiguration it calls ConfigurationStore.StoreConfiguration only when the FSM implements ConfigurationStore (otherwise it returns early). MockFSM therefore records only LogCommand payloads in its logs slice and never records a configuration unless the ConfigStoreFSM option is used.；条件：Applies to commit-application in the captured snapshot for every server, regardless of protocol version; Noop and barrier entries likewise never reach FSM.Apply.。
- `5a436a477b8e4920bbcd4123e81f07fa-knowledge-1` r1 · behavior：The captured cluster test helper's EnsureSame compares FSM-applied log payloads and the FSM's recorded configuration list, and its polling limit defaults to 5 seconds (overridden only by a positive MakeClusterOpts.LongstopTimeout). Built with a plain MockFSM and without ConfigStoreFSM, both compared values are empty for a scenario whose only entries are configuration and noop entries, so EnsureSame can pass without establishing that a peer holds the configuration entry.；条件：Applies to clusters created through MakeCluster/MakeClusterCustom without ConfigStoreFSM; the configuration comparison is only meaningful when the FSM implements ConfigurationStore.。
- `5a436a477b8e4920bbcd4123e81f07fa-knowledge-2` r1 · behavior：The appendEntries truncation path is not a mechanism for configurations.latest to stay stale: on a term conflict the conflicting entry is included in newEntries, the suffix is stored, and processConfigurationLogEntry is run for every new entry in the same call, so a configuration entry is (re)applied when it is (re)appended; when the truncated suffix really contained a configuration entry, rolling latest back to the committed configuration is the intended result.；条件：Applies to appendEntries handling of AppendEntriesRequest batches that clear a log suffix at or below configurations.latestIndex.。
- `5a436a477b8e4920bbcd4123e81f07fa-knowledge-3` r1 · behavior：Membership changes are applied with command-specific suffrage rules: AddVoter replaces a non-voter/staging entry with a Voter and only rewrites the address of an existing Voter; AddNonvoter appends a Nonvoter when the server is absent and, when the server is already present with a different suffrage (Voter or Staging), only writes its address while keeping that suffrage; DemoteVoter is the command that turns an existing server into a Nonvoter; RemoveServer deletes the entry. A resulting configuration with no voters is rejected.；条件：Applies to nextConfiguration for a request whose prevIndex matches the current configuration index; the capture's table expectations record the suffrage outcome for each command and initial suffrage.。
- `e2a8cfd757e74ee4965e45968de09795-knowledge-0` r1 · behavior：Only some committed log types reach the FSM thread: prepareLog returns a commit tuple for LogBarrier and LogCommand, and for LogConfiguration only when protocolVersion > 2. LogNoop, LogAddPeerDeprecated, LogRemovePeerDeprecated and LogConfiguration under protocol <= 2 return nil, so they never enter the FSM batch; processLogs still responds to any future attached to them from the main thread and then advances lastApplied.；条件：Applies to processLogs dispatching committed entries to fsmMutateCh on the leader and on followers, for every configuration of the FSM (with or without ConfigurationStore and BatchingFSM).。
- `e2a8cfd757e74ee4965e45968de09795-knowledge-1` r1 · behavior：The FSM thread's local applied index advances for every entry it receives, except for LogConfiguration when the FSM does not implement ConfigurationStore, where the handler returns early on the stated grounds of not incrementing the index for an unimplemented operation. The index it reports in a snapshot request is that local index, so it can legitimately sit below the committed configuration index.；条件：Applies to the single-apply path in runFSM; the batching path instead takes the index and term of the last entry in the batch whether or not it was sent to ApplyBatch.。
- `e2a8cfd757e74ee4965e45968de09795-knowledge-2` r1 · behavior：takeSnapshot refuses to create a snapshot when the FSM-reported index is below the committed configuration index, and otherwise records that index/term together with the committed configuration and its index, then compacts only up to min(snapshot index, last log index - TrailingLogs).；条件：Applies to automatic and user-triggered snapshots on any server; the committed configuration is read from the main thread through configurationsCh after the FSM snapshot has been started.。
- `e2a8cfd757e74ee4965e45968de09795-knowledge-3` r1 · behavior：A server's reported last log index is max(lastLogIndex, lastSnapshotIndex), so installing a snapshot raises the server's last index even though appendEntries and installSnapshot do not rewrite the stored log index; installSnapshot updates lastApplied, the last snapshot index, both configurations and log compaction.；条件：Applies to raftState.getLastIndex as used by election and replication bookkeeping and to the InstallSnapshot handler.。
- `e2a8cfd757e74ee4965e45968de09795-knowledge-4` r1 · behavior：The automatic snapshot condition compares the log store's last index with the snapshot index using an unsigned subtraction and no ordering guard, so a log store index below the snapshot index makes the comparison permanently true.；条件：Applies to shouldSnapshot as invoked by the snapshot goroutine on its random SnapshotInterval; the log store index is the store's own LastIndex, not the snapshot-aware getLastIndex.。
- `87206f99921a4f25986b0b6525d9d58c-knowledge-0` r1 · fact：A node that recovers through InstallSnapshot while its log store keeps a lower index reports shouldSnapshot() as true indefinitely and keeps creating fresh snapshots at the installed snapshot index while completely idle: in two executions of the same fixed harness the recovered node produced 15 and 13 distinct snapshot IDs at index 202 with applied_delta 0 over a 900ms window (SnapshotInterval 40ms), while the leading node of the same cluster reported shouldSnapshot() false and exactly 1 distinct snapshot ID at index 202.；条件：Observed with MakeCluster(3), SnapshotInterval 40ms, SnapshotThreshold 20, TrailingLogs 5, in-memory log/snapshot stores, protocol 3, after isolating one follower, committing 140 further commands so the leader's log compacts past that follower's next index, reconnecting so the follower recovers by InstallSnapshot (log store last index stays 62, snapshot index 202), then isolating the recovered node for a 900ms window sampled every 40ms. Two executions are instances, not a universal guarantee; MonotonicLogStore implementations, production SnapshotInterval values and long-running persistence were not observed.。
- `87206f99921a4f25986b0b6525d9d58c-knowledge-1` r1 · behavior：A verifyFuture can be woken by only one notification (vote is guarded by the notify channel being non-nil and set to nil when it fires), and every respond path is idempotent through the deferError responded flag; vote(true) only notifies once the counted votes reach quorumSize, while vote(false) notifies immediately so the leader loop can step down when any peer reports a new leader.；条件：Applies to VerifyLeader/verifyFuture handling in the captured revision, including the quorumSize==0 dispatch sentinel and the follower/candidate paths that reject arrivals on the shared verify channel with ErrNotLeader.。
- `87206f99921a4f25986b0b6525d9d58c-knowledge-2` r1 · behavior：On stepping down, the leader loop responds ErrLeadershipLost to every future still in its own notify set; replication goroutines keep their notify maps separate and only clear them through notifyAll at the end of a replication RPC, so a late notification can push an already-answered verify future back onto the shared verify channel, where the next non-leader loop answers it again through the idempotent respond path.；条件：Applies to leadership loss (step-down, shutdown, or state change out of Leader) with outstanding VerifyLeader requests; the arrivals are handled by whichever run loop is active when they are read.。
- `3aab71eb943140cfa801c33349322eb2-knowledge-0` r1 · behavior：InstallSnapshot validates freshness only by term: an older term is ignored, a newer term transitions the receiver to follower and is adopted, and there is no comparison of the request's LastLogIndex with the receiver's own lastApplied, last snapshot index or log store range. On success the handler restores the FSM from the requested snapshot, sets lastApplied to the request's LastLogIndex, sets the last snapshot index to the request's LastLogIndex/LastLogTerm, replaces both the latest and committed configurations from the request, and then removes all old logs (monotonic stores) or compacts up to the request's index.；条件：Applies to InstallSnapshotRequest handling on any server that reaches the handler, including a server whose own applied index or snapshot index is higher than the request's; the only preceding checks in the handler are the snapshot version bounds and the term.。
- `3aab71eb943140cfa801c33349322eb2-knowledge-1` r1 · behavior：Recovery from a restored snapshot index depends on log replay: processLogs rejects an index at or below lastApplied, otherwise it walks from lastApplied+1 to the target index fetching each log from the store and panics when a needed entry is missing, so a restored index below the previously applied index leaves re-application to entries that must still exist in the log.；条件：Applies to commit-application on any server after a restore, including the install path that sets lastApplied from the request; the walk is bounded by the target commit index and sources entries either from the in-flight future map or the log store.。
- `3aab71eb943140cfa801c33349322eb2-knowledge-2` r1 · behavior：The sender reaches the snapshot path only when it cannot produce entries from its per-peer nextIndex, and nextIndex moves on follower responses: a rejected AppendEntries sets nextIndex to max(min(nextIndex-1, response.LastLog+1), 1), and the snapshot is opened when setupAppendEntries reports the log is not found, i.e. when the needed prefix has been compacted away.；条件：Applies to the leader-side replication loop for each peer; the reported last log index used in the backoff comes from the follower's AppendEntriesResponse.LastLog.。
- `47c982576c6d45aab2335682617238da-knowledge-0` r1 · fact：Across three executions of the same isolation/compaction/reconnect probe on a 3-node in-memory cluster, the node that entered the InstallSnapshot path never reported an applied index below its own maximum: its applied index advanced 27 -> 112 -> 197 -> 257 across rounds with decrease_count 0 and applied_at_end equal to max_applied_seen, while its snapshot index (257) stayed above its surviving log store last index (197) and the two nodes that never entered the install path were monotone as well (snapshot index 257, log store last index 257, decrease_count 0).；条件：Observed with MakeCluster(3), SnapshotInterval 30ms, SnapshotThreshold 10, TrailingLogs 5, in-memory log/snapshot stores, protocol 3, in three rounds of 25 warm commands, isolating one follower, 60 further commands through the remaining quorum, reconnecting, and polling all nodes every 2ms for 1.2s. The probe does not construct a leader snapshot index below a follower's applied index, so this is an observed bounded result and not a guarantee for other configurations.。
- `47c982576c6d45aab2335682617238da-knowledge-1` r1 · behavior：Pipelined replication keeps two separate cursors: pipelineSend advances a private send cursor to the last pipelined entry index + 1 as soon as the request is handed to the pipeline, while the per-follower nextIndex and the commitment map advance only from successful decoded responses (updateLastAppended stores nextIndex = last entry index + 1 and matches commitment, then notifies the verify futures as leader). The decoder aborts the pipeline on the first unsuccessful response, on a newer term (notifyAll(false) plus a step-down notification) and pipelineSend returns shouldStop when setup fails such as a compacted prefix, after which the caller falls back to standard replication or the snapshot path. setPreviousLog additionally special-cases nextIndex-1 equal to the last snapshot index so a snapshot-backed prefix is accepted as the previous log entry.；条件：Applies to the leader-side pipeline path in the captured revision for peers that support AppendEntriesPipeline, including the fallback to replicateTo after the pipeline aborts.。
- `d3b8b97b4e5e491189c06b05ec8b2fae-knowledge-0` r1 · behavior：An incoming AppendEntries is classified as a heartbeat by its field values on the receiving side (non-zero term, a leader address present, PrevLogEntry and PrevLogTerm zero, no entries, LeaderCommitIndex zero). When the transport has a heartbeat handler, it is invoked directly from the connection goroutine and the RPC never reaches the consumer channel; otherwise the request is dispatched to the run loop like any other RPC. The handler registered by Raft is processHeartbeat, which checks shutdown and the command type and then calls the same appendEntries handler the run loop uses.；条件：Applies to NetworkTransport (and to transports that implement SetHeartbeatHandler); InmemTransport declines the fast path and pushes heartbeats onto the consumer channel. The classification depends on request field values, not on an explicit RPC type.。
- `d3b8b97b4e5e491189c06b05ec8b2fae-knowledge-1` r1 · behavior：For a heartbeat-shaped request the reachable mutations are narrow: the older-term check can return without touching state, a newer term or the sentinel condition sets the state to Follower and adopts the term, the leader address and ID are recorded, and success sets last contact; the previous-log check, the entry loop, configuration processing and the commit-index update are all skipped because PrevLogEntry is zero, there are no entries and LeaderCommitIndex is zero. Each reachable mutation goes through a synchronised accessor (atomic state or lastLock for snapshot/log indexes), leaderLock, lastContactLock, or a channel send for observer notification.；条件：Applies to the appendEntries code path when invoked with a heartbeat-shaped request, whether by the transport fast path or the run loop; a request with entries, a non-zero PrevLogEntry or a non-zero LeaderCommitIndex takes the ordinary path and is not covered by this statement.。
- `d3b8b97b4e5e491189c06b05ec8b2fae-knowledge-2` r1 · behavior：The leader's heartbeat goroutine sends a request carrying only the RPC header, term and leader fields, so its LeaderCommitIndex is zero; on a successful response it refreshes last contact, resets the failure count and notifies any waiting verify futures with the response's success value. Followers therefore learn the leader's commit index from the replicate loop's random CommitTimeout path rather than from heartbeats.；条件：Applies to the leader-side heartbeat routine for each peer in the captured revision; the same shape is what the receiving network transport classifies as a heartbeat.。
- `aa7d57947d8f4eb8bed8cb78688a4feb-knowledge-0` r1 · behavior：GetConfiguration returns a configurationsFuture whose configurations value is built from the atomically published latest configuration only, so Configuration() reports the real membership while Index() reports the zero value for every caller regardless of the configuration entry the value came from. The membership-change guard in nextConfiguration only enforces prevIndex when it is greater than zero, so an index taken from GetConfiguration cannot express the documented condition that the change applies only to the configuration that was read.；条件：Applies to Raft.GetConfiguration on any server and to every membership change command routed through nextConfiguration; the internal configuration tracking filled from the main thread through configurationsCh does carry the index and is unaffected.。
- `a0b4af872b994e478c880e57485154a6-knowledge-0` r2 · fact：In a live four-voter cluster whose latest configuration entry index was 3, three nodes returned a configuration with four servers while GetConfiguration's Index() reported 0, so the reported index did not identify the configuration returned by the same call; a membership change guarded with that returned value was applied after an intervening change (entry 4 -> 5), while the same change guarded with the genuine index 3 was rejected with 'configuration changed since 3 (latest is 5)'.；条件：Observed in one execution with MakeCluster(3) plus one joining voter through the in-memory transport, protocol 3, reading GetConfiguration on every node after AddVoter returned index 3 and then applying a guarded change; one node's read was outside applicability because it still showed three servers at read time. The values are an observed instance under these conditions, not a claim about internal configuration state.。
  原 r1：In a live four-voter cluster whose latest configuration entry index was 3, three nodes returned a configuration with four servers while GetConfiguration's Index() reported 0, so the reported index did not identify the configuration returned by the same call; a membership change guarded with that returned value was applied after an intervening change (entry 4 -> 5), while the same change guarded with the genuine index 3 was rejected with 'configuration changed since 3 (latest is 5)'.；更正：；受影响引用：无登记。
- `ab8ea0d2f60f422796f9d946edf40b48-knowledge-0` r1 · behavior：A leader that cannot contact a quorum stops being leader through the lease check rather than through the verification itself: the leader loop samples per-peer last contact and steps down when fewer than quorumSize voters were contacted within LeaderLeaseTimeout, after which the step-down cleanup responds ErrLeadershipLost to every future still in the leader's notify set. VerifyLeader therefore completes with an error in the order of the lease when its peers are silent, and configuration validation requires LeaderLeaseTimeout to be at least 5ms and no larger than HeartbeatTimeout.；条件：Applies to Raft.VerifyLeader on a leader whose peers are unreachable in the captured revision; the request itself only counts replies and a false reply steps the leader down immediately, while silence is resolved by the lease check and the step-down cleanup.。
- `7823fda370ca4a11b3e4d0ad9908eb1b-knowledge-0` r1 · fact：In a three-node cluster with heartbeat, election and leader-lease timeouts all 300ms, VerifyLeader on the healthy leader returned nil immediately (0ms) while the node stayed Leader, and after isolating the leader from both followers the same call completed in 306ms with the error 'leadership lost while committing log', leaving the node in state Follower.；条件：Observed in one fault-free execution through the in-memory transport where the leader was partitioned with c.Partition, the client waited up to 6s on the returned future, and the leader was still in the Leader state when the isolated call was issued. The values are an instance under these conditions and not a bound for other timeout ratios or loaded hosts.。
- `3e1c60d4f59d4003a5efce001e1e4374-knowledge-0` r1 · fact：In twenty-five rounds of the captured upgrade scenario the published configuration reached every node with a per-round maximum wait between 0ms and 6ms (median 0ms) and the configuration entry was present in every node's log store; no round showed a node publishing the old membership while its own log already contained the configuration entry (all_converged true and any_lag_with_entry false in 25 of 25 rounds, 75 of 75 node results converged).；条件：Observed with twenty-five fresh in-memory clusters of a protocol-2 pair plus a protocol-3 joiner, each round following one AddVoter of the joiner, polling every 5ms for up to 3s, reading only the atomically published configuration content and the log store. This is a bounded repeated observation for this scenario and not a general guarantee; the earlier local failures of the captured test were not reproduced and remain unexplained.。
- `83e05a1268184d598ceffcdfe382b2d6-knowledge-0` r1 · behavior：ReloadConfig merges exactly the five reloadable fields (TrailingLogs, SnapshotInterval, SnapshotThreshold, HeartbeatTimeout, ElectionTimeout) onto the current configuration under a reload lock, runs the same validation used at construction on the merged result, and stores it only when validation succeeds; on failure it returns the validation error without storing anything. After a successful reload that lowers the heartbeat timeout it additionally notifies the leader and follower notification channels so replication and heartbeat timers adopt the shorter value, while other reloadable decreases take effect at the next natural timer.；条件：Applies to Raft.ReloadConfig on a running node in the captured revision; fields outside the reloadable set, such as the leader lease, are not reloadable and are taken from the current configuration when the merged result is validated.。
- `50470719317e436ab8ffb5b992db7441-knowledge-0` r1 · fact：On a running single-node cluster with heartbeat and election at 50ms and leader lease at 50ms, a reload setting heartbeat and election to 10ms was rejected with 'LeaderLeaseTimeout (50ms) cannot be larger than heartbeat timeout (10ms)' and the reported reloadable configuration stayed unchanged at 50ms, while a reload setting heartbeat and election to 100ms was accepted and reported, with the lease still 50ms.；条件：Observed in one fault-free execution through the in-memory transport on a single node, comparing ReloadableConfig before and after each attempt. The values are an instance under these conditions; other validated fields and other invalid combinations were not exercised.。
- `246186dca08549b4a8535799f9742a99-knowledge-0` r1 · behavior：A node exposes three intentionally different progress views: LastIndex is the last index in stable storage including the snapshot index, CommitIndex is the committed index, and AppliedIndex is the last index sent to the FSM thread's apply channel, which the documentation explicitly says does not mean the FSM has consumed and applied it. The value is written when processLogs dispatches a batch to the FSM thread, so application state may lag it. Snapshot metadata is a fourth, FSM-thread-owned value: runFSM reports the index it has accounted for in a snapshot request, and takeSnapshot refuses to snapshot when that index is below the committed configuration index, so no accessor drives snapshot metadata.；条件：Applies to the captured revision's accessors Raft.LastIndex, Raft.CommitIndex and Raft.AppliedIndex and to the snapshot request path; the values may differ at any instant, especially while the FSM thread has queued work.。
- `46289ca57dde4a1181f22bd834b3523d-knowledge-0` r1 · behavior：HasExistingState reports existing state when the stable store's current term is above zero, or the log store's last index is above zero, or the snapshot store lists at least one snapshot; a 'not found' reading of the term is treated as no term while other term errors are returned, and log and snapshot errors are returned. NewRaft correspondingly restores any old state (snapshots, logs, peers) when constructing the node. The helper does not consult the persisted vote directly, but in the captured write paths a vote is only persisted after the term has been raised durably (setCurrentTerm before persistVote in both the election path and the vote-handling path), so a stored vote implies a non-zero current term and is covered by the first check.；条件：Applies to HasExistingState with any LogStore, StableStore and SnapshotStore, and to NewRaft's restore behaviour in the captured revision; the vote-order argument applies to the two write paths present in this revision.。
- `5f9e27a6f308417e8bf9ca4c60f970dc-knowledge-0` r1 · behavior：The LogStore interface promises FirstIndex and LastIndex returning 0 when there are no entries, requires GetLog/StoreLog/DeleteRange (inclusive range), and explicitly allows StoreLogs to leave a gap between previous logs and the stored batch. Raft relies on that gap as the signal that logs before a restored snapshot are discontinuous, and offers MonotonicLogStore.IsMonotonic for stores that cannot tolerate gaps, in which case Raft removes all previous logs after a snapshot restore instead of relying on the gap. The captured in-memory store indexes entered logs by index and does not implement the opt-in, so it relies on the documented freedom.；条件：Applies to any LogStore implementation used with the captured revision; the gap-reliance affects the paths that resynchronise followers and restore snapshots, and the opt-in is only consulted where old logs are removed.。
- `5f9e27a6f308417e8bf9ca4c60f970dc-knowledge-1` r1 · behavior：Two documented contracts bound what the log types mean. A LogBarrier exists to ensure all preceding operations have been applied to the FSM and only returns once the FSM manager acknowledges it, so it is not equivalent to a committed no-op. A log entry's AppendedAt is operational information only: it is not used for coordination or as part of the replication protocol, followers may observe a future timestamp due to clock skew, and the leader is not required to persist before delivering to followers. The oldest-log helper tolerates truncation racing with its read by retrying until the first index is stable or a hard error is returned.；条件：Applies to the captured revision's barrier handling, to any component that reads AppendedAt (for example age metrics), and to the oldest-log metric helper.。
- `6962a0dc36854f06b25086c2b0574c7c-knowledge-0` r1 · behavior：When the leader's protocol version is below 2, every membership change is appended as the deprecated remove-peer entry carrying encodePeers output, and encodePeers gathers only servers whose suffrage is Voter, with the comment that other suffrage types are not supported by that format; the matching decoder reconstructs a configuration of voters only, and the same encoder is also used to fill the peers field of a vote response for protocol-version-below-2 servers. The versioned configuration format is used for protocol version 2 and above.；条件：Applies to appendConfigurationEntry on a leader with protocolVersion below 2 and to decodePeers wherever a deprecated entry is processed; the lossy property only matters if the computed configuration contains a non-voter or staging server, which the deprecated format cannot represent.。
- `8d8ffb8edcfb4ca79bfbcf1fb35683f3-knowledge-0` r1 · behavior：Shutdown is idempotent and two-phased: the first call takes the shutdown lock, closes the shutdown channel, records the node as shut down, sets the Shutdown state and returns a shutdown future bound to the node, while subsequent calls return a bare shutdown future so nothing is closed twice. The bound future's Error waits for the node's goroutine group and then closes the transport if it implements WithClose; work that is queued for the FSM thread when the shutdown channel closes is answered with ErrRaftShutdown by the dispatching code instead of being left pending.；条件：Applies to Raft.Shutdown in the captured revision and to the dispatch paths that select on the shutdown channel, such as the processLogs batch handoff; the transport is only closed when it implements WithClose.。
- `04c20350eed842e49c7f1229f2968eba-knowledge-0` r1 · behavior：An observation carries the emitting Raft instance and an event payload that is one of the documented types (a vote request, a Raft state, a peer change, a leader change and the heartbeat-failure/resume observations). Delivery is per observer and best-effort by default: a non-blocking observer gets a non-blocking send and the library counts the observation as dropped when its channel is full, while a blocking observer performs a plain send that applies backpressure to the emitting goroutine. Each observer can have a filter that suppresses delivery, and both counters are maintained per observer. Registration and deregistration take the observers write lock while delivery iterates under the read lock, so a blocking observer blocks the emitting goroutine but only prevents registrations, not other observers from being visited.；条件：Applies to Raft.RegisterObserver/DeregisterObserver and to every observe call site in the captured revision; losslessness is not promised for the default non-blocking observer, and the blocking mode is opt-in per observer.。
- `71da525e349f4f9281515c56c0aeeff0-knowledge-0` r1 · behavior：Barrier appends a barrier log entry and resolves the caller only when that entry has been acknowledged by the FSM thread, so a successful call means all preceding operations have been applied to the FSM; the call is only issuable on the leader and fails otherwise, and a timeout supplied to Barrier bounds how long the caller waits for the command to be started (enqueued), not how long the FSM takes to apply it. That pairs with the log-level contract of the barrier type itself, which exists precisely to be stronger than a committed no-op.；条件：Applies to Raft.Barrier in the captured revision; the timeout parameter is an enqueue bound, and the completion of the returned future is what indicates that preceding operations have reached the FSM.。
- `9dccaf2e005b48f0b226c3557732d731-knowledge-0` r1 · behavior：Every incoming RPC is admitted only after its header's protocol version is checked twice: a message whose protocol version is outside the supported range is rejected as unsupported, and a message whose version is more than one behind the receiver's own configured protocol version is rejected as well. A receiver therefore serves messages from its own version and one version older, which is what allows adjacent-version mixed deployments during rolling upgrades, while an older sender is refused outright rather than silently misinterpreted.；条件：Applies to every RPC dispatched through the run loop's processRPC path in the captured revision, including append entries, vote and pre-vote requests, snapshots and the leadership-transfer message; the check is on the RPC header, so it constrains peers rather than the local configuration format.。
- `0c4e85a704e844668bbd9eb7aaad5797-knowledge-0` r1 · behavior：When the FSM implements BatchingFSM, the apply loop sends only command and configuration entries to ApplyBatch, in commit order and without gaps; no-ops and barriers are excluded from the batch but still advance the batch's index and term bookkeeping, so the FSM thread's reported index covers the whole batch. Responses are mapped back to the entries that were sent, one per sent log in order, and every queued future in the batch is answered in input order - a future whose entry was not sent receives a nil response, and a response count that does not match the number of sent logs panics rather than being silently truncated. Without BatchingFSM the same loop applies entries one at a time.；条件：Applies to the captured revision's FSM thread for an FSM that implements BatchingFSM; batches are bounded by MaxAppendEntries and are built by processLogs, so the exclusions concern entry types rather than whole batches.。

## 执行成本与原始记录

Agent 调用 49 次；控制器目标执行 11 次。
目标进程累计秒数：172.022421；含准备的动作秒数：177.44419497500166；两者不相加。
请求模型：`deepseek-flash` / `high`；服务端模型版本仅以回执为准。
[完整状态与历史](state.json)、[当前工作索引](research.json)、[实际配置](config.json)、[事件](events.jsonl)。
源码身份、工具成功及模型解释各有边界；脚本化产品仅验证框架，不作为自主发现证据。
