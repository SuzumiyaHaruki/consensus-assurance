# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 3 项；当前 Unit 3 项、义务 3 项、固定检查制品 3 项。已产生观察的正式结论 3 项：已确认违反 2 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **36.68 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 199.00 秒、26 次 Agent 调用、11 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2201.00 | 199.00 |
| Agent 调用 | 40 | 14 | 26 |
| 控制器目标执行 | 16 | 5 | 11 |
| 新 Unit | 6 | 3 | 3 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 3 次＋探索 2 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v47`；展示版本 `audit-products-v47`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`240.84125101599966`（配置值不表示触发了超时）。
[调用记录](logs/75a943c011ed4bab8e1f80dc5fc51425/check.json)；[stdout](logs/75a943c011ed4bab8e1f80dc5fc51425/stdout.log)；[stderr](logs/75a943c011ed4bab8e1f80dc5fc51425/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移超时后，隐式联合配置退出缺少继续触发 | 已确认违反；另有场景尚未完成 | 机械比较：观察到违反；对应性意见：no_issue_found；；评估已保存，当前检查尚未完整处置 | [O-implicit-exit-continuation](#claim-O-implicit-exit-continuation) |
| 2. Status 配置副本遗漏 AutoLeave | 已确认违反 | 三个节点实际应用隐式联合配置后，ApplyConfChange 返回 AutoLeave=true，但紧接着的 Status.Config 返回 false。实时配置仍为 true，正常退出也继续发生，因此证据支持状态导出错误，不支持实时共识状态损坏。 | [O-status-config-copy](#claim-O-status-config-copy) |
| 3. Does singleton ReadIndex preserve linearizable read safety after crash recovery when the durable log contains completed writes…（原文摘录） | 待调查线索 | 机械比较：观察到违反；对应性意见：尚未记录；Direct oracle correspondence is unreviewed；评估已保存，当前检查尚未完整处置 | [O-singleton-read-safety](#claim-O-singleton-read-safety) |

<a id="claim-O-implicit-exit-continuation"></a>

### 1. 领导权转移超时后，隐式联合配置退出缺少继续触发

**已确认违反**。要求原文：For a committed and applied implicit joint transition, Raft must retain automatic continuation to the final configuration when a leader and both quorums are available and caller-required ticking, transport, persistence and application continue. A rejected internal exit proposal during a transient leadership transfer must not leave the transition permanently dependent on an unrelated new client proposal after the transfer has ended.

决定性范围：Implicit joint exit with the current leader retained as a voter, a transient failed transfer, no ongoing failures and fair servicing of all implementation-requested work.
Configuration entry is genuinely committed and applied through the normal interface.；Transport may lose finitely many messages, then delivers all generated messages; local Ready work is processed reliably in order.；Stable available leader and sufficient incoming/outgoing voters; no infinite elections or failed storage.；No obligation for a fresh unrelated user command or manually proposed explicit exit is imposed on implicit-transition callers.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：False；独立场景完整处置：False。
[固定测试](direct-checks/ac82cea4acbf4a828f758deb67ba1f21/assurance_generated_test.go)；[条件与检查器](direct-checks/ac82cea4acbf4a828f758deb67ba1f21/plan.json)；[原始观察](logs/92f9eafb5eda45ac87090790bf0aed6c/stdout.log)；[assessment](direct-checks/ac82cea4acbf4a828f758deb67ba1f21/92f9eafb5eda45ac87090790bf0aed6c-assessment.json)；[对应性复核](submissions/a6f0872673c04a63b1be617ddc01e94a/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/92f9eafb5eda45ac87090790bf0aed6c/check.json)
执行边界：TestAssuranceJointExitFixed uses public RawNode calls for all mutations and read-only recursive state capture for recurrence. Stops after fixed service periods independently of joint-exit success.；Crash-free MemoryStorage persistence substitutes external disk, retaining Ready ordering.；Finite deliberate loss of TimeoutNow only in overlap prefix.；Read-only private-state serialization adds observation without changing protocol transitions.
固定比较 `check-autoexit-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 1 项。

观察缺口：Event 6 {'case': 'control', 'operation': 'implicit-remove-3'}: No corresponding prerequisite events reached: admitted/joint_applied, transfer/transfer_started

| 记录字段 | 观察 1（违反见证） | 观察 2（未完成） |
| --- | --- | --- |
| case | transfer_overlap | control |
| operation | implicit-remove-3 | implicit-remove-3 |
| event | cycle_result | cycle_result |
| recurrent | true | false |
| joint_active | true | false |
| admitted.index | 5 | 未记录 |
| admitted.case | transfer_overlap | 未记录 |
| admitted.auto_leave | true | 未记录 |
| admitted.node | 1 | 未记录 |
| transfer.index | 5 | 未记录 |
| transfer.transferee | 2 | 未记录 |
| conf_index | 5 | 5 |
| leader | 1 | 1 |
| live_auto_leave | true | false |
| outgoing_count | 3 | 0 |
| queue | 0 | 0 |
| role | StateLeader | StateLeader |
| term | 2 | 2 |
| transferee | 0 | 0 |

前提关联：观察 1 → matched；观察 2 → not_reached。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-O-status-config-copy"></a>

### 2. Status 配置副本遗漏 AutoLeave

**已确认违反**。要求原文：A Status configuration copy of an installed tracker configuration must preserve its AutoLeave value at the observation point, without changing the original configuration.

决定性范围：RawNode.Status in a serialized crash-free instance immediately after applying a genuinely committed implicit joint change, before further state-machine operations.
No concurrent mutation during Status call.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/edb999e034fe469ea38f3c5551262a0f/assurance_generated_test.go)；[条件与检查器](direct-checks/edb999e034fe469ea38f3c5551262a0f/plan.json)；[原始观察](logs/3fc0cc339fff420ab9534bb00d46b6ae/stdout.log)；[assessment](direct-checks/edb999e034fe469ea38f3c5551262a0f/3fc0cc339fff420ab9534bb00d46b6ae-assessment.json)；[对应性复核](submissions/981bf99d6869401bb8acd47e19327c73/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/3fc0cc339fff420ab9534bb00d46b6ae/check.json)
执行边界：Public RawNode mutation API and real three-node Ready/Advance loop; serialized paired configuration outputs before Advance.；MemoryStorage represents crash-free persistence with writes completed before outbound messages.；Read-only live flag diagnostic; no protocol mutation or substituted peer acknowledgments.
固定比较 `check-config-copy`：观察到违反；已比较 9 项，完整见证 3 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 | 观察 4（违反见证） | 观察 5（违反见证） | 观察 6（违反见证） | 观察 7 | 观察 8 | 观察 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| case | explicit | explicit | explicit | implicit | implicit | implicit | implicit | implicit | implicit |
| node | 1 | 2 | 3 | 1 | 2 | 3 | 1 | 2 | 3 |
| index | 5 | 5 | 5 | 5 | 5 | 5 | 6 | 6 | 6 |
| event | config_copy_result | config_copy_result | config_copy_result | config_copy_result | config_copy_result | config_copy_result | config_copy_result | config_copy_result | config_copy_result |
| auto_leave | false | false | false | false | false | false | false | false | false |
| installed.auto_leave | false | false | false | true | true | true | false | false | false |
| live_auto_leave | false | false | false | true | true | true | false | false | false |
| membership_equal | true | true | true | true | true | true | true | true | true |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched；观察 5 → matched；观察 6 → matched；观察 7 → matched；观察 8 → matched；观察 9 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-O-singleton-read-safety"></a>

### 3. Does singleton ReadIndex preserve linearizable read safety after crash recovery when the durable log contains completed writes…（原文摘录）

**待调查线索**。要求原文：A completed linearizable read served using a returned ReadState after applying strictly beyond its index must reflect the latest completed preceding register write when no later write intervenes, including after recovery from loss of only non-durable metadata.

决定性范围：Singleton register state machine using ReadOnlySafe, legal Ready processing and a crash preserving all synchronized state; recovered application follows committed-entry order and serves a read only after satisfying the returned index.
Write completion follows commitment and actual application.；Read invocation occurs after that write completion and after restart; no concurrent or intervening writes.；All MustSync=true work flushes preceding staged writes and log entries; only later MustSync=false metadata may be lost.；Snapshot is created from actually applied state and configuration.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/3226e76b52244dcea7eabcca01545606/assurance_generated_test.go)；[条件与检查器](direct-checks/3226e76b52244dcea7eabcca01545606/plan.json)；[原始观察](logs/9c5a903def644a949c591133e223be1c/stdout.log)；[assessment](direct-checks/3226e76b52244dcea7eabcca01545606/9c5a903def644a949c591133e223be1c-assessment.json)

当前争议／阻塞：Direct oracle correspondence is unreviewed

固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/9c5a903def644a949c591133e223be1c/check.json)
执行边界：Actual singleton protocol prefix, modeled required durable flushes, reconstruction and register application; no private state substitution.；Separate caller-owned staged and durable storage copies simulate permitted loss of non-synchronized metadata.；In-memory register resets to its actual saved snapshot and replays ordered committed entries.；Control flushes all Ready batches; main history flushes every MustSync batch.
固定比较 `check-singleton-read`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| history | singleton-false | singleton-true |
| event | read_completed | read_completed |
| value | A | B |
| written.value | B | B |
| written.index | 4 | 4 |
| invoked.context | after-restart | after-restart |
| invoked.prior_write_index | 4 | 4 |
| fence.context | after-restart | after-restart |
| applied | 3 | 5 |
| applied_beyond_fence | true | true |
| context | after-restart | after-restart |
| phase | restarted | restarted |
| read_index | 2 | 4 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：Can a fully replicated implicit configuration overlap a public TransferLeader call before Advance, and does a finite TimeoutNow loss followed by reliable heartbeat/application draining leave the old…
所选问题／策略（原文摘录）：Exercise the active Candidate with actual three-node bootstrap, election, replication and configuration application. All protocol mutations use public RawNode methods. MemoryStorage represents crash-free durable writes; no crashes occur.…
[受理问题、条件与来源](submissions/f47343aaa9ae4ccea54d461c4dc7092d/accepted.json)；[固定输入](submissions/f47343aaa9ae4ccea54d461c4dc7092d/inputs/joint_explore_test.go)
<a id="exploration-7787ec32a33f4ae0a2f558ac34428ecd"></a>
[探索执行 1](#exploration-7787ec32a33f4ae0a2f558ac34428ecd)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/7787ec32a33f4ae0a2f558ac34428ecd/check.json)；[实际输出](logs/7787ec32a33f4ae0a2f558ac34428ecd/stdout.log)；[诊断](logs/7787ec32a33f4ae0a2f558ac34428ecd/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/7787ec32a33f4ae0a2f558ac34428ecd/check.json)
[执行文件清单](experiments/bf3812042e8549748218129306b2a540/workspace-delta/manifest.json)；[执行文件清单](experiments/bf3812042e8549748218129306b2a540/workspace-outcome/manifest.json)；[执行文件清单](experiments/bf3812042e8549748218129306b2a540/workspace/assurance_generated_test.go)
后续受理交接原文导航：[交接 1](#exploration-feedback-cd8ca4bb2b2341afa0a1b0c48d3a464c)

条件探索：Can singleton ReadIndex return a stale completed read after a legal crash loses only non-synced commit metadata, while durable prior commands are replayed in bounded application batches? The caller…
所选问题／策略（原文摘录）：The singleton fast path bypasses the current-term commit guard. Ready.MustSync permits commit-only nondurable writes. This exploration constructs the pre-crash writes, actual synchronized log/HardState prefix and snapshot, then…
[受理问题、条件与来源](submissions/8532130c29f142ea9556fbe19b130f65/accepted.json)；[固定输入](submissions/8532130c29f142ea9556fbe19b130f65/inputs/singleton_explore_test.go)
<a id="exploration-0fd1590766834982ba62b47eac531581"></a>
[探索执行 2](#exploration-0fd1590766834982ba62b47eac531581)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/0fd1590766834982ba62b47eac531581/check.json)；[实际输出](logs/0fd1590766834982ba62b47eac531581/stdout.log)；[诊断](logs/0fd1590766834982ba62b47eac531581/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/0fd1590766834982ba62b47eac531581/check.json)
[执行文件清单](experiments/a90e7afa3dc24daeaf04aff3159893bb/workspace-delta/manifest.json)；[执行文件清单](experiments/a90e7afa3dc24daeaf04aff3159893bb/workspace-outcome/manifest.json)；[执行文件清单](experiments/a90e7afa3dc24daeaf04aff3159893bb/workspace/assurance_generated_test.go)
后续受理交接原文导航：[交接 2](#exploration-feedback-b087357834a44374bbfba4d834844214)

<a id="exploration-feedback-cd8ca4bb2b2341afa0a1b0c48d3a464c"></a>
[交接 1](#exploration-feedback-cd8ca4bb2b2341afa0a1b0c48d3a464c) · 后续说明；关联：[探索执行 1](#exploration-7787ec32a33f4ae0a2f558ac34428ecd)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration 7787ec32a33f4ae0a2f558ac34428ecd executed a three-node public-API history: implicit removal entry index 5 was committed and applied; transfer target 2 was installed before Advance; one emitted TimeoutNow was dropped. At timeout and after thirty…
[完整交接；精确引用不表示已解决或已正式化](submissions/cd8ca4bb2b2341afa0a1b0c48d3a464c/accepted.json)

<a id="exploration-feedback-b087357834a44374bbfba4d834844214"></a>
[交接 2](#exploration-feedback-b087357834a44374bbfba4d834844214) · 后续说明；关联：[探索执行 2](#exploration-0fd1590766834982ba62b47eac531581)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration 0fd1590766834982ba62b47eac531581 completed both commands at indexes 3 and 4 with value B, durable last=4 and durable commit=2. Restart from that actual durable state elected term 3, returned ReadState index 2, then served A after applying index 3…
[完整交接；精确引用不表示已解决或已正式化](submissions/b087357834a44374bbfba4d834844214/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：A leader admits proposals subject to membership, transfer and configuration guards, assigns term/index and replicates. Followers validate previous log identity and preserve committed prefixes. Append responses and self…
- 上下文／权威转换（原文导航摘录）：Eligible followers campaign after logical timeout or explicit request, with unapplied committed configuration and pending-snapshot guards. Vote freshness and term/vote rules constrain support; persisted self and remote…
- 两条主线的连接（原文导航摘录）：Authority selects whose support can form decisions, but committed history survives authority changes. Log freshness carries prior decisions into elections; current-term commitment qualifies deferred read processing.…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.15 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.11 分钟 · 受理 continue：The implicit-transition interface assigns exit initiation to raft, unlike explicit transitions. Source review narrows the discriminator to…。[完整交接](submissions/f685df71daad4c1b927e067ccc04833e/accepted.json)

- 11.59 分钟 · 实际执行：Exercise the active Candidate with actual three-node bootstrap, election, replication and configuration application. All protocol mutations…；探索执行正常结束。[执行记录](logs/7787ec32a33f4ae0a2f558ac34428ecd/check.json)

- 14.67 分钟 · 受理 obligation：Ground the implementation-owned implicit exit responsibility separately from bounded waiting. The next fixed check will look for a closed,…。[完整交接](submissions/cd8ca4bb2b2341afa0a1b0c48d3a464c/accepted.json)

- 17.87 分钟 · 实际执行：领导权转移超时后，隐式联合配置退出缺少继续触发；执行完成；比较见 assessment。[执行记录](logs/92f9eafb5eda45ac87090790bf0aed6c/check.json)

- 20.64 分钟 · 受理 review：领导权转移超时后，隐式联合配置退出缺少继续触发。[完整交接](submissions/a6f0872673c04a63b1be617ddc01e94a/accepted.json)

- 23.45 分钟 · 受理 obligation：Investigate the independent copy responsibility exposed by the prior observation discrepancy. Keep the confirmed continuation result and…。[完整交接](submissions/f3191dcf1fbe40f59b11e61d40a28c9b/accepted.json)

- 25.06 分钟 · 实际执行：Status 配置副本遗漏 AutoLeave；执行完成；比较见 assessment。[执行记录](logs/3fc0cc339fff420ab9534bb00d46b6ae/check.json)

- 26.76 分钟 · 受理 review：Status 配置副本遗漏 AutoLeave。[完整交接](submissions/981bf99d6869401bb8acd47e19327c73/accepted.json)

- 31.18 分钟 · 受理 explore：The singleton fast path bypasses the current-term commit guard. Ready.MustSync permits commit-only nondurable writes. This exploration…。[完整交接](submissions/8532130c29f142ea9556fbe19b130f65/accepted.json)

- 31.43 分钟 · 实际执行：The singleton fast path bypasses the current-term commit guard. Ready.MustSync permits commit-only nondurable writes. This exploration…；探索执行正常结束。[执行记录](logs/0fd1590766834982ba62b47eac531581/check.json)

- 33.54 分钟 · 受理 obligation：Fix the read-safety responsibility from the interface under an explicitly permitted durability model, independently of request-loss…。[完整交接](submissions/b087357834a44374bbfba4d834844214/accepted.json)

- 35.69 分钟 · 受理 check：Fresh fixed execution with actual write/read endpoint correlation and a stronger-durability control; no reinterpretation of exploration as…。[完整交接](submissions/3226e76b52244dcea7eabcca01545606/accepted.json)

- 35.95 分钟 · 实际执行：Does singleton ReadIndex preserve linearizable read safety after crash recovery when the durable log contains completed writes…（原文摘录）；执行完成；比较见 assessment。[执行记录](logs/9c5a903def644a949c591133e223be1c/check.json)

- 36.67 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/75a943c011ed4bab8e1f80dc5fc51425/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-O-implicit-exit-continuation](research.json)：[O-implicit-exit-continuation](#claim-O-implicit-exit-continuation)；具体进度与缺口见对应义务
- [unit-O-singleton-read-safety](research.json)：[O-singleton-read-safety](#claim-O-singleton-read-safety)；具体进度与缺口见对应义务

<a id="candidate-4aab3da6357c49b7b30616e98205979c"></a>

暂停调查：After an implicit joint configuration has been committed and applied, does raft retain an automatic exit continuation when the appliedTo proposal is rejected by an in-progress leader transfer which subsequently times out, while the original leader and both quorums remain available and all existing work is drained?
[候选原文与历史](state.json)
保存的语义未知：A fixed check must establish a repeatable suffix from behavior-determining state, external tick/message schedule and drained queues; finite elapsed ticks alone do not exclude future automatic continuation.

<a id="candidate-2d4aabb0fa7e4b35b5f07e8eb963a28d"></a>

研究中问题：Does singleton ReadIndex preserve linearizable read safety after crash recovery when the durable log contains completed writes beyond a legally non-durable commit index, and a new leader answers before committing its current-term entry?
[候选原文与历史](state.json)

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Deferred reads after configuration-triggered commitment.；Separate pendingReadIndexMessages lifecycle across resets.；Lease-read assumptions and deeper membership/recovery overlap variants remain open.
  尚无精确对应交接。

- B-election：pendingReadIndexMessages is separate from readOnly and is not cleared in reset; investigate subsequent use across role changes.
  尚无精确对应交接。

- B-config：Can configuration-triggered first current-term commitment legally leave pending reads without a release trigger?
  相关交接：[交接 1](submissions/8532130c29f142ea9556fbe19b130f65/accepted.json)

- B-read：Configuration-triggered commitment differs from append-response commitment in its deferred-read follow-up.
  相关交接：[交接 1](submissions/8532130c29f142ea9556fbe19b130f65/accepted.json)；[交接 2](submissions/b087357834a44374bbfba4d834844214/accepted.json)

- B-config-copy：Whether consumers outside the captured library use Status.Config for persistence or operational decisions is not established.
  相关交接：[交接 1](submissions/981bf99d6869401bb8acd47e19327c73/accepted.json)

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
