# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**。已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 3 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **37.76 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 134.40 秒、33 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2265.60 | 134.40 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 1 | 5 |

受控目标执行进程耗时（正式检查＋探索）：已记录 20.75 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 795.09 秒。

目标执行组成：正式检查 3 次＋探索 0 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v54`；展示版本 `audit-products-v54`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/85365c371fe547c6ac09da582ba88426/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`312.8052121589935`（配置值不表示触发了超时）。
[调用记录](logs/85365c371fe547c6ac09da582ba88426/check.json)；[stdout](logs/85365c371fe547c6ac09da582ba88426/stdout.log)；[stderr](logs/85365c371fe547c6ac09da582ba88426/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 增量快照同步丢失已决定的键 | 已确认违反 | 三节点合法断连重连后，跟随者的决定、接受和压缩索引均为 3，但读取状态从包含键 11 变成仅包含键 22、33；领导者仍包含全部三个键。固定执行完成了内容比较，作用域限于本次内存存储的同轮次增量同步。 | [claim_snapshot_content](#claim-claim_snapshot_content) |
| 2. 旧请求被替换后 append_notify 仍返回成功 | 已确认违反 | 请求值 42 仅在旧领导者本地接受；新法定人数在同一位置决定了 99，并在通知轮询前同步到旧领导者。随后原请求返回 Ok(1)，但同一节点读取位置 1 的决定内容是 99，构成已完成的身份一致性反例。 | [claim_notify_identity](#claim-claim_notify_identity) |

<a id="claim-claim_snapshot_content"></a>

### 1. 增量快照同步丢失已决定的键

**已确认违反**。要求原文：When a follower successfully synchronizes a decided prefix from its current leader through a delta snapshot, the resulting snapshot and decided suffix must represent the same application state as that decided prefix, preserving the previously decided prefix as well as the transferred delta.

决定性范围：Successful same-configuration follower AcceptSync using SnapshotType::Delta and conforming key/value snapshots; compare application state at the synchronization decided boundary.
Each sender is a configured non-Byzantine replica.；Snapshot create folds entries in order; merge applies delta updates, as documented.；MemoryStorage runs without injected errors; network disconnect can lose messages and endpoints call reconnected after restoration.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/ab5a276bea084b4685d2ecb30d073d8b/omnipaxos/tests/assurance_generated.rs)；[条件与检查器](direct-checks/ab5a276bea084b4685d2ecb30d073d8b/plan.json)；[原始观察](logs/4c1e4585ab8748119316ce21b39868e9/stdout.log)；[assessment](direct-checks/ab5a276bea084b4685d2ecb30d073d8b/4c1e4585ab8748119316ce21b39868e9-assessment.json)；[对应性复核](submissions/415c932d82ea443baeaa015e225e8409/accepted.json)

固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 18.97 秒；执行进程耗时 8.15 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/4c1e4585ab8748119316ce21b39868e9/check.json)
执行边界：Single-thread public-API three-node driver with MemoryStorage and documented key/value snapshot semantics. Explicit try_become_leader selects leader; bounded queue drains drive generated messages. No wall-clock progress assertion is made.；No target changes. Transport is a deterministic FIFO delivery driver with an explicitly declared disconnection.；Application Entry/Snapshot uses a BTreeMap for canonical serialization and overwrite merge equivalent to documented HashMap semantics.
固定比较 `check_delta_content`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case | delta_missing_suffix |
| node | 3 |
| ordinal | 41 |
| returned | true |
| actual_state | {"22":220,"33":330} |
| admitted.expected_state | {"11":110,"22":220,"33":330} |
| admitted.delta | true |
| admitted.before_decided | 1 |
| admitted.before_accepted | 1 |
| admitted.transfer_decided | 3 |
| admitted.transfer_compacted | 3 |
| accepted | 3 |
| compacted | 3 |
| decided | 3 |
| event | sync_result |
| phase_accept | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

该问题保留的失败执行：[原始失败](logs/58fc8f11f87544cab25add823ec6957d/stdout.log)；[诊断](logs/58fc8f11f87544cab25add823ec6957d/stderr.log)。修订转折见时间线，旧失败不覆盖当前结果。

<a id="claim-claim_notify_identity"></a>

### 2. 旧请求被替换后 append_notify 仍返回成功

**已确认违反**。要求原文：A successful append_notify completion at a returned log index must identify the submitted entry as the decided content at that index; deciding a replacement entry at the same position under a later ballot must not supply successful completion of the original invocation.

决定性范围：Locally assigned append_notify across a same-configuration leader change, with original entry excluded from the new quorum history and a different entry decided at the assigned position.
Unique distinguishable values and one outstanding notify operation.；Default MemoryStorage and no snapshots.；Real executor timer; operations and transport can complete before the next actor tick.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/c2be126ce9fc4e7992584096594b3723/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/c2be126ce9fc4e7992584096594b3723/plan.json)；[原始观察](logs/688fe534b64d4b1aa17da552ba0804fb/stdout.log)；[assessment](direct-checks/c2be126ce9fc4e7992584096594b3723/688fe534b64d4b1aa17da552ba0804fb-assessment.json)；[对应性复核](submissions/0286852d034a4806a23bb19e3470d666/accepted.json)

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 33.09 秒；执行进程耗时 8.47 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/688fe534b64d4b1aa17da552ba0804fb/check.json)
执行边界：Mixed public-API actor/core driver with conforming Tokio AsyncRuntime adapter. Real five-second timer permits construction before notifier polling.；No target modifications. Custom AsyncRuntime uses tokio::spawn and tokio::time::sleep without altered time.；Other two replicas are driven synchronously through core APIs. An unused node-1 placeholder preserves vector indexing and never receives protocol traffic.
固定比较 `check_notify_identity`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case | replacement_before_drain |
| operation | 1 |
| completed | true |
| success | true |
| content_at_index | 99 |
| admitted.proposed | 42 |
| admitted.operation | 1 |
| admitted.isolated_accept_messages | 2 |
| replacement.operation | 1 |
| replacement.decided | 1 |
| replacement.replacement | 99 |
| event | notify_result |
| index | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Append is buffered during Prepare or accepted in Leader/Accept. Promises are indexed by sender and a prepare quorum selects highest accepted-round/length history. The leader synchronizes that history before accepting…
- 上下文／权威转换（原文导航摘录）：BLE uses heartbeat rounds, connectivity and ballots to suggest leadership; manual takeover also increments a ballot. SequencePaxos independently requires a newer promise, resets leader accounting, and gathers a prepare…
- 两条主线的连接（原文导航摘录）：A new ballot does not discard established history: promises report accepted round/index and decided index, the selected history is synchronized, then follower support can qualify new formation. Leader accounting is…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.91 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 21.68 分钟 · 修订前 v1：构建失败，未观察到测试启动；保存的机械比较：结果未确定；复核与修订见各自后续节点。[原固定输入](direct-checks/9ecab0d4907541c0b8119eab341062cc/plan.json)；[原执行记录](logs/58fc8f11f87544cab25add823ec6957d/check.json)；[原保存评估](direct-checks/9ecab0d4907541c0b8119eab341062cc/58fc8f11f87544cab25add823ec6957d-assessment.json)

- 23.29 分钟 · 受理 revise_check：Technical prerequisite repair only: remove optional logging-only ServerConfig initialization. Actual selected compilation excludes logging;…。[完整交接](submissions/ab5a276bea084b4685d2ecb30d073d8b/accepted.json)

- 23.61 分钟 · 实际执行：增量快照同步丢失已决定的键；执行完成；比较见 assessment。[执行记录](logs/4c1e4585ab8748119316ce21b39868e9/check.json)

- 26.17 分钟 · 受理 review：增量快照同步丢失已决定的键；v2 checker_correspondence: no_issue_found。[完整交接](submissions/415c932d82ea443baeaa015e225e8409/accepted.json)

- 32.27 分钟 · 受理 check：Test a sourced identity-check ordering gap while retaining the confirmed independent snapshot finding.。[完整交接](submissions/c2be126ce9fc4e7992584096594b3723/accepted.json)

- 32.84 分钟 · 实际执行：旧请求被替换后 append_notify 仍返回成功；执行完成；比较见 assessment。[执行记录](logs/688fe534b64d4b1aa17da552ba0804fb/check.json)

- 34.78 分钟 · 受理 review：旧请求被替换后 append_notify 仍返回成功；v1 checker_correspondence: no_issue_found。[完整交接](submissions/0286852d034a4806a23bb19e3470d666/accepted.json)

- 37.75 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/85365c371fe547c6ac09da582ba88426/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Buffered StopSign is not forwarded by forward_buffered_proposals; determine caller completion contract and alternative paths.；Runtime completion uses assigned position before ballot invalidation;…
  尚无精确对应交接。

- b_elect：Heartbeat replies accumulate in a vector; transport duplicate policy and implications for election remain unread.
  尚无精确对应交接。

- b_config：SequencePaxos message dispatch has no visible configuration filter; investigate caller routing and legal overlap before treating this as a gap.
  尚无精确对应交接。

- b_notify_completion：Can a new ballot replace the assigned slot and decide it before this drain runs, causing successful completion for different content?
  相关交接：[交接 1](submissions/0286852d034a4806a23bb19e3470d666/accepted.json)

- surface:SequencePaxos::forward_stopsign：Buffered reconfiguration continuation differs from buffered ordinary proposals.
  尚无精确对应交接。

- surface:OmniPaxos::handle_incoming：Cross-configuration routing contract must be traced before evaluating missing local checks.
  尚无精确对应交接。

- surface:ActorState::push_to_all_subs：Snapshot/Trimmed entries compress several logical indices but subscriber cursor increments by one; trace delivery boundaries separately.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[direct_check](logs/58fc8f11f87544cab25add823ec6957d/stdout.log)；[stderr](logs/58fc8f11f87544cab25add823ec6957d/stderr.log)；[执行记录](logs/58fc8f11f87544cab25add823ec6957d/check.json)
