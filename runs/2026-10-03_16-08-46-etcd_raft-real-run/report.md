# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 3 项；当前 Unit 3 项、义务 3 项、固定检查制品 3 项。已产生观察的正式结论 3 项：已确认违反 3 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、25 次 Agent 调用、10 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.11 | 0.00 |
| Agent 调用 | 40 | 15 | 25 |
| 控制器目标执行 | 16 | 6 | 10 |
| 新 Unit | 6 | 3 | 3 |
| 语义复核 | 10 | 3 | 7 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 3 次＋探索 3 次，其中失败／未完成 1 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v44`；展示版本 `audit-products-v44`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`8.796893256003386`（配置值不表示触发了超时）。
[调用记录](logs/bf752775fd1048c4aa4c33e95cdc951b/check.json)；[stdout](logs/bf752775fd1048c4aa4c33e95cdc951b/stdout.log)；[stderr](logs/bf752775fd1048c4aa4c33e95cdc951b/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 被移除的旧领导者错误使用单节点读屏障捷径 | 已确认违反 | 固定执行中，旧领导者已应用自身移除，唯一投票者为另一节点；后者完成新写入后，旧节点仍在无任何新网络支持的情况下返回 ReadState。启用移除后降级可阻止该路径；已验证的是读屏障支持资格缺失，并非已完成的陈旧客户端读取。 | [O-read-singleton](#claim-O-read-singleton) |
| 2. 领导权转移取消后自动退出联合配置缺少续行触发 | 已确认违反 | 固定执行中，联合配置应用时发起转移导致自动退出提案被拒；转移超时取消后，正常心跳与完整 Ready 处理进入状态重复的循环，联合配置仍未退出。无转移对照和后续普通提案均可完成退出；该结果不代表共识安全破坏或整体不可用。 | [O-auto-exit](#claim-O-auto-exit) |
| 3. 状态查询复制联合配置时丢失 AutoLeave 标志 | 已确认违反 | 固定执行中，隐式联合配置的实时 AutoLeave 为 true，但 RawNode.Status 返回 false；直接 Clone 也返回 false，查询后的实时值仍为 true。显式联合配置的 false 对照保持一致；该缺陷属于状态复制失真，并未证明活动共识状态被修改。 | [O-config-copy](#claim-O-config-copy) |

<a id="claim-O-read-singleton"></a>

### 1. 被移除的旧领导者错误使用单节点读屏障捷径

**已确认违反**。要求原文：Under ReadOnlySafe, if no quorum communication occurs after a fresh ReadIndex request, local singleton support can authorize a returned ReadState only when the responder itself is the sole voter in its installed configuration. A removed node cannot count itself as the different sole voter.

决定性范围：Necessary local-support eligibility for ReadOnlySafe singleton responses after applied self-removal, with optional immediate step-down disabled and zero post-request peer communication.
Non-Byzantine peers, unique new read context, serialized RawNode methods and valid applied membership history.；No quorum acknowledgment or other network message reaches the responder after the request.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/bcc5f00ea18c4f69a56d6bb32a6c47c7/assurance_generated_test.go)；[条件与检查器](direct-checks/bcc5f00ea18c4f69a56d6bb32a6c47c7/plan.json)；[原始观察](logs/637a23bb7ef346fbbfb558fc4d9e6f6a/stdout.log)；[assessment](direct-checks/bcc5f00ea18c4f69a56d6bb32a6c47c7/637a23bb7ef346fbbfb558fc4d9e6f6a-assessment.json)；[对应性复核](submissions/8db4b77ad85c463c847084fa1b6a87ae/accepted.json)

执行边界：Serialized RawNode driver, actual message producers, faithful no-crash MemoryStorage. A simple application records committed payloads only to establish later-write ordering, not to claim completed client read.；No target changes or direct state mutation. Partition drops every peer message after completed self-removal.；ReadStates are observed only for the unique request context; final result is always emitted after drain, including no-response control.；The post-request delivered-message counter is measured at the actual Step boundary.
固定比较 `C-read-singleton`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| step_down | false | true |
| operation | post-removal-read | post-removal-read |
| node | 1 | 1 |
| context | read-after-new-write | read-after-new-write |
| event | read_result | read_result |
| read_returned | true | false |
| local_singleton_support | false | false |
| request.partitioned | true | true |
| request.prior_write_value | new | new |
| index | 5 | 0 |
| peer_messages_delivered | 0 | 0 |
| response_count | 1 | 0 |
| self_voter | false | false |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-O-auto-exit"></a>

### 2. 领导权转移取消后自动退出联合配置缺少续行触发

**已确认违反**。要求原文：For an installed implicit joint configuration with AutoLeave enabled, Raft must automatically continue the transition to the incoming configuration when possible. If a transfer temporarily blocks the exit proposal and then is canceled while the leader and a joint quorum remain available, continued servicing of required ticks, transport, storage and application must not leave exit permanently dependent on an unrelated new client proposal or forced leadership change.

决定性范围：Automatic joint-exit continuation after temporary leadership-transfer blockage, with the same leader, working joint quorum and all required caller work serviced.
Non-Byzantine peers and faithful persistence; network may lose the transfer request but subsequently delivers all messages.；Caller serializes RawNode methods, applies committed configuration entries in order and advances each processed Ready; calls Tick regularly.；No outstanding unprocessed committed entries or snapshot remains in the repeating suffix.；No new client proposal is required as a continuation stimulus; application does not request an explicit/manual joint transition.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/97a3e50ceabe4b0a9c0afc673f10a231/assurance_generated_test.go)；[条件与检查器](direct-checks/97a3e50ceabe4b0a9c0afc673f10a231/plan.json)；[原始观察](logs/c14ff92624034255a3f506d0795b2631/stdout.log)；[assessment](direct-checks/97a3e50ceabe4b0a9c0afc673f10a231/c14ff92624034255a3f506d0795b2631-assessment.json)；[对应性复核](submissions/979bbcc5223b4f53869f85802044fdd2/accepted.json)

执行边界：Serialized synchronous RawNode driver with actual protocol-produced messages and in-memory storage implementing faithful persistence for a no-crash history. Reflection reads full state without changing target logic.；No target source changes or protocol state mutation. Network drops only TimeoutNow during failed transfer; all other messages are delivered.；Reflection traverses private state for cycle equality, excluding logger/traceLogger and MemoryStorage.callStats only. It retains all live slice elements, nilness, maps, struct fields and function code identity; storage is included via raftLog.storage.；MemoryStorage substitutes durable I/O for an execution without crashes; no fsync fault is modeled.；All events use actual observed values. No outcomes are asserted with testing.Fatal; fatal checks concern driver prerequisites or unsupported state encoding only.
固定比较 `C-auto-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case | transfer_overlap |
| operation | implicit-remove-3 |
| leader | 1 |
| joint_index | 5 |
| event | cycle_result |
| repeat_cycle | true |
| joint_pending | true |
| admitted.live_auto_leave | true |
| admitted.outgoing_count | 3 |
| admitted.transfer | 0 |
| admitted.leader_state | StateLeader |
| admitted.queues_empty | true |
| additional_drops | 0 |
| period_ticks | 10 |
| state_after | str，10172 字符；首尾预览：{"injected":true,"joint_index":5,"nodes":{"1":{"$t…ansport until quiescent; repeat","transport":null}；[c14ff92624034255a3f506d0795b2631 / event[22] / state_after](logs/c14ff92624034255a3f506d0795b2631/stdout.log) |
| state_before | str，10172 字符；首尾预览：{"injected":true,"joint_index":5,"nodes":{"1":{"$t…ansport until quiescent; repeat","transport":null}；[c14ff92624034255a3f506d0795b2631 / event[22] / state_before](logs/c14ff92624034255a3f506d0795b2631/stdout.log) |
| state_equal | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-O-config-copy"></a>

### 3. 状态查询复制联合配置时丢失 AutoLeave 标志

**已确认违反**。要求原文：A Config copy returned through RawNode.Status must preserve the currently installed configuration AutoLeave value, including true for implicit joint mode, while being separate from the live configuration.

决定性范围：Value preservation of installed automatic-exit mode when RawNode.Status copies tracker.Config at a serialized observation point.
Caller uses legal bootstrap/election/committed configuration application and observes without concurrent protocol mutation.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/823a0ee252034a7585c4dc40d9f4ce63/assurance_generated_test.go)；[条件与检查器](direct-checks/823a0ee252034a7585c4dc40d9f4ce63/plan.json)；[原始观察](logs/acb05566ff2845d7ae7c8290db5c5b07/stdout.log)；[assessment](direct-checks/823a0ee252034a7585c4dc40d9f4ce63/acb05566ff2845d7ae7c8290db5c5b07-assessment.json)；[对应性复核](submissions/fd484537db074895b7af093887bc8dbf/accepted.json)

执行边界：Actual public RawNode producer/consumer sequence with read-only live-state observation. Two independent cases use implicit true and explicit false modes.；No target edits, direct protocol-state mutation or fabricated messages.；MemoryStorage substitutes persistence in a no-crash history; Ready entries and HardState are stored before message delivery.；Public methods are serialized; private tracker.AutoLeave is read solely to observe the input to Status. No protocol event occurs between source read and result.
固定比较 `C-config-copy`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| case | ConfChangeTransitionJointImplicit | ConfChangeTransitionJointExplicit |
| operation | committed-remove-3 | committed-remove-3 |
| node | 1 | 1 |
| index | 5 | 5 |
| entry_term | 2 | 2 |
| event | copy_result | copy_result |
| copied_auto_leave | false | false |
| source.source_auto_leave | true | false |
| source.joint | true | true |
| direct_clone_auto_leave | false | false |
| live_after | true | false |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For Candidate 7e761f13c65b42ff9e000d76ca4d64ec, does joint exit resume after transfer begins between ApplyConfChange and Advance, its TimeoutNow is lost, and the same leader cancels transfer while…
所选问题／策略（原文摘录）：Resolve the selected Candidate legal-history and trigger uncertainty using a serialized RawNode caller, actual election and committed implicit joint change, and one network-loss class limited to transfer TimeoutNow. All Ready work is…
[受理问题、条件与来源](submissions/27e6ca3e005547459fc22a974189f476/accepted.json)；[固定输入](submissions/27e6ca3e005547459fc22a974189f476/inputs/explore_transfer_test.go)
探索执行失败或未完成；没有正式性质判定。[执行记录](logs/7258115162494ec3a595e0bdae135706/check.json)；[实际输出](logs/7258115162494ec3a595e0bdae135706/stdout.log)；[诊断](logs/7258115162494ec3a595e0bdae135706/stderr.log)
[执行文件清单](experiments/8a115a48563640b8a1c5d122c0ae7bdb/workspace-delta/manifest.json)；[执行文件清单](experiments/8a115a48563640b8a1c5d122c0ae7bdb/workspace-outcome/manifest.json)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/599b5d727bd74c7699f22890af3ce56a/accepted.json)

条件探索：For Candidate 7e761f13c65b42ff9e000d76ca4d64ec, does joint exit resume after transfer begins between ApplyConfChange and Advance, its TimeoutNow is lost, and the same leader cancels transfer while…
所选问题／策略（原文摘录）：Repair exploration driver: ErrStepPeerNotFound for an already removed peer response is expected admission rejection and is now logged, not fatal. Preserve transfer/application overlap and all protocol calls. Status.Config.Clone omits…
[受理问题、条件与来源](submissions/599b5d727bd74c7699f22890af3ce56a/accepted.json)；[固定输入](submissions/599b5d727bd74c7699f22890af3ce56a/inputs/explore_transfer_v2_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/a440abc8f2ab4f5b8eb31a5979fe9cf3/check.json)；[实际输出](logs/a440abc8f2ab4f5b8eb31a5979fe9cf3/stdout.log)；[诊断](logs/a440abc8f2ab4f5b8eb31a5979fe9cf3/stderr.log)
[执行文件清单](experiments/1a452ac115a149db82428f44cbf32bfa/workspace-delta/manifest.json)；[执行文件清单](experiments/1a452ac115a149db82428f44cbf32bfa/workspace-outcome/manifest.json)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/dab3c5d9b41b4e93becb8072b9c67e1c/accepted.json)

条件探索：With ReadOnlySafe and StepDownOnRemoval=false, can a removed leader whose installed config is singleton {2} issue a local ReadState after node 2 independently becomes leader and applies a later…
所选问题／策略（原文摘录）：A sourced discrepancy connects membership loss to the singleton ReadIndex fast path: switchToConfig may retain leader role after self-removal, and IsSingleton checks cardinality without self-membership. Use actual bootstrap, election,…
[受理问题、条件与来源](submissions/49ab4373e2524a208f2091d59b757cd4/accepted.json)；[固定输入](submissions/49ab4373e2524a208f2091d59b757cd4/inputs/explore_removed_read_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/daa885484a134fa99fd3460aa3e93e7b/check.json)；[实际输出](logs/daa885484a134fa99fd3460aa3e93e7b/stdout.log)；[诊断](logs/daa885484a134fa99fd3460aa3e93e7b/stderr.log)
[执行文件清单](experiments/efb8119a3c064c1695e525f34e95f573/workspace-delta/manifest.json)；[执行文件清单](experiments/efb8119a3c064c1695e525f34e95f573/workspace-outcome/manifest.json)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/290356c47b5a44039756903845223330/accepted.json)

后续受理解释（关联 1 次执行）：The first exploration reached joint application at index 5, transfer target 2, loss of TimeoutNow and timeout cancellation. It observed no later log entry through 50 ticks, then exit entry 7 after a diagnostic proposal. However both subtests ended on the…
[完整交接；当前正式处置见上方固定制品与复核](submissions/599b5d727bd74c7699f22890af3ce56a/accepted.json)

后续受理解释（关联 1 次执行）：Repaired exploration completed: control exits at index 6. Transfer overlap retains live AutoLeave true and outgoing voters at index 5 through 50 ticks; transfer clears at tick 10, all queues and Readys drain, and ordinary follow-up commits index 6 then exit…
[完整交接；当前正式处置见上方固定制品与复核](submissions/dab3c5d9b41b4e93becb8072b9c67e1c/accepted.json)

后续受理解释（关联 1 次执行）：Exploration executes self-removal leaving node 1 in StateLeader with voters [2], node 2 commits/applies new value at index 7, and node 1 produces a local ReadState at index 5 without communication. Step-down-enabled control produces none. This establishes…
[完整交接；当前正式处置见上方固定制品与复核](submissions/290356c47b5a44039756903845223330/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)。
- 共识形成与推进（原文导航摘录）：A proposer reaches the current leader directly or via follower forwarding. Leader assigns term/index, checks quota and configuration serialization, then appends and replicates. Follower validates the prior term/index…
- 上下文／权威转换（原文导航摘录）：A promotable node without unapplied committed configuration changes campaigns, optionally pre-voting. Votes require up-to-date history and compatible term/vote state; persisted replies are aggregated under installed…
- 两条主线的连接（原文导航摘录）：Eligible support depends jointly on current term and installed membership. Role reset discards volatile replication/vote support, but retained committed history restricts future vote eligibility and append acceptance.…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.26 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 10.46 分钟 · 实际执行：Resolve the selected Candidate legal-history and trigger uncertainty using a serialized RawNode caller, actual election and committed…；探索执行失败或未完成。[执行记录](logs/7258115162494ec3a595e0bdae135706/check.json)

- 13.10 分钟 · 实际执行：Repair exploration driver: ErrStepPeerNotFound for an already removed peer response is expected admission rejection and is now logged, not…；条件观察完成。[执行记录](logs/a440abc8f2ab4f5b8eb31a5979fe9cf3/check.json)

- 15.52 分钟 · 受理 obligation：The implicit-mode contract grounds implementation-owned continuation; repaired exploration establishes construction value without proving a…。[完整交接](submissions/dab3c5d9b41b4e93becb8072b9c67e1c/accepted.json)

- 19.95 分钟 · 实际执行：领导权转移取消后自动退出联合配置缺少续行触发；执行完成；比较见 assessment。[执行记录](logs/c14ff92624034255a3f506d0795b2631/check.json)

- 22.42 分钟 · 受理 review：领导权转移取消后自动退出联合配置缺少续行触发。[完整交接](submissions/979bbcc5223b4f53869f85802044fdd2/accepted.json)

- 25.53 分钟 · 受理 obligation：Investigate the distinct configuration-copy duty revealed by an actual observation, while preserving the confirmed continuation witness and…。[完整交接](submissions/d821ee509e084bf2a89f5688e5cce683/accepted.json)

- 27.98 分钟 · 实际执行：状态查询复制联合配置时丢失 AutoLeave 标志；执行完成；比较见 assessment。[执行记录](logs/acb05566ff2845d7ae7c8290db5c5b07/check.json)

- 29.49 分钟 · 受理 review：状态查询复制联合配置时丢失 AutoLeave 标志。[完整交接](submissions/fd484537db074895b7af093887bc8dbf/accepted.json)

- 33.22 分钟 · 实际执行：A sourced discrepancy connects membership loss to the singleton ReadIndex fast path: switchToConfig may retain leader role after…；条件观察完成。[执行记录](logs/daa885484a134fa99fd3460aa3e93e7b/check.json)

- 35.82 分钟 · 受理 obligation：Fix a narrow independently sourced read-support eligibility responsibility, retaining the unobserved client endpoint and optional-step-down…。[完整交接](submissions/290356c47b5a44039756903845223330/accepted.json)

- 37.87 分钟 · 受理 check：Execute the accepted necessary-support obligation with actual membership/later-write history, zero observed post-request network delivery…。[完整交接](submissions/bcc5f00ea18c4f69a56d6bb32a6c47c7/accepted.json)

- 38.12 分钟 · 实际执行：被移除的旧领导者错误使用单节点读屏障捷径；执行完成；比较见 assessment。[执行记录](logs/637a23bb7ef346fbbfb558fc4d9e6f6a/check.json)

- 39.84 分钟 · 受理 review：被移除的旧领导者错误使用单节点读屏障捷径。[完整交接](submissions/8db4b77ad85c463c847084fa1b6a87ae/accepted.json)

- 40.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/bf752775fd1048c4aa4c33e95cdc951b/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v4 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v4：概览、Behavior／Fact 与来源](audit-spec/v4.json)

- core_overview：Cancellation documentation discrepancy.；Pending read context behavior across membership changes.；Deeper asynchronous snapshot and flow-control histories remain unexamined.；Singleton read-response…
  尚无精确对应交接。

- B-read：Whether local-only singleton ReadState production remains eligible after the responder is removed while StepDownOnRemoval is false.；Detailed repeated RequestCtx and membership-transition histories…
  相关交接：[交接 1](submissions/49ab4373e2524a208f2091d59b757cd4/accepted.json)；[交接 2](submissions/290356c47b5a44039756903845223330/accepted.json)；[交接 3](submissions/8db4b77ad85c463c847084fa1b6a87ae/accepted.json)

- surface:Node.ApplyConfChange / README cancellation：README says zero NodeID and still call ApplyConfChange; current Node and RawNode documentation say skip rejected changes. No cancellation history is assumed until this is resolved.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[exploration](logs/7258115162494ec3a595e0bdae135706/stdout.log)；[stderr](logs/7258115162494ec3a595e0bdae135706/stderr.log)；[执行记录](logs/7258115162494ec3a595e0bdae135706/check.json)
