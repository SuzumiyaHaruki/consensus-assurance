# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**。已受理 Candidate 3 项；当前 Unit 3 项、义务 3 项、固定检查制品 3 项。正式执行尝试 3 次；已保存评估的义务 3 项，其中有实际比较 3 项。已确认违反 3 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **30.27 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 583.78 秒、31 次 Agent 调用、12 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1816.22 | 583.78 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 3 | 3 |
| 语义复核 | 10 | 3 | 7 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 44.87 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 46.01 秒。

目标执行组成：正式检查 3 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v53`；展示版本 `audit-products-v53`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/e99d17997449471da16a693c9ad2b5f3/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`881.0082093440014`（配置值不表示触发了超时）。
[调用记录](logs/e99d17997449471da16a693c9ad2b5f3/check.json)；[stdout](logs/e99d17997449471da16a693c9ad2b5f3/stdout.log)；[stderr](logs/e99d17997449471da16a693c9ad2b5f3/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. Accept 已应答但恢复报告仍为预接受 | 已确认违反 | 实际慢路径中，两名接收者均返回匹配 ballot 的 AcceptReply；随后更高 ballot 的 Prepare 报告仍为 PREACCEPTED(1) 和 PREACCEPTED_EQ(2)，均低于 ACCEPTED(3)。证据限定为本地已应答支持的阶段记录与报告，不证明集群决策分歧。 | [C-accepted-support-reporting](#claim-C-accepted-support-reporting) |
| 2. 同一实例在恢复后提交不同命令 | 已确认违反 | 固定执行中，节点0先为实例0.0提交 PUT(17, chosen)，节点3随后在实际恢复触发后为同一实例提交 NOOP；两次状态均为 COMMITTED。历史包含一次故障和合法的分类型消息调度，保留原有保护；尚未测量客户端结果或隔离唯一必要根因。 | [C-recovery-decision-agreement](#claim-C-recovery-decision-agreement) |
| 3. PrepareReply 传输丢失值轮次 | 已确认违反 | 实际执行中，同一实例的 PrepareReply 在发送端对应 VBallot=1，解码后变为 0；零值对照保持为 0。该证据支持局部 RPC 值轮次保留责任的反例，尚未证明集群决策分歧。 | [C-prepare-vballot-preservation](#claim-C-prepare-vballot-preservation) |

<a id="claim-C-accepted-support-reporting"></a>

### 1. Accept 已应答但恢复报告仍为预接受

**已确认违反**。要求原文：When an acceptor handles an eligible Accept for an uncommitted instance and emits an AcceptReply matching the requested ballot, a subsequent Prepare response for that instance must report support at least at ACCEPTED status, provided no intervening value-replacement transition has occurred. A higher promise alone must not erase the acknowledged acceptance phase.

决定性范围：Local retention/reporting of acknowledged acceptance across a subsequent higher Prepare in static-membership volatile EPaxos.
Valid Accept emitted by the implementation slow path；Request ballot at least current promise; instance not committed/executed before Accept；No intervening command replacement, restart or Commit delivery before Prepare。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/3e1092bea08c4711883f9dc7a905426a/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/3e1092bea08c4711883f9dc7a905426a/plan.json)；[原始观察](logs/a9ddd1a609834a22b2b145faedb16460/stdout.log)；[assessment](direct-checks/3e1092bea08c4711883f9dc7a905426a/a9ddd1a609834a22b2b145faedb16460-assessment.json)；[对应性复核](submissions/9e5ef53106584705a551cf6f5b67efb8/accepted.json)

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.93 秒；执行进程耗时 7.66 秒；[实际命令、工具版本与输入记录](logs/a9ddd1a609834a22b2b145faedb16460/check.json)
执行边界：Synchronous bounded allocations with production handlers, RPC factory and codecs; one explicit delivery schedule.；Allocate eight slots per row instead of MAX_INSTANCE and omit autonomous networking/execution/timers.；Buffer-backed SendMsg replaces sockets; dispatch selected emitted messages once; other messages remain pending.；Emit correlated observations without changing target protocol state or behavior.
固定比较 `P-accepted-status`：观察到违反；已比较 2 项，完整见证 2 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2（违反见证） |
| --- | --- | --- |
| acceptor | 1 | 2 |
| replica | 0 | 0 |
| instance | 0 | 0 |
| event | accepted_support_reported | accepted_support_reported |
| recognized_accepted_support | false | false |
| prepare_ballot | 8 | 8 |
| status | 1 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-C-recovery-decision-agreement"></a>

### 2. 同一实例在恢复后提交不同命令

**已确认违反**。要求原文：Within one fixed EPaxos configuration and crash-fault history, once a command batch is committed for a replica-row/instance, any later commitment for that same row/instance at a nonfailed participant must contain the same ordered command batch, including across per-instance recovery and higher ballot promises.

决定性范围：Per-instance command decision agreement across recovery in a five-node volatile configuration tolerating up to two crash failures.
Static N=5,F=2 and distinct participant identities；At most one crash in the selected history; no Byzantine inputs or restart；Messages are actual emitted bytes and dispatched in a schedule allowed by per-type protocol channels。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/480e846629894a2b8094ca598ee592b3/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/480e846629894a2b8094ca598ee592b3/plan.json)；[原始观察](logs/4c474e84178449438f85e415d0f2019b/stdout.log)；[assessment](direct-checks/480e846629894a2b8094ca598ee592b3/4c474e84178449438f85e415d0f2019b-assessment.json)；[对应性复核](submissions/d59f79d19de34f6ba511d1b9257fef0b/accepted.json)

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 21.26 秒；执行进程耗时 20.99 秒；[实际命令、工具版本与输入记录](logs/4c474e84178449438f85e415d0f2019b/check.json)
执行边界：Controlled actual-handler schedule with codec receipt, per-type FIFO dispatch and a real recovery-trigger worker.；Bound allocation to eight instances per row; omit autonomous peer listeners and protocol event loops, preserving their selected dispatch semantics.；Buffer sockets and explicitly separate receipt from per-type dispatch; model one peer crash using the Alive eligibility change.；Run the actual executor only at node3 for its known hole; use unbuffered recovery queue to suspend it at the next request and synchronize cleanup.；Emit command JSON and status snapshots; target code and message fields are not replaced.
固定比较 `P-recovery-agreement`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| replica | 0 |
| instance | 0 |
| event | recovery_result |
| committed | true |
| commands | [{"Op":0,"K":0,"V":""}] |
| first.commands | [{"Op":1,"K":17,"V":"Y2hvc2Vu"}] |
| first.status | 4 |
| requested.initial_status | 4 |
| requested.known_max | 1 |
| node | 3 |
| original_status | 4 |
| status | 4 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-C-prepare-vballot-preservation"></a>

### 3. PrepareReply 传输丢失值轮次

**已确认违反**。要求原文：For a valid PrepareReply produced by an EPaxos acceptor and successfully transported through the registered peer RPC codec into a fresh message for the same acceptor/instance, the decoded VBallot must equal the producer-reported value ballot. The transport must preserve the support provenance that the recovery selector compares.

决定性范围：PrepareReply value-ballot preservation at the acceptor-to-recovery RPC boundary in static-membership crash-fault EPaxos.
Unmodified producer and consumer codecs from the same captured implementation；Valid in-memory acceptor state established by protocol handlers; complete noncorrupt delivery to a fresh registered reply object。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/534d73ff61aa4d0fb6c1491bf9be5777/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/534d73ff61aa4d0fb6c1491bf9be5777/plan.json)；[原始观察](logs/e4f3fbd3c91a45959da21038728d7adc/stdout.log)；[assessment](direct-checks/534d73ff61aa4d0fb6c1491bf9be5777/e4f3fbd3c91a45959da21038728d7adc-assessment.json)；[对应性复核](submissions/e35d582823d14e169943dade8ae7faef/accepted.json)

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.80 秒；执行进程耗时 8.55 秒；[实际命令、工具版本与输入记录](logs/e4f3fbd3c91a45959da21038728d7adc/check.json)
执行边界：Synchronous bounded replicas with actual handlers and peer codecs; buffer-backed SendMsg captures emitted bytes.；Bound instance allocation and omit automatic networking/timers/executor startup for local handler isolation.；Buffered writers replace peer sockets; the driver selects and synchronously dispatches valid emitted messages once.；Emit prerequisite and result JSON after synchronous handler/codec completion; no protocol implementation edits.
固定比较 `P-prepare-vballot`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| scenario | owner_0 | owner_1 |
| acceptor | 1 | 2 |
| replica | 0 | 1 |
| instance | 0 | 0 |
| event | prepare_decoded | prepare_decoded |
| vballot | 0 | 0 |
| produced.expected_vballot | 0 | 1 |
| ballot | 5 | 3 |
| status | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：Can recovery of a known missing instance select and then commit a different command after a real earlier fast decision, when its self report advertises a newly attempted value ballot and remote…
所选问题／策略（原文摘录）：S-recovery resets self vbal before reporting, and selection ranks that NONE self report against remote support. Explore a concrete prefix rather than presume agreement failure: five volatile nodes, actual fast decision at owner0/learner2;…
[受理问题、条件与来源](submissions/909283c7b6f04dbfb5bcaa0ab8bfd278/accepted.json)；[固定输入](submissions/909283c7b6f04dbfb5bcaa0ab8bfd278/inputs/recovery_agreement_explore.go)
<a id="exploration-7e8a903bb4d44050a9eaabf0f32448bb"></a>
[探索执行 1](#exploration-7e8a903bb4d44050a9eaabf0f32448bb)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/7e8a903bb4d44050a9eaabf0f32448bb/check.json)；[实际输出](logs/7e8a903bb4d44050a9eaabf0f32448bb/stdout.log)；[诊断](logs/7e8a903bb4d44050a9eaabf0f32448bb/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.02 秒；执行进程耗时 7.67 秒；[实际命令、工具版本与输入记录](logs/7e8a903bb4d44050a9eaabf0f32448bb/check.json)
[执行输入文件清单](experiments/efabf87b666945279c58b6722f6f6f85/workspace-delta/manifest.json)
[执行后文件清单](experiments/efabf87b666945279c58b6722f6f6f85/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-480e846629894a2b8094ca598ee592b3)

<a id="exploration-feedback-480e846629894a2b8094ca598ee592b3"></a>
[交接 1](#exploration-feedback-480e846629894a2b8094ca598ee592b3) · 后续说明；关联：[探索执行 1](#exploration-7e8a903bb4d44050a9eaabf0f32448bb)
后续受理交接原文（摘录，不是各次执行的独立观察）：The reviewed acceptance-report run confirmed only its local phase discrepancy. Separately, exploration 7e8a903bb4d44050a9eaabf0f32448bb reached a original committed PUT at nodes0/2 and a committed NOOP at node3 for row0.instance0 with type-queue order checks…
[完整交接；精确引用不表示已解决或已正式化](submissions/480e846629894a2b8094ca598ee592b3/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：A proposal is batched into its receiving replica row and starts phase 1 with owner-ID ballot. Conflict indices establish Seq/Deps. Thrifty PreAccept reaches selected alive peers, whose reports are qualified by…
- 上下文／权威转换（原文导航摘录）：Authority is per row/instance. inst.bal guards incoming work; leader bookkeeping lastTriedBallot guards phase replies. Executor-driven recovery replaces local attempt bookkeeping while retaining proposals and stored…
- 两条主线的连接（原文导航摘录）：Recovery authority does not independently determine a new value: its consumer uses reported support provenance/status and attributes to decide which formation path is eligible. bal may rise while vbal and prior…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.90 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.17 分钟 · 实际执行：PrepareReply 传输丢失值轮次；执行完成；比较见 assessment。[执行记录](logs/e4f3fbd3c91a45959da21038728d7adc/check.json)

- 9.69 分钟 · 受理 review：PrepareReply 传输丢失值轮次。[完整交接](submissions/e35d582823d14e169943dade8ae7faef/accepted.json)

- 12.94 分钟 · 实际执行：Accept 已应答但恢复报告仍为预接受；执行完成；比较见 assessment。[执行记录](logs/a9ddd1a609834a22b2b145faedb16460/check.json)

- 14.80 分钟 · 受理 review：Accept 已应答但恢复报告仍为预接受。[完整交接](submissions/9e5ef53106584705a551cf6f5b67efb8/accepted.json)

- 18.12 分钟 · 实际执行：S-recovery resets self vbal before reporting, and selection ranks that NONE self report against remote support. Explore a concrete prefix…；探索执行正常结束。[执行记录](logs/7e8a903bb4d44050a9eaabf0f32448bb/check.json)

- 22.11 分钟 · 受理 check：Fix a separate per-instance decision agreement obligation and strengthen the exploratory recovery-trigger premise before fresh execution.。[完整交接](submissions/480e846629894a2b8094ca598ee592b3/accepted.json)

- 22.47 分钟 · 实际执行：同一实例在恢复后提交不同命令；执行完成；比较见 assessment。[执行记录](logs/4c474e84178449438f85e415d0f2019b/check.json)

- 25.31 分钟 · 受理 review：同一实例在恢复后提交不同命令。[完整交接](submissions/d59f79d19de34f6ba511d1b9257fef0b/accepted.json)

- 30.27 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e99d17997449471da16a693c9ad2b5f3/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：PrepareReply codec omits VBallot; the reviewed local transport witness is retained with the Candidate. Downstream selection consequences remain separate.；Acceptance-phase reporting has a reviewed…
  尚无精确对应交接。

- B-preaccept：Command fill uses LeaderId row while lookup uses Replica row; reachability under recovery remains open
  尚无精确对应交接。

- B-form：Reply uniqueness relies on transport/producer behavior, not an acceptor identity in these reply types；Initial leader bookkeeping ballot starts at -1 and seq at -1; effect across sender IDs needs…
  相关交接：[交接 1](submissions/480e846629894a2b8094ca598ee592b3/accepted.json)；[交接 2](submissions/d59f79d19de34f6ba511d1b9257fef0b/accepted.json)

- B-accept：Broader decision consequences of acceptance-phase misreporting are separate from the reviewed local report witness.
  相关交接：[交接 1](submissions/9e5ef53106584705a551cf6f5b67efb8/accepted.json)

- B-learn：Commit for local row assumes leader bookkeeping when inspecting NOOP proposals
  尚无精确对应交接。

- B-authority：Repeated attempts may reuse ballot; local recovery rewrites vbal before reporting self support; preservation consequences remain open
  相关交接：[交接 1](submissions/480e846629894a2b8094ca598ee592b3/accepted.json)；[交接 2](submissions/d59f79d19de34f6ba511d1b9257fef0b/accepted.json)

- B-wire：Downstream selection/decision consequences are separate from the established local codec defect.
  相关交接：[交接 1](submissions/e35d582823d14e169943dade8ae7faef/accepted.json)

- B-select：Self report ballot rewrite versus remote report provenance; same-VBallot status ties; counts include reports below selected VBallot
  相关交接：[交接 1](submissions/e35d582823d14e169943dade8ae7faef/accepted.json)；[交接 2](submissions/9e5ef53106584705a551cf6f5b67efb8/accepted.json)；[交接 3](submissions/480e846629894a2b8094ca598ee592b3/accepted.json)；[交接 4](submissions/d59f79d19de34f6ba511d1b9257fef0b/accepted.json)

- B-recover-trigger：Counter measures iterations, not a strict elapsed-time deadline; dependency-blocked committed roots may need separate continuation analysis
  尚无精确对应交接。

- B-config：Allowed non-odd membership configurations and relation between registered list/config count require separate contract reading
  尚无精确对应交接。

- B-exec：Local time tie-breaker consistency for same-row equal-Seq cycles; asynchronous observation ownership; SCAN conflict integration
  尚无精确对应交接。

- B-client：Client retry policy and deduplication contract not yet traced
  尚无精确对应交接。

- surface:epaxos.(*Replica).recordInstanceMetadata：bal and vbal overwrite the same bytes; Durable=false in normal server entry and no restart reader yet established. Investigate applicability before a persistence obligation.
  尚无精确对应交接。

- surface:epaxos.(*Replica).handleAccept：Eligible Accept leaves tentative Status despite a matching acknowledgment; the local reporting witness is retained with its Candidate. Wider recovery/decision consequences remain open.
  尚无精确对应交接。

- surface:epaxos.(*Replica).handleAcceptReply：Unequal-ballot return precedes greater-ballot retry branch; periodic recovery is an alternative continuation whose efficacy remains open.
  尚无精确对应交接。

- surface:epaxos.(*Replica).startRecoveryForInstance：Recovery replaces vbal with newly attempted ballot before self report and may reuse ballots. Need legal overlapping history and support preservation analysis.
  尚无精确对应交接。

- surface:epaxos.(*Replica).handleTryPreAcceptReply：Recovery selector duplicates predicates, apparently excluding entry to TryPreAccept; detailed deferred/quorum accounting remains unclassified locally.
  尚无精确对应交接。

- surface:epaxos.nodeArray.Less：Equal Seq/same-row ties use local proposeTime rather than instance index; legal cycle/equal-Seq reachability unknown.
  尚无精确对应交接。

- surface:epaxos.(*Replica).updateAttributes / state.Conflict：Ordinary conflict index uses exact key; state.Conflict recognizes SCAN ranges. Need source of SCAN proposals and ordering responsibility.
  尚无精确对应交接。

- surface:client retry policy：In-repository client implementation remains to be read; TODO in protocol is not itself an invocation guarantee.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
