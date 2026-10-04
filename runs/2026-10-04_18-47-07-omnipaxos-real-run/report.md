# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**。已受理 Candidate 3 项；当前 Unit 3 项、义务 3 项、固定检查制品 3 项。正式执行尝试 3 次；已保存评估的义务 3 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **40.01 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、31 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.34 | 0.00 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 3 | 3 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 607.28 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 633.43 秒。

目标执行组成：正式检查 3 次＋探索 0 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v49`；展示版本 `audit-products-v49`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Audit investigation reached the authorized total time budget；[完整停止记录](state.json)。


## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权切换后，追加通知错误确认了被替换的写入 | 已确认违反 | 原领导者提交的 101 未到达其他副本；新领导者与另一副本在同一位置决定了 202。原节点同步后，101 的 append_notify 仍返回 Ok(1)，公开日志读取却为 Decided(202)。这是客户端成功通知与实际决定内容不对应，不是已观察到的共识分歧。 | [claim-notify-correspondence](#claim-claim-notify-correspondence) |
| 2. 快照前缀导致决定日志订阅回退到已发送的位置 | 已确认违反 | 从已压缩前缀开始订阅时，实际保留条目的位置序列为 3、4、3、4，而底层决定日志未变化。订阅游标把一个快照摘要计为一个原始日志位置，后续推送重发旧后缀，产生 4→3 的顺序回退。 | [claim-stream-order](#claim-claim-stream-order) |
| 3. Does PersistentStorage::write_atomically restore its observable pre-call state when serializing a later entry fails after earlier…（原文摘录） | 检查未执行到比较 | 构建期间超时；未观察到测试启动；原因摘录：Direct oracle correspondence is unreviewed；[完整评估与原因](direct-checks/39480597f171477ab8596f2a7174d492/254524b668a24ec999ae949908ad836a-assessment.json) | [claim-storage-rollback](#claim-claim-storage-rollback) |

<a id="claim-claim-notify-correspondence"></a>

### 1. 领导权切换后，追加通知错误确认了被替换的写入

**已确认违反**。要求原文：If append_notify for an entry returns Ok(k), the decided log entry denoted by k must be that submitted entry; decision of a different entry at the reused index does not authorize success for this operation.

决定性范围：Pending append notifications in a fixed valid cluster, including leadership changes, with no log compaction, no storage failures and unique payloads so operation content is observable.
Correct peer identities and unmodified messages produced by the implementation.；Configured runtime timers and caller-driven transport execute; network may temporarily isolate a peer.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/5e2212e260544fe198af4637fe73c813/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/5e2212e260544fe198af4637fe73c813/plan.json)；[原始观察](logs/adcc1c901782418b971256e7f414647b/stdout.log)；[assessment](direct-checks/5e2212e260544fe198af4637fe73c813/adcc1c901782418b971256e7f414647b-assessment.json)；[对应性复核](submissions/4ab2d5440586404d927effd85ff52613/accepted.json)

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 33.24 秒；执行进程耗时 10.34 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/adcc1c901782418b971256e7f414647b/check.json)
执行边界：Single current-thread Tokio test with a public AsyncRuntime implementation equivalent to the repository Tokio adapter. Actual core peers produce all messages. Prefix assertions check stable old leadership, empty peers, emitted original proposals, higher-ballot replacement quorum, and origin replacement. The result event comes from the awaited original append_notify and an independent read of the live actor log.；No target changes. A test Entry and no-snapshot type instantiate the generic API.；TestRuntime supplies public executor hooks using ordinary tokio::spawn and tokio::time::sleep; no virtual time or actor interception.；Caller transport temporarily drops old-leader traffic and defers traffic to the isolated node. Retained messages preserve per-link order.
固定比较 `notify-content`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | notify-original |
| event | completion |
| success | true |
| decided_value | 202 |
| admission.payload | 101 |
| admission.producer_observed | true |
| admission.peers_empty | true |
| admission.origin_decided | 0 |
| chosen.leader | 2 |
| chosen.decided | 1 |
| chosen.value | 202 |
| replacement.value | 202 |
| replacement.decided | 1 |
| returned_index | 1 |
| error_kind | none |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-stream-order"></a>

### 2. 快照前缀导致决定日志订阅回退到已发送的位置

**已确认违反**。要求原文：Within one subscribe_decided stream over a stable decided log, emitted retained Decided entries must preserve their original log order: an entry from an earlier position must not follow an emitted entry from a later position.

决定性范围：One accepted subscription starting before an already compacted prefix, with a nonempty retained decided suffix, no concurrent changes to log decisions or compaction, and an actively drained subscriber.
Valid fixed membership and reliable in-memory storage.；Unique entry values allow independent mapping of emitted entries to previously observed original log positions.；Runtime timers and channel receiver are driven.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/2854ece9034643948355b1c57a8553d1/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/2854ece9034643948355b1c57a8553d1/plan.json)；[原始观察](logs/09941e2a9e084150bd1c84ff412dd312/stdout.log)；[assessment](direct-checks/2854ece9034643948355b1c57a8553d1/09941e2a9e084150bd1c84ff412dd312-assessment.json)；[对应性复核](submissions/259c9586ad1546679ed9d47c978710c2/accepted.json)

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 8.08 秒；执行进程耗时 5.46 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/09941e2a9e084150bd1c84ff412dd312/check.json)
执行边界：Build a real three-node cluster, decide five unique values, read their original order, and snapshot the first three entries through the public API. Move the snapshotted core into the actor and subscribe from zero with capacity 32. Consume initial catch-up and every following item until a fixed time cutoff, then verify the underlying retained decided suffix remains unchanged. Compute order from the independently observed original positions, not payload magnitude.；No target modifications or injected protocol/storage state.；Test Entry has a snapshot that stores and concatenates the represented prefix values.；Public AsyncRuntime hooks use real Tokio spawn and timers.
固定比较 `stream-order`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| subscription | from-zero |
| event | stream_window |
| order_preserved | false |
| admission.history_ready | true |
| admission.from | 0 |
| admission.compacted | 3 |
| admission.decided | 5 |
| admission.retained_count | 2 |
| observed_items | 5 |
| stable_decided | 5 |
| window_complete | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-storage-rollback"></a>

### 3. Does PersistentStorage::write_atomically restore its observable pre-call state when serializing a later entry fails after earlier…（原文摘录）

**检查未执行到比较**。要求原文：When Storage::write_atomically returns Err, the storage state must be rolled back to its pre-call state; in particular, get_log_len on the same instance must equal its pre-call value before any subsequent mutation.

决定性范围：PersistentStorage handling a nonconcurrent atomic batch on a healthy database, where a later Entry serialization returns Err after an earlier entry serialized successfully.
Entry implements the required serialization/deserialization and storage traits; its serializer may return the Result error supported by that interface.；No concurrent writer, process crash or compaction during the invocation and observation.。

[完整要求、假设与排除范围](state.json)

制品 v1；检查未执行到比较；对应性意见：尚未记录；场景比较完整：False；独立场景完整处置：False。
[固定测试](direct-checks/39480597f171477ab8596f2a7174d492/omnipaxos/tests/assurance_generated.rs)；[条件与检查器](direct-checks/39480597f171477ab8596f2a7174d492/plan.json)；[原始观察](logs/98360cc693e249de83ae6ae095ab045b/stdout.log)；[assessment](direct-checks/39480597f171477ab8596f2a7174d492/254524b668a24ec999ae949908ad836a-assessment.json)

当前争议／阻塞：Direct oracle correspondence is unreviewed；[完整评估与阻塞](direct-checks/39480597f171477ab8596f2a7174d492/254524b668a24ec999ae949908ad836a-assessment.json)

固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 592.12 秒；执行进程耗时 591.48 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；构建期间超时；未观察到测试启动；[实际命令、工具版本与输入记录](logs/254524b668a24ec999ae949908ad836a/check.json)
执行边界：Open a fresh real PersistentStorage in a disposable workspace directory. Append one valid entry, then invoke write_atomically with a promise change and two entries, the second of which deterministically returns a serde error. Compare live get_log_len before/after the returned result. Drop storage before reopen and cleanup to respect RocksDB ownership.；No target or database replacement. Use real persistent backend and native serialization calls.；Test Entry implements Serialize with a deterministic normal error for value 99; valid values serialize as u64. This supplies a fault through the declared fallible interface.；An atomic counter reports whether the failing serializer actually ran.
固定比较 `atomic-extent`：结果未确定；已比较 0 项，完整见证 0 项，缺失 0 项。

观察缺口：No applicable completed result event was reached

该问题保留的失败执行：[原始失败](logs/98360cc693e249de83ae6ae095ab045b/stdout.log)；[诊断](logs/98360cc693e249de83ae6ae095ab045b/stderr.log)。修订转折见时间线，旧失败不覆盖当前结果。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)。
- 共识形成与推进（原文导航摘录）：Append is buffered during prepare, sent locally during Leader/Accept, or forwarded. Current-ballot promises populate participant slots; a prepare quorum selects maximal accepted-round/index history, synchronizes it,…
- 上下文／权威转换（原文导航摘录）：Tick drives BLE; matching heartbeat rounds/configurations influence leader selection. SequencePaxos requires a higher ballot before initiating preparation. Followers persist a higher promise, reject lower-ballot…
- 两条主线的连接（原文导航摘录）：Authority alone does not enable acceptance: the new leader first gathers promise support and adopts accepted history, including prior decisions, before appending buffered work. A stopped selected history blocks appends.…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.55 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 14.13 分钟 · 实际执行：领导权切换后，追加通知错误确认了被替换的写入；执行完成；比较见 assessment。[执行记录](logs/adcc1c901782418b971256e7f414647b/check.json)

- 16.08 分钟 · 受理 review：领导权切换后，追加通知错误确认了被替换的写入。[完整交接](submissions/4ab2d5440586404d927effd85ff52613/accepted.json)

- 19.51 分钟 · 受理 obligation：Retain the confirmed notification learning and investigate a distinct ordered-decision-consumption responsibility exposed by…。[完整交接](submissions/f5e302dd5cfd4481b916372be22d8eba/accepted.json)

- 22.68 分钟 · 实际执行：快照前缀导致决定日志订阅回退到已发送的位置；执行完成；比较见 assessment。[执行记录](logs/09941e2a9e084150bd1c84ff412dd312/check.json)

- 24.38 分钟 · 受理 review：快照前缀导致决定日志订阅回退到已发送的位置。[完整交接](submissions/259c9586ad1546679ed9d47c978710c2/accepted.json)

- 28.32 分钟 · 受理 obligation：Preserve accepted subscriber learning and select a distinct explicit storage rollback contract. Keep cross-session synchronization…。[完整交接](submissions/1bae8c4ca5dc4c68ba82fee59b51d712/accepted.json)

- 30.11 分钟 · 受理 check：Execute the accepted rollback responsibility with a real serializer error and direct before/after Storage queries.。[完整交接](submissions/39480597f171477ab8596f2a7174d492/accepted.json)

- 40.00 分钟 · 实际执行：Does PersistentStorage::write_atomically restore its observable pre-call state when serializing a later entry fails after earlier…（原文摘录）；执行失败或未完成。[执行记录](logs/254524b668a24ec999ae949908ad836a/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-claim-storage-rollback](research.json)：[claim-storage-rollback](#claim-claim-storage-rollback)；具体进度与缺口见对应义务

<a id="candidate-e1c6be4b17394cffbe72a5f910f1addf"></a>

研究中问题：Does PersistentStorage::write_atomically restore its observable pre-call state when serializing a later entry fails after earlier operations have staged writes and advanced next_log_key?
[候选原文与历史](state.json)
保存的语义未知：Need fixed execution to distinguish database atomicity from rollback of observable cached extent and retained batch state.

### 地图登记与研究交接

以下是地图 v4 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)

- core_overview：Legal transport history for delayed same-ballot AcceptSync.；Heartbeat duplicate accounting contract.；Compaction and reconfiguration edge paths.；Persistent backend failure/crash durability.；Actor…
  尚无精确对应交接。

- b-formation：Same-ballot recovery may replace peer support metadata; accepted indexes are assigned rather than max-merged. Consequence depends on permitted message history.
  尚无精确对应交接。

- b-follow：AcceptSync does not check its sequence against a retained prior session; determine whether older same-ballot synchronization can reach a later Prepare phase under the actual transport contract.
  尚无精确对应交接。

- b-recovery：Caller delivery ordering and whether old-connection messages may remain deliverable after reconnection.
  尚无精确对应交接。

- b-election：Heartbeat reply accumulation counts vector entries; participant uniqueness and duplicate-delivery assumptions need source investigation.
  尚无精确对应交接。

- b-storage：Persistent backend crash durability and in-memory cache state after storage errors are not established by the read transaction API.
  尚无精确对应交接。

- b-runtime-assign：Remote and deferred-batch assignment lifecycles across authority changes remain separate.
  相关交接：[交接 1](submissions/4ab2d5440586404d927effd85ff52613/accepted.json)

- b-runtime-loop：Backpressure-specific progress remains separate.
  尚无精确对应交接。

- b-subscriber：Multiple-subscriber cursor interactions and post-subscription compaction remain independent.
  相关交接：[交接 1](submissions/259c9586ad1546679ed9d47c978710c2/accepted.json)；[交接 2](submissions/1bae8c4ca5dc4c68ba82fee59b51d712/accepted.json)

- b-persistent-batch：Does an entry serialization failure after earlier staged operations restore cached extent and clear staged writes as required by write_atomically?
  尚无精确对应交接。

- f-promise：Persistent backend crash durability under configured options.
  相关交接：[交接 1](submissions/2d4a747b58254dcda4dfb90d2fed0a8d/accepted.json)

- f-runtime-assignment：Remote and deferred-batch assignment provenance under authority changes.
  相关交接：[交接 1](submissions/4ab2d5440586404d927effd85ff52613/accepted.json)；[交接 2](submissions/f5e302dd5cfd4481b916372be22d8eba/accepted.json)

- f-sub-cursor：Cross-subscriber minimum cursor and compaction during active subscriptions.
  相关交接：[交接 1](submissions/259c9586ad1546679ed9d47c978710c2/accepted.json)；[交接 2](submissions/1bae8c4ca5dc4c68ba82fee59b51d712/accepted.json)

- f-storage-extent：Rollback behavior on serialization failure partway through batch construction.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[direct_check](logs/98360cc693e249de83ae6ae095ab045b/stdout.log)；[stderr](logs/98360cc693e249de83ae6ae095ab045b/stderr.log)；[执行记录](logs/254524b668a24ec999ae949908ad836a/check.json)
