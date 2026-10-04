# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **16.04 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1437.55 秒、35 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 962.45 | 1437.55 |
| Agent 调用 | 40 | 5 | 35 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v48`；展示版本 `audit-products-v48`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/e1ce7fac08f94fbf94e08ee431bcbb7f/check.json)；[stdout](logs/e1ce7fac08f94fbf94e08ee431bcbb7f/stdout.log)；[stderr](logs/e1ce7fac08f94fbf94e08ee431bcbb7f/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 异步追加返回成功但对应日志内容不同，驱动顺序仍需修正 | 待调查线索 | 机械比较：观察到违反；对应性意见：revision_needed；原因摘录：Direct oracle correspondence remains disputed: CheckRun 1193fe7d1b0942ab9e4b02a15e871f54 completed. Raw events correlate UUID…；[完整评估与原因](direct-checks/c1381eddf6a7411f91ba415214691456/1193fe7d1b0942ab9e4b02a15e871f54-assessment.json) | [c-notify-identity](#claim-c-notify-identity) |

<a id="claim-c-notify-identity"></a>

### 1. 异步追加返回成功但对应日志内容不同，驱动顺序仍需修正

**待调查线索**。要求原文：If append_notify completes successfully with an assigned log index, the decided entry at that index must be the entry submitted by that invocation, including when leadership changes between acceptance and notification. Timeout or Superseded is permitted instead of success.

决定性范围：The captured async runtime over one valid three-node core configuration, distinct comparable entry payloads, no compaction or crash, and real core/runtime messages delivered by the caller. A partition may delay an old leader response while a different quorum elects a new leader and decides a different entry.
Each node has a unique configured id and initially empty MemoryStorage.；Application supplies transport; no messages or state are fabricated or modified.；Success is interpreted at the one-based accepted index returned by the runtime; core read offset is index minus one.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：revision_needed；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/c1381eddf6a7411f91ba415214691456/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/c1381eddf6a7411f91ba415214691456/plan.json)；[原始观察](logs/1193fe7d1b0942ab9e4b02a15e871f54/stdout.log)；[assessment](direct-checks/c1381eddf6a7411f91ba415214691456/1193fe7d1b0942ab9e4b02a15e871f54-assessment.json)；[对应性复核](submissions/86f6ae4f65884913a191e6ded6f8ee2a/accepted.json)

当前争议／阻塞：Direct oracle correspondence remains disputed: CheckRun 1193fe7d1b0942ab9e4b02a15e871f54 completed. Raw events correlate UUID cd3c2e81-e401-47fe-a5e6-7d49223d04cc: input 101, real old-leader assignment index 1 at ballot n=1 with old decided index 0, replacement value 202 decided at origin while the old future remained pending, then success Ok(1) with live decided value 202. The implication oracle is appropriate: success requires the invoked entry, while errors are allowed; assignment is one-based accepted length and read uses index minus one. No result is substituted. However, fixed harness lines 91-108 hold every non-TaggedProposal message during dispatch and immediately deliver the TaggedProposal. The stable() prefix only checks phases and can return before the final Accepted(0) response is drained. Such a message on 3->1 could be retained while the later TaggedProposal overtakes it. This contradicts the harness legality claim of per-link FIFO even though the decisive delayed 1->3 stream is ordered. The log does not record enough earlier messages to exclude this premise mismatch. Repair only that dispatch loop: continue delivering nonpartitioned traffic in order while retaining node 1 outbound traffic; leave the delayed assignment, replacement decision, contract and oracle unchanged. Fresh execution must retain the original discriminator.；Open review issue 3f4f8cd299a041a1b61c9d77ff3ade7b [s-notify-contract,s-notify-errors,s-runtime-assignment,s-runtime-forward,s-runtime-drain,s-runtime-loop,s-entry,s-runtime-transport]: EntryId matching and stable-leader assignment gate are exercised by real producers.; The supersession check follows the success branch; an unassigned pending request survives the earlier higher-ballot ticks.; The measured API/content discrepancy is complete, but declared FIFO compliance remains unresolved for the setup-to-dispatch boundary.

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；动作总耗时 28.71 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/1193fe7d1b0942ab9e4b02a15e871f54/check.json)
执行边界：Three public actors and a controlled in-process caller transport; generated messages are routed or retained unchanged. Bounded loops assert prerequisite reachability only.；Executor adapter delegates spawn/sleep to Tokio without modifying actor semantics.；Transport withholds old leader links and later releases the original 1->3 stream; no protocol substitutions.
固定比较 `notify-entry-identity`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | old-write |
| case | delayed_assignment |
| success | true |
| actual_value | 202 |
| admission.input | 101 |
| setup.old_leader | 1 |
| admission.entry_id | cd3c2e81-e401-47fe-a5e6-7d49223d04cc |
| assignment.entry_id | cd3c2e81-e401-47fe-a5e6-7d49223d04cc |
| assignment.assigned_idx | 1 |
| setup.empty | true |
| admission.old_leader | 1 |
| assignment.old_decided | 0 |
| replacement.entry_id | cd3c2e81-e401-47fe-a5e6-7d49223d04cc |
| replacement.assigned_idx | 1 |
| replacement.new_leader | 2 |
| replacement.pending | true |
| event | notification |
| entry_id | cd3c2e81-e401-47fe-a5e6-7d49223d04cc |
| status | ok |
| returned_idx | 1 |
| decided_idx | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Caller append buffers or forwards until a leader is in Accept. The leader gathers matching per-node promises to a configured preparation quorum, selects maximum accepted round/length and maximum decided index, installs…
- 上下文／权威转换（原文导航摘录）：BLE heartbeat rounds and manual takeover nominate ballots. SequencePaxos acquires local preparation authority only above its prior leader and promise. Prepare flushes pending writes, persists the promise, resets receive…
- 两条主线的连接（原文导航摘录）：Authority changes constrain which accepted history can become new support: promises report accepted round/length and existing decision index; maximal history is installed before new proposals are accepted. Follower…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.81 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.13 分钟 · 受理 obligation：Ground one runtime completion responsibility after tracing actual assignment producers, ballot transitions and notifier consumer; no…。[完整交接](submissions/6a2f13c8a43448b694a1549dff31ab96/accepted.json)

- 12.65 分钟 · 受理 check：Fix the real-message history and independent success-implies-entry-identity comparison for the accepted obligation.。[完整交接](submissions/c1381eddf6a7411f91ba415214691456/accepted.json)

- 13.14 分钟 · 实际执行：异步追加返回成功但对应日志内容不同，驱动顺序仍需修正；执行完成；比较见 assessment。[执行记录](logs/1193fe7d1b0942ab9e4b02a15e871f54/check.json)

- 15.57 分钟 · 受理 review：异步追加返回成功但对应日志内容不同，驱动顺序仍需修正。[完整交接](submissions/86f6ae4f65884913a191e6ded6f8ee2a/accepted.json)

- 16.03 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e1ce7fac08f94fbf94e08ee431bcbb7f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-c-notify-identity](research.json)：[c-notify-identity](#claim-c-notify-identity)；具体进度与缺口见对应义务
- [3f4f8cd299a041a1b61c9d77ff3ade7b](research.json)：CheckRun 1193fe7d1b0942ab9e4b02a15e871f54 completed. Raw events correlate UUID cd3c2e81-e401-47fe-a5e6-7d49223d04cc: input 101, real old-leader assignment index 1 at ballot n=1 with old decided index 0, replacement value 202 decided at origin while the old future remained pending, then success Ok(1) with live decided value 202. The implication oracle is appropriate: success requires the invoked entry, while errors are allowed; assignment is one-based accepted length and read uses index minus one. No result is substituted. However, fixed harness lines 91-108 hold every non-TaggedProposal message during dispatch and immediately deliver the TaggedProposal. The stable() prefix only checks phases and can return before the final Accepted(0) response is drained. Such a message on 3->1 could be retained while the later TaggedProposal overtakes it. This contradicts the harness legality claim of per-link FIFO even though the decisive delayed 1->3 stream is ordered. The log does not record enough earlier messages to exclude this premise mismatch. Repair only that dispatch loop: continue delivering nonpartitioned traffic in order while retaining node 1 outbound traffic; leave the delayed assignment, replacement decision, contract and oracle unchanged. Fresh execution must retain the original discriminator.

<a id="candidate-f52a4a5873ef4bfa8aa3845439ce54a7"></a>

研究中问题：Does append_notify preserve the submitted entry identity when an old leader Assigned reply arrives after a new leader has decided another entry at that index?
[候选原文与历史](state.json)
保存的语义未知：Need execution of the real message-producing actors and a legal per-link ordered schedule to establish late assignment after replacement decision.

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Configuration isolation at transport/runtime boundaries.；Buffered StopSign handling after leadership loss.；Persistent backend atomicity, runtime notification identity across ballots, batching…
  尚无精确对应交接。

- b-elect：Heartbeat replies are stored in a vector without sender deduplication; legal transport duplication assumptions need reading.
  尚无精确对应交接。

- b-form：Whether delayed Accepted messages after same-ballot reconnect can misrepresent support requires producer-history analysis.
  尚无精确对应交接。

- b-follow：Buffered StopSign forwarding is absent from forward_buffered_proposals; its lifecycle when a preparing leader becomes a follower remains open.
  尚无精确对应交接。

- b-recover：Delayed same-ballot synchronization and replies across reconnect sessions require history analysis.
  尚无精确对应交接。

- b-storage：In-repository MemoryStorage and PersistentStorage implementations need inspection; injection does not externalize their obligations.；Compaction and snapshot merge paths need detailed reading.
  尚无精确对应交接。

- b-config：Public dispatch does not visibly filter SequencePaxos messages by configuration; caller routing duties across configurations need investigation.；Member uniqueness and next configuration id…
  尚无精确对应交接。

- b-client：Runtime batching reconciliation and decided subscription cursor behavior remain only partly read.
  尚无精确对应交接。

- b-notify：Does a real delayed Assigned from an isolated old leader survive until a different value is decided at the assigned slot under a new leader, and then produce success for the old request?
  相关交接：[交接 1](submissions/86f6ae4f65884913a191e6ded6f8ee2a/accepted.json)

- f-support：Same-ballot reconnect leaves previous indexes in place; determine why these remain valid under permitted crash and transport histories.
  尚无精确对应交接。

- f-assignment：Effect of late old-ballot assignment after a replacement entry is decided at that index.
  尚无精确对应交接。

- surface:Storage::write_atomically：Inspect captured backend implementations against the atomicity contract and restart behavior.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
