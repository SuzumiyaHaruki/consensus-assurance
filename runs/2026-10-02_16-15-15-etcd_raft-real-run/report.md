# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。本轮有 2 项已产生观察的正式问题：已确认违反 1 项、有限检查未见违反 1 项、待调查线索 0 项；另有源码解释 1 项、探索执行 3 次。正式义务共 2 项，执行次数不等于问题数。

实际持续 **75.04 分钟**；结束类型：**Agent 提出的研究依据不足**。
剩余 297.86 秒、19 次 Agent 调用、11 次控制器目标执行。源码调查能力：仍有预算。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 4800.0 | 4502.14 | 297.86 |
| Agent 调用 | 40 | 21 | 19 |
| 控制器目标执行 | 16 | 5 | 11 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |
| 模型工具 | 6 | 0 | 未启用 |

目标执行组成：正式检查 2 次＋探索 3 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
模型检查：未使用 TLA+／TLC。新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v37`；展示版本 `audit-products-v37`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Reasoned early stop with unresolved scope and capacity remaining. This is not bounded completion of the entire frontier, resource exhaustion or overall correctness. The selected formal…；[完整停止记录](state.json)。


## 主要结果

| 问题 | 当前结果 | 实际回答摘录 | 证据 |
| --- | --- | --- | --- |
| 1. When a synchronous Node caller has persisted a Ready and used the documented early Advance permission, must a new configuration…（原文摘录） | 已确认违反 | Execution 5f04338bd9e04060b57241324ec589da records the complete early-Advance witness: pending first configuration index 3, internal Applied 3 and voters {1}; subsequent… | [C_PENDING_CONFIG_ADMISSION](state.json) |
| 2. Does a delayed append-completion notification preserve the current accepted logical log entry when storage temporarily contains…（原文摘录） | 有限检查未见违反 | Execution ce685a3cf2234bbca54f8b07081bf7f0 completed with unchanged target files. P_STORAGE_VIEW compared one admitted operation and reported holds with a complete… | [C_ACCEPTED_LOG_VIEW](state.json) |
| When a newly elected leader initializes its own Match from an inherited prior-term log tail, can that initialized Match alone… | 源码解释，未经性质执行 | raftLog.maybeCommit requires selected entry term equal to nonzero current leader term; a selected inherited prior-term entry fails this guard.；The first current-term… | [候选记录](state.json) |

### 1. When a synchronous Node caller has persisted a Ready and used the documented early Advance permission, must a new configuration…（原文摘录）

**已确认违反**。要求原文：With configuration validation enabled, a synchronous Node must not accept a subsequent configuration proposal as a configuration log entry while a prior committed configuration change has neither been applied through ApplyConfChange nor rejected by the caller, including when the caller has persisted the Ready and used the documented permission to Advance before finishing application.

决定性范围：Public Node configuration proposal admission during finite ordered application deferral after completed Ready persistence.
Serialized Node event loop and public API calls.；Ready entries, HardState and snapshots are saved before Advance; no early outbound response delivery.；Caller eventually activates the first configuration and preserves inter-Ready application order; the first configuration is not rejected.；Configuration validation enabled; simple configuration changes outside joint state; stable leader during the selected interval.。
范围参数：{"entry": "Node.ProposeConfChange", "storage_mode": "synchronous", "faults": "No crash; newly added peers may be absent"}
排除：RawNode-only caller contract；AsyncStorageWrites；Configuration validation disabled；Crash recovery and device atomicity；General election safety, divergent application results or quorum intersection proof；Eventual success of a permitted proposal。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution 5f04338bd9e04060b57241324ec589da records the complete early-Advance witness: pending first configuration index 3, internal Applied 3 and voters {1}; subsequent index 4 is an EntryConfChange before first activation. Withholding Advance yields an empty EntryNormal, while applying first makes the rejection implication inapplicable. All three recorded endpoints complete. Correspondence review finds no issue with this scoped admission comparison and explains why explicit Node step-order permission applies despite the alternative immediate-duty reading. This review is not an independent execution, a general safety proof or a claim of inconsistent committed decisions.

制品 v1；机械比较 **观察到违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试／模型](direct-checks/bf815d8c91654e9fb8e33e3226800174/assurance_generated_test.go)；[条件与检查器](direct-checks/bf815d8c91654e9fb8e33e3226800174/plan.json)；[原始观察](logs/5f04338bd9e04060b57241324ec589da/stdout.log)；[assessment](direct-checks/bf815d8c91654e9fb8e33e3226800174/5f04338bd9e04060b57241324ec589da-assessment.json)；[对应性复核](submissions/3f552a2502ef4ae880e7522146b8ec9a/accepted.json)

固定比较 `P_PENDING_CONFIG`：观察到违反；已比较 3 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） | 观察 3 |
| --- | --- | --- | --- |
| op | second-config-deferred_no_advance | second-config-deferred_early_advance | second-config-applied_then_advance |
| node | 1 | 1 | 1 |
| proposal_seq | 2 | 2 | 2 |
| phase | processed_entry | processed_entry | processed_entry |
| first_pending_at_processing | true | true | false |
| accepted_as_configuration | false | true | true |
| first.first_type | EntryConfChange | EntryConfChange | EntryConfChange |
| first.persisted | true | true | true |
| admission.first_index | 3 | 3 | 3 |
| admission.saved | true | true | true |
| admission.first_rejected | false | false | false |
| entry_data_bytes | 0 | 6 | 6 |
| entry_type | EntryNormal | EntryConfChange | EntryConfChange |
| event | proposal_result | proposal_result | proposal_result |
| first_index | 3 | 3 | 3 |
| first_rejected | false | false | false |
| policy | deferred_no_advance | deferred_early_advance | applied_then_advance |
| processing_term | 2 | 2 | 2 |
| second_index | 4 | 4 | 4 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 2. Does a delayed append-completion notification preserve the current accepted logical log entry when storage temporarily contains…（原文摘录）

**有限检查未见违反**。要求原文：Consuming a delayed append-completion notification must preserve the current accepted logical log entry while its replacement storage write is pending and Storage contains a conflicting intervening version, provided no new accepted append, snapshot or other history-changing operation occurs during that completion interval.

决定性范围：Asynchronous local storage completion across leader-context changes with an accepted replacement not yet reflected in Storage.
Serialized RawNode calls.；Reliable FIFO append requests and FIFO local responses; remote responses delivered only after their writes.；Protocol messages produced by actual raft nodes; caller initializes a valid shared committed prefix.；No crash, snapshot, compaction or configuration activation during the selected preservation interval.。
范围参数：{"storage_mode": "AsyncStorageWrites", "faults": "finite network loss and response/write delays"}
排除：Byzantine or forged messages；Crash-atomic device behavior；General election safety or committed-entry agreement across nodes；General liveness or timing guarantees。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution ce685a3cf2234bbca54f8b07081bf7f0 completed with unchanged target files. P_STORAGE_VIEW compared one admitted operation and reported holds with a complete comparison. At admission node 2 was in term 4, Storage held term 3 at index 3 and the accepted replacement carried term 2/payload retained-from-first-leader. After the delayed term-2 completion, the full logical entry still matched the independently captured replacement. Current replacement work subsequently completed and all driver queues drained. This review finds no correspondence issue for the fixed version; controller assessment owns reviewed status.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试／模型](direct-checks/c1d4b567efee4cfd958ac3f6356e6964/assurance_generated_test.go)；[条件与检查器](direct-checks/c1d4b567efee4cfd958ac3f6356e6964/plan.json)；[原始观察](logs/ce685a3cf2234bbca54f8b07081bf7f0/stdout.log)；[assessment](direct-checks/c1d4b567efee4cfd958ac3f6356e6964/ce685a3cf2234bbca54f8b07081bf7f0-assessment.json)；[对应性复核](submissions/6e072fd4e6604d8c812c6a672350fc16/accepted.json)

固定比较 `P_STORAGE_VIEW`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| op | replacement |
| node | 2 |
| entry_index | 3 |
| phase | after_old_completion |
| log_entry | {"data":"cmV0YWluZWQtZnJvbS1maXJzdC1sZWFkZXI=","index":3,"term":2,"type":0} |
| admission.replacement_serial | 4 |
| admission.completion_type | MsgStorageAppendResp |
| admission.stale_response | true |
| admission.stored_conflicts | true |
| admission.pending_writes | 1 |
| event | old_completion_result |
| log_term | 2 |
| original_entry_term | 2 |
| pending_completions | 4 |
| pending_writes | 1 |
| raft_term | 4 |
| serial | 9 |
| stored_term | 3 |
| unstable_entries | 2 |
| unstable_offset | 3 |

前提关联：观察 1 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


条件探索：Under AsyncStorageWrites with ordered local workers, does an actual later-term vote request followed by old and then current append completions leave and then clear the follower unstable prefix, even…
所选问题／策略（原文摘录）：Construct a single history through public RawNode methods using three actual raft instances. Bootstrap each Storage from the same term-1 committed snapshot, run a real term-2 election, then replicate a proposal to node 2 while delaying its…
[受理问题、条件与来源](submissions/ce088ac9c931490aa3551e39e28b158f/accepted.json)；[固定输入](submissions/ce088ac9c931490aa3551e39e28b158f/inputs/storage_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/094ea077ebb340d39d82022bc7e733ad/check.json)；[实际输出](logs/094ea077ebb340d39d82022bc7e733ad/stdout.log)；[诊断](logs/094ea077ebb340d39d82022bc7e733ad/stderr.log)
[执行文件清单](experiments/b14df3dbfb2647fc82d19a72e8e2b133/workspace-delta/manifest.json)；[执行文件清单](experiments/b14df3dbfb2647fc82d19a72e8e2b133/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "prefix", "follower_applied": 2, "leader_commit": 2, "leader_term": 2}
结构化观察原值（非性质判定；全部事件见日志）：{"entry_index": 3, "entry_term": 2, "event": "append_held", "node": 2, "op": "reconfirm", "request_term": 0, "unstable_offset": 3}
执行后交接摘录：Exploration 9e5d14f4513e4988a856d198246a176f completed actual leaders 1/term2, 3/term3, then 1/term4. At node 2, index 3 had logical term 2, stored term 3, two unstable entries and one pending replacement write. Consuming the delayed term-2 completion…；[完整解释与剩余问题](submissions/4d3f28aea9c74c2c820a4717a7b643c9/accepted.json)
该交接保留的未知：Execute a fresh fixed check with expected entry bytes captured from the actual accepted replacement work, an independent operation identity, and result observations after delayed and current completion.

条件探索：Can a delayed original append completion change the follower log view to an intervening conflicting stored entry after a later actual leader has restored the original entry in unstable memory, while…
所选问题／策略（原文摘录）：Extend the actual-producer history to five RawNodes and three leadership terms. Keep append-worker requests FIFO. After writes, delay local completion responses to node 2 in FIFO order while delivering durable responses to other…
[受理问题、条件与来源](submissions/a37d283ba41d4332b8e5eab54bb3d19d/accepted.json)；[固定输入](submissions/a37d283ba41d4332b8e5eab54bb3d19d/inputs/storage_replacement_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/9e5d14f4513e4988a856d198246a176f/check.json)；[实际输出](logs/9e5d14f4513e4988a856d198246a176f/stdout.log)；[诊断](logs/9e5d14f4513e4988a856d198246a176f/stderr.log)
[执行文件清单](experiments/974f9e20870344d6993b268f48a1f619/workspace-delta/manifest.json)；[执行文件清单](experiments/974f9e20870344d6993b268f48a1f619/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"commit": 2, "event": "leader", "node": 1, "phase": "prefix", "term": 2}
结构化观察原值（非性质判定；全部事件见日志）：{"entry_index": 3, "entry_term": 2, "event": "original_completion", "node": 2, "op": "replacement", "response_term": 2, "response_type": "MsgStorageAppendResp"}
执行后交接摘录：Exploration 9e5d14f4513e4988a856d198246a176f completed actual leaders 1/term2, 3/term3, then 1/term4. At node 2, index 3 had logical term 2, stored term 3, two unstable entries and one pending replacement write. Consuming the delayed term-2 completion…；[完整解释与剩余问题](submissions/4d3f28aea9c74c2c820a4717a7b643c9/accepted.json)
该交接保留的未知：Execute a fresh fixed check with expected entry bytes captured from the actual accepted replacement work, an independent operation identity, and result observations after delayed and current completion.

条件探索：With actual public Node configuration proposals, does the pending-change guard follow ApplyConfChange activation or the internal applied frontier advanced by Node.Advance, when configuration…
所选问题／策略（原文摘录）：Compare three explicit caller policies from independently constructed one-voter prefixes: defer ApplyConfChange and withhold Advance; defer ApplyConfChange but call Advance early; and activate first before Advance. A real election and…
[受理问题、条件与来源](submissions/5de54877903c4de3b1de183e103e433b/accepted.json)；[固定输入](submissions/5de54877903c4de3b1de183e103e433b/inputs/early_advance_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/6dab32606865456a91887dbe509c632f/check.json)；[实际输出](logs/6dab32606865456a91887dbe509c632f/stdout.log)；[诊断](logs/6dab32606865456a91887dbe509c632f/stderr.log)
[执行文件清单](experiments/ea6912d8a30e4f169e8b9f28761a9394/workspace-delta/manifest.json)；[执行文件清单](experiments/ea6912d8a30e4f169e8b9f28761a9394/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"commit": 3, "event": "before_second", "first_activated": false, "first_index": 3, "internal_applied": 2, "policy": "deferred_no_advance", "voters": {"1": {}}}
结构化观察原值（非性质判定；全部事件见日志）：{"commit": 3, "event": "second_proposal_processed", "first_activated": false, "first_index": 3, "internal_applied": 2, "policy": "deferred_no_advance", "voters": {"1": {}}}
执行后交接摘录：Constructed a fixed check from the explored producer history. It separates first committed admission, second proposal processing, actual emitted entry type and final ordered activation. The oracle does not infer dropping from nil error, compare internal…；[完整解释与剩余问题](submissions/bf815d8c91654e9fb8e33e3226800174/accepted.json)
该交接保留的未知：Read the fresh execution and correlated comparisons, then review the complete checker correspondence including the unresolved caller-duty interpretation.

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v7：概览、Behavior／Fact 与来源](audit-spec/v7.json)。
- 共识形成与推进（原文导航摘录）：RawNode.Propose or serialized Node proposal handling reaches the current role. Followers forward to a known leader unless forwarding is disabled; candidates drop. The leader assigns current-term consecutive indexes,…
- 上下文／权威转换（原文导航摘录）：Ticks or Campaign enter hup, which checks promotability and unapplied configuration changes. Pre-election does not raise term; a real campaign increments term and records self Vote, with self response delayed for…
- 两条主线的连接（原文导航摘录）：Term/role reset discards votes, peer progress and safe-read acknowledgment tracker while preserving local log and committed frontier. Self progress is initialized from local lastIndex, including potentially unstable…

- 08:27:59 +0000（距创建墙钟 763.1 秒，含暂停间隔）；Agent 回合墙钟 383.80 秒 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 08:34:59 +0000（距创建墙钟 1183.3 秒，含暂停间隔）；目标工具耗时 13.19 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/094ea077ebb340d39d82022bc7e733ad/check.json)

- 08:40:16 +0000（距创建墙钟 1500.9 秒，含暂停间隔）；目标工具耗时 13.21 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/9e5d14f4513e4988a856d198246a176f/check.json)

- 08:48:54 +0000（距创建墙钟 2018.5 秒，含暂停间隔）；目标工具耗时 12.46 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/ce685a3cf2234bbca54f8b07081bf7f0/check.json)

- 09:03:04 +0000（距创建墙钟 2868.4 秒，含暂停间隔）；目标工具耗时 15.18 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/6dab32606865456a91887dbe509c632f/check.json)

- 09:18:20 +0000（距创建墙钟 3784.7 秒，含暂停间隔）；目标工具耗时 15.35 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/5f04338bd9e04060b57241324ec589da/check.json)

- 09:23:52 +0000（距创建墙钟 4116.3 秒，含暂停间隔）；Agent 回合墙钟 161.69 秒 · 认识／制品更新：The controller assessment for C_PENDING_CONFIG_ADMISSION now records outcome violated, confirmed true, bounded_complete true and reviewed_complete true with no blockers, attributed to execution…。[完整交接](submissions/983c867bbadd4ddda6f7db44eaad1e35/accepted.json)

- 09:25:32 +0000（距创建墙钟 4216.2 秒，含暂停间隔）；Agent 回合墙钟 99.52 秒 · 认识／制品更新：The latest index has no pending_work or review issues. Its controller assessments retain one confirmed, bounded and reviewed admission violation and one bounded, reviewed storage-preservation hold.…。[完整交接](submissions/64d2afc1a5b54845aa85e7771e3d38d6/accepted.json)

- 09:28:41 +0000（距创建墙钟 4405.4 秒，含暂停间隔）；Agent 回合墙钟 188.87 秒 · 认识／制品更新：Fresh source review distinguishes response production from public read completion. Safe reads normally register the committed index and caller context, locally acknowledge, broadcast context, and…。[完整交接](submissions/5229ae1e345d4d35bcc3097a9ea36e61/accepted.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

**开放责任：Ready synchronous send ordering documentation**

地图保留的缺口：README/doc.go allow same-batch message/write overlap while Ready.Messages requires persistence first. A follower new-entry batch with unchanged HardState distinguishes those policies. Examples and test callers persist entries before send; no captured normative precedence resolves broad overlap permission.
可改变判断的下一步：Resolve whether synchronous overlap permission includes follower append responses, or identify a real caller policy with a separately justified conditional requirement.
[地图 v7：概览、Behavior／Fact 与来源](audit-spec/v7.json)

候选：For synchronous Node Ready containing new follower entries but no HardState change, may the caller transmit the generated MsgAppResp before those same-batch entries are durable?
保存的语义未知：Which normative statement governs follower response ordering under the synchronous same-batch-overlap wording, absent an explicit captured precedence or role/message restriction?
恢复条件：Captured authoritative clarification defines same-batch overlap by message/role, or a concrete synchronous caller policy is selected for explicitly conditional exploration rather than general API attribution.
[候选原文与历史](state.json)

本轮记录的恢复条件：A concrete source or caller contract resolves the synchronous role/message ordering conflict.；A specific in-contract read, campaign or recovery history supplies an independent responsibility and observable endpoint.；Counterevidence challenges the scoped Node early-Advance interpretation or another retained result.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。模型结果与实现证据分开，脚本化 Agent 产品不证明自主发现。
