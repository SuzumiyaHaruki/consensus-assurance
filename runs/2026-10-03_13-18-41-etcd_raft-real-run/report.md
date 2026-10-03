# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 4 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。已产生观察的正式结论 2 项：已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、27 次 Agent 调用、12 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.16 | 0.00 |
| Agent 调用 | 40 | 13 | 27 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 2 次＋探索 2 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v43`；展示版本 `audit-products-v43`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`4.5008924459980335`（配置值不表示触发了超时）。
[调用记录](logs/ae44f182d2554f78887a76df67af00b5/check.json)；[stdout](logs/ae44f182d2554f78887a76df67af00b5/stdout.log)；[stderr](logs/ae44f182d2554f78887a76df67af00b5/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

## 主要结果

| 问题 | 当前结果 | 回答摘录 | 检查进度 | 定位 |
| --- | --- | --- | --- | --- |
| 1. 降级为 learner 的旧领导者仍通过单节点读捷径 | 已确认违反 | 在 StepDownOnRemoval=false、ReadOnlySafe 模式下，双方已应用降级配置后，旧领导者作为 learner 在未收到任何读期间消息的情况下返回索引 3；唯一投票节点已应用索引 5 的新写入。该结果违反本次检查的单节点读支持资格要求；尚未据此认定客户端线性一致性端点违规。 | 机械比较：观察到违反；对应性意见：no_issue_found；当前检查已完整处置 | [o-singleton-read-eligibility](#claim-o-singleton-read-eligibility) |
| 2. Status 复制配置时遗漏 AutoLeave | 已确认违反 | 已提交的固定检查中，隐式联合配置安装返回 AutoLeave=true，但紧接着调用 Status 得到 false；显式配置的 false 对照保持一致。源码中的 Config.Clone 未复制该字段，结论仅限配置状态报告错误，不代表运行中的自动退出策略被清除。 | 机械比较：观察到违反；对应性意见：no_issue_found；当前检查已完整处置 | [o-status-autoleave-copy](#claim-o-status-autoleave-copy) |
| Does the synchronous Node.Advance optimization permit advancing a Ready containing a committed configuration change before… | 记录状态 `paused` | 尚无正式义务 | — | [候选 1](#candidate-cc41ebdc8ff24f87be8731a39b2069b1) |
| If application of an implicit joint configuration triggers automatic exit while leadership transfer is in progress, can transfer… | 记录状态 `paused` | 尚无正式义务 | — | [候选 2](#candidate-593759733a0f4d5a9aaa662a8c98d8cb) |

<a id="claim-o-singleton-read-eligibility"></a>

### 1. 降级为 learner 的旧领导者仍通过单节点读捷径

**已确认违反**。要求原文：In ReadOnlySafe mode, completing a ReadIndex request through the singleton shortcut without a quorum-confirmation round requires that the local responding node be the sole voter in its installed configuration. A retained learner leader with a different sole voter must not complete the request using only its local state.

决定性范围：Eligibility of the local-only ReadOnlySafe shortcut after a fully applied leader-to-learner demotion, with StepDownOnRemoval disabled.
Non-Byzantine peers and immutable unique IDs.；Configuration change is committed using the prior configuration and applied in order.；Caller persists Ready state before sends and calls ApplyConfChange before Advance.；Read request uses a fresh unique context; no incoming voter message is delivered after invocation.。
范围参数：{"ReadOnlyOption": "ReadOnlySafe", "StepDownOnRemoval": false}
排除：Lease-based reads and clock assumptions.；Early Advance before configuration application.；A requirement that every read must complete.；Global linearizability endpoint without a separate observed client history.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：在 StepDownOnRemoval=false、ReadOnlySafe 模式下，双方已应用降级配置后，旧领导者作为 learner 在未收到任何读期间消息的情况下返回索引 3；唯一投票节点已应用索引 5 的新写入。该结果违反本次检查的单节点读支持资格要求；尚未据此认定客户端线性一致性端点违规。

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：True。
[固定测试](direct-checks/b1ac8b0d3d584f8b90f1f75b49f9c285/assurance_generated_test.go)；[条件与检查器](direct-checks/b1ac8b0d3d584f8b90f1f75b49f9c285/plan.json)；[原始观察](logs/e94f713eff47485582d7004dd190b24e/stdout.log)；[assessment](direct-checks/b1ac8b0d3d584f8b90f1f75b49f9c285/e94f713eff47485582d7004dd190b24e-assessment.json)；[对应性复核](submissions/223f1d0d9cb248b8aee3bab8c991e024/accepted.json)

固定比较 `singleton-eligibility`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| run | demotion | demotion |
| node | 1 | 2 |
| request | fresh-read-1 | fresh-read-2 |
| result_emitted | true | true |
| incoming_since_admission | 0 | 0 |
| local_is_sole_voter | false | true |
| admission.safe_mode | true | true |
| admission.isolated | true | true |
| admission_known | true | true |
| applied | 3 | 5 |
| event | read_result | read_result |
| read_index | 3 | 5 |
| response_number | 1 | 1 |
| role | StateLeader | StateLeader |
| term | 2 | 3 |
| value | old | new |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-o-status-autoleave-copy"></a>

### 2. Status 复制配置时遗漏 AutoLeave

**已确认违反**。要求原文：A Status configuration copy must preserve the installed AutoLeave policy when no configuration transition intervenes between establishment and observation. Copying configuration must not silently reinterpret an implicit automatic joint transition as an explicit application-controlled transition.

决定性范围：AutoLeave field preservation in synchronous RawNode.Status after applying a joint configuration.
Status called immediately after ApplyConfChange on the same thread, before Advance can trigger automatic exit.；Committed change is applied normally; no concurrent RawNode calls.。

排除：General status fields；Any claim that Status changes live tracker state；External operator consequences。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：已提交的固定检查中，隐式联合配置安装返回 AutoLeave=true，但紧接着调用 Status 得到 false；显式配置的 false 对照保持一致。源码中的 Config.Clone 未复制该字段，结论仅限配置状态报告错误，不代表运行中的自动退出策略被清除。

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：True。
[固定测试](direct-checks/c34f1669973445af97dd9f8eeaa34e49/assurance_generated_test.go)；[条件与检查器](direct-checks/c34f1669973445af97dd9f8eeaa34e49/plan.json)；[原始观察](logs/bcedae7735174e4cb70f70772e0c3f7d/stdout.log)；[assessment](direct-checks/c34f1669973445af97dd9f8eeaa34e49/bcedae7735174e4cb70f70772e0c3f7d-assessment.json)；[对应性复核](submissions/806d7bb2c5074370bfb33a7a26a436ab/accepted.json)

固定比较 `status-policy-copy`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| case | implicit | explicit |
| node | 1 | 1 |
| index | 3 | 3 |
| observed | true | true |
| auto_leave | false | false |
| installed.auto_leave | true | false |
| event | status_copy | status_copy |
| outgoing_count | 1 | 1 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="candidate-cc41ebdc8ff24f87be8731a39b2069b1"></a>

研究中问题：Does the synchronous Node.Advance optimization permit advancing a Ready containing a committed configuration change before ApplyConfChange, and if so can the accounted applied frontier let that node campaign using superseded membership?
当前记录状态：`paused`；[cc41ebdc8ff24f87be8731a39b2069b1：候选原文与历史](state.json)
保存的语义未知：Whether delaying ApplyConfChange until after early Node.Advance is permitted for a committed configuration entry; interface and package guidance need reconciliation.；Whether an applicable no-campaign obligation is stronger than the accounted-frontier guard and can be grounded without assuming actual configuration installation.
恢复条件：A sourced interpretation establishes whether early Advance may precede ApplyConfChange and identifies the applicable campaign restriction; or a legal in-repository caller demonstrates that overlap.

<a id="candidate-593759733a0f4d5a9aaa662a8c98d8cb"></a>

研究中问题：If application of an implicit joint configuration triggers automatic exit while leadership transfer is in progress, can transfer timeout leave the unchanged leader indefinitely joint in an otherwise quiescent, quorum-connected cluster?
当前记录状态：`paused`；[593759733a0f4d5a9aaa662a8c98d8cb：候选原文与历史](state.json)
保存的语义未知：Which sourced finite progress responsibility, if any, requires automatic exit after a rejected transfer-time proposal without another application event?

条件探索：For Candidate cc41ebdc8ff24f87be8731a39b2069b1, with a declared restart image containing a committed self-removal entry, does public Node.Campaign remain blocked before Advance but become admitted…
所选问题／策略（原文摘录）：Source contracts permit early Advance after persistence but the configuration-specific ordering remains disputed. A small public Node comparison can determine whether serialized dispatch itself prevents stale configuration campaign…
[受理问题、条件与来源](submissions/3f89e226ef804f02a46c793a4fbdfdb8/accepted.json)；[固定输入](submissions/3f89e226ef804f02a46c793a4fbdfdb8/inputs/advance_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/e334066fc8334a10b647e3ad10a35d36/check.json)；[实际输出](logs/e334066fc8334a10b647e3ad10a35d36/stdout.log)；[诊断](logs/e334066fc8334a10b647e3ad10a35d36/stderr.log)
[执行文件清单](experiments/7c6f6297beb9420c9e4478ae97873a52/workspace-delta/manifest.json)；[执行文件清单](experiments/7c6f6297beb9420c9e4478ae97873a52/workspace-outcome/manifest.json)
执行后精确引用交接：[见下方集中解释；不是本次独立观察](submissions/3de72180d6d0476a824c243fa3ef4933/accepted.json)

条件探索：For 593759733a0f4d5a9aaa662a8c98d8cb, does a leadership transfer to a lagging outgoing voter, started after implicit joint configuration application but before Advance, suppress auto-exit until an…
所选问题／策略（原文摘录）：Execute the sourced application/transfer interleaving while maintaining both joint quorums through nodes 1 and 2. Compare no-transfer control and separately labelled post-window application stimulus. A finite observation cannot itself…
[受理问题、条件与来源](submissions/d552ebc382c9410592c1076e68a70b6a/accepted.json)；[固定输入](submissions/d552ebc382c9410592c1076e68a70b6a/inputs/autoleave_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/c53c22ac25bc475cb34ed9068fd3f977/check.json)；[实际输出](logs/c53c22ac25bc475cb34ed9068fd3f977/stdout.log)；[诊断](logs/c53c22ac25bc475cb34ed9068fd3f977/stderr.log)
[执行文件清单](experiments/dbf15397b64f46758ab283dbb1e51b7b/workspace-delta/manifest.json)；[执行文件清单](experiments/dbf15397b64f46758ab283dbb1e51b7b/workspace-outcome/manifest.json)
执行后精确引用交接：[见下方集中解释；不是本次独立观察](submissions/c34f1669973445af97dd9f8eeaa34e49/accepted.json)

后续受理解释（执行 e334066fc8334a10b647e3ad10a35d36）：The public Node experiment observed both schedules from commit=2/applied=1 with node 2 in voters. Before accounting, Campaign stayed follower. With configuration first, Advance yielded applied=2/self_voter=false and Campaign stayed term-1 follower. With…
[完整交接；当前正式处置见上方固定制品与复核](submissions/3de72180d6d0476a824c243fa3ef4933/accepted.json)
该交接当时的剩余问题（非当前欠账）：Whether delaying ApplyConfChange until after early Node.Advance is permitted for a committed configuration entry; interface and package guidance need reconciliation.；Whether an applicable no-campaign obligation is stronger than the accounted-frontier guard and can be grounded without assuming actual configuration installation.；Investigate retained removed-leader singleton read authority under an unambiguous, fully applied configuration history.

后续受理解释（执行 c53c22ac25bc475cb34ed9068fd3f977）：Transfer overlap remained joint at index 3 after 10 and 30 ticks with transfer target cleared at 10; a later normal entry application triggered exit at index 5. The no-transfer control exited at index 4 before ticking. Status reported AutoLeave=false even…
[完整交接；当前正式处置见上方固定制品与复核](submissions/c34f1669973445af97dd9f8eeaa34e49/accepted.json)
该交接当时的剩余问题（非当前欠账）：Automatic-exit normative finite progress duty remains unresolved; elapsed ticks alone are not a proof of violation.；The status-copy discrepancy requires this fresh fixed comparison and correspondence review.

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v7：概览、Behavior／Fact 与来源](audit-spec/v7.json)。
- 共识形成与推进（原文导航摘录）：Leader proposals receive term/index, append to the log and queue a persistence-delayed self acknowledgment. Peer acknowledgments update progress; tracker aggregates current voters using both majorities for joint…
- 上下文／权威转换（原文导航摘录）：Campaign transitions establish candidate term and self vote; vote eligibility uses local vote/leader context and log freshness. PreVote leaves term and vote unchanged. Step handles message terms before role handlers,…
- 两条主线的连接（原文导航摘录）：Term dispatch prevents ordinary old responses from becoming new leader support. Persistence-delayed vote/append replies and leader self replies connect durable support to election and commit decisions. Configuration…

- 05:29:10 +0000（距创建墙钟 629.5 秒，含暂停间隔）；Agent 回合墙钟 361.73 秒 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 05:31:48 +0000（距创建墙钟 786.8 秒，含暂停间隔）；目标工具耗时 14.96 秒 · 实际执行：条件探索；条件观察完成；对象 e334066fc8334a10b647e3ad10a35d36。[执行记录](logs/e334066fc8334a10b647e3ad10a35d36/check.json)

- 05:42:05 +0000（距创建墙钟 1403.8 秒，含暂停间隔）；目标工具耗时 14.44 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment；对象 9050f0c543c046d98f7220703a46ed84。[执行记录](logs/e94f713eff47485582d7004dd190b24e/check.json)

- 05:44:44 +0000（距创建墙钟 1562.8 秒，含暂停间隔）；Agent 回合墙钟 158.20 秒 · 受理 review：降级为 learner 的旧领导者仍通过单节点读捷径；对象 unit-o-singleton-read-eligibility。[完整交接](submissions/223f1d0d9cb248b8aee3bab8c991e024/accepted.json)

- 05:50:37 +0000（距创建墙钟 1916.5 秒，含暂停间隔）；目标工具耗时 14.29 秒 · 实际执行：条件探索；条件观察完成；对象 c53c22ac25bc475cb34ed9068fd3f977。[执行记录](logs/c53c22ac25bc475cb34ed9068fd3f977/check.json)

- 05:55:14 +0000（距创建墙钟 2192.7 秒，含暂停间隔）；Agent 回合墙钟 275.67 秒 · 受理 check：A fresh fixed comparison tests the independently grounded Status-copy responsibility uncovered during auto-exit exploration.；对象 unit-o-status-autoleave-copy, 39855916eecb42bea58a07447bd9c962。[完整交接](submissions/c34f1669973445af97dd9f8eeaa34e49/accepted.json)

- 05:55:29 +0000（距创建墙钟 2208.3 秒，含暂停间隔）；目标工具耗时 14.68 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment；对象 b257ed38f8df4cb99a25261cfc0b2c53。[执行记录](logs/bcedae7735174e4cb70f70772e0c3f7d/check.json)

- 05:56:43 +0000（距创建墙钟 2281.8 秒，含暂停间隔）；Agent 回合墙钟 72.64 秒 · 受理 review：Status 复制配置时遗漏 AutoLeave；对象 unit-o-status-autoleave-copy。[完整交接](submissions/806d7bb2c5074370bfb33a7a26a436ab/accepted.json)

- 05:58:36 +0000（距创建墙钟 2394.9 秒，含暂停间隔）；Agent 回合墙钟 112.83 秒 · 受理 research：Retain smaller informative source conclusions near the controller time boundary, without expanding either confirmed result or manufacturing…。[完整交接](submissions/fec47c8d0ea64eecbc359133c250e6ae/accepted.json)

- 05:58:41 +0000（距创建墙钟 2399.8 秒，含暂停间隔）；Agent 回合墙钟 4.54 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/ae44f182d2554f78887a76df67af00b5/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。
- 暂停调查：[候选 1](#candidate-cc41ebdc8ff24f87be8731a39b2069b1)；恢复条件见该候选。
- 暂停调查：[候选 2](#candidate-593759733a0f4d5a9aaa662a8c98d8cb)；恢复条件见该候选。

### 地图登记与研究交接

以下是地图 v7 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v7：概览、Behavior／Fact 与来源](audit-spec/v7.json)

- core_overview：Synchronous persistence/send ordering discrepancy across interface descriptions.；Whether early synchronous Advance may precede configuration installation and allow campaigning with stale…
  尚无精确对应交接。

- b-commit：Whether the separately unresolved early-Advance configuration-callback contract permits a history outside the application-before-Advance argument.
  相关交接：[交接 8](#handoff-fec47c8d0ea64eecbc359133c250e6ae)

- b-application：Whether early synchronous Advance is permitted before ApplyConfChange, or whether the configuration callback has a stricter completion boundary.
  相关交接：[交接 2](#handoff-3de72180d6d0476a824c243fa3ef4933)；[交接 5](#handoff-eb02638a38f3431b97382a5e878fcf0f)；[交接 6](#handoff-c34f1669973445af97dd9f8eeaa34e49)

- b-read：Whether the separately unresolved early-Advance configuration-callback contract permits a history outside the application-before-Advance argument.
  相关交接：[交接 3](#handoff-e66fc906614b4ddea75bef662d7d2d77)；[交接 4](#handoff-223f1d0d9cb248b8aee3bab8c991e024)；[交接 5](#handoff-eb02638a38f3431b97382a5e878fcf0f)；[交接 8](#handoff-fec47c8d0ea64eecbc359133c250e6ae)

- f-applied-frontier：Whether configuration installation must precede early Advance even though ordinary application may overlap.
  尚无精确对应交接。

<a id="handoff-a4567a01174c47be8a79a362d2e10330"></a>

交接 1：[完整原文](submissions/a4567a01174c47be8a79a362d2e10330/accepted.json)；精确引用 b-context, b-ready, f-current-term-commit。
回答摘录：Ready explicitly imposes persistence before synchronous sends despite contradictory package prose. The remaining core paths connect vote tally, recovery, membership installation and host completion. Early Advance exposes a sourced uncertainty in the producer…
该交接当时的剩余问题（非当前欠账）：Resolve configuration callback ordering under early Advance before treating the resulting campaign as a defect.；Retain the pending-read history question and documentation conflict independently.

<a id="handoff-3de72180d6d0476a824c243fa3ef4933"></a>

交接 2：[完整原文](submissions/3de72180d6d0476a824c243fa3ef4933/accepted.json)；精确引用 b-application, b-context。
解释已在上方条件探索中集中展示。

<a id="handoff-e66fc906614b4ddea75bef662d7d2d77"></a>

交接 3：[完整原文](submissions/e66fc906614b4ddea75bef662d7d2d77/accepted.json)；精确引用 b-membership, b-read。
回答摘录：The public contract selects quorum-based safe reads; the shortcut tests only cardinality while configuration application may retain a nonvoting leader role. Demotion preserves participant status and removes the need to infer a shutdown duty after removal.
该交接当时的剩余问题（非当前欠账）：Does an actual public RawNode two-peer history admit and apply the leader demotion as a simple configuration change?；Will the demoted StateLeader emit a fresh ReadState without receiving any current voter acknowledgment?

<a id="handoff-223f1d0d9cb248b8aee3bab8c991e024"></a>

交接 4：[完整原文](submissions/223f1d0d9cb248b8aee3bab8c991e024/accepted.json)；精确引用 b-membership, b-read。
回答摘录：The actual two-node public RawNode history admits and applies leader demotion to learner. With singleton voters=[2], learner 1 retains StateLeader and returns fresh-read-1 at index 3 with zero incoming messages, while node 2 has applied write index 5 and…
该交接当时的剩余问题（非当前欠账）：A client read consumption endpoint and broader linearizability consequences are outside the accepted check.；Independent early-Advance contract ambiguity remains paused.；Other formation and context relationships remain available for investigation.

<a id="handoff-eb02638a38f3431b97382a5e878fcf0f"></a>

交接 5：[完整原文](submissions/eb02638a38f3431b97382a5e878fcf0f/accepted.json)；精确引用 b-application, b-read。
回答摘录：The accepted assessment confirms the local singleton read-support eligibility violation after correspondence review. Its reachability and result-emission premises are answered by the actual demotion history. A separate source path shows application-triggered…
该交接当时的剩余问题（非当前欠账）：Does a legal public API schedule suppress the sole exit trigger while leaving a joint quorum available?；Do subsequent ticks and ordinary heartbeat/append acknowledgments produce another application event or exit trigger?；What finite responsibility follows from automatic exit without assuming a general eventual-delivery or client-traffic guarantee?

<a id="handoff-c34f1669973445af97dd9f8eeaa34e49"></a>

交接 6：[完整原文](submissions/c34f1669973445af97dd9f8eeaa34e49/accepted.json)；精确引用 b-application。
解释已在上方条件探索中集中展示。

<a id="handoff-806d7bb2c5074370bfb33a7a26a436ab"></a>

交接 7：[完整原文](submissions/806d7bb2c5074370bfb33a7a26a436ab/accepted.json)；精确引用 b-status-copy, f-auto-leave-policy。
回答摘录：The fixed implicit case installed AutoLeave=true and immediately observed false in Status at the same configuration index 3; explicit mode preserved false. ConfState reads the live field and Status copies through Clone, which omits it. The immediate…
该交接当时的剩余问题（非当前欠账）：Any downstream status-consumer consequence is outside this local copy obligation.；Automatic-exit retry after transfer timeout still lacks a grounded finite progress obligation.

<a id="handoff-fec47c8d0ea64eecbc359133c250e6ae"></a>

交接 8：[完整原文](submissions/fec47c8d0ea64eecbc359133c250e6ae/accepted.json)；精确引用 b-commit, b-membership, b-read, b-status-copy。
回答摘录：Controller assessments now confirm both reviewed local violations. Independent source review bounds their implications: Config.Clone also feeds Changer.checkAndCopy, but valid EnterJoint overwrites AutoLeave, LeaveJoint clears it, and Simple rejects joint…
该交接当时的剩余问题（非当前欠账）：Early Advance before configuration callback remains a contractual uncertainty with conditional candidacy observations.；Automatic joint exit after failed transfer remained joint for 30 ticks and resumed on new application; no finite normative progress obligation was established.；Wider client consequences of singleton read authority and downstream consumers of erroneous Status are outside the confirmed checks.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
