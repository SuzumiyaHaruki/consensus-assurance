# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 2 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移超时后，隐式联合配置缺少自动退出触发 | 已确认违反 | 修正观测后，节点在转移超时、应用完成且正常处理心跳的情况下，完整协议状态每十个 tick 重复，AutoLeave 仍为真且没有退出提案。额外客户端提案随后触发退出；该结果指向自动续行缺失，不是共识安全违例。 | [O-auto-joint-continuation](#claim-O-auto-joint-continuation) |
| 2. Status 配置副本丢失 AutoLeave 标志 | 已确认违反 | 隐式联合配置应用后，返回的 ConfState 和实时配置均为 AutoLeave=true，但紧接着的 Status.Config.AutoLeave=false。固定执行显示自动退出随后正常完成；该缺陷属于状态副本失真，不代表实时配置被修改。 | [O-status-auto-fidelity](#claim-O-status-auto-fidelity) |
| Does the documented permission to call Advance while applying a Ready include delaying ApplyConfChange, and if so can campaign… | 暂停调查，尚无正式义务 | An applicable source resolves whether configuration installation may follow synchronous Node.Advance; then fix a separately scoped obligation/check if warranted. | [候选 1](#candidate-b53d1b5d808543a78a44be6432d23027) |

<a id="claim-O-auto-joint-continuation"></a>

### 1. 领导权转移超时后，隐式联合配置缺少自动退出触发

**已确认违反**。要求原文：For an implicit joint configuration assigned to Raft, after its entry has been applied and a transient leadership-transfer attempt has ended, a stable eligible leader with available joint quorums must retain an automatic path to propose leaving joint state. It must not remain in a closed repeating protocol execution with AutoLeave set and no leave proposal solely because the last application-triggered attempt was rejected during transfer.

决定性范围：Automatic continuation of implicit joint exit under a stable leader after failed transfer, with all emitted storage/application work completed and ordinary ticking/message delivery continued.
Non-Byzantine participants and valid initial configuration.；Synchronous caller persists before sends, applies entries/configurations before Advance, and processes all emitted work in order.；Transfer attempt may lose a TimeoutNow; after timeout the suffix delivers all network traffic and ticks every node.；No independent new client proposal or manual leave-joint is owed.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/66b8a80b11c344c8bf733893c60aa32a/assurance_generated_test.go)；[条件与检查器](direct-checks/66b8a80b11c344c8bf733893c60aa32a/plan.json)；[原始观察](logs/30c25f44a82b4d0c81c3b3b6e2d9d883/stdout.log)；[assessment](direct-checks/66b8a80b11c344c8bf733893c60aa32a/30c25f44a82b4d0c81c3b3b6e2d9d883-assessment.json)；[对应性复核](submissions/47ce59e6e8684345a0457dc8687b6c84/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.43 秒；执行进程耗时 11.98 秒；[实际命令、工具版本与输入记录](logs/30c25f44a82b4d0c81c3b3b6e2d9d883/check.json)
执行边界：Single-threaded three-node RawNode scheduler. No target changes, forged responses or concurrent observations. Transient TimeoutNow loss; apply-before-Advance throughout. Reflection serializes all fields recursively, including storage data, logs, pending queues, progress, inflights, timers, function identities, read tracking and RawNode completion state; it omits only output-only loggers and MemoryStorage mutex/call-count instrumentation. State values are retained directly, without hashes. Empty slice capacity and pointer allocation identity are not protocol state. All scheduler queues and outstanding Ready work are empty at comparison points. Corrected active_result reads raft.trk.Config.AutoLeave directly under sole driver ownership; status_auto_leave remains a diagnostic.；Replace physical transport/storage with a deterministic in-process network and MemoryStorage.；Record read-only recursive protocol state; omit logger/traceLogger, MemoryStorage.Mutex and MemoryStorage.callStats because execution is single-threaded and these do not determine the next protocol transition.；Corrected active_result samples the live AutoLeave flag instead of the Status.Config copy; retains status_auto_leave separately.
固定比较 `auto-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | implicit_exit_transfer_timeout |
| leader | 1 |
| joint_index | 3 |
| event | active_result |
| closed_joint_cycle | true |
| admitted.transfer_clear | true |
| admitted.completed_application | true |
| admitted.policy | ticks_all_deliver_all_no_new_proposals |
| applied | 3 |
| auto_leave | true |
| commit | 3 |
| cycle_equal | true |
| joint | true |
| leave_proposals_in_cycle | 0 |
| leave_proposals_total | 0 |
| period_ticks | 10 |
| protocol_state | str，8915 字符；首尾预览：*raft.RawNode(raft.RawNode{raft:*raft.raft(raft.ra…te:1,Commit:3},stepsOnAdvance:[]raftpb.Message[]})；[30c25f44a82b4d0c81c3b3b6e2d9d883 / event[3] / protocol_state](logs/30c25f44a82b4d0c81c3b3b6e2d9d883/stdout.log) |
| status_auto_leave | false |
| transfer_clear | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-O-status-auto-fidelity"></a>

### 2. Status 配置副本丢失 AutoLeave 标志

**已确认违反**。要求原文：A Status snapshot of the current Raft configuration must preserve the active Config.AutoLeave value. Config.Clone must copy that value along with the membership sets rather than reporting a default value unrelated to the source configuration.

决定性范围：Value fidelity of AutoLeave in a serialized Status snapshot of a legally installed implicit joint configuration.
Caller owns RawNode serially and uses normal persisted, applied, then Advanced Ready handling.；Observation occurs after ApplyConfChange and before further protocol mutation.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/a53aa8cfdece4cf698ca51c32f272ca6/assurance_generated_test.go)；[条件与检查器](direct-checks/a53aa8cfdece4cf698ca51c32f272ca6/plan.json)；[原始观察](logs/cf49d6a54dac42d187e53cbec83f0ea8/stdout.log)；[assessment](direct-checks/a53aa8cfdece4cf698ca51c32f272ca6/cf49d6a54dac42d187e53cbec83f0ea8-assessment.json)；[对应性复核](submissions/56dae62ea33941d49b26e51d5c806bc0/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.60 秒；执行进程耗时 12.85 秒；[实际命令、工具版本与输入记录](logs/cf49d6a54dac42d187e53cbec83f0ea8/check.json)
执行边界：Single serialized RawNode with MemoryStorage and actual proposal/Ready application. No state mutation instrumentation or forged acknowledgements. Drops only remote learner traffic.；Use MemoryStorage and a transport that loses learner-bound messages; sole-voter support remains local.
固定比较 `status-fidelity`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | implicit_status_copy |
| node | 1 |
| entry_index | 3 |
| event | status_result |
| observed_auto_leave | false |
| installed.expected_auto_leave | true |
| installed.implicit | true |
| live_auto_leave | true |
| outgoing_count | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：Under the conditional reading that Node.Advance may precede ApplyConfChange during ongoing application, does a real persisted removal replay permit public Node.Campaign to enter candidacy before the…
[受理问题、条件与来源](submissions/2c489d46aca44961883d243645b9d14d/accepted.json)；[固定输入](submissions/2c489d46aca44961883d243645b9d14d/inputs/explore_advance_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-b53d1b5d808543a78a44be6432d23027)
<a id="exploration-9590878d35a843a4813070eb2b0bb0a6"></a>
[探索执行 1](#exploration-9590878d35a843a4813070eb2b0bb0a6)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/9590878d35a843a4813070eb2b0bb0a6/check.json)；[实际输出](logs/9590878d35a843a4813070eb2b0bb0a6/stdout.log)；[诊断](logs/9590878d35a843a4813070eb2b0bb0a6/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.04 秒；执行进程耗时 12.60 秒；[实际命令、工具版本与输入记录](logs/9590878d35a843a4813070eb2b0bb0a6/check.json)
[执行输入文件清单](experiments/d270fb3f3c314eed9b72f69476ca7f08/workspace-delta/manifest.json)
[执行后文件清单](experiments/d270fb3f3c314eed9b72f69476ca7f08/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-51a7212c4cf446b5b0fb564ddb552f96)

<a id="exploration-feedback-51a7212c4cf446b5b0fb564ddb552f96"></a>
[交接 1](#exploration-feedback-51a7212c4cf446b5b0fb564ddb552f96) · 后续说明；关联：[探索执行 1](#exploration-9590878d35a843a4813070eb2b0bb0a6)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration 9590878d35a843a4813070eb2b0bb0a6 completed with exit 0. Real replication committed node 1 removal at index 3 in term 2. Replaying that history without Advance left applied=1 and campaign stayed follower/term 2; acknowledging the Ready before…
[完整交接；精确引用不表示已解决或已正式化](submissions/51a7212c4cf446b5b0fb564ddb552f96/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns entry term/index, replicates and counts Match acknowledgements through active voter quorums. Current-term matching gates commit advancement. Followers match the preceding entry and reject…
- 上下文／权威转换（原文导航摘录）：Campaign and term handling acquire or lose leader authority. Real candidacy increments term; reset discards peer support and readOnly tracking. A new leader retains history, appends an empty current-term entry and…
- 两条主线的连接（原文导航摘录）：Progress support is leader-context local, while committed history survives reset. Configuration application changes quorum interpretation and can itself advance commit. Persistence-qualified replies connect durable…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.90 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 8.90 分钟 · 实际执行：Resolve actual production dispatch and replay reachability using a generated election/replication prefix. This is construction knowledge…；探索执行正常结束。[执行记录](logs/9590878d35a843a4813070eb2b0bb0a6/check.json)

- 10.28 分钟 · 受理 pause：The remaining discriminator is normative caller ordering, not whether the public dispatch permits candidacy. Further input variants cannot…。[完整交接](submissions/51a7212c4cf446b5b0fb564ddb552f96/accepted.json)

- 13.06 分钟 · 受理 obligation：Investigate a separate sourced automatic-continuation responsibility with a closed-cycle witness rather than imposing an unsupported…。[完整交接](submissions/0460e0221ea648ac8b63893329e79460/accepted.json)

- 16.35 分钟 · 修订前 v1：目标进程执行成功；保存的机械比较：有限检查未见违反；复核与修订见各自后续节点。[原固定输入](direct-checks/b43d3a00c37c490d9b64c651e09ed535/plan.json)；[原执行记录](logs/68c541c593f245b696bd951e33298fa2/check.json)；[原保存评估](direct-checks/b43d3a00c37c490d9b64c651e09ed535/68c541c593f245b696bd951e33298fa2-assessment.json)

- 18.47 分钟 · 受理 review：The fixed execution completed, but its predicate reads a configuration copy that omits the field controlling the obligation. Preserve the…；v1 checker_correspondence: revision_needed。[完整交接](submissions/758a19f97d8a451e8b32a343e6dcecfe/accepted.json)

- 20.27 分钟 · 受理 revise_check：Correct observation of the active configuration flag; preserve generated history, caller duties, recurrence comparison, requirement and…。[完整交接](submissions/66b8a80b11c344c8bf733893c60aa32a/accepted.json)

- 20.47 分钟 · 实际执行：领导权转移超时后，隐式联合配置缺少自动退出触发；执行完成；比较见 assessment。[执行记录](logs/30c25f44a82b4d0c81c3b3b6e2d9d883/check.json)

- 22.65 分钟 · 受理 review：领导权转移超时后，隐式联合配置缺少自动退出触发；v2 checker_correspondence: no_issue_found。[完整交接](submissions/47ce59e6e8684345a0457dc8687b6c84/accepted.json)

- 25.41 分钟 · 实际执行：Status 配置副本丢失 AutoLeave 标志；执行完成；比较见 assessment。[执行记录](logs/cf49d6a54dac42d187e53cbec83f0ea8/check.json)

- 26.62 分钟 · 受理 review：Status 配置副本丢失 AutoLeave 标志；v1 checker_correspondence: no_issue_found。[完整交接](submissions/56dae62ea33941d49b26e51d5c806bc0/accepted.json)

- 28.30 分钟 · 受理 research：Resolve an initially suspicious call-site difference under its actual ordinary-ordering premises instead of fabricating a trigger or…。[完整交接](submissions/d7c53b795d294258b9e56d347935ce38/accepted.json)

- 29.72 分钟 · 受理 research：Retain newly traced retry protections and specific snapshot-completion premises; no fabricated obligation or execution is needed for this…。[完整交接](submissions/3b9f78b518974f68b10b7f50b204f72d/accepted.json)

- 29.99 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/1cef5559c0694c7d9148dcc3ed10ea4d/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<a id="candidate-b53d1b5d808543a78a44be6432d23027"></a>

暂停调查：Does the documented permission to call Advance while applying a Ready include delaying ApplyConfChange, and if so can campaign admission incorrectly treat a committed but uninstalled configuration as applied?
[候选原文与历史](state.json)
保存的语义未知：Whether Node.Advance application overlap legally includes deferring ApplyConfChange; RawNode.Advance uses stricter applied-and-saved wording.
恢复条件：An applicable source resolves whether configuration installation may follow synchronous Node.Advance; then fix a separately scoped obligation/check if warranted.
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-9590878d35a843a4813070eb2b0bb0a6)

<details><summary>地图登记与研究交接</summary>

以下是地图 v6 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)

- core_overview：Early Advance versus configuration installation and campaign admission.；Configuration-driven first-current-term pending-read release is protected under apply-before-Advance; the remaining overlap…
  尚无精确对应交接。

- B-context：Whether allowed early Advance may move the campaign scan lower bound past a configuration not yet installed by ApplyConfChange.
  相关交接：[交接 1](submissions/a7c06920926d4dbb9749ae3e7078d241/accepted.json)；[交接 2](submissions/51a7212c4cf446b5b0fb564ddb552f96/accepted.json)；[交接 3](submissions/47ce59e6e8684345a0457dc8687b6c84/accepted.json)；[交接 4](submissions/d7c53b795d294258b9e56d347935ce38/accepted.json)

- B-config：Does the application-overlap permission include deferring ApplyConfChange beyond Advance?
  相关交接：[交接 1](submissions/a7c06920926d4dbb9749ae3e7078d241/accepted.json)；[交接 2](submissions/d7c53b795d294258b9e56d347935ce38/accepted.json)

- B-ready：Package usage text permits current-batch send/persist overlap while Ready requires persistence first; applicability needs resolution.
  相关交接：[交接 1](submissions/a7c06920926d4dbb9749ae3e7078d241/accepted.json)

- B-application：Whether early Advance permission requires configuration installation first.
  相关交接：[交接 1](submissions/51a7212c4cf446b5b0fb564ddb552f96/accepted.json)；[交接 2](submissions/47ce59e6e8684345a0457dc8687b6c84/accepted.json)；[交接 3](submissions/a53aa8cfdece4cf698ca51c32f272ca6/accepted.json)

- B-reads：Deferred configuration application beyond Advance remains conditional on the paused caller-contract question; this source argument does not cover that disputed ordering.
  相关交接：[交接 1](submissions/d7c53b795d294258b9e56d347935ce38/accepted.json)

- B-retry：The Node interface calls SnapshotFinish a no-op, while the handler transitions StateSnapshot to StateProbe. Determine whether this is documentation drift or an intentional compatibility…
  相关交接：[交接 1](submissions/3b9f78b518974f68b10b7f50b204f72d/accepted.json)

- F-applied：Whether configuration installation is independently required before an early Advance that advances this marker.
  相关交接：[交接 1](submissions/51a7212c4cf446b5b0fb564ddb552f96/accepted.json)

- surface:doc.go Usage step 2 versus Ready.Messages：Conflicting persistence-before-send guidance; do not choose the weaker contract to create a witness.
  尚无精确对应交接。

- surface:ReportSnapshot completion correlation：Peer-only status and StateSnapshot guard lack an explicit attempt correlation field. Need legal callback/receiver-ack history and retry consequences before assigning a requirement; existing probe…
  尚无精确对应交接。

- surface:SnapshotFinish documented no-op：Node API describes no-op but the StateSnapshot handler moves to probing with PendingSnapshot-derived Next. This sourced difference is not yet a defect; externally observable contract and alternative…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 3 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 3 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、26 次 Agent 调用、12 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.08 | 0.00 |
| Agent 调用 | 40 | 14 | 26 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 3 | 7 |
| 修订 | 6 | 1 | 5 |

受控目标执行进程耗时（正式检查＋探索）：已记录 49.06 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 51.16 秒。

目标执行组成：正式检查 3 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/1cef5559c0694c7d9148dcc3ed10ea4d/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`15.85675599000001`（配置值不表示触发了超时）。
[调用记录](logs/1cef5559c0694c7d9148dcc3ed10ea4d/check.json)；[stdout](logs/1cef5559c0694c7d9148dcc3ed10ea4d/stdout.log)；[stderr](logs/1cef5559c0694c7d9148dcc3ed10ea4d/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

