# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**。已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 2 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **31.02 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 538.94 秒、32 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1861.06 | 538.94 |
| Agent 调用 | 40 | 8 | 32 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 4.42 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 482.53 秒。

目标执行组成：正式检查 2 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v50`；展示版本 `audit-products-v50`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`594.4998435549996`（配置值不表示触发了超时）。
[调用记录](logs/e5419d5836eb453c8062899855365ee7/check.json)；[stdout](logs/e5419d5836eb453c8062899855365ee7/stdout.log)；[stderr](logs/e5419d5836eb453c8062899855365ee7/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 旧任期分配消息导致写入被错误确认 | 已确认违反 | 三节点同一配置中，101 的真实分配消息被延迟；新主节点随后在同一位置决定了 202。释放保持链路 FIFO 顺序的旧消息后，101 的 append_notify 返回 Ok(1)，但原节点读取到的是 Decided(202)。这验证的是客户端完成关联错误，不是两个节点决定了冲突日志。 | [claim-notify-same-entry](#claim-claim-notify-same-entry) |
| 2. 持久存储返回错误后仍保留失败事务的状态 | 已确认违反 | 序列化返回 Err 后，公开读取的日志长度从 1 变成 2。随后仅设置 decided index 的独立事务，提交了失败事务中的 promise=2 和条目 11，重新打开数据库后仍可读到。该结果限定为 Storage 接口回滚违约，未证明集群级安全破坏。 | [claim-storage-error-rollback](#claim-claim-storage-error-rollback) |

<a id="claim-claim-notify-same-entry"></a>

### 1. 旧任期分配消息导致写入被错误确认

**已确认违反**。要求原文：For an admitted append_notify operation, an Ok assigned position must identify that operation's proposed entry in the decided log; a different entry decided at that position under a later ballot must not satisfy the operation.

决定性范围：Async runtime client completion within one valid fixed configuration, genuine non-Byzantine protocol/runtime messages, and successful storage. Focus on a delayed assignment across leader change when an old unchosen entry is replaced.
Unique operation identity and distinct proposed values allow independent correlation.；No compaction obscures the compared entry.；Application transports actual messages to their intended recipients; delay and partition preserve per-directed-link FIFO among delivered messages.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/8c4dc87dc3104a0ab63e5a71d28e1a3a/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/8c4dc87dc3104a0ab63e5a71d28e1a3a/plan.json)；[原始观察](logs/f6b6e1f52baa4f8991b6320420cee535/stdout.log)；[assessment](direct-checks/8c4dc87dc3104a0ab63e5a71d28e1a3a/f6b6e1f52baa4f8991b6320420cee535-assessment.json)；[对应性复核](submissions/718e607a0e1d4e4db235b152b59b870d/accepted.json)

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 17.00 秒；执行进程耗时 2.15 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/f6b6e1f52baa4f8991b6320420cee535/check.json)
执行边界：Three real OmniPaxos nodes and three real ActorState loops, driven through public APIs. Caller-owned per-link FIFO queues implement partitions and delay. Real tokio task/time primitives implement the public AsyncRuntime trait. Core prefix is initialized with explicit try_become_leader and drained before spawning actors. Runtime and protocol ticks remain enabled; large legal election/resend thresholds avoid unrelated election churn during the short controlled history. Bounded event/outgoing channels are continually drained. The result event is absent if the operation remains pending in the observation window.；No target changes. Custom AsyncRuntime delegates directly to tokio spawn and sleep because selected crate default features need not expose TokioRuntime.；Caller transport replaces network I/O with FIFO queues, holding all old leader outbound messages then releasing only link 1->2 in original order.；Read observations are public API copies of the actual local decided log. Assigned positions are prefix lengths: returned k is compared at zero-based read index k-1, as established by append_tracked accepted_after.
固定比较 `notify-identity`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | old-request |
| event | completion |
| success | true |
| observed_value | 202 |
| admitted.proposed | 101 |
| setup.op_id | old-request |
| admitted.entry_id | 43db97b7-53d4-47c6-a7b0-9cf04c2eb13a |
| assigned.entry_id | 43db97b7-53d4-47c6-a7b0-9cf04c2eb13a |
| unreplicated.entry_id | 43db97b7-53d4-47c6-a7b0-9cf04c2eb13a |
| assigned.assigned_idx | 1 |
| setup.empty | true |
| admitted.op_id | old-request |
| unreplicated.old_outbound_delivered | 0 |
| unreplicated.accepted_message_observed | true |
| replacement.entry_id | 43db97b7-53d4-47c6-a7b0-9cf04c2eb13a |
| replacement.assigned_idx | 1 |
| replacement.pending | true |
| entry_id | 43db97b7-53d4-47c6-a7b0-9cf04c2eb13a |
| returned_idx | 1 |
| status | ok |
| decided_idx | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-storage-error-rollback"></a>

### 2. 持久存储返回错误后仍保留失败事务的状态

**已确认违反**。要求原文：When Storage::write_atomically returns Err, the storage state exposed to its caller must equal the pre-call state, and a later independent successful transaction must not commit operations retained from the failed call.

决定性范围：PersistentStorage direct Storage API use on a live backend with a deterministic returned entry-serialization error after earlier operations were prepared.
Entry implements the required Entry, Serialize and Deserialize interfaces; serialization error is returned normally, not panic.；Successful database initialization and I/O outside the selected error; no concurrent writers or compaction.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/66acce1428c3477f8a6c0f0d1ea19ee1/omnipaxos/tests/assurance_generated.rs)；[条件与检查器](direct-checks/66acce1428c3477f8a6c0f0d1ea19ee1/plan.json)；[原始观察](logs/eb1ca4d437f64ec8882a7005a78fb321/stdout.log)；[assessment](direct-checks/66acce1428c3477f8a6c0f0d1ea19ee1/eb1ca4d437f64ec8882a7005a78fb321-assessment.json)；[对应性复核](submissions/4323ead78f324ec992ca1d07f91fb0eb/accepted.json)

固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 465.54 秒；执行进程耗时 2.27 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/eb1ca4d437f64ec8882a7005a78fb321/check.json)
执行边界：Actual PersistentStorage backed by RocksDB in a unique execution-workspace directory, with a user-defined Entry serializer returning a deterministic ordinary error for one selected value. No backend or dependency code modifications, no process crash or private access. The database is closed before cleanup. Prerequisite events identify successful setup and actual selected error; subsequent transaction success is checked in code and retained as a diagnostic event before the later result.；Use the public Entry serialization extension point to supply a returned error; all other entry values serialize normally.；Direct backend calls isolate the explicit Storage interface contract; no claim that the whole Paxos core continues after its storage panic.；Observe get_log_len from the live object and promise/entry data from backend public readers, then reopen as a diagnostic.
固定比较 `rollback-live-length`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | failed-transaction |
| event | immediate_state |
| log_len | 2 |
| admitted.before_len | 1 |
| admitted.op_id | failed-transaction |
| failed.op_id | failed-transaction |
| failed.returned_error | true |
| failed.serialization_error_observed | true |
| first | 7 |
| promise_n | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `rollback-later-promise`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | failed-transaction |
| event | after_independent |
| promise_n | 2 |
| admitted.before_promise_n | 1 |
| admitted.op_id | failed-transaction |
| failed.op_id | failed-transaction |
| failed.returned_error | true |
| failed.serialization_error_observed | true |
| decided_idx | 0 |
| log_len | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：Proposals are buffered/forwarded or accepted by the leader. A new leader first gathers per-node Promises in its ballot, chooses highest accepted round and longest corresponding suffix, and synchronizes a prepare quorum…
- 上下文／权威转换（原文导航摘录）：Caller-driven BLE ticks select ballots; explicit takeover also invokes handle_leader. A strictly newer ballot resets leader aggregation and stores a promise. A follower Prepare may acquire newer authority, or reacquire…
- 两条主线的连接（原文导航摘录）：Ballot election is not a decision quorum. Promises and persisted accepted history constrain new leader formation; batching is flushed before promises, old accepted indexes are reset at a new self ballot, and…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.36 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 7.34 分钟 · 受理 obligation：Ground the client completion responsibility and prepare a controlled schedule around a genuine delayed assignment; source analysis has not…。[完整交接](submissions/1a2ce71c7a7b419f9115245884cd9b8c/accepted.json)

- 12.03 分钟 · 实际执行：旧任期分配消息导致写入被错误确认；执行完成；比较见 assessment。[执行记录](logs/f6b6e1f52baa4f8991b6320420cee535/check.json)

- 14.99 分钟 · 受理 review：旧任期分配消息导致写入被错误确认。[完整交接](submissions/718e607a0e1d4e4db235b152b59b870d/accepted.json)

- 18.40 分钟 · 受理 obligation：Investigate a separately grounded storage rollback responsibility after source review reveals mutation before a fallible serialization…。[完整交接](submissions/d239ae354c4f49a1b0de5a5b772356b1/accepted.json)

- 20.56 分钟 · 受理 check：Use a controlled entry serializer error to measure live state and delayed failed-transaction effects against the accepted Storage rollback…。[完整交接](submissions/66acce1428c3477f8a6c0f0d1ea19ee1/accepted.json)

- 28.32 分钟 · 实际执行：持久存储返回错误后仍保留失败事务的状态；执行完成；比较见 assessment。[执行记录](logs/eb1ca4d437f64ec8882a7005a78fb321/check.json)

- 30.09 分钟 · 受理 review：持久存储返回错误后仍保留失败事务的状态。[完整交接](submissions/4323ead78f324ec992ca1d07f91fb0eb/accepted.json)

- 31.01 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e5419d5836eb453c8062899855365ee7/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：Cross-configuration message routing responsibility and delayed traffic legality.；Persistent backend returned-error rollback of reusable write batch and next_log_key; crash durability and…
  尚无精确对应交接。

- b-authority：Configuration identity differs between derived Ballot equality and ordering; outer SequencePaxos routing applicability remains unestablished.
  尚无精确对应交接。

- b-prepare：Delayed Promise and AcceptSync interaction during repeated same-ballot recovery needs history-level investigation.
  尚无精确对应交接。

- b-decide：Accepted indexes are assigned rather than maximized; legal response ordering and consequences of regression remain unread.
  尚无精确对应交接。

- b-recover：Caller network delivery and reconnect obligations under silent last-message loss need contract investigation.
  尚无精确对应交接。

- b-storage：Crash durability under RocksDB options and OS failure remains unread; the selected question covers returned serialization error and live backend state.
  相关交接：[交接 1](submissions/d239ae354c4f49a1b0de5a5b772356b1/accepted.json)

- b-config：Node list uniqueness and cross-configuration traffic routing are not established by the read validation.
  尚无精确对应交接。

- b-client：Batch tracking across untracked core writes and rejected remote proposals remains separate from the selected delayed-assignment question.
  尚无精确对应交接。

- b-persistent-transaction：After a real serialization Err, do public log-length reads and a subsequent successful transaction reveal retained changes from the failed transaction?
  相关交接：[交接 1](submissions/4323ead78f324ec992ca1d07f91fb0eb/accepted.json)

- surface:SequencePaxos::handle / Ballot::cmp：BLE reply admission checks configuration ID, while SequencePaxos dispatch has no visible equivalent and ballot ordering omits config_id. Determine caller instance-routing obligations and whether…
  尚无精确对应交接。

- surface:LeaderState::get_min_all_accepted_idx：Accepted-index vector spans max_pid rather than configured nodes; determine whether sparse legal node IDs cause trim eligibility to include unused zero slots.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
