# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **23.95 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 962.91 秒、34 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1437.09 | 962.91 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 30.56 秒。

目标动作总耗时（含已记录的准备与复制）：未记录有效总量；2 项未完整记录，合计不完整。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v49`；展示版本 `audit-products-v49`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/8214cfbc18054a4285cc9017185c9ccb/check.json)；[stdout](logs/8214cfbc18054a4285cc9017185c9ccb/stdout.log)；[stderr](logs/8214cfbc18054a4285cc9017185c9ccb/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移失败后，隐式联合配置可能失去自动退出触发 | 已确认违反 | 在已应用的隐式联合配置与领导权转移重叠、仅丢失一次 TimeoutNow 的历史中，转移超时后出现完整状态重复的心跳执行周期，AutoLeave 仍为 true。后续普通提案可以触发退出；本结果限定为自动继续执行责任，不声称共识安全破坏。 | [claim_auto_joint_continuation](#claim-claim_auto_joint_continuation) |

<a id="claim-claim_auto_joint_continuation"></a>

### 1. 领导权转移失败后，隐式联合配置可能失去自动退出触发

**已确认违反**。要求原文：After an implicit joint configuration has been committed and applied, Raft must retain an implementation-owned continuation that eventually initiates exit once doing so is possible. If a temporary leader transfer rejects the initial exit proposal and subsequently aborts, a continuing eligible leader with available joint quorums, regular ticks and completed storage/application work must not remain indefinitely in that joint configuration solely because no unrelated client proposal or explicit leave-joint request arrives.

决定性范围：Implicit joint transitions under a stable current leader after a failed transfer, with caller transport, storage and application duties fulfilled. The obligation is automatic continuation, not a time bound on exit.
Crash-fault protocol participants; no Byzantine message fabrication or state mutation.；Reliable transport after a finite loss, continued regular ticks, quorums available in both configurations, no subsequent forced leadership change.；Caller persists Ready before sending messages, applies committed configurations in order, and completes each Ready with Advance (or obeys corresponding async completion duties).；No continuing leadership-transfer request, explicit configuration request or unrelated workload is required to rescue Raft-owned implicit exit.。
范围参数：{"transition": "ConfChangeTransitionJointImplicit"}
[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/44176fa2ca7c4b308ed397b6406d5ad8/assurance_generated_test.go)；[条件与检查器](direct-checks/44176fa2ca7c4b308ed397b6406d5ad8/plan.json)；[原始观察](logs/5ef2409f00cd47c983439ae485dde415/stdout.log)；[assessment](direct-checks/44176fa2ca7c4b308ed397b6406d5ad8/5ef2409f00cd47c983439ae485dde415-assessment.json)；[对应性复核](submissions/5879c4e494674df29e6a94d9f28cfee9/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 14.72 秒；[实际命令、工具版本与输入记录](logs/5ef2409f00cd47c983439ae485dde415/check.json)
执行边界：Serialized RawNode network with synchronous MemoryStorage persistence and actual committed configuration application; read-only recursive state observation and no modified target code.；MemoryStorage represents durable completion without injecting crashes; application processing records configuration application and otherwise consumes normal entries.；A single emitted TimeoutNow is lost in the selected network policy; subsequent delivery is reliable.；Read-only reflection and JSON event reporting observe private protocol state; logging, storage call statistics and unlocked mutex internals are excluded from recurrence comparison.
固定比较 `joint_auto_exit_cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case_id | implicit-remove3-overlap-true |
| config_index | 3 |
| event | cycle_result |
| cycle_closed | true |
| auto_leave | true |
| admitted.applied | 3 |
| admitted.overlap | true |
| admitted.implicit | true |
| admitted.auto_leave | true |
| admitted.transfer | 2 |
| admitted.timeout_drops | 1 |
| admitted.drained | true |
| start.applied | 3 |
| start.leader | true |
| start.transfer | 0 |
| start.timeout_drops | 1 |
| start.drained | true |
| all_rounds_drained | true |
| applied | 3 |
| heartbeat_messages_only | true |
| joint | true |
| last | 3 |
| overlap | true |
| phase | cycle_result |
| stable_leader | true |
| state_equal | true |
| timeout_drops | 1 |
| transfer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：Can a fully produced implicit joint change overlap a failed transfer, then remain joint after application work drains and reliable tick/message processing resumes? Observe no-transfer control and a…
所选问题／策略（原文摘录）：Candidate 584b72abffa84bc88a7de31800f4271d has a specific producer-history uncertainty. Source assigns automatic exit to Raft when possible; the only normal retry entry is appliedTo, whereas transfer abort clears only its field. The…
[受理问题、条件与来源](submissions/8f6ad00e20794cd68723616be5f4f64f/accepted.json)；[固定输入](submissions/8f6ad00e20794cd68723616be5f4f64f/inputs/joint_exit_explore_test.go)
<a id="exploration-e3c2ba7fe2ee42f0a688d757f326d034"></a>
[探索执行 1](#exploration-e3c2ba7fe2ee42f0a688d757f326d034)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/e3c2ba7fe2ee42f0a688d757f326d034/check.json)；[实际输出](logs/e3c2ba7fe2ee42f0a688d757f326d034/stdout.log)；[诊断](logs/e3c2ba7fe2ee42f0a688d757f326d034/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 15.84 秒；[实际命令、工具版本与输入记录](logs/e3c2ba7fe2ee42f0a688d757f326d034/check.json)
[执行文件清单](experiments/012363b43f684d73b12b5b4740e46426/workspace-delta/manifest.json)；[执行文件清单](experiments/012363b43f684d73b12b5b4740e46426/workspace-outcome/manifest.json)；[执行文件清单](experiments/012363b43f684d73b12b5b4740e46426/workspace/assurance_generated_test.go)
后续受理交接原文导航：[交接 1](#exploration-feedback-70848c5ea82843dfb49986101915bf01)

<a id="exploration-feedback-70848c5ea82843dfb49986101915bf01"></a>
[交接 1](#exploration-feedback-70848c5ea82843dfb49986101915bf01) · 后续说明；关联：[探索执行 1](#exploration-e3c2ba7fe2ee42f0a688d757f326d034)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration e3c2ba7fe2ee42f0a688d757f326d034 produced an actual three-node term-2 election and implicit removal of node 3 at index 3. Transfer to caught-up node 2 began before leader configuration application; exactly one emitted MsgTimeoutNow was dropped.…
[完整交接；精确引用不表示已解决或已正式化](submissions/70848c5ea82843dfb49986101915bf01/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：A caller proposes through RawNode/Node. The leader assigns term/index, appends unstable entries and replicates with predecessor identity. Followers require matching predecessor, refuse committed conflicts, and queue…
- 上下文／权威转换（原文导航摘录）：A promotable node with no unapplied committed configuration changes campaigns, optionally with pre-vote. Votes require eligible vote state and an up-to-date candidate log; configured voter quorums determine election.…
- 两条主线的连接（原文导航摘录）：The term and active configuration jointly qualify support: a leader consumes only current-context responses from tracked participants, while quorum evaluation selects voters and joint majorities. Membership application…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.01 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.16 分钟 · 实际执行：Candidate 584b72abffa84bc88a7de31800f4271d has a specific producer-history uncertainty. Source assigns automatic exit to Raft when…；探索执行正常结束。[执行记录](logs/e3c2ba7fe2ee42f0a688d757f326d034/check.json)

- 13.10 分钟 · 受理 obligation：Ground the implicit-exit continuation duty separately from its proposed recurrent-suffix evidence. The legal overlap and bounded…。[完整交接](submissions/70848c5ea82843dfb49986101915bf01/accepted.json)

- 16.79 分钟 · 受理 check：Construct a separately fixed event implication for the accepted automatic-exit obligation. Preserve the explored legal overlap, use…。[完整交接](submissions/44176fa2ca7c4b308ed397b6406d5ad8/accepted.json)

- 17.05 分钟 · 实际执行：领导权转移失败后，隐式联合配置可能失去自动退出触发；执行完成；比较见 assessment。[执行记录](logs/5ef2409f00cd47c983439ae485dde415/check.json)

- 20.43 分钟 · 受理 review：领导权转移失败后，隐式联合配置可能失去自动退出触发。[完整交接](submissions/5879c4e494674df29e6a94d9f28cfee9/accepted.json)

- 23.94 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/8214cfbc18054a4285cc9017185c9ccb/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Whether the source-local absence of an automatic-exit retry after transfer abort admits a complete recurrent execution suffix under continued caller service.；Read queue behavior when configuration…
  尚无精确对应交接。

- b_membership：Whether read requests deferred before first current-term commit can remain pending after a configuration-induced commit; caller ReadIndex retries are explicitly required.
  尚无精确对应交接。

- b_recovery：Detailed recovery of concurrent snapshot and apply work remains outside the initial backbone.
  尚无精确对应交接。

- b_reads：Effects of retained pre-commit requests across authority and membership changes require narrower histories.
  尚无精确对应交接。

- surface:Node.Ready and RawNode.ApplyConfChange documentation：doc.go instructs calling ApplyConfChange for cancelled changes using NodeID zero, while Node/RawNode comments allow rejection without a call; distinguish cancellation representation and supported…
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
