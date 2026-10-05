# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **26.29 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 822.36 秒、31 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1577.64 | 822.36 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 39.61 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 40.90 秒。

目标执行组成：正式检查 1 次＋探索 2 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v50`；展示版本 `audit-products-v50`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/3ca144c9de2b48f88cb03cb9b332d905/check.json)；[stdout](logs/3ca144c9de2b48f88cb03cb9b332d905/stdout.log)；[stderr](logs/3ca144c9de2b48f88cb03cb9b332d905/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 批量确认的远端读请求上下文被后续请求覆盖 | 已确认违反 | 三个投票节点、任期和成员配置稳定时，后续读请求的心跳确认释放两个待处理请求。节点 2 原始上下文为 1101:30，实际响应及 ReadyToRead 均变成节点 3 的 2202:30；后续请求本身正确。证据验证的是内部请求关联缺陷，不证明陈旧读取或无限停滞。 | [C_remote_read_context](#claim-C_remote_read_context) |
| Can an initialized node recovering a membership-changing snapshot use the newly published applied index to campaign before the… | 研究中，尚无正式义务 | Can actual recovery publication overlap stepping in the suspected ordering without bypassing another lock or scheduling guard?；Which legal committed… | [候选 1](#candidate-420f52dd41a44b56bd16b76d9e40b6bb) |

<a id="claim-C_remote_read_context"></a>

### 1. 批量确认的远端读请求上下文被后续请求覆盖

**已确认违反**。要求原文：When a stable leader confirms and releases pending ReadIndex requests originating at remote eligible peers, each released request must be returned to its origin with its own original SystemCtx, so that the receiving peer exposes ReadyToRead for that request rather than another request context. This includes earlier requests released by confirmation of a later queued request.

决定性范围：Correlation of confirmed remote read-index requests through the internal Peer API and its actual raft handlers, in one unchanged multi-voter configuration and term.
Non-Byzantine voting peers; unique nonzero contexts supplied under the caller batching contract.；A current-term log entry is committed before requests; each origin has one pending request in the examined release, allowing origin identity to correlate observations independently of context.；Ordinary messages may be lost before delivery; delivered messages are neither forged nor reordered within a sender-to-recipient stream.；The consumer obligation applies to requests actually released by confirmation, not to merely submitted or unconfirmed requests.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/aa81eae8110f472789dc9c13001bf4c1/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/aa81eae8110f472789dc9c13001bf4c1/plan.json)；[原始观察](logs/606dd79be1bc46bb8c55ab57347d7089/stdout.log)；[assessment](direct-checks/aa81eae8110f472789dc9c13001bf4c1/606dd79be1bc46bb8c55ab57347d7089-assessment.json)；[对应性复核](submissions/ff457bbdd68b47d686c599749ab8d6d2/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 12.20 秒；执行进程耗时 11.78 秒；[实际命令、工具版本与输入记录](logs/606dd79be1bc46bb8c55ab57347d7089/check.json)
执行边界：Single TestAssuranceRemoteReadContext using captured raft Peer, TestLogDB and real generated messages.；Storage is the captured in-memory TestLogDB; no crash or durability conclusion.；Sequential update/application driver handles bootstrap configuration entries and empty no-op entries through Peer APIs; no application state-machine payloads or NodeHost client objects are used.；Transport is a FIFO generated-message queue with explicit first-context outbound heartbeat loss; no protocol handler, response content or source file is replaced.；Read-only inspection of live peer state supplies prerequisites and release identity. Fixed unique contexts replace random caller context generation.
固定比较 `check_wire_context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | prefix_release | prefix_release |
| origin | 2 | 3 |
| event | wire | wire |
| context | 2202:30 | 2202:30 |
| admitted.expected_context | 1101:30 | 2202:30 |
| admitted.term | 2 | 2 |
| admitted.current_term_committed | true | true |
| admitted.pending_count | 2 | 2 |
| admitted.first_round_drops | 2 | 2 |
| released.removed | true | true |
| released.term | 2 | 2 |
| from | 1 | 1 |
| index | 4 | 4 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `check_ready_context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | prefix_release | prefix_release |
| origin | 2 | 3 |
| event | ready | ready |
| context | 2202:30 | 2202:30 |
| admitted.expected_context | 1101:30 | 2202:30 |
| admitted.term | 2 | 2 |
| admitted.current_term_committed | true | true |
| admitted.pending_count | 2 | 2 |
| admitted.first_round_drops | 2 | 2 |
| released.removed | true | true |
| released.term | 2 | 2 |
| applied | 4 | 4 |
| index | 4 | 4 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For candidate 420f52dd41a44b56bd16b76d9e40b6bb, conditional on accepted snapshot metadata and a successful payload recovery, can actual RSM.Recover publish lastApplied while actual…
所选问题／策略（原文摘录）：Resolve a concrete lock/publication premise using real RSM.Recover, node.RestoreRemotes, updateAppliedIndex, tick and Peer snapshot/election handling. Reuse the captured root node helper only for initialized bootstrap and resource…
[受理问题、条件与来源](submissions/0ea15bde495e4736b56b11e7f39d307c/accepted.json)；[固定输入](submissions/0ea15bde495e4736b56b11e7f39d307c/inputs/recovery_overlap_explore_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-420f52dd41a44b56bd16b76d9e40b6bb)
<a id="exploration-484dd45fb8ef4585beb600c5f8546a33"></a>
[探索执行 1](#exploration-484dd45fb8ef4585beb600c5f8546a33)：已进入测试，执行失败；性质归因另核；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/484dd45fb8ef4585beb600c5f8546a33/check.json)；[实际输出](logs/484dd45fb8ef4585beb600c5f8546a33/stdout.log)；[诊断](logs/484dd45fb8ef4585beb600c5f8546a33/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.42 秒；执行进程耗时 13.98 秒；[实际命令、工具版本与输入记录](logs/484dd45fb8ef4585beb600c5f8546a33/check.json)
[执行文件清单](experiments/d8a19d0b1fff4245824e45199b45135a/workspace-delta/manifest.json)；[执行文件清单](experiments/d8a19d0b1fff4245824e45199b45135a/workspace-outcome/manifest.json)；[执行文件清单](experiments/d8a19d0b1fff4245824e45199b45135a/workspace/assurance_generated_test.go)
后续受理交接原文导航：[交接 1](#exploration-feedback-9437395c655942f58be1a593f43adaa7)

条件探索：For candidate 420f52dd41a44b56bd16b76d9e40b6bb, conditional on accepted snapshot metadata and a successful payload recovery, can actual RSM.Recover publish lastApplied while actual…
所选问题／策略（原文摘录）：Repair only the unreached bootstrap prerequisite from exploration 484dd45fb8ef4585beb600c5f8546a33: when substituting the RSM snapshot input fixture before bootstrap, reconnect node.toApplyQ to the new StateMachine.TaskQ exactly as newNode…
[受理问题、条件与来源](submissions/9437395c655942f58be1a593f43adaa7/accepted.json)；[固定输入](submissions/9437395c655942f58be1a593f43adaa7/inputs/recovery_overlap_explore_v2_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-420f52dd41a44b56bd16b76d9e40b6bb)
<a id="exploration-9bcba8762802454d99893eafcb3689a7"></a>
[探索执行 2](#exploration-9bcba8762802454d99893eafcb3689a7)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/9bcba8762802454d99893eafcb3689a7/check.json)；[实际输出](logs/9bcba8762802454d99893eafcb3689a7/stdout.log)；[诊断](logs/9bcba8762802454d99893eafcb3689a7/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.28 秒；执行进程耗时 13.85 秒；[实际命令、工具版本与输入记录](logs/9bcba8762802454d99893eafcb3689a7/check.json)
[执行文件清单](experiments/7a917e59dee040fe888c23fb8db093ce/workspace-delta/manifest.json)；[执行文件清单](experiments/7a917e59dee040fe888c23fb8db093ce/workspace-outcome/manifest.json)；[执行文件清单](experiments/7a917e59dee040fe888c23fb8db093ce/workspace/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

<a id="exploration-feedback-9437395c655942f58be1a593f43adaa7"></a>
[交接 1](#exploration-feedback-9437395c655942f58be1a593f43adaa7) · 后续说明；关联：[探索执行 1](#exploration-484dd45fb8ef4585beb600c5f8546a33)
后续受理交接原文（摘录，不是各次执行的独立观察）：The first exploration compiled and ran but failed at bootstrap not established, before any snapshot recovery or overlap observation. Its replacement RSM did not receive bootstrap tasks because toApplyQ still referenced the original instance. newNode…
[完整交接；精确引用不表示已解决或已正式化](submissions/9437395c655942f58be1a593f43adaa7/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Client proposal queues reach the serialized peer. Leader assigns term/index and replicates; qualified current-term voting-member match supports commitment. Followers check previous log term and preserve committed…
- 上下文／权威转换（原文导航摘录）：Election ticks on eligible full voters trigger campaigns only after committed application catches up. Votes require log freshness and single-vote eligibility, and outer response admission composes with candidate…
- 两条主线的连接（原文导航摘录）：Authority reset retains committed history while discarding votes, read confirmation queues and peer replication progress. New leaders append a current-term no-op before multi-voter ReadIndex readiness. Applied…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.06 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.17 分钟 · 受理 obligation：Ground the narrowly scoped remote read-context preservation duty in captured test expectations and the real consumer contract; construct a…。[完整交接](submissions/571fdaa3aaf64be9ac65eeab811de98a/accepted.json)

- 12.05 分钟 · 受理 check：Execute a fixed producer-to-consumer history for the accepted correlation obligation, preserving actual peer admission and independent…。[完整交接](submissions/aa81eae8110f472789dc9c13001bf4c1/accepted.json)

- 12.25 分钟 · 实际执行：批量确认的远端读请求上下文被后续请求覆盖；执行完成；比较见 assessment。[执行记录](logs/606dd79be1bc46bb8c55ab57347d7089/check.json)

- 14.87 分钟 · 受理 review：批量确认的远端读请求上下文被后续请求覆盖。[完整交接](submissions/ff457bbdd68b47d686c599749ab8d6d2/accepted.json)

- 19.13 分钟 · 受理 continue：Reselect the independent recovery publication/context validity question after the remote read-context finding is confirmed.。[完整交接](submissions/8f663983e4d647ea84debe5a10a986da/accepted.json)

- 22.51 分钟 · 实际执行：Resolve a concrete lock/publication premise using real RSM.Recover, node.RestoreRemotes, updateAppliedIndex, tick and Peer…；已进入测试，执行失败；性质归因另核。[执行记录](logs/484dd45fb8ef4585beb600c5f8546a33/check.json)

- 24.09 分钟 · 实际执行：Repair only the unreached bootstrap prerequisite from exploration 484dd45fb8ef4585beb600c5f8546a33: when substituting the RSM snapshot…；探索执行正常结束。[执行记录](logs/9bcba8762802454d99893eafcb3689a7/check.json)

- 26.29 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/3ca144c9de2b48f88cb03cb9b332d905/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [420f52dd41a44b56bd16b76d9e40b6bb](research.json)：[候选 1](#candidate-420f52dd41a44b56bd16b76d9e40b6bb)

1 次探索已有原始执行记录，尚待受理解释；前提与观察是否达到仍需核对：[探索执行 2](#exploration-9bcba8762802454d99893eafcb3689a7)

<a id="candidate-420f52dd41a44b56bd16b76d9e40b6bb"></a>

研究中问题：Can an initialized node recovering a membership-changing snapshot use the newly published applied index to campaign before the snapshot membership reaches its raft peer?
[候选原文与历史](state.json)
保存的语义未知：Can actual recovery publication overlap stepping in the suspected ordering without bypassing another lock or scheduling guard?；Which legal committed configuration/snapshot history produces differing peer membership while preserving local eligibility to campaign?；Does an emitted old-membership campaign suffice for a sourced local responsibility discrepancy, or is a subsequent authority/decision endpoint needed?
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-484dd45fb8ef4585beb600c5f8546a33)；[探索执行 2](#exploration-9bcba8762802454d99893eafcb3689a7)

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Snapshot recovery publication can precede the raftMu-protected membership callback; investigate actual overlapping step and legal configuration history.；Remote prefix read release preserves the…
  尚无精确对应交接。

- B_form：Detailed witness payload persistence and snapshot retry states remain unread.
  尚无精确对应交接。

- B_authority：Quiescence timing variants and transport restart ordering remain open.
  相关交接：[交接 1](submissions/8f663983e4d647ea84debe5a10a986da/accepted.json)

- B_members：Snapshot recovery publishes its applied index before its separate RestoreRemotes callback; whether active stepping can consume it with old peer membership is tracked by B_recover.
  尚无精确对应交接。

- B_persist：LogDB crash durability and backend implementations have not been traced.
  尚无精确对应交接。

- B_apply：Session duplicate-result caching and on-disk replay variants not fully mapped.
  尚无精确对应交接。

- B_recover：During non-initial snapshot recovery, can a step holding raftMu read snapshot-published lastApplied and campaign using pre-snapshot peer membership before RestoreRemotes acquires raftMu?；What legal…
  相关交接：[交接 1](submissions/8f663983e4d647ea84debe5a10a986da/accepted.json)

- B_client：Whole-client outcome after receipt of a mismatched remote read context is outside the executed peer-level observation.
  尚无精确对应交接。

- F_commit：Backend durability not yet traced.
  尚无精确对应交接。

- F_visible_applied：Whether campaign admission can consume snapshot publication before peer membership restoration in a consequential legal recovery history.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[exploration](logs/484dd45fb8ef4585beb600c5f8546a33/stdout.log)；[stderr](logs/484dd45fb8ef4585beb600c5f8546a33/stderr.log)；[执行记录](logs/484dd45fb8ef4585beb600c5f8546a33/check.json)
