# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **20.41 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1175.64 秒、33 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1224.36 | 1175.64 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 24.71 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 25.60 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v50`；展示版本 `audit-products-v50`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/a461e21f6e4b4728b3b54efef8e8cc4d/check.json)；[stdout](logs/a461e21f6e4b4728b3b54efef8e8cc4d/stdout.log)；[stderr](logs/a461e21f6e4b4728b3b54efef8e8cc4d/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移失败后，自动退出联合配置缺少继续触发 | 已确认违反 | 已提交的固定检查观察到：转移超时后，活跃 AutoLeave 仍为 true，系统在持续处理心跳、存储及 Ready 的情况下回到相同完整协议状态，联合配置未退出。后续普通提案可恢复退出；这支持限定调度下的自动继续执行缺陷，不表示共识安全破坏或固定时限超时。 | [C-auto-continuation](#claim-C-auto-continuation) |

<a id="claim-C-auto-continuation"></a>

### 1. 领导权转移失败后，自动退出联合配置缺少继续触发

**已确认违反**。要求原文：After a committed implicit joint configuration has been applied, Raft must retain implementation-owned continuation to propose its final configuration when safe and possible. A leadership transfer that expires without replacing the leader must not leave this automatic transition permanently dependent on an unrelated new client proposal when joint quorums, tick processing, transport and storage/application processing remain available.

决定性范围：Automatic joint-exit continuation under a stable same-term leader following failed transfer; serialized ordinary RawNode callers, continuing required ticks and reliable transport after finite loss.
The initiating implicit configuration proposal actually committed and was applied; application does not reject it.；After finite transfer-trigger message loss, both constituent quorums remain available, all produced network messages and Ready batches are processed, and no future client proposal or campaign is required to drive the automatic transition.；No crashes, no Byzantine messages, ordinary configuration validation enabled.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/ba280b9ed3ec4970b1cdf0dd26b41e3b/assurance_generated_test.go)；[条件与检查器](direct-checks/ba280b9ed3ec4970b1cdf0dd26b41e3b/plan.json)；[原始观察](logs/b3eb529c83cf4f2cb0805dd73823d8ab/stdout.log)；[assessment](direct-checks/ba280b9ed3ec4970b1cdf0dd26b41e3b/b3eb529c83cf4f2cb0805dd73823d8ab-assessment.json)；[对应性复核](submissions/6e6c738895304cd0a52b965e194cba1c/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.36 秒；执行进程耗时 11.91 秒；[实际命令、工具版本与输入记录](logs/b3eb529c83cf4f2cb0805dd73823d8ab/check.json)
执行边界：Serialized public RawNode APIs with read-only internal observation. Fresh bootstrap generates membership history; all peer messages arise from actual Ready output and are protobuf-cloned into a FIFO transport. Persist MemoryStorage, apply entries/configurations and Advance in order. No spawned goroutines or deferred callbacks; RawNode needs no shutdown method. Full JSON state retained at both suffix cuts, without hashes.；Substitute in-memory synchronous storage for durable media in no-crash scope.；Replace external transport with a FIFO queue; transiently drop transfer-trigger network messages by predetermined type/time policy.；Read internal state with reflection, omitting only logger/traceLogger, storage mutex and diagnostic call counters; retain all semantic fields including private inflight state and timers. No target state is written by observation.；Compare handler function identities and captured receiver state; no alternate algorithm or callback implementation.；Status.Config.AutoLeave is retained only diagnostically; principal selector reads live raft.trk.Config.AutoLeave.
固定比较 `CK-auto-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | failed_transfer |
| node | 1 |
| conf_index | 5 |
| event | cycle_result |
| closed_pending_cycle | true |
| admitted.policy_transfer | true |
| admitted.live_auto_leave | true |
| admitted.joint | true |
| admitted.transfer_active | true |
| admitted.role | StateLeader |
| deliveries | 40 |
| delivery_errors | 0 |
| end_pending | true |
| kind | cycle_result |
| live_auto_leave | true |
| only_heartbeat_delivery | true |
| outgoing_count | 3 |
| policy_transfer | true |
| same_state | true |
| start_pending | true |
| tick | 30 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For candidate 8b412541680b42dd938dc9d5945e1aed, can actual three-node producers reach application-completion rejection during a transfer, then remain joint after transfer timeout while transport,…
所选问题／策略（原文摘录）：Use public RawNode bootstrap, campaign, proposal, application and transfer APIs; no internal writes or fabricated peer responses. One FIFO transport serializes actual emitted messages and transiently drops MsgTimeoutNow through ten ticks.…
[受理问题、条件与来源](submissions/fae007e987274eb4b5df7bbd1b810cde/accepted.json)；[固定输入](submissions/fae007e987274eb4b5df7bbd1b810cde/inputs/autoleave_explore_test.go)
<a id="exploration-5f3a0ce8f3f04e0fb97500e9ef58228c"></a>
[探索执行 1](#exploration-5f3a0ce8f3f04e0fb97500e9ef58228c)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/5f3a0ce8f3f04e0fb97500e9ef58228c/check.json)；[实际输出](logs/5f3a0ce8f3f04e0fb97500e9ef58228c/stdout.log)；[诊断](logs/5f3a0ce8f3f04e0fb97500e9ef58228c/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.25 秒；执行进程耗时 12.81 秒；[实际命令、工具版本与输入记录](logs/5f3a0ce8f3f04e0fb97500e9ef58228c/check.json)
[执行文件清单](experiments/3fa6e294679344ccb126365229205710/workspace-delta/manifest.json)；[执行文件清单](experiments/3fa6e294679344ccb126365229205710/workspace-outcome/manifest.json)；[执行文件清单](experiments/3fa6e294679344ccb126365229205710/workspace/assurance_generated_test.go)
后续受理交接原文导航：[交接 1](#exploration-feedback-40776cdbcca247c78089e51aad3c9900)

<a id="exploration-feedback-40776cdbcca247c78089e51aad3c9900"></a>
[交接 1](#exploration-feedback-40776cdbcca247c78089e51aad3c9900) · 后续说明；关联：[探索执行 1](#exploration-5f3a0ce8f3f04e0fb97500e9ef58228c)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration 5f3a0ce8f3f04e0fb97500e9ef58228c completed with actual producer history. Leader term 2 applied implicit joint entry index 5, started transfer to 2 before Advance, and one emitted MsgTimeoutNow was dropped. At tick 10 transferee cleared; through…
[完整交接；精确引用不表示已解决或已正式化](submissions/40776cdbcca247c78089e51aad3c9900/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：A1: a leader assigns term/index to proposals, appends unstable entries and replicates through peer Progress. Local and remote append support is published after persistence. Responses pass term dispatch and known-peer…
- 上下文／权威转换（原文导航摘录）：A2: eligible voters campaign only without unapplied committed configuration or pending snapshot. Real campaign increments term, records self vote durably and requests votes using last log term/index; configured majority…
- 两条主线的连接（原文导航摘录）：Applied membership determines support eligibility for both election and log commitment. Joint config requires both old and new majorities; recovery restores that same configuration, not a fresh quorum. Term reset clears…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.05 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 10.10 分钟 · 实际执行：Use public RawNode bootstrap, campaign, proposal, application and transfer APIs; no internal writes or fabricated peer responses. One FIFO…；探索执行正常结束。[执行记录](logs/5f3a0ce8f3f04e0fb97500e9ef58228c/check.json)

- 13.67 分钟 · 受理 obligation：Ground automatic continuation without imposing a deadline; retain exploration as construction knowledge and separately preserve discovered…。[完整交接](submissions/40776cdbcca247c78089e51aad3c9900/accepted.json)

- 16.82 分钟 · 受理 check：Construct a fresh fixed recurrent-state witness against the accepted automatic-continuation duty. Preserve the tested legal overlap,…。[完整交接](submissions/ba280b9ed3ec4970b1cdf0dd26b41e3b/accepted.json)

- 17.03 分钟 · 实际执行：领导权转移失败后，自动退出联合配置缺少继续触发；执行完成；比较见 assessment。[执行记录](logs/b3eb529c83cf4f2cb0805dd73823d8ab/check.json)

- 19.92 分钟 · 受理 review：领导权转移失败后，自动退出联合配置缺少继续触发。[完整交接](submissions/6e6c738895304cd0a52b965e194cba1c/accepted.json)

- 20.40 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/a461e21f6e4b4728b3b54efef8e8cc4d/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Same-leader quiet-suffix closure after failed transfer; finite queue-drained observations and later proposal rescue do not alone prove indefinite lost continuation.；Configuration-driven pending-read…
  尚无精确对应交接。

- B-election：pendingReadIndexMessages survives reset while readOnly is replaced; exact cross-term pending-request consequences remain unexamined.
  尚无精确对应交接。

- B-transfer：Does the observed timeout-without-retry admit an indefinitely repeatable quiet suffix under fully available quorums?
  相关交接：[交接 1](submissions/6e6c738895304cd0a52b965e194cba1c/accepted.json)

- B-config：Can configuration-driven first current-term commitment leave pending reads without an implementation trigger? ReadIndex explicitly requires caller retries, so absence alone is not a completion…
  尚无精确对应交接。

- B-auto：Whether the same-leader quiet suffix after failed transfer is closed under all required ticks, peer responses and Ready completions without new client proposals.
  相关交接：[交接 1](submissions/6e6c738895304cd0a52b965e194cba1c/accepted.json)

- B-io：Fine-grained asynchronous snapshot/application overlap remains unread beyond the completion handlers.
  尚无精确对应交接。

- B-client：Read retry progress and changed-configuration pending-read retention need separate applicability analysis.
  尚无精确对应交接。

- B-status：Does a fixed same-history check confirm the copy-preservation contract fails for an actually produced automatic joint configuration?
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
