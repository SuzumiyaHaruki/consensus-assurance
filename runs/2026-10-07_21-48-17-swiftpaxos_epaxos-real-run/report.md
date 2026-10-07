# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 2 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. Accept 已确认，恢复回复仍报告预接受状态 | 已确认违反 | 五副本执行中，副本 2 确认实例 (0,0) 的 Accept 后，在更高 ballot 6 的 PrepareReply 中仍报告 PREACCEPTED_EQ（2），而非 ACCEPTED（3）。命令与依赖仍保留；该证据确认的是局部阶段历史报告缺陷，尚未证明全局决策冲突。 | [O_accepted_phase_report](#claim-O_accepted_phase_report) |
| 2. PrepareReply 在线路传输中丢失 value ballot | 已确认违反 | 实际提案建立的 value ballot 为 1；同一 Prepare 请求的回复经原实现编码、解码后变为 0。该局部传输缺陷已被执行观测，尚未据此证明恢复决策冲突。 | [O_prepare_value_ballot](#claim-O_prepare_value_ballot) |

<a id="claim-O_accepted_phase_report"></a>

### 1. Accept 已确认，恢复回复仍报告预接受状态

**已确认违反**。要求原文：After an acceptor admits an Accept for an existing uncommitted instance and acknowledges that request at its ballot, a subsequent successful higher-ballot Prepare must report that instance as ACCEPTED if no intervening protocol action has replaced its value or advanced its phase. This preserves the accepted-versus-preaccepted distinction required by recovery selection.

决定性范围：Local acceptance-phase history exported by PrepareReply after admitted acceptance; no intervening value/phase change for the same instance.
Fixed non-Byzantine membership; requests are emitted by actual protocol producers.；No crash/restart or durable-store recovery in this history.；No concurrent mutation while a handler or its serialized reply is observed.。
范围参数：{"membership": "odd membership with configured f=(N-1)/2", "thrifty": true}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：Accept 已确认，恢复回复仍报告预接受状态；五副本执行中，副本 2 确认实例 (0,0) 的 Accept 后，在更高 ballot 6 的 PrepareReply 中仍报告 PREACCEPTED_EQ（2），而非 ACCEPTED（3）。命令与依赖仍保留；该证据确认的是局部阶段历史报告缺陷，尚未证明全局决策冲突。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/7cc51bf98faf46ffbcc507a188772d68/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/7cc51bf98faf46ffbcc507a188772d68/plan.json)；[原始观察](logs/60e27f33b9834b7d87fa2fe866557a2e/stdout.log)；[assessment](direct-checks/7cc51bf98faf46ffbcc507a188772d68/60e27f33b9834b7d87fa2fe866557a2e-assessment.json)；[对应性复核](submissions/622b1d6ceca445aa9c8b623353c4329b/accepted.json)；[对应性复核](submissions/8325cd5300cb4824af9fcb9d43810baa/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.52 秒；执行进程耗时 7.22 秒；[实际命令、工具版本与输入记录](logs/60e27f33b9834b7d87fa2fe866557a2e/check.json)
执行边界：TestAssuranceAcceptedHistory invokes unmodified handlers and codecs over per-directed-link byte streams. Emits admitted acknowledgment and actual serialized PrepareReply; no goroutines or resources needing asynchronous cleanup are started.；Constructor-equivalent bounded in-memory replicas instead of New network startup; initialized fields follow S_init/S_base.；Actual SendMsg writes to bufio.Writer over bytes.Buffer rather than TCP. Decode uses registered message New/Unmarshal.；Handler calls use an explicit serial schedule; recovery trigger is injected for a known unresolved slot instead of waiting on the execution scanner timer.；No protocol field is patched after initialization; proposals and all later messages use implementation producers.
固定比较 `accepted_phase`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| origin | 0 |
| instance | 0 |
| acceptor | 2 |
| completed | true |
| status | 2 |
| accepted.admitted | true |
| accepted.coordinator_accept_count | 1 |
| event | prepare_report |
| promise | 6 |
| seq | 1 |
| value_ballot | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-O_prepare_value_ballot"></a>

### 2. PrepareReply 在线路传输中丢失 value ballot

**已确认违反**。要求原文：A successfully serialized and decoded PrepareReply must preserve the value ballot copied from the acceptor local instance by handlePrepare, for the same acceptor, instance and Prepare request. Recovery must receive that value-history context unchanged across the message transport boundary.

决定性范围：Value-ballot fidelity at the PrepareReply transport boundary under an actual producer-derived local history.
Non-Byzantine messages and successful codec completion；No concurrent producer mutation during observation。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：PrepareReply 在线路传输中丢失 value ballot；实际提案建立的 value ballot 为 1；同一 Prepare 请求的回复经原实现编码、解码后变为 0。该局部传输缺陷已被执行观测，尚未据此证明恢复决策冲突。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/5a2b2f345fc443bcb65aca976b19061d/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/5a2b2f345fc443bcb65aca976b19061d/plan.json)；[原始观察](logs/0485c6c015bc4645a45e0f815f23a3f0/stdout.log)；[assessment](direct-checks/5a2b2f345fc443bcb65aca976b19061d/0485c6c015bc4645a45e0f815f23a3f0-assessment.json)；[对应性复核](submissions/082a059d9fad492e84491c333cb7ea05/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.77 秒；执行进程耗时 7.49 秒；[实际命令、工具版本与输入记录](logs/0485c6c015bc4645a45e0f815f23a3f0/check.json)
执行边界：TestAssurancePrepareValueBallot; unchanged handlers and codecs, byte-stream links and deterministic dispatch, no workers or resources requiring cleanup.；Bounded constructor-equivalent replicas omit network and execution goroutine startup.；Real SendMsg/Marshal and New/Unmarshal operate over per-link byte buffers.；A decoded PreAcceptReply is held pending while a later Prepare on a different message-type channel is dispatched.；Recovery entry is invoked for a known unresolved slot instead of waiting for the scanner timer.
固定比较 `prepare_vballot`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| origin | 1 |
| instance | 0 |
| acceptor | 1 |
| recipient | 2 |
| request_ballot | 5 |
| completed | true |
| decoded_vballot | 0 |
| sent.producer_vballot | 1 |
| sent.emitted | true |
| decoded_status | 1 |
| event | prepare_decoded |
| seq | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="issue-c1ed709a89224ed2aa4ed4b56ad7e25b"></a>
[争议 c1ed709a89224ed2aa4ed4b56ad7e25b](#issue-c1ed709a89224ed2aa4ed4b56ad7e25b)（继续核对）；对象 `11ad458fb92b4f9ba03f0760f37a2a7f` v1：F_history: The broad acceptance-history question must not assume that the Prepare wire path transmits local vbal. The producer constructs it but the codec omits it; downstream outcome attribution needs this independent mechanism.;…
[完整争议与来源](state.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Original coordinators propose a per-row instance and aggregate matching-ballot preaccept support, then commit fast or send Accept; a majority of matching Accept replies commits. Full commits propagate the value to…
- 上下文／权威转换（原文导航摘录）：Per-instance bal rejects old requests and is raised by Prepare. Local vbal and Status describe retained value history. Recovery resets bookkeeping and prepares a derived ballot; Prepare constructs a report from the…
- 两条主线的连接（原文导航摘录）：Formation writes a local command/phase/value-ballot tuple. Prepare constructs a report of that tuple and recovery consumes its decoded form to choose formation continuation. The transport boundary matters: Status is…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.95 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 14.38 分钟 · 实际执行：Accept 已确认，恢复回复仍报告预接受状态；执行完成；比较见 assessment。[执行记录](logs/60e27f33b9834b7d87fa2fe866557a2e/check.json)

- 18.28 分钟 · 受理 review：Accept 已确认，恢复回复仍报告预接受状态；v1 checker_correspondence: no_issue_found。[完整交接](submissions/622b1d6ceca445aa9c8b623353c4329b/accepted.json)

- 24.29 分钟 · 受理 check：Fix a producer-derived nonzero-value-ballot transport check and correct the map at this related handoff.。[完整交接](submissions/5a2b2f345fc443bcb65aca976b19061d/accepted.json)

- 24.42 分钟 · 实际执行：PrepareReply 在线路传输中丢失 value ballot；执行完成；比较见 assessment。[执行记录](logs/0485c6c015bc4645a45e0f815f23a3f0/check.json)

- 27.72 分钟 · 受理 review：PrepareReply 在线路传输中丢失 value ballot；v1 checker_correspondence: no_issue_found。[完整交接](submissions/082a059d9fad492e84491c333cb7ea05/accepted.json)

- 28.65 分钟 · 受理 review：Accept 已确认，恢复回复仍报告预接受状态；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/8325cd5300cb4824af9fcb9d43810baa/accepted.json)

- 30.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/9912167fd18b46bd9afc2cc3b6aabc42/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [c1ed709a89224ed2aa4ed4b56ad7e25b](research.json)：[争议 c1ed709a89224ed2aa4ed4b56ad7e25b](#issue-c1ed709a89224ed2aa4ed4b56ad7e25b)（继续核对）

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Acknowledged acceptance can retain PREACCEPTED_EQ in the subsequent report; downstream recovery-choice consequences remain open.；PrepareReply wire value-ballot preservation is now a separate sourced…
  尚无精确对应交接。

- B_propose：Whether foreign-row restart is supported with durable mode and its metadata lookup.
  尚无精确对应交接。

- B_preaccept：Foreign-row missing-command indexing and effect of an Accept that did not advance Status.
  尚无精确对应交接。

- B_aggregate：Reply counting has no sender field in PreAcceptReply/AcceptReply; repeated-round and transport premises need investigation.；Higher AcceptReply nack branch follows an inequality return and is…
  尚无精确对应交接。

- B_accept：Whether the established phase-reporting defect leads to a different recovery choice, considering other participants and independent ballot mechanisms.
  相关交接：[交接 1](submissions/622b1d6ceca445aa9c8b623353c4329b/accepted.json)

- B_commit：Interaction of delayed decisions with a higher promise and recovery propagation.
  尚无精确对应交接。

- B_recover：Fresh self VBallot may outrank previously accepted remote values.；Identical conditions for subcases 3 and 4 appear to make TryPreAccept branch unreachable.；Committed recovery assignment does not call…
  尚无精确对应交接。

- B_try：Reachability from current prepare selection; request success does not visibly assign vbal.
  尚无精确对应交接。

- B_execute：Same-row tie ordering uses local proposeTime; whether such SCC ties are reachable.；Shared-field synchronization is not comprehensively established.
  尚无精确对应交接。

- B_membership：Supported even/small membership constraints not established.；No EPaxos demotion callback was found in the read master path.
  尚无精确对应交接。

- B_transport：Reconnect/retransmit responsibilities beyond read path remain unestablished.
  尚无精确对应交接。

- B_persist：Whether durable mode has any supported initialization/reconstruction caller.
  尚无精确对应交接。

- B_client：Retry and exactly-once contract not established; client implementation not yet traced.
  尚无精确对应交接。

- B_prepare_wire：Does a producer-established nonzero local value ballot survive the actual encode/decode path in a fixed execution?
  尚无精确对应交接。

- F_history：Whether local phase/value-ballot reports preserve accepted-value constraints across a legal recovery history.
  相关交接：[交接 1](submissions/622b1d6ceca445aa9c8b623353c4329b/accepted.json)

- surface:Replica.handleAccept：Accept changes attributes and acknowledges its ballot without assigning ACCEPTED; recovery branches on the unchanged phase.
  尚无精确对应交接。

- surface:Replica.startRecoveryForInstance：The newly raised local vbal enters self PrepareReply before any remote support and can influence highest-value-ballot selection.
  尚无精确对应交接。

- surface:Replica.recordInstanceMetadata：Both ballots serialize at the same offset, but default deployment disables durable mode and reconstruction applicability is unresolved.
  尚无精确对应交接。

- surface:Replica.handlePrepareReply：Committed installation lacks conflict/prefix maintenance; identical subcase 3/4 conditions and tie replacement require further investigation.
  尚无精确对应交接。

- surface:Replica.updateAttributes：Dependency indexing is by a single command key whereas state.Conflict recognizes scan ranges; SCAN caller applicability remains unread.
  尚无精确对应交接。

- surface:Exec.nodeArray.Less：Local proposeTime is a same-row tie breaker; reachability of divergent equal-sequence SCC ordering is unresolved.
  尚无精确对应交接。

- surface:Client retry behavior：Retry TODO is sourced, but actual client retry policy and contract remain unread.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 2 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、33 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.09 | 0.00 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 3 | 7 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 14.71 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 15.29 秒。

目标执行组成：正式检查 2 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/9912167fd18b46bd9afc2cc3b6aabc42/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`80.78576919199986`（配置值不表示触发了超时）。
[调用记录](logs/9912167fd18b46bd9afc2cc3b6aabc42/check.json)；[stdout](logs/9912167fd18b46bd9afc2cc3b6aabc42/stdout.log)；[stderr](logs/9912167fd18b46bd9afc2cc3b6aabc42/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

