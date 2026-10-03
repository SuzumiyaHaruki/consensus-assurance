# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。已产生观察的正式结论 2 项：已确认违反 1 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **32.61 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 443.19 秒、30 次 Agent 调用、12 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1956.81 | 443.19 |
| Agent 调用 | 40 | 10 | 30 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 2 次＋探索 2 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v42`；展示版本 `audit-products-v42`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`501.7987342289998`（配置值不表示触发了超时）。
[调用记录](logs/dcc9feb90ea44741bb22943de78bc132/check.json)；[stdout](logs/dcc9feb90ea44741bb22943de78bc132/stdout.log)；[stderr](logs/dcc9feb90ea44741bb22943de78bc132/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前结果 | 实际回答摘录 | 证据 |
| --- | --- | --- | --- |
| 1. 领导权转移超时后自动退出联合配置缺少重试触发 | 已确认违反 | 固定实验中，转移请求丢失后领导者在第 10 个 tick 清除转移状态；至第 40 个 tick，双侧心跳正常但仍停留在联合配置，且未生成退出条目。随后一条普通提案触发自动退出；结论限于该合法交错下的自动重试停滞，不主张 40 tick 的接口期限或共识安全违规。 | [c_auto_exit_retry](state.json) |
| 2. Can a removed former leader with StepDownOnRemoval=false use the singleton ReadIndex shortcut to certify its old prefix after the…（原文摘录） | 待调查线索 | 见下方固定观察 | [c_removed_read_fence](state.json) |
| Can a removed former leader with StepDownOnRemoval=false use the singleton ReadIndex shortcut to certify its old prefix after the… | 研究中，记录状态 `escalated` | 评估已保存，当前版本尚未完成复核 | [候选 1](#candidate-fa267c61288944acbf9df7f94f7681d6) |

### 1. 领导权转移超时后自动退出联合配置缺少重试触发

**已确认违反**。要求原文：For an applied implicit joint configuration, Raft owns the automatic proposal of the exit transition when safe. If an internal exit proposal is temporarily rejected during leadership transfer and that transfer fails, a stable leader with both quorums available must retain an autonomous path to retry and finish the exit; it must not require an unrelated client proposal or another leadership change merely to recover that internal work.

决定性范围：Implicit automatic joint transitions, with legal serialized RawNode application, failed transient leadership transfer, continuing ticks, prompt persistence/application and reliable quorum communication after the dropped transfer request.
No crashes or storage failures; caller completes Ready persistence and application before Advance.；Both joint majorities remain responsive and same leader remains authoritative.；No further configuration requests or ordinary client proposals are supplied during the observation interval.。

排除：Explicit joint transitions whose exit belongs to the caller.；Permanent quorum loss, successful leadership transfer, or caller failure to process Ready.；A universal numeric completion deadline or proof of all-history liveness.；Consensus safety, client data loss and availability consequences beyond joint-state retention.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：固定实验中，转移请求丢失后领导者在第 10 个 tick 清除转移状态；至第 40 个 tick，双侧心跳正常但仍停留在联合配置，且未生成退出条目。随后一条普通提案触发自动退出；结论限于该合法交错下的自动重试停滞，不主张 40 tick 的接口期限或共识安全违规。

制品 v1；机械比较 **观察到违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/5aeed0d3a1d548b8913ff7a9402a692c/assurance_generated_test.go)；[条件与检查器](direct-checks/5aeed0d3a1d548b8913ff7a9402a692c/plan.json)；[原始观察](logs/eff178129dba40e5bb813284a477729d/stdout.log)；[assessment](direct-checks/5aeed0d3a1d548b8913ff7a9402a692c/eff178129dba40e5bb813284a477729d-assessment.json)；[对应性复核](submissions/fccd1e3da11e4520a8d42c095465a63e/accepted.json)

固定比较 `auto_exit_finished`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| case | control | transfer_timeout |
| joint_index | 3 | 3 |
| event | result | result |
| outgoing | 0 | 3 |
| admission.auto_leave | true | true |
| admission.outgoing | 3 | 3 |
| admission.role | StateLeader | StateLeader |
| acks2 | 40 | 40 |
| acks3 | 0 | 40 |
| applied | 4 | 3 |
| auto_leave | false | true |
| commit | 4 | 3 |
| exit_entries | 1 | 0 |
| last | 4 | 3 |
| role | StateLeader | StateLeader |
| stable_authority | true | true |
| stage | result | result |
| term | 2 | 2 |
| tick | 40 | 40 |
| transferee | 0 | 0 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


### 2. Can a removed former leader with StepDownOnRemoval=false use the singleton ReadIndex shortcut to certify its old prefix after the…（原文摘录）

**待调查线索**。要求原文：Under ReadOnlySafe, any returned read-index certificate for a new read must provide a safe log-prefix fence for that read: it must not certify a local prefix excluding a write completed before read invocation in the same Raft history. Removal without immediate stepdown may cause refusal or pending behavior, but must not cause an obsolete former leader to issue a stale safety certificate.

决定性范围：Live, unstopped RawNode using ReadOnlySafe and StepDownOnRemoval=false, after actual removal into a different singleton voter configuration; successor write completes before a unique read request on the old node.
Caller persists and applies Ready work in order before Advance; no storage failures or crashes.；A write completes only when the retained current voter applies its committed write; read invocation follows that completion.；Read request context is unique; the library node remains unstopped and no embedding-layer read rejection is assumed.。

排除：Applications that stop or reject all reads after local removal.；ReadOnlyLeaseBased, context reuse, early Advance, fabricated terms or progress.；An obligation to return a result when the request is dropped or pending.；Production embedding endpoints, wall-clock deadlines and arbitrary crash recovery.。

当前争议／阻塞：Direct oracle correspondence is unreviewed

制品 v1；机械比较 **观察到违反**；对应性复核 待复核；独立场景完整处置：False。
[固定测试](direct-checks/de49c28ef9c441ffb62d7cf37227c89b/assurance_generated_test.go)；[条件与检查器](direct-checks/de49c28ef9c441ffb62d7cf37227c89b/plan.json)；[原始观察](logs/6665279a962d4a609d8de580be3d44a4/stdout.log)；[assessment](direct-checks/de49c28ef9c441ffb62d7cf37227c89b/6665279a962d4a609d8de580be3d44a4-assessment.json)

固定比较 `safe_returned_fence`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| case | retained_role | stepdown_control |
| read_id | read-after-write-retained_role | read-after-write-stepdown_control |
| event | read_result | read_result |
| read_returned | true | false |
| covers_completed_write | false | false |
| write.write_index | 6 | 6 |
| write.new_value | 1 | 1 |
| write.write_completed | true | true |
| admission.write_index | 6 | 6 |
| applied_through_fence | true | 未记录 |
| new_applied | 6 | 6 |
| new_role | StateLeader | StateLeader |
| new_term | 3 | 3 |
| new_value | 1 | 1 |
| old_applied | 4 | 4 |
| old_commit | 4 | 4 |
| old_member | false | false |
| old_role | StateLeader | StateFollower |
| old_term | 2 | 2 |
| old_value | 0 | 0 |
| read_context | read-after-write-retained_role | 未记录 |
| read_count | 1 | 0 |
| read_index | 4 | 未记录 |
| write_completed | true | true |
| write_index | 6 | 6 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="candidate-fa267c61288944acbf9df7f94f7681d6"></a>

研究中问题：Can a removed former leader with StepDownOnRemoval=false use the singleton ReadIndex shortcut to certify its old prefix after the surviving voter has independently acquired authority and completed a later write, or does an applicable caller duty or another implementation mechanism exclude that history?
当前记录状态：`escalated`；[fa267c61288944acbf9df7f94f7681d6：候选原文与历史](state.json)
保存的语义未知：Fresh fixed observations and correspondence must verify write-before-read ordering, returned context and applicable ReadOnlySafe responsibility.

条件探索：For candidate b44572373d454dcf9fbba1e08f7a955f, does an implicit joint change removing voter 3 leave automatically after a transfer to voter 2 is started between ApplyConfChange and Advance, its…
所选问题／策略（原文摘录）：Use actual three-node RawNode election, replication and Ready/Advance to resolve the legal overlap and retry-trigger premises before fixing a bounded liveness obligation. No target protocol state is edited; memory storage represents…
[受理问题、条件与来源](submissions/fdf21247e8b9473abd6251e4d6bf6ff7/accepted.json)；[固定输入](submissions/fdf21247e8b9473abd6251e4d6bf6ff7/inputs/auto_leave_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/1514d7be2baa4094be4f4a559ea73ade/check.json)；[实际输出](logs/1514d7be2baa4094be4f4a559ea73ade/stdout.log)；[诊断](logs/1514d7be2baa4094be4f4a559ea73ade/stderr.log)
[执行文件清单](experiments/f45fa7e2a8984ea8991bc10f6a4cf24c/workspace-delta/manifest.json)；[执行文件清单](experiments/f45fa7e2a8984ea8991bc10f6a4cf24c/workspace-outcome/manifest.json)
执行后精确引用交接：[见下方集中解释；不是本次独立观察](submissions/37c111c9e8ad48648ad674c19c5cc423/accepted.json)
执行后精确引用交接：[见下方集中解释；不是本次独立观察](submissions/5aeed0d3a1d548b8913ff7a9402a692c/accepted.json)

条件探索：For fa267c61288944acbf9df7f94f7681d6, can an actual implicit joint removal of leader 1 and voter 3 leave node 1 in leader role while node 2 alone campaigns, applies set-one, then node 1 emits a stale…
所选问题／策略（原文摘录）：Resolve same-history reachability with actual elections and configuration application, without editing target state or using a new-leader message fabricated by the driver. Caller applicability remains separately open.
[受理问题、条件与来源](submissions/52243bcb531544ab94cb2b1fe2202128/accepted.json)；[固定输入](submissions/52243bcb531544ab94cb2b1fe2202128/inputs/removed_read_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/2b93f866725c4c13ac2c78db651dcb67/check.json)；[实际输出](logs/2b93f866725c4c13ac2c78db651dcb67/stdout.log)；[诊断](logs/2b93f866725c4c13ac2c78db651dcb67/stderr.log)
[执行文件清单](experiments/f77de62abc2f4c83ae40db14bc51046c/workspace-delta/manifest.json)；[执行文件清单](experiments/f77de62abc2f4c83ae40db14bc51046c/workspace-outcome/manifest.json)
执行后精确引用交接：[见下方集中解释；不是本次独立观察](submissions/de49c28ef9c441ffb62d7cf37227c89b/accepted.json)

后续受理解释（执行 1514d7be2baa4094be4f4a559ea73ade）：Exploration observed control final state outgoing=0 and AutoLeave=false at index 4. Failed-transfer case dropped one actual TimeoutNow, remained leader in term 2, cleared transferee by tick 10, and retained joint state with applied=commit=last=3 through tick…
[完整交接；当前正式处置见上方固定制品与复核](submissions/37c111c9e8ad48648ad674c19c5cc423/accepted.json)
该交接当时的剩余问题（非当前欠账）：A fresh fixed check must correlate the installed joint change, application acknowledgment, expired transfer and bounded final observation.；No API deadline is specified; distinguish a finite non-completion measurement from the source-supported absence of an autonomous retry trigger.

后续受理解释（执行 1514d7be2baa4094be4f4a559ea73ade）：The fixed driver retains the exact legal overlap from exploration, adds independently identified admission/result events and records authority, quorum traffic and actual exit-entry production. Control failure cannot filter the primary observation. The rescue…
[完整交接；当前正式处置见上方固定制品与复核](submissions/5aeed0d3a1d548b8913ff7a9402a692c/accepted.json)
该交接当时的剩余问题（非当前欠账）：Fresh formal execution and current checker correspondence.；Interpretation of finite non-completion against source-supported absence of a retry trigger.

后续受理解释（执行 2b93f866725c4c13ac2c78db651dcb67）：Exploration reached final singleton membership with old node absent but still StateLeader when stepdown was false. The successor became term-3 leader and applied the write at index 6; only then the old node emitted ReadState index 4 while applied/value…
[完整交接；当前正式处置见上方固定制品与复核](submissions/de49c28ef9c441ffb62d7cf37227c89b/accepted.json)
该交接当时的剩余问题（非当前欠账）：Fresh execution and checker correspondence against the implication oracle.

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)。
- 共识形成与推进（原文导航摘录）：Leader appends proposals with term and index and queues its own persistence-dependent acknowledgment. Follower verifies log prefix, appends a nonconflicting suffix and queues an acknowledgment. Leader consumes…
- 上下文／权威转换（原文导航摘录）：Campaign changes role and normally increments term; self-vote waits for persistence. Candidate polls responses of the matching election type and becomes leader on VoteWon. Higher-term messages normally step down;…
- 两条主线的连接（原文导航摘录）：Term filtering, reset of progress and the current-term commit condition connect eligible support to authority. Durable log and committed snapshot state survive role transitions while transient vote and progress…

- 03:27:02 +0000（距创建墙钟 578.3 秒，含暂停间隔）；Agent 回合墙钟 326.37 秒 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 03:29:36 +0000（距创建墙钟 732.6 秒，含暂停间隔）；目标工具耗时 17.21 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/1514d7be2baa4094be4f4a559ea73ade/check.json)

- 03:35:26 +0000（距创建墙钟 1082.4 秒，含暂停间隔）；Agent 回合墙钟 167.57 秒 · 认识／制品更新。[完整交接](submissions/5aeed0d3a1d548b8913ff7a9402a692c/accepted.json)

- 03:35:42 +0000（距创建墙钟 1098.3 秒，含暂停间隔）；目标工具耗时 15.17 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/eff178129dba40e5bb813284a477729d/check.json)

- 03:42:28 +0000（距创建墙钟 1504.3 秒，含暂停间隔）；Agent 回合墙钟 227.68 秒 · 认识／制品更新。[完整交接](submissions/34c3b2a1a6cf4bd1bbf46260ef9fded6/accepted.json)

- 03:45:23 +0000（距创建墙钟 1679.2 秒，含暂停间隔）；目标工具耗时 15.50 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/2b93f866725c4c13ac2c78db651dcb67/check.json)

- 03:48:44 +0000（距创建墙钟 1880.7 秒，含暂停间隔）；Agent 回合墙钟 200.91 秒 · 认识／制品更新。[完整交接](submissions/de49c28ef9c441ffb62d7cf37227c89b/accepted.json)

- 03:49:00 +0000（距创建墙钟 1896.7 秒，含暂停间隔）；目标工具耗时 15.19 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/6665279a962d4a609d8de580be3d44a4/check.json)

- 03:50:00 +0000（距创建墙钟 1956.3 秒，含暂停间隔）；Agent 回合墙钟 58.52 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/dcc9feb90ea44741bb22943de78bc132/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-c_removed_read_fence](research.json)：Bounded direct comparison completed; local attribution remains pending: Direct oracle correspondence is unreviewed；[候选 1](#candidate-fa267c61288944acbf9df7f94f7681d6)；评估已保存，当前版本尚未完成复核（[c_removed_read_fence](state.json)；[固定计划](direct-checks/de49c28ef9c441ffb62d7cf37227c89b/plan.json)；[执行记录](logs/6665279a962d4a609d8de580be3d44a4/check.json)）

### 地图登记与研究交接

以下是地图 v4 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)

- core_overview：Same-batch persistence contract discrepancy.；Configuration-induced commit versus deferred read release.；Automatic joint exit can be rejected during transfer; existence of another completion trigger…
  尚无精确对应交接。

- b_persist_response：Conflicting same-batch send ordering statements in doc.go and Ready.Messages need applicability resolution.
  尚无精确对应交接。

- b_config：Whether a legal history can make configuration installation cause the first current-term commit despite campaign admission guards remains a local question.
  相关交接：[交接 1](#handoff-9ca0cdc169d44ec1a42eee09d2d56c7b)；[交接 4](#handoff-34c3b2a1a6cf4bd1bbf46260ef9fded6)

- b_application：Early Advance before configuration application is allowed by general Advance prose; how callers preserve configuration-specific ordering remains a local contract question.
  相关交接：[交接 1](#handoff-9ca0cdc169d44ec1a42eee09d2d56c7b)

- b_reads：Version-dependent retry context prose is not resolved here; use unique contexts when constructing checks.
  相关交接：[交接 4](#handoff-34c3b2a1a6cf4bd1bbf46260ef9fded6)

- b_auto_leave：Whether finite non-completion should be attributed under the automatic retry responsibility requires checker correspondence; no numeric API deadline is given.
  相关交接：[交接 2](#handoff-37c111c9e8ad48648ad674c19c5cc423)；[交接 3](#handoff-fccd1e3da11e4520a8d42c095465a63e)

- b_singleton_read_authority：Whether legal removal leaves a live former leader able to certify a prefix older than a subsequently completed write on the retained singleton.；Whether caller contracts require immediate shutdown or…
  尚无精确对应交接。

- f_transfer_pending：The scheduling of previously rejected internal proposals after timeout is not implied by clearing this field.
  尚无精确对应交接。

- f_local_commit：Detailed out-of-band snapshot/storage caller policies remain external interface assumptions.
  尚无精确对应交接。

- f_single_voter_config：The singleton read consumer may need an additional self-membership premise when leader removal does not force role change.
  尚无精确对应交接。

- surface:doc.go Ready processing versus Ready.Messages：Usage permits sending messages during same-batch entry persistence, while Ready.Messages requires entry persistence first. Dependent append acknowledgments share Messages in sync mode; determine…
  尚无精确对应交接。

<a id="handoff-9ca0cdc169d44ec1a42eee09d2d56c7b"></a>

交接 1：[完整原文](submissions/9ca0cdc169d44ec1a42eee09d2d56c7b/accepted.json)；精确引用 b_application, b_authority, b_config。
回答摘录：Membership aggregation uses only configured voters and both majorities while joint; campaign admission blocks committed unapplied configuration entries. Node serializes mutation but continues handling input during an outstanding Ready. ReadIndex explicitly…
该交接当时的剩余问题（非当前欠账）：Can actual Ready/Advance or asynchronous completion legally interleave transfer between joint configuration installation and appliedTo?；Does a normal tick/heartbeat/Ready cycle retrigger appliedTo without new committed entries?；What finite completion comparison is justified by automatic-transition contract and fair delivery assumptions?；Retained persistence-ordering document conflict remains unresolved; no test will assume the weaker clause.

<a id="handoff-37c111c9e8ad48648ad674c19c5cc423"></a>

交接 2：[完整原文](submissions/37c111c9e8ad48648ad674c19c5cc423/accepted.json)；精确引用 b_auto_leave。
解释已在上方条件探索中集中展示。

<a id="handoff-fccd1e3da11e4520a8d42c095465a63e"></a>

交接 3：[完整原文](submissions/fccd1e3da11e4520a8d42c095465a63e/accepted.json)；精确引用 b_auto_leave。
回答摘录：The fixed measured comparison retained joint state only for the transfer history, despite completed application, transfer timeout and serviced quorum traffic. Current correspondence supports the scoped missing-autonomous-retry explanation; the result is…
该交接当时的剩余问题（非当前欠账）：Other authority/configuration and persistence boundaries remain open; this result does not settle the whole transfer Fact.

<a id="handoff-34c3b2a1a6cf4bd1bbf46260ef9fded6"></a>

交接 4：[完整原文](submissions/34c3b2a1a6cf4bd1bbf46260ef9fded6/accepted.json)；精确引用 b_config, b_reads。
回答摘录：The automatic-exit check is confirmed by current controller assessment with correspondence completed. Separately, code shows that removed leaders only step down when StepDownOnRemoval is enabled, while singleton ReadIndex tests voter cardinality before any…
该交接当时的剩余问题（非当前欠账）：Caller legality of continuing ReadIndex on a removed yet unstopped node.；Actual protocol history reaching a new singleton leader and completed write without first notifying the removed leader of a higher term.；Whether a returned ReadState permits the stale application value under the documented applied-index condition.；Early-Advance configuration ordering remains a separate unresolved caller-contract boundary; it is not used in this new history.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
