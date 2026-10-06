# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **31.54 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 2 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 恢复回复在传输中丢失值轮次 | 已确认违反 | 可信执行中，实例 1.0 的发送端值轮次为 1，解码后变为 0；请求轮次 7 和消息身份保持一致，解码完整结束。该结果支持 PrepareReply 的局部字段保真缺陷，尚未证明集群决策分歧。 | [C_prepare_vballot_preserved](#claim-C_prepare_vballot_preserved) |
| 2. 已用于提交的接受支持仍被报告为预接受 | 已确认违反 | 可信执行中，原协调者收到两个真实 AcceptReply 后提交，但接受者 0 的阶段仍为 PREACCEPTED_EQ（2）。在 Commit 尚未送达时，更高轮次的 PrepareReply 仍报告阶段 2，未反映其已接受的支持；尚未验证后续全局决策分歧。 | [C_accepted_phase_report](#claim-C_accepted_phase_report) |

<a id="claim-C_prepare_vballot_preserved"></a>

### 1. 恢复回复在传输中丢失值轮次

**已确认违反**。要求原文：For a PrepareReply produced by handlePrepare for a legal instance history and delivered intact through the registered serialization path to a fresh PrepareReply object, the decoded VBallot must equal the value ballot reported by the producer. The separate promise Ballot must not substitute for this consumed value context.

决定性范围：Local preservation of the value-ballot field across an intact PrepareReply transport boundary.
Non-Byzantine peers and intact bytes；Handler-produced report and fresh registered receiver object；No concurrent mutation while the report is serialized。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/5ec99f304c634b909da9f6c724dd3107/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/5ec99f304c634b909da9f6c724dd3107/plan.json)；[原始观察](logs/35b34756363847b183b2d3913113dbea/stdout.log)；[assessment](direct-checks/5ec99f304c634b909da9f6c724dd3107/35b34756363847b183b2d3913113dbea-assessment.json)；[对应性复核](submissions/d6f05c0ff902407f95d7f1f0e33b333e/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 9.00 秒；执行进程耗时 8.62 秒；[实际命令、工具版本与输入记录](logs/35b34756363847b183b2d3913113dbea/check.json)
执行边界：Single-threaded real handler and real serialization prefix with bounded constructor-equivalent storage and buffered peer links.；No target code changes.；Network and run-loop scheduling replaced by serial dispatch of actual serialized messages; unrelated messages remain buffered.；Constructor goroutines omitted; only empty used fields initialized and instance capacity reduced to 16.
固定比较 `K_prepare_vballot`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | nonzero_origin |
| acceptor | 0 |
| origin | 1 |
| instance | 0 |
| requester | 2 |
| event | report_decoded |
| decoded_vballot | 0 |
| sent.reported_vballot | 1 |
| sent.prefix_reached | true |
| decode_completed | true |
| remaining_bytes | 0 |
| request_ballot | 7 |
| status | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C_accepted_phase_report"></a>

### 2. 已用于提交的接受支持仍被报告为预接受

**已确认违反**。要求原文：An accepting peer that processes an eligible Accept and acknowledges that ballot must retain an ACCEPTED-or-later classification for the accepted instance metadata. A subsequent Prepare before any intervening value change must report that classification, including when the origin has committed using this support but its Commit message has not reached the peer.

决定性范围：Local phase fidelity of successfully accepted support across a later promise-only Prepare.
Non-Byzantine peers, static membership, intact messages；Eligible Accept reaches the storage branch and its reply matches the request ballot；No intervening value-changing operation at the inspected peer。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/14283691c3414f058f1ff46ed820b0f0/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/14283691c3414f058f1ff46ed820b0f0/plan.json)；[原始观察](logs/5889f79a2ba84d4dbf016630607560c4/stdout.log)；[assessment](direct-checks/14283691c3414f058f1ff46ed820b0f0/5889f79a2ba84d4dbf016630607560c4-assessment.json)；[对应性复核](submissions/e2997c6ea6534b6bb6ce9e677ae262df/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.28 秒；执行进程耗时 7.94 秒；[实际命令、工具版本与输入记录](logs/5889f79a2ba84d4dbf016630607560c4/check.json)
执行边界：Real proposal, preaccept, accept, accept-reply and prepare handlers with actual codecs in a bounded serial schedule.；No target changes.；Bounded constructor-equivalent state and in-memory peer streams; no background goroutines.；Direct dispatch of serialized messages and direct recovery entry; pending Commit messages remain undelivered.
固定比较 `K_accepted_phase`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | chosen_slow_path |
| acceptor | 0 |
| origin | 1 |
| instance | 0 |
| event | accepted_phase_report |
| accepted_or_later | false |
| accepted.eligible_accept_completed | true |
| accepted.origin_committed | true |
| decode_completed | true |
| local_phase | 2 |
| remaining_bytes | 0 |
| report_seq | 1 |
| reported_phase | 2 |
| request_ballot | 7 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：Can a legal missing-slot recovery after one accepting peer crashes commit a different command batch from the existing origin commitment, with old Commit buffered while a later-slot PreAccept is…
[受理问题、条件与来源](submissions/3d3517e1d06f4125ae45f6c0a900ea34/accepted.json)；[固定输入](submissions/3d3517e1d06f4125ae45f6c0a900ea34/inputs/recovery_explore_test.go)
<a id="exploration-6195681062194053841c80dbea5f750e"></a>
[探索执行 1](#exploration-6195681062194053841c80dbea5f750e)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/6195681062194053841c80dbea5f750e/check.json)；[实际输出](logs/6195681062194053841c80dbea5f750e/stdout.log)；[诊断](logs/6195681062194053841c80dbea5f750e/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.39 秒；执行进程耗时 7.74 秒；[实际命令、工具版本与输入记录](logs/6195681062194053841c80dbea5f750e/check.json)
[执行输入文件清单](experiments/6eb0e8d2f6404b5cb540a7a8e72917e5/workspace-delta/manifest.json)
[执行后文件清单](experiments/6eb0e8d2f6404b5cb540a7a8e72917e5/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Client proposals allocate an origin-row instance and preaccept with dependency/sequence attributes from conflict indexes. Acceptor preaccept reports are filtered by the coordinator attempt and phase; replies merge…
- 上下文／权威转换（原文导航摘录）：Authority is scoped to origin-row/instance and ballot, not one global log leader. startRecovery replaces bookkeeping, retains proposals, chooses an attempt ballot, retags its local entry and includes a self report…
- 两条主线的连接（原文导航摘录）：Recovery reports are the bridge from prior formation to authority transfer: promise Ballot qualifies the new attempt, while VBallot and Status decide which existing support the new coordinator uses. Commit/execute…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.25 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 12.20 分钟 · 实际执行：恢复回复在传输中丢失值轮次；执行完成；比较见 assessment。[执行记录](logs/35b34756363847b183b2d3913113dbea/check.json)

- 14.41 分钟 · 受理 review：恢复回复在传输中丢失值轮次；v1 checker_correspondence: no_issue_found。[完整交接](submissions/d6f05c0ff902407f95d7f1f0e33b333e/accepted.json)

- 20.76 分钟 · 受理 check：Submit the distinct accepted-support phase obligation and its fixed actual slow-path witness, alongside the natural map update from the…。[完整交接](submissions/14283691c3414f058f1ff46ed820b0f0/accepted.json)

- 20.90 分钟 · 实际执行：已用于提交的接受支持仍被报告为预接受；执行完成；比较见 assessment。[执行记录](logs/5889f79a2ba84d4dbf016630607560c4/check.json)

- 23.44 分钟 · 受理 review：已用于提交的接受支持仍被报告为预接受；v1 checker_correspondence: no_issue_found。[完整交接](submissions/e2997c6ea6534b6bb6ce9e677ae262df/accepted.json)

- 27.52 分钟 · 实际执行：Probe the remaining actual safety consequence with real quorum handlers, a known missing-slot recovery trigger and explicit per-type…；探索执行正常结束。[执行记录](logs/6195681062194053841c80dbea5f750e/check.json)

- 31.54 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/be69ad5115b74bb0afbc032a8870317d/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-6195681062194053841c80dbea5f750e)

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：PrepareReply codec omits VBallot; the scoped transport result does not settle wider recovery-selection or agreement consequences.；Accepted status retention, ballot reuse/retagging and quorum formula…
  尚无精确对应交接。

- B_phase1：Command fill uses LeaderId rather than Replica in the ACCEPTED-or-later branch; recovery may make them different.
  尚无精确对应交接。

- B_form：Threshold applicability and implicit self support need separate scrutiny; values are mapped as code observations, not qualified quorum proof.
  尚无精确对应交接。

- B_accept：Does retaining prior status after positive acceptance allow recovery to misclassify support?
  相关交接：[交接 1](submissions/14283691c3414f058f1ff46ed820b0f0/accepted.json)；[交接 2](submissions/e2997c6ea6534b6bb6ce9e677ae262df/accepted.json)

- B_authority：Repeated attempts can reuse ballots; strict increase and old-reply handling beyond equal-ballot filtering remain unresolved.
  尚无精确对应交接。

- B_recover_select：Selected-value safety under equal tags, wire omission, self-report retagging and accepted-status retention needs discrimination; these are separate premises.
  尚无精确对应交接。

- B_recovery_watch：Progress through recursive missing dependencies and unreachable TryPreAccept entry remains open.
  尚无精确对应交接。

- B_membership：Runtime membership replacement or restart reconstruction not established.
  尚无精确对应交接。

- B_apply：Application ordering under equal seq and same origin uses local proposeTime; legal reachability of consequential ties is unestablished.；Execution and protocol mutate shared instances concurrently;…
  尚无精确对应交接。

- B_history：Default executable passes durable=false and StableStore initializes nil; no restart reader has been established. Durable metadata discrepancy is not yet an applicable recovery defect.
  尚无精确对应交接。

- B_client：Client timeout/retry and duplicate completion semantics have not been read fully.
  尚无精确对应交接。

- F_local_value：Validity of retagging and status transitions remains open.
  相关交接：[交接 1](submissions/e2997c6ea6534b6bb6ce9e677ae262df/accepted.json)

- F_decision：Global agreement and dependency ordering remain to be checked.
  尚无精确对应交接。

- surface:Replica.handlePrepareReply case 4：TryPreAccept branch repeats prior condition and appears unreachable; separate receive/response code exists but current production entry history is unresolved.
  尚无精确对应交接。

- surface:Replica.updateAttributes versus state.Conflict：Key-indexed attribute construction and range-aware SCAN conflict semantics differ; scan caller eligibility and actual ordering consequence need investigation.
  尚无精确对应交接。

- surface:Client retry and completion policy：Server TODO is observed; complete client-side retry, reconnection and timeout contract remains unread.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 2 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 507.67 秒、33 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1892.33 | 507.67 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 24.30 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 25.67 秒。

目标执行组成：正式检查 2 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v55`；展示版本 `audit-products-v55`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/be69ad5115b74bb0afbc032a8870317d/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`748.2123926490021`（配置值不表示触发了超时）。
[调用记录](logs/be69ad5115b74bb0afbc032a8870317d/check.json)；[stdout](logs/be69ad5115b74bb0afbc032a8870317d/stdout.log)；[stderr](logs/be69ad5115b74bb0afbc032a8870317d/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

