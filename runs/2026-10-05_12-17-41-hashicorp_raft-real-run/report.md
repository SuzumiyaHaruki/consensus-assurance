# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 4 项；当前 Unit 4 项、义务 4 项、固定检查制品 4 项。正式执行尝试 4 次；已保存评估的义务 4 项，其中有实际比较 4 项。已确认违反 3 项、有限检查未见违反 1 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、8 次 Agent 调用、4 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.28 | 0.00 |
| Agent 调用 | 40 | 32 | 8 |
| 控制器目标执行 | 8 | 4 | 4 |
| 新 Unit | 4 | 4 | 0 |
| 语义复核 | 6 | 4 | 2 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 47.92 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 49.76 秒。

目标执行组成：正式检查 4 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v51`；展示版本 `audit-products-v51`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/f1ba2518c0a24b2aa46f51a4cd3441a4/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`17.96219735900013`（配置值不表示触发了超时）。
[调用记录](logs/f1ba2518c0a24b2aa46f51a4cd3441a4/check.json)；[stdout](logs/f1ba2518c0a24b2aa46f51a4cd3441a4/stdout.log)；[stderr](logs/f1ba2518c0a24b2aa46f51a4cd3441a4/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：已记录完成事件；产物另行校验。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 截断后写入失败：跟随者日志水位超过持久日志 | 已确认违反 | 在仅注入一次 StoreLogs 失败、真实 DeleteRange 已删除冲突后缀之后，跟随者的内存日志水位仍为 (3,2)，而持久日志最后一个索引为 2，并返回 Success=false。断言 raft_last_log_index(3) == store_last_index(2)… | [claim-truncate-store-failure-watermark](#claim-claim-truncate-store-failure-watermark) |
| 2. 安装快照后未重置日志水位：跟随者报告已清除的日志索引 | 已确认违反 | 在成功安装索引为 4 的快照并清空日志存储（last_index=0）之后，跟随者的内存日志水位仍为 10，getLastIndex 也返回 10。断言 raft_last_log_index(10) == snapshot_index(4) 为假，形成一次直接高报持久日志的违规见证；可达性前提与领导者侧后果仍作为独立边界保留。 | [claim-snapshot-install-stale-watermark](#claim-claim-snapshot-install-stale-watermark) |
| 3. 快照触发阈值比较出现无符号下溢：日志滞后于快照时仍判定需要快照 | 已确认违反 | 在日志存储为空（last_index=0）、上次快照索引为 4、阈值为默认 8192 的重启恢复状态下，真实的 shouldSnapshot 返回 true（snapshot_due=true），即 0-4 的无符号差值回绕后超过阈值。断言 snapshot_due==false… | [claim-snapshot-trigger-underflow](#claim-claim-snapshot-trigger-underflow) |
| 4. 冲突截断后的配置回滚：最新配置与保留的已提交配置一致（有界无违规） | 有限检查未见违反 | 在一次合法的冲突截断（从未提交配置索引 3 处截断）之后，跟随者保留 latest_index=1、committed_index=1，原子发布副本暴露 1 台服务器配置，索引 3 处已是 term 9 的普通命令。断言 latest_index==committed_index… | [claim-config-rollback-consistency](#claim-claim-config-rollback-consistency) |

<a id="claim-claim-truncate-store-failure-watermark"></a>

### 1. 截断后写入失败：跟随者日志水位超过持久日志

**已确认违反**。要求原文：When appendEntries has deleted a conflicting log suffix and the subsequent StoreLogs of the leader's replacement entries returns an error, the follower must not continue with an in-memory log watermark (lastLog/lastLogIdx as returned by getLastLog/getLastIndex) that exceeds the log it durably holds. Either the watermark must be restored to a value consistent with the store after the failure, or the follower must stop presenting the deleted indices as present, so that a later legal AppendEntries is not accepted against a stale previous-log coordinate and the leader is not left repeatedly retrying against a follower that permanently rejects at the same index without an ErrLogNotFound that would trigger snapshot recovery.

决定性范围：The appendEntries error path after a successful truncation and a failing StoreLogs (raft.go 1524-1544), and the recovery it leaves for the leader's per-follower replication loop.
The LogStore is the injected implementation; a DeleteRange may succeed while a following StoreLogs of other entries returns an error, and the error is a legal return of the LogStore interface.；The conflicting AppendEntries is well formed (prevLogTerm matches at PrevLogEntry) so the truncation branch is reached before the store write fails.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/c10ac30f34bd4aa2b59419972cc1dc10/assurance_generated_test.go)；[条件与检查器](direct-checks/c10ac30f34bd4aa2b59419972cc1dc10/plan.json)；[原始观察](logs/de1a5dd120d44cfa887ed4a83c31c01a/stdout.log)；[assessment](direct-checks/c10ac30f34bd4aa2b59419972cc1dc10/de1a5dd120d44cfa887ed4a83c31c01a-assessment.json)；[对应性复核](submissions/0173f32a8d4b43fca1930c13dfd91300/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.21 秒；执行进程耗时 12.74 秒；[实际命令、工具版本与输入记录](logs/de1a5dd120d44cfa887ed4a83c31c01a/check.json)
执行边界：Package-internal Go test that seeds a real InmemStore, wraps it so StoreLogs fails on demand, builds a Raft instance with skipStartup so no background loop races the handler, invokes appendEntries directly on the main-thread path, and emits the follower watermark and store last index as CA_EVENT records.；StoreLogs of the injected LogStore is wrapped to return an error when armed; DeleteRange, GetLog, FirstIndex, LastIndex and the StableStore methods remain the unmodified InmemStore implementation, so the truncation still succeeds and only the replacement write fails.；The Raft instance is created with the internal skipStartup flag so the main loop and FSM goroutines do not run; appendEntries is invoked directly as the main-thread handler and LeaderCommitIndex is 0 so no FSM application is attempted.
固定比较 `chk-store-failure-watermark`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | assurance-node |
| write_failed | true |
| raft_last_log_index | 3 |
| store.store_last_index | 2 |
| store.write_failed | true |
| event | watermark_observed |
| raft_last_index | 3 |
| raft_last_log_term | 2 |
| reported_success | false |
| store_last_index | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-snapshot-install-stale-watermark"></a>

### 2. 安装快照后未重置日志水位：跟随者报告已清除的日志索引

**已确认违反**。要求原文：After installSnapshot has restored a snapshot at index S and has cleared or compacted the log store accordingly, the follower must not continue to report a log watermark (lastLogIndex/lastLogTerm as read by getLastLog/getLastIndex/getLastEntry) that describes entries the install has removed. Either the watermark must be reset to a value consistent with the installed snapshot and the retained log, or the follower must otherwise ensure that no reader - its own previous-log comparison, the AppendEntriesResponse.LastLog it returns, or any configuration reconstruction - treats a removed index as present.

决定性范围：The installSnapshot success path (raft.go 1814-1955) after the snapshot is restored, in particular the absence of any setLastLog before the log store is cleared or compacted, and the readers of the resulting watermark.
The SnapshotStore and LogStore are the injected implementations; the snapshot restore and the log clear/compaction are the unmodified library calls.；The follower's in-memory watermark index can be greater than the installed snapshot's LastLogIndex when the install begins.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/b5cad4d12d844479a64b76dff2fc56b4/assurance_generated_test.go)；[条件与检查器](direct-checks/b5cad4d12d844479a64b76dff2fc56b4/plan.json)；[原始观察](logs/af5ed6e5cd714a38bc74fced5d1bbcc5/stdout.log)；[assessment](direct-checks/b5cad4d12d844479a64b76dff2fc56b4/af5ed6e5cd714a38bc74fced5d1bbcc5-assessment.json)；[对应性复核](submissions/b4ef05794ee143cd9bbb46a1bd2e9522/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.11 秒；执行进程耗时 11.69 秒；[实际命令、工具版本与输入记录](logs/af5ed6e5cd714a38bc74fced5d1bbcc5/check.json)
执行边界：Package-internal Go test that seeds a real InmemStore wrapped to report IsMonotonic()=true, builds Raft with skipStartup, starts only the real runFSM consumer so the snapshot restore can complete, invokes installSnapshot directly on the main-thread path with a real msgpack FSM payload, and emits the installed snapshot index, the store's last index and the follower's own watermark as CA_EVENT records.；The LogStore is the real InmemStore with only IsMonotonic() added, so installSnapshot takes the removeOldLogs branch that clears the log; no read, write, delete or compaction logic is replaced.；The Raft instance is created with the internal skipStartup flag, then only the genuine runFSM goroutine is started so the handler's restore request can be consumed; the main loop and the snapshotter do not run, and installSnapshot is invoked directly as the main-thread handler.；The snapshot payload is produced with the package's own msgpack encoder so the real MockFSM.Restore path succeeds; the RPC framing layer is bypassed.
固定比较 `chk-install-snapshot-watermark`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | assurance-node |
| install_succeeded | true |
| raft_last_log_index | 10 |
| store.snapshot_index | 4 |
| store.install_succeeded | true |
| applied_index | 4 |
| event | watermark_observed |
| raft_last_index | 10 |
| raft_last_log_term | 1 |
| snapshot_index | 4 |
| snapshot_term | 1 |
| store_last_index | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-snapshot-trigger-underflow"></a>

### 3. 快照触发阈值比较出现无符号下溢：日志滞后于快照时仍判定需要快照

**已确认违反**。要求原文：The periodic snapshot trigger must not report that a snapshot is due when there are no log entries beyond the last snapshot. When the log store's last index is below the last snapshot index, the delta the trigger is deciding on must be treated as zero (or the trigger must otherwise avoid firing); it must not be computed as an unsigned difference that wraps into a value at or above SnapshotThreshold.

决定性范围：shouldSnapshot (snapshot.go 106-120) as called by runSnapshots, for a node whose log store's last index is at or below its last snapshot index.
The LogStore and SnapshotStore are the injected implementations; the restore path and the trigger are the unmodified library code.；The configured SnapshotThreshold is a positive value (the default is used).。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/33c180e9b3204244868ec453b611b4b5/assurance_generated_test.go)；[条件与检查器](direct-checks/33c180e9b3204244868ec453b611b4b5/plan.json)；[原始观察](logs/ef3cbb2ccf0f41239b71a02eadb8859b/stdout.log)；[assessment](direct-checks/33c180e9b3204244868ec453b611b4b5/ef3cbb2ccf0f41239b71a02eadb8859b-assessment.json)；[对应性复核](submissions/eed5fbff8b454c71b653a28c7d737c79/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.85 秒；执行进程耗时 11.43 秒；[实际命令、工具版本与输入记录](logs/ef3cbb2ccf0f41239b71a02eadb8859b/check.json)
执行边界：Package-internal Go test that pre-creates a real snapshot, builds Raft with skipStartup so the restore happens but no goroutine runs, asserts the restored snapshot coordinate and the empty log as preconditions, then calls the real shouldSnapshot handler and emits its result plus the measured indices as CA_EVENT records.；The node is built with the internal skipStartup flag so no background loop races the direct call to the periodic trigger; the trigger function, the stores, the snapshot store and the restore path are the unmodified implementation.；The snapshot payload is a genuine msgpack FSM snapshot produced with the package's own encoder so MockFSM.Restore succeeds, and the default SnapshotThreshold is used unchanged.
固定比较 `chk-snapshot-trigger`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | assurance-node |
| restored | true |
| snapshot_due | true |
| admit.restored | true |
| event | trigger_observed |
| log_store_last_index | 0 |
| snapshot_index | 4 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-config-rollback-consistency"></a>

### 4. 冲突截断后的配置回滚：最新配置与保留的已提交配置一致（有界无违规）

**有限检查未见违反**。要求原文：When appendEntries truncates a conflicting log suffix, the configuration state the follower continues to use must remain consistent with the retained log prefix: the latest configuration and its index must correspond to an entry the follower still holds at that index, and the committed configuration must not name an index inside the truncated range. After the rollback the follower must not publish, via Raft.GetConfiguration or via the membership and voter-count checks of requestVote/requestPreVote/quorumSize/checkLeaderLease, a configuration that is neither the committed configuration nor one backed by a retained configuration entry.

决定性范围：Follower-side truncation path of appendEntries (raft.go) when a conflict is detected at an index at or below configurations.latestIndex, and the configuration state visible afterwards.
The StableStore, LogStore and transport are the injected implementations; the transport delivers AppendEntries to the main thread.；The conflicting AppendEntries is well formed (prevLogTerm matches at PrevLogEntry) so the truncation branch is reached.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/6f010f21b7bb424dbbabaa4858e0c221/assurance_generated_test.go)；[条件与检查器](direct-checks/6f010f21b7bb424dbbabaa4858e0c221/plan.json)；[原始观察](logs/707f29df1d3a4f05859e384114c012c4/stdout.log)；[assessment](direct-checks/6f010f21b7bb424dbbabaa4858e0c221/707f29df1d3a4f05859e384114c012c4-assessment.json)；[对应性复核](submissions/e419bf454fcb4a6b94a2f646c9f1497b/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.58 秒；执行进程耗时 12.05 秒；[实际命令、工具版本与输入记录](logs/707f29df1d3a4f05859e384114c012c4/check.json)
执行边界：Package-internal Go test that seeds a real InmemStore with configuration and command entries, lets NewRaft rebuild the latest/committed configuration from them, asserts those preconditions, drives one conflicting AppendEntries through the real handler, and emits the resulting configuration state as CA_EVENT records.；The Raft instance is created with the internal skipStartup flag so the main loop and FSM do not race the direct call to appendEntries; the handler, the stores, the configuration state and the startup configuration scan are the unmodified implementation.；LeaderCommitIndex is 0 so the follower's commit-advancement and FSM application paths are not exercised; the check is about the configuration state left by the truncation branch.
固定比较 `chk-config-rollback`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| node | assurance-node |
| truncation_succeeded | true |
| latest_index | 1 |
| cfg.committed_index | 1 |
| cfg.truncation_succeeded | true |
| committed_index | 1 |
| entry3_term | 9 |
| entry3_type | 0 |
| event | config_observed |
| last_log_index | 3 |
| published_servers | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)。
- 共识形成与推进（原文导航摘录）：A decision is formed as a log entry and advanced only after a quorum has durably stored it. The leader's dispatchLogs assigns (index, term) to each logFuture, stores it locally and records its own match; each peer's…
- 上下文／权威转换（原文导航摘录）：Authority is a per-instance, durable term plus at most one vote. A follower that stops hearing from a leader starts a candidate loop that raises currentTerm (persisted first) and solicits votes, optionally behind a…
- 两条主线的连接（原文导航摘录）：The two core lines meet at the term fence carried by every entry. A log entry is only meaningful together with the term of the leader that wrote it: a follower accepts new entries only when the previous-log coordinate…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.99 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 6.77 分钟 · 受理 obligation：First Candidate on the accepted v1 map. It fixes one attributed follower-side responsibility over F-config: after appendEntries truncates a…。[完整交接](submissions/17b9f8abcb904ef0a7bc79042aaa382f/accepted.json)

- 8.76 分钟 · 受理 explained：Source reading resolves the suspicion raised by the truncation branch: the reset latest := committed cannot name a configuration that is…。[完整交接](submissions/8bbfe7a62c184496977e6a08df419935/accepted.json)

- 13.43 分钟 · 实际执行：截断后写入失败：跟随者日志水位超过持久日志；执行完成；比较见 assessment。[执行记录](logs/de1a5dd120d44cfa887ed4a83c31c01a/check.json)

- 14.46 分钟 · 受理 review：截断后写入失败：跟随者日志水位超过持久日志。[完整交接](submissions/0173f32a8d4b43fca1930c13dfd91300/accepted.json)

- 16.12 分钟 · 受理 obligation：Third Candidate, on the accepted v1 map, opened after the store-failure lead was confirmed. Reading installSnapshot end to end shows that…。[完整交接](submissions/78dd029209564b8c9fd5e05485962f85/accepted.json)

- 17.86 分钟 · 实际执行：安装快照后未重置日志水位：跟随者报告已清除的日志索引；执行完成；比较见 assessment。[执行记录](logs/af5ed6e5cd714a38bc74fced5d1bbcc5/check.json)

- 18.71 分钟 · 受理 review：安装快照后未重置日志水位：跟随者报告已清除的日志索引。[完整交接](submissions/b4ef05794ee143cd9bbb46a1bd2e9522/accepted.json)

- 22.23 分钟 · 实际执行：快照触发阈值比较出现无符号下溢：日志滞后于快照时仍判定需要快照；执行完成；比较见 assessment。[执行记录](logs/ef3cbb2ccf0f41239b71a02eadb8859b/check.json)

- 23.05 分钟 · 受理 review：快照触发阈值比较出现无符号下溢：日志滞后于快照时仍判定需要快照。[完整交接](submissions/eed5fbff8b454c71b653a28c7d737c79/accepted.json)

- 24.78 分钟 · 实际执行：冲突截断后的配置回滚：最新配置与保留的已提交配置一致（有界无违规）；执行完成；比较见 assessment。[执行记录](logs/707f29df1d3a4f05859e384114c012c4/check.json)

- 25.49 分钟 · 受理 review：冲突截断后的配置回滚：最新配置与保留的已提交配置一致（有界无违规）。[完整交接](submissions/e419bf454fcb4a6b94a2f646c9f1497b/accepted.json)

- 38.59 分钟 · 受理 research：Closing one last premise behind an already-confirmed check with a single read, since the run is at its boundary.。[完整交接](submissions/6c034eacee9647e5b40701e75e39a745/accepted.json)

- 39.24 分钟 · 受理 research：Closing one last premise behind an already-confirmed check with a single read, since the run is at its boundary.。[完整交接](submissions/240bb74624be4c15824574b10831d6a8/accepted.json)

- 39.69 分钟 · 受理 research：Closing one last premise behind an already-confirmed check with a single read, since the run is at its boundary.。[完整交接](submissions/29b50038b2514aaaacf38dd99e9f2bdc/accepted.json)

- 40.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/f1ba2518c0a24b2aa46f51a4cd3441a4/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v4 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)

- core_overview：Pipeline mode (pipelineReplicate/pipelineSend/pipelineDecode) was read only at the level needed to see how a peer match is recorded; its internal response ordering was not traced in full.；Leadership…
  尚无精确对应交接。

- b-client-apply：The library does not pin an explicit completion deadline for a future that is enqueued but never committed; whether the caller-supplied timeout is the only bound is not established here.
  尚无精确对应交接。

- F-log-watermark：Reachability of the installSnapshot case from a legal leader history remains open: the confirmed witness needs a follower whose watermark index exceeds the leader's snapshot index (check…
  相关交接：[交接 1](submissions/71380a95eb94462b8c4b571288dd7f19/accepted.json)；[交接 2](submissions/575f7b0578574185b0e80a6c7e4fccfa/accepted.json)；[交接 3](submissions/7dad026d80dd4fc980cc5db5e76af9ec/accepted.json)；[交接 4](submissions/70e1962cd7804ee4892a32625a5beaf4/accepted.json)

- surface:Transport (net_transport.go, tcp_transport.go, inmem_transport.go)：net_transport.go, tcp_transport.go and inmem_transport.go are in-repository Transport implementations (NetworkTransport, TCPTransport, InmemTransport), not caller-supplied code, and none of them was…
  相关交接：[交接 1](submissions/50e8cec7367b4914ba6ed262ff2e92f7/accepted.json)；[交接 2](submissions/3429b9644abb4a3e908a95436466b2d1/accepted.json)；[交接 3](submissions/bd87805616d9485ba1c20c7a86b467bd/accepted.json)；[交接 4](submissions/bbf2e6c3e85b4cf2bb1763ec9cc5c2c3/accepted.json)；[交接 5](submissions/0619c5051d0046b7817f60023db35e4f/accepted.json)；[交接 6](submissions/b6088ab89fc046b3a30dbfcf42c9631c/accepted.json)

- surface:Transport interface contract assumed by the protocol handlers：The Raft object is constructed with an injected Transport and the handlers assume only that RPCs are delivered to the Consumer channel and that…
  尚无精确对应交接。

- surface:FSM.Apply/Snapshot/Restore determinism：The library sequences and batches entries but deterministic application and snapshot state are the caller FSM's contract.
  尚无精确对应交接。

- surface:StableStore/LogStore/SnapshotStore durability guarantees：The library relies on the caller stores for fsync-level durability; write ordering inside the library is visible but the actual durability is external.
  尚无精确对应交接。

- surface:Observer and saturation metrics (observer.go, saturation.go)：Observability plumbing only; it reflects state changes but does not participate in any safety or liveness decision.
  尚无精确对应交接。

- surface:fuzzy/ and raft-compat/ integration harnesses：Test and compatibility scaffolding outside the library's protocol responsibility.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
