# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。已产生观察的正式结论 1 项：已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **29.07 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 655.75 秒、33 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1744.25 | 655.75 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 1 次＋探索 1 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v45`；展示版本 `audit-products-v45`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/292f283d04c94d49a897f0c95bdf9e88/check.json)；[stdout](logs/292f283d04c94d49a897f0c95bdf9e88/stdout.log)；[stderr](logs/292f283d04c94d49a897f0c95bdf9e88/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移失败后，自动退出联合配置失去继续触发 | 已确认违反 | 固定执行中，隐式联合配置已提交并应用，丢失一条 TimeoutNow 后原领导者继续服务；在持续心跳和完整处理待办工作的十个 tick 周期内，协议状态完整重复而 AutoLeave 仍未完成。无转移对照正常退出，后续普通提案也能恢复退出，因此结论限于缺少无关新提案时的自动继续机制，不是共识安全或整体服务停顿。 | [C-auto-exit-continuation](#claim-C-auto-exit-continuation) |

<a id="claim-C-auto-exit-continuation"></a>

### 1. 领导权转移失败后，自动退出联合配置失去继续触发

**已确认违反**。要求原文：After an implicit joint configuration has been committed and applied, Raft must retain or restore an internally driven continuation to leave the joint configuration when an overlapping leadership transfer aborts, provided leadership and a viable joint quorum remain stable and required storage, application, ticks and network work continue. Completing that automatic transition must not depend on an unrelated new client proposal.

决定性范围：Implementation-owned automatic joint-exit continuation under an aborted transfer with stable leadership and viable joint quorum.
Only network TimeoutNow loss is needed in the prefix; ordinary Raft messages continue to be delivered；Caller performs ordered persistence, committed configuration application and completion acknowledgments；The suffix contains regular ticks and drains all resulting work without unrelated new proposals；No crash, Byzantine input, invalid membership operation or skipped caller completion。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/a220543c8d2c42ebacdcd0a6f854f473/assurance_generated_test.go)；[条件与检查器](direct-checks/a220543c8d2c42ebacdcd0a6f854f473/plan.json)；[原始观察](logs/aaa140bb2be04782910221a321e75432/stdout.log)；[assessment](direct-checks/a220543c8d2c42ebacdcd0a6f854f473/aaa140bb2be04782910221a321e75432-assessment.json)；[对应性复核](submissions/017f63cdbe644a8194dda4db775df6e9/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/aaa140bb2be04782910221a321e75432/check.json)
执行边界：Three real RawNodes with MemoryStorage, public mutation APIs, serialized Ready handling and complete deterministic network drain. All assertions before result are initialization/driver prerequisites. The fixed result is emitted regardless of recurrence or exit outcome.；No protocol modifications or internal field writes.；MemoryStorage substitutes successful durable-write completion under a no-crash fault schedule.；Reflection reads private state only to compare two complete runtime states; excludes non-behavioral logger objects and storage access counters.；Drops exactly the first generated TimeoutNow in transfer branch; later messages are delivered.；Absolute test tick/event counters are omitted from recurrence state because the independently declared repeated input is ten tick-all/drain iterations; they do not feed Raft.
固定比较 `CK-auto-exit-cycle`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| operation_id | without_transfer/implicit-remove-3 | aborted_transfer/implicit-remove-3 |
| event | recurrence_result | recurrence_result |
| cycle_repeat | false | true |
| pending | false | true |
| operation.operation_id | without_transfer/implicit-remove-3 | aborted_transfer/implicit-remove-3 |
| operation.entered | true | true |
| operation.all_work_drained | true | true |
| suffix.operation_id | without_transfer/implicit-remove-3 | aborted_transfer/implicit-remove-3 |
| suffix.eligible | true | true |
| all_work_drained | true | true |
| applied | 6 | 5 |
| case | without_transfer | aborted_transfer |
| commit | 6 | 5 |
| config.auto_leave | false | true |
| configuration_index | 5 | 5 |
| cycle_ticks | 10 | 10 |
| deliveries.1>2:MsgApp | 6 | 4 |
| deliveries.1>2:MsgHeartbeat | 30 | 30 |
| deliveries.1>2:MsgVote | 1 | 1 |
| deliveries.1>3:MsgApp | 6 | 4 |
| deliveries.1>3:MsgVote | 1 | 1 |
| deliveries.2>1:MsgAppResp | 6 | 4 |
| deliveries.2>1:MsgHeartbeatResp | 30 | 30 |
| deliveries.2>1:MsgVoteResp | 1 | 1 |
| deliveries.3>1:MsgAppResp | 6 | 4 |
| deliveries.3>1:MsgVoteResp | 1 | 1 |
| dropped_timeout_now | 0 | 1 |
| last | 6 | 5 |
| lead | 1 | 1 |
| leave_entries | 1 | 0 |
| pending_conf | 6 | 5 |
| phase | recurrence_result | recurrence_result |
| queue | 0 | 0 |
| role | StateLeader | StateLeader |
| state.configuration_index | 5 | 5 |
| state.timeout_now_already_dropped | 0 | 1 |
| state.transfer_injected | true | true |
| state.transfer_policy | false | true |
| term | 2 | 2 |
| ticks | 30 | 30 |
| transfer | 0 | 0 |
| deliveries.1>3:MsgHeartbeat | 未记录 | 30 |
| deliveries.3>1:MsgHeartbeatResp | 未记录 | 30 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For candidate 7a4d12cd2e7049239f2a24776a95391f, does applying a committed implicit joint change while transfer is active suppress automatic leave, and do ordinary ticks/heartbeats restore it after…
所选问题／策略（原文摘录）：The legal schedule uses three bootstrapped RawNodes, full persistence and ordered application through Ready/Advance, an actual committed implicit removal, and a public TransferLeader call after ApplyConfChange but before Advance. Only…
[受理问题、条件与来源](submissions/b037f84c9a154a92b6d76e50c1913cce/accepted.json)；[固定输入](submissions/b037f84c9a154a92b6d76e50c1913cce/inputs/autoleave_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/4cefa9ac8b454a8891e746a89558055c/check.json)；[实际输出](logs/4cefa9ac8b454a8891e746a89558055c/stdout.log)；[诊断](logs/4cefa9ac8b454a8891e746a89558055c/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/4cefa9ac8b454a8891e746a89558055c/check.json)
[执行文件清单](experiments/27c2bd6ac1ba400f9e0c71f5382902b1/workspace-delta/manifest.json)；[执行文件清单](experiments/27c2bd6ac1ba400f9e0c71f5382902b1/workspace-outcome/manifest.json)；[执行文件清单](experiments/27c2bd6ac1ba400f9e0c71f5382902b1/workspace/assurance_generated_test.go)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/61c544b7746e422691a78dfe987e3ee3/accepted.json)

后续受理解释（关联 1 次执行）：Exploration CheckRun 4cefa9ac8b454a8891e746a89558055c completed. Both branches bootstrapped three nodes, elected node 1 and committed/applied implicit removal of node 3 at index 5. Without transfer, the internal leave entry committed/applied at 6. With…
[完整交接；精确引用不表示已解决或已正式化](submissions/61c544b7746e422691a78dfe987e3ee3/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader proposals acquire current term/index and enter the unstable log. Self and follower append acknowledgments wait for caller persistence before contributing Match support. Voting membership selects the majority…
- 上下文／权威转换（原文导航摘录）：A promotable node without unapplied committed configuration changes can campaign. Pre-vote does not change term; real candidacy increments term and persists votes, and only current voting quorum support wins. Winning…
- 两条主线的连接（原文导航摘录）：Membership qualifies both election and replication support. Term resets discard old match/vote/readOnly acknowledgment tracking; Step rejects stale responses, while previously committed history remains binding. Entry…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.35 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 11.45 分钟 · 实际执行：The legal schedule uses three bootstrapped RawNodes, full persistence and ordered application through Ready/Advance, an actual committed…；条件观察完成。[执行记录](logs/4cefa9ac8b454a8891e746a89558055c/check.json)

- 14.92 分钟 · 受理 obligation：Exploration resolved legal overlap and observed a trigger-dependent result. Fix the automatic-transition responsibility separately from any…。[完整交接](submissions/61c544b7746e422691a78dfe987e3ee3/accepted.json)

- 20.35 分钟 · 受理 check：Fresh fixed execution for the accepted automatic-exit obligation. Add complete-state recurrence to address the finite-observation gap while…。[完整交接](submissions/a220543c8d2c42ebacdcd0a6f854f473/accepted.json)

- 20.62 分钟 · 实际执行：领导权转移失败后，自动退出联合配置失去继续触发；执行完成；比较见 assessment。[执行记录](logs/aaa140bb2be04782910221a321e75432/check.json)

- 24.84 分钟 · 受理 review：领导权转移失败后，自动退出联合配置失去继续触发。[完整交接](submissions/017f63cdbe644a8194dda4db775df6e9/accepted.json)

- 29.07 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/292f283d04c94d49a897f0c95bdf9e88/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Optimized early Advance and configuration application timing；Repeatable application-free suffix after failed transfer；Detailed snapshot storage errors and compaction ownership；Read context queue…
  尚无精确对应交接。

- B-election：Interactions of optimized Advance-before-application with election configuration scanning remain unexamined
  尚无精确对应交接。

- B-leadercommit：Configuration-triggered commit has different read-release effects; legal first-current-term history remains unresolved
  尚无精确对应交接。

- B-durability：Concrete caller durable storage is outside this library; MemoryStorage is not crash durability
  尚无精确对应交接。

- B-recovery：Storage errors and snapshot worker failure schedules require further focused reading
  尚无精确对应交接。

- B-config：Read continuation when configuration application first commits a current-term entry remains a legal-history question
  尚无精确对应交接。

- B-autoleave：Whether an application-free heartbeat/tick execution after abort preserves all behavior-determining state across a complete timer period
  相关交接：[交接 1](submissions/61c544b7746e422691a78dfe987e3ee3/accepted.json)；[交接 2](submissions/017f63cdbe644a8194dda4db775df6e9/accepted.json)

- B-apply：Optimized early Advance is allowed by Node documentation; exact configuration ordering consequences remain open
  尚无精确对应交接。

- B-read：Whether earlier pending messages surviving role changes create a separate resource or correlation responsibility；Configuration commit/read-release asymmetry has no established completion violation;…
  尚无精确对应交接。

- surface:MemoryStorage and unstable ownership/compaction：Read slice ownership and compaction/reconstruction mechanisms beyond their interface boundary.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
