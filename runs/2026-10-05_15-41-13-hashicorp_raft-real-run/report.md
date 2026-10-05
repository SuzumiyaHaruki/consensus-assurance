# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 5 项；当前 Unit 4 项、义务 4 项、固定检查制品 4 项。正式执行尝试 4 次；已保存评估的义务 4 项，其中有实际比较 4 项。已确认违反 3 项、有限检查未见违反 1 项、待调查线索 0 项；另有已获源码解释的 Candidate 1 项。受理、执行与结论分别计数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、11 次 Agent 调用、2 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.24 | 0.00 |
| Agent 调用 | 40 | 29 | 11 |
| 控制器目标执行 | 8 | 6 | 2 |
| 新 Unit | 4 | 4 | 0 |
| 语义复核 | 6 | 4 | 2 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 71.19 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 73.39 秒。

目标执行组成：正式检查 4 次＋探索 2 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v52`；展示版本 `audit-products-v52`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/4c4961ad4c024385b44696e477a7698b/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`8.649562370999774`（配置值不表示触发了超时）。
[调用记录](logs/4c4961ad4c024385b44696e477a7698b/check.json)；[stdout](logs/4c4961ad4c024385b44696e477a7698b/stdout.log)；[stderr](logs/4c4961ad4c024385b44696e477a7698b/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 配置变更持久化失败后仍发布新配置 | 已确认违反 | 在单节点 leader 上注入一次 StoreLogs 失败后，AddVoter 返回注错错误、日志末索引仍为 2、已提交配置索引仍为 1，但该节点的最新配置已变为 2 个 voter、latestIndex=3，即采纳了日志中并不存在的成员集合；对应属性 latest_voter_count 等于尝试前的 1 被判为 violated。 | [oblig-config-from-durable-entry](#claim-oblig-config-from-durable-entry) |
| 2. 未落盘的配置会被标记为已提交 | 已确认违反 | 同一场景走完后，节点 A 仍为 Leader，其已提交配置含 2 个 voter、配置索引为 3，但索引 3 的日志条目类型是 LogNoop，且加入节点的自身配置只有 1 个 voter；属性（已提交配置含 2 个 voter 时该索引必须是配置条目）被判为 violated。 | [oblig-config-committed-backed-by-entry](#claim-oblig-config-committed-backed-by-entry) |
| 3. GetConfiguration 的配置索引恒为 0 | 已确认违反 | 在已提交的单节点集群上，最新配置写在索引 1（已提交配置索引也为 1），但 Raft.GetConfiguration().Index() 返回 0，且 Raft.Stats 的 latest_configuration_index 同为 "0"，read_error 为 nil；属性 reported_index ==… | [oblig-config-readout-index](#claim-oblig-config-readout-index) |
| 4. 重启后只恢复日志中存在的配置 | 有限检查未见违反 | 重启前该节点已提交 2 个 voter 的配置（索引 3，写盘曾失败一次）；用相同 store 重启后它重新变为 Leader，最新配置只有 1 个 voter、索引 1，且该索引上的条目类型为 LogConfiguration（读取无错误），即重启后节点按日志恢复配置；对应属性因前置条件（重启后报告 2 个 voter）不成立而… | [oblig-restart-config-log-backed](#claim-oblig-restart-config-log-backed) |
| Is a heartbeat delivered through the transport fast path serialized with the main loop before it updates the receiver's term,… | 源码解释，未经性质执行 | setState and setCurrentTerm use atomic stores and setLeader uses a mutex, so a pure heartbeat does not produce a torn read of any single field；a pure heartbeat carries… | [候选原文与来源](state.json) |

<a id="claim-oblig-config-from-durable-entry"></a>

### 1. 配置变更持久化失败后仍发布新配置

**已确认违反**。要求原文：A server must not publish or commit a configuration change as its latest configuration unless the corresponding configuration log entry was durably stored, so that the voter set used for quorum, election eligibility and the leader lease always corresponds to an entry present in the log or snapshot.

决定性范围：One configuration change attempted by a stable leader whose durable log write for that configuration entry fails.
configurationChangeChIfStable has admitted the request (latest==committed and the leader has committed an entry of its term)；the only faulted component is the LogStore's StoreLogs call。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/f30f1a06376c4c90ae7671e61e7159f1/assurance_generated_test.go)；[条件与检查器](direct-checks/f30f1a06376c4c90ae7671e61e7159f1/plan.json)；[原始观察](logs/96a2fe479e6d4bf895ca503bd3ee8a29/stdout.log)；[assessment](direct-checks/f30f1a06376c4c90ae7671e61e7159f1/96a2fe479e6d4bf895ca503bd3ee8a29-assessment.json)；[对应性复核](submissions/40182703dbea40e9868391cfcbade498/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.61 秒；执行进程耗时 11.43 秒；[实际命令、工具版本与输入记录](logs/96a2fe479e6d4bf895ca503bd3ee8a29/check.json)
执行边界：Single-voter in-memory cluster; a LogStore wrapper fails exactly one StoreLogs call; the harness admits a configuration-append attempt and reports the node's latest/committed configuration indexes and latest voter count afterwards.；A LogStore wrapper fails exactly one StoreLogs call; no target source is replaced；election/heartbeat/lease timeouts are shortened and the log level is raised to ERROR so the single-voter election completes quickly；the harness reads the Raft instance's latest/committed configuration after the injected failure
固定比较 `ck-config-from-durable-entry`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| attempt | config-append-1 |
| phase | after_failed_append |
| store_failed | true |
| latest_voter_count | 2 |
| attempt.pre_voter_count | 1 |
| append_error | assurance: injected log store failure |
| committed_index | 1 |
| event | config_state_after_failure |
| latest_index | 3 |
| log_last_index | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-oblig-config-committed-backed-by-entry"></a>

### 2. 未落盘的配置会被标记为已提交

**已确认违反**。要求原文：A server must not treat a configuration as committed unless the log entry at that configuration index is a configuration entry encoding that configuration, so the voter set used for quorum, election eligibility and the leader lease is always backed by an agreed log entry.

决定性范围：One node that adopted an unpersisted configuration and later returned to the leader state with the vote of a fresh peer, compared with the log entry at its committed configuration index.
the node's configuration entry write failed once, so its latest configuration has no supporting entry；the joining peer starts without a configuration, as a fresh node does。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/7ef5901155e64103956200d5f738ee92/assurance_generated_test.go)；[条件与检查器](direct-checks/7ef5901155e64103956200d5f738ee92/plan.json)；[原始观察](logs/f3a70e0ed6fa4a30b0f2ee8179c1de81/stdout.log)；[assessment](direct-checks/7ef5901155e64103956200d5f738ee92/f3a70e0ed6fa4a30b0f2ee8179c1de81-assessment.json)；[对应性复核](submissions/87133f954ddf4c3fbe67e5c75204af6b/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.75 秒；执行进程耗时 12.31 秒；[实际命令、工具版本与输入记录](logs/f3a70e0ed6fa4a30b0f2ee8179c1de81/check.json)
执行边界：Two-node in-memory cluster: node A bootstraps as a single voter, one injected StoreLogs failure during AddVoter leaves it holding an unpersisted configuration, and node B joins with an empty configuration. The harness admits the adoption event and then reports the committed configuration, its index, the log entry type at that index and the peer's voter count.；one LogStore wrapper fails exactly one StoreLogs call; no target source is replaced；the joining peer starts unbootstrapped with an empty configuration and log, standing in for a fresh node；election and heartbeat timeouts are shortened and the log level is raised to ERROR so the sequence completes quickly
固定比较 `ck-committed-config-backed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | phantom-1 |
| phase | after_recovery |
| committed_voter_count | 2 |
| log_entry_is_configuration | false |
| committed_config_index | 3 |
| committed_log_last_index | 3 |
| event | committed_config_state |
| log_entry_read_error | <nil> |
| log_entry_type_at_config_index | LogNoop |
| node_state | Leader |
| peer_config_voter_count | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-oblig-config-readout-index"></a>

### 3. GetConfiguration 的配置索引恒为 0

**已确认违反**。要求原文：Raft.GetConfiguration must report, through the returned future's Index, the log index at which the node's latest configuration was written, so that a caller can order or fence later configuration changes on it; the reported index must not be a value the constructor never assigns.

决定性范围：One synchronous Raft.GetConfiguration call on a node whose latest configuration is committed, compared with the index at which that configuration was written.
the caller may call GetConfiguration from any goroutine, as the API documents；the latest configuration index is observable on the same node。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/36e09e497bab4899a4bd5d03a54fbfb2/assurance_generated_test.go)；[条件与检查器](direct-checks/36e09e497bab4899a4bd5d03a54fbfb2/plan.json)；[原始观察](logs/458dbca4e1f14745aa3358f60007e9f8/stdout.log)；[assessment](direct-checks/36e09e497bab4899a4bd5d03a54fbfb2/458dbca4e1f14745aa3358f60007e9f8-assessment.json)；[对应性复核](submissions/d358d55fc11b41a3b6d39f455ef9ec83/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.17 秒；执行进程耗时 10.98 秒；[实际命令、工具版本与输入记录](logs/458dbca4e1f14745aa3358f60007e9f8/check.json)
执行边界：Single-voter in-memory cluster driven to the leader state; the harness admits one config_index_probe carrying the live latest configuration index and then reports the index returned by GetConfiguration().Index() plus the Stats readout.；election/heartbeat/lease timeouts are shortened and the log level is raised to ERROR so the single-voter election completes quickly；the harness reads the live latest configuration index for the probe and the public API readout for the result; no target source is replaced
固定比较 `ck-config-index-readout`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| probe | cfg-index-1 |
| phase | readout |
| reported_index | 0 |
| probe.live_latest_config_index | 1 |
| event | config_index_readout |
| live_latest_config_index_now | 1 |
| read_error | <nil> |
| stats_reported_index | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-oblig-restart-config-log-backed"></a>

### 4. 重启后只恢复日志中存在的配置

**有限检查未见违反**。要求原文：A restarted server must report as its latest configuration only a configuration that is encoded by the configuration entry at the index it reports, so that the voter set it acts on after recovery is always backed by its own log.

决定性范围：One node restarted over identical stores after it had committed a configuration whose entry was never written.
the same LogStore, StableStore, SnapshotStore and transport are reused with a fresh FSM；no fault is injected into the restart itself。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/891902f8243d485f804a60e5548f1675/assurance_generated_test.go)；[条件与检查器](direct-checks/891902f8243d485f804a60e5548f1675/plan.json)；[原始观察](logs/eff72fbd4d964106bac23d2173842459/stdout.log)；[assessment](direct-checks/891902f8243d485f804a60e5548f1675/eff72fbd4d964106bac23d2173842459-assessment.json)；[对应性复核](submissions/cf2b1c94fbcb460190639fad1ca7dd23/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.70 秒；执行进程耗时 12.26 秒；[实际命令、工具版本与输入记录](logs/eff72fbd4d964106bac23d2173842459/check.json)
执行边界：Two in-memory nodes; node A's configuration write is failed once and it later commits the adopted configuration with the help of a fresh peer; node A is then shut down and a new Raft instance is created over the same stores, and the harness reports the re-derived configuration and the log entry at its index.；one LogStore wrapper fails exactly one StoreLogs call; no target source is replaced；the restarted instance reuses the same LogStore, StableStore, SnapshotStore and transport as the original, with a fresh FSM；timeouts are shortened and the log level is raised to ERROR so the sequence completes quickly
固定比较 `ck-restart-config-backed`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| scenario | restart-1 |
| phase | after_restart |
| restarted_latest_voter_count | 1 |
| log_entry_is_configuration | true |
| event | restart_configuration_state |
| log_entry_read_error | <nil> |
| log_entry_type_at_latest_config | LogConfiguration |
| restarted_committed_config_index | 1 |
| restarted_committed_voter_count | 1 |
| restarted_latest_config_index | 1 |
| restarted_log_last_index | 4 |
| restarted_state | Leader |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：Does the transport heartbeat handler answer an incoming AppendEntries heartbeat the same way after the node has been shut down as it does while the node is running, or does the shutdown branch drop…
所选问题／策略（原文摘录）：Resolve the last executable residual by construction: the transport heartbeat handler returns without answering when the node is shut down, and this exploration compares the same handler call while the node is running and after a clean…
[受理问题、条件与来源](submissions/e18e7851798149d3a7d5960882687d90/accepted.json)；[固定输入](submissions/e18e7851798149d3a7d5960882687d90/inputs/harness_heartbeat_shutdown.go)
<a id="exploration-cddc83f40d9a47d38b31bc51db19e435"></a>
[探索执行 1](#exploration-cddc83f40d9a47d38b31bc51db19e435)：未进入测试：包发现／构建准备失败；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/cddc83f40d9a47d38b31bc51db19e435/check.json)；[实际输出](logs/cddc83f40d9a47d38b31bc51db19e435/stdout.log)；[诊断](logs/cddc83f40d9a47d38b31bc51db19e435/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.41 秒；执行进程耗时 10.93 秒；[实际命令、工具版本与输入记录](logs/cddc83f40d9a47d38b31bc51db19e435/check.json)
[执行文件清单](experiments/412d061e522a4842bedbb368997e6cfc/workspace-delta/manifest.json)；[执行文件清单](experiments/412d061e522a4842bedbb368997e6cfc/workspace-outcome/manifest.json)；[执行文件清单](experiments/412d061e522a4842bedbb368997e6cfc/workspace/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

条件探索：Does the transport heartbeat handler answer an incoming AppendEntries heartbeat the same way after the node has been shut down as it does while the node is running, or does the shutdown branch drop…
所选问题／策略（原文摘录）：Retry the heartbeat-handler exploration with the compile error fixed: the RPC response channel is send-only on the target struct, so the harness now owns a bidirectional channel and passes it as RespChan, receiving the response from its…
[受理问题、条件与来源](submissions/b556c143953e4720a9d9bac5894ba0f5/accepted.json)；[固定输入](submissions/b556c143953e4720a9d9bac5894ba0f5/inputs/harness_heartbeat_shutdown.go)
<a id="exploration-318454ef0fb447c695271945bf024c25"></a>
[探索执行 2](#exploration-318454ef0fb447c695271945bf024c25)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/318454ef0fb447c695271945bf024c25/check.json)；[实际输出](logs/318454ef0fb447c695271945bf024c25/stdout.log)；[诊断](logs/318454ef0fb447c695271945bf024c25/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.75 秒；执行进程耗时 13.29 秒；[实际命令、工具版本与输入记录](logs/318454ef0fb447c695271945bf024c25/check.json)
[执行文件清单](experiments/af9083ba20bd47ffaa3ea4451b785321/workspace-delta/manifest.json)；[执行文件清单](experiments/af9083ba20bd47ffaa3ea4451b785321/workspace-outcome/manifest.json)；[执行文件清单](experiments/af9083ba20bd47ffaa3ea4451b785321/workspace/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v16：概览、Behavior／Fact 与来源](audit-spec/v16.json)。
- 共识形成与推进（原文导航摘录）：The leader appends each accepted command as a local log entry for its term (b-dispatch-logs), then each per-peer replication goroutine pushes AppendEntries and reports the highest index the peer has stored…
- 上下文／权威转换（原文导航摘录）：Authority is scoped to a term and to the voter set of the latest configuration. A follower that stops hearing a leader becomes a candidate (b-heartbeat-timeout); the candidate proposes and persists the next term and…
- 两条主线的连接（原文导航摘录）：A1 and A2 meet on three sourced points. First, the term-start-index rule in the commitment makes the leader's own new-term entry a precondition for committing anything, so a server that merely won an election cannot…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.63 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 10.41 分钟 · 实际执行：配置变更持久化失败后仍发布新配置；执行完成；比较见 assessment。[执行记录](logs/96a2fe479e6d4bf895ca503bd3ee8a29/check.json)

- 11.62 分钟 · 受理 review：配置变更持久化失败后仍发布新配置。[完整交接](submissions/40182703dbea40e9868391cfcbade498/accepted.json)

- 15.32 分钟 · 实际执行：GetConfiguration 的配置索引恒为 0；执行完成；比较见 assessment。[执行记录](logs/458dbca4e1f14745aa3358f60007e9f8/check.json)

- 16.18 分钟 · 受理 review：GetConfiguration 的配置索引恒为 0。[完整交接](submissions/d358d55fc11b41a3b6d39f455ef9ec83/accepted.json)

- 18.81 分钟 · 受理 explained：Resolve the paused heartbeat-fast-path candidate with the mechanism that actually protects the authority context, rather than leaving a…。[完整交接](submissions/29037eddf588447a8b6a6447b04ca41a/accepted.json)

- 19.84 分钟 · 受理 continue：Record the answered heartbeat mechanism in the map and open the next safety-relevant question. The explained candidate showed that the fast…。[完整交接](submissions/c35ac0f294e44cfbadd8bc2c4aa7cbd3/accepted.json)

- 21.68 分钟 · 实际执行：未落盘的配置会被标记为已提交；执行完成；比较见 assessment。[执行记录](logs/f3a70e0ed6fa4a30b0f2ee8179c1de81/check.json)

- 22.73 分钟 · 受理 review：未落盘的配置会被标记为已提交。[完整交接](submissions/87133f954ddf4c3fbe67e5c75204af6b/accepted.json)

- 26.69 分钟 · 实际执行：重启后只恢复日志中存在的配置；执行完成；比较见 assessment。[执行记录](logs/eff72fbd4d964106bac23d2173842459/check.json)

- 27.46 分钟 · 受理 review：重启后只恢复日志中存在的配置。[完整交接](submissions/cf2b1c94fbcb460190639fad1ca7dd23/accepted.json)

- 32.77 分钟 · 实际执行：Resolve the last executable residual by construction: the transport heartbeat handler returns without answering when the node is shut down,…；未进入测试：包发现／构建准备失败。[执行记录](logs/cddc83f40d9a47d38b31bc51db19e435/check.json)

- 33.82 分钟 · 实际执行：Retry the heartbeat-handler exploration with the compile error fixed: the RPC response channel is send-only on the target struct, so the…；探索执行正常结束。[执行记录](logs/318454ef0fb447c695271945bf024c25/check.json)

- 36.96 分钟 · 受理 research：Remove the last stale statement in the map. The A2 activity still carried the heartbeat-ordering question that the behavior-level work has…。[完整交接](submissions/0c5624b6b3f4414b89aeadd289af00bd/accepted.json)

- 38.07 分钟 · 受理 research：Record the transport-side consequence of the observed shutdown branch. Reading the transport's response wait shows it selects only on the…。[完整交接](submissions/4ab9855e3bf0457fb9c79e9eb1a9bffe/accepted.json)

- 39.84 分钟 · 受理 research：One last sourced addition: the transport surface now records the consequence of the fast-path response wait, which has no deadline, so a…。[完整交接](submissions/385eb39a5ebe419186cedf2193e1d49f/accepted.json)

- 40.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/4c4961ad4c024385b44696e477a7698b/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

2 次探索已有原始执行记录，尚待受理解释；前提与观察是否达到仍需核对：[探索执行 1](#exploration-cddc83f40d9a47d38b31bc51db19e435)；[探索执行 2](#exploration-318454ef0fb447c695271945bf024c25)

### 地图登记与研究交接

以下是地图 v16 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v16：概览、Behavior／Fact 与来源](audit-spec/v16.json)

- core_overview：The heartbeat fast path (Raft.processHeartbeat, installed by NewRaft and dispatched from NetworkTransport.handleConn) runs appendEntries off the main loop for pure heartbeats; the fields touched are…
  尚无精确对应交接。

- b-commit-quorum：Whether the majority-intersection reasoning covers every permitted sequence of one-at-a-time changes is not established by execution; reading only shows that at most one uncommitted change is…
  相关交接：[交接 1](submissions/319847d9ad82453cacecfd3bfafe4ccf/accepted.json)

- b-follower-append：The (setState, setCurrentTerm) pair in appendEntries is not atomic as a pair, so an off-thread heartbeat and a concurrent campaign can still interleave at the field level; whether an external reader…
  尚无精确对应交接。

- b-prevote：Whether an inflated pre-vote tally in a mixed-version cluster (a peer without the pre-vote RPC is counted as granting) causes avoidable election churn is not established; the pre-vote itself grants…
  相关交接：[交接 1](submissions/a411364a13604fcba807a3107b7c6072/accepted.json)

- b-leadership-transfer：Whether a non-leader or stale peer can use TimeoutNow to cause repeated election rounds is not established; the request's term and sender are not consulted.
  相关交接：[交接 1](submissions/a411364a13604fcba807a3107b7c6072/accepted.json)

- b-config-change：Whether an application FSM that applied entries under the in-memory configuration is consistent with the configuration re-derived after a restart is not established.
  相关交接：[交接 1](submissions/37f8587b7a894993afeca7d9456f2d84/accepted.json)；[交接 2](submissions/6af2cbb8b3e9472e8af40c72f4ffe9e3/accepted.json)；[交接 3](submissions/95d77925a8344c51854132272883edaf/accepted.json)；[交接 4](submissions/a3c83ff2c550442fa5d6a6711b3e015a/accepted.json)

- b-fsm-apply：Whether the election restriction always keeps truncation above every committed configuration index is argued from source reading rather than established by execution.
  相关交接：[交接 1](submissions/6af2cbb8b3e9472e8af40c72f4ffe9e3/accepted.json)

- b-config-readout：Whether any caller outside this repository depends on the reported configuration index cannot be settled from this snapshot; inside the snapshot only Raft.Stats consumes the future's Index()
  相关交接：[交接 1](submissions/319847d9ad82453cacecfd3bfafe4ccf/accepted.json)；[交接 2](submissions/a3c83ff2c550442fa5d6a6711b3e015a/accepted.json)

- b-offline-recovery：Whether a caller that fences a later change on the recovered configuration index can be misled is not established, because that index is a forced value rather than the index of a real entry.
  尚无精确对应交接。

- f-commit-quorum：Whether every permitted sequence of one-at-a-time configuration changes keeps a quorum of the latest configuration intersecting a quorum of the committed one is not established by execution.
  相关交接：[交接 1](submissions/f153f5c4cb174b73bd4c1ee8a6b31b56/accepted.json)；[交接 2](submissions/a3c83ff2c550442fa5d6a6711b3e015a/accepted.json)

- f-applied-prefix：Whether the FSM itself persists its effect is application-owned and not established here.
  尚无精确对应交接。

- surface:Transport.SetHeartbeatHandler：Transport-level plumbing that decides whether a request is fast-pathed to the beacon handler or delivered on the consumer channel; it is not itself a consensus obligation, and its response wait after…
  尚无精确对应交接。

- surface:raft-compat (multi-version test module)：A separate Go module that replaces github.com/hashicorp/raft with this working copy and pulls a previous release plus an older tag, then exercises mixed-version clusters for rolling upgrades and…
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[exploration](logs/cddc83f40d9a47d38b31bc51db19e435/stdout.log)；[stderr](logs/cddc83f40d9a47d38b31bc51db19e435/stderr.log)；[执行记录](logs/cddc83f40d9a47d38b31bc51db19e435/check.json)
