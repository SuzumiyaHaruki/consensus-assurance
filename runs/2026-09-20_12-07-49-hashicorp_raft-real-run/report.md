# 共识义务驱动局部审计报告

运行标识：`04b04265fe6f4887bea3eb4e2bb8456d`；模式：**真实工具运行**。

问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。

分析入口：`autonomous`。regression 表示预设开发回归，不能计为自主发现验收。


## 义务与有界审计结论
尚无已受理的有界审计问题或结论。

## 本次流程进度

工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。

| 阶段 | 已记录的进度 |
| --- | --- |
| 材料阅读 | 已完成首轮阅读；保存 25 个片段 |
| 义务与代码关系 | 发现结果已被工作流接受；当前图有 0 项主张、0 个审计单元 |
| 直接实现检查 | 已保存 0 个制品；完成 0 次执行；不等于整体性质成立 |
| 局部模型 | 已保存 0 个模型版本；保存不代表检查通过 |
| 轨迹校准 | 0 条校准记录；不等同于性质判定 |
| 模型搜索 | 0 次执行记录；逐项结果见下方，未执行不计通过 |
| 性质证据 | 0 条直接证据；范围与层级见证据记录 |

若 agent 回复完成而目标发现仍未被接受，不能把该回复视为已成立的关系图。历史记录未保存具体拒绝原因时，报告不补造原因。

## 分析输入与探索范围

仓库：`/home/nitro/Desktop/hashicorp-raft`
提交：`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；分支：`detached / unavailable`；脏工作区：`False`。
快照：`20fa957a41394ac4bdb318eceb1da537`，纳入 88 个文件；读取 25 个材料片段，仍有未读范围的文件 84 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。
候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。

## 义务与选择依据

领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考：
- `configured_reference`：未提供协议参考清单
定向补读：Read material；关联 []；实际新增片段 ['README.md:1:80', 'docs/README.md:1:80', 'api.go:1:80', 'transport.go:1:80', 'raft.go:1:80', 'log.go:1:80', 'config.go:1:80', 'fsm.go:1:80']。
定向补读：Prioritize breadth across all seven responsibility coordinates, then inspect one concrete persistence adapter. These eight ranges contain 1,010 previously unread lines and avoid all supplied cached intervals. A provisional estimate of 45 characters per line gives approximately 45,450 unique characters, below the 52,933-character allowance; exact source accounting must preflight the batch and defer lower-priority ranges if necessary. Documentation and interface comments supply attributed expectations; requested implementations supply behavior observations. Neither establishes correctness alone.；关联 []；实际新增片段 ['api.go:800:899', 'commitment.go:1:104', 'raft.go:285:441', 'raft.go:1203:1291', 'fsm.go:81:240', 'raft.go:1814:1955', 'snapshot.go:125:278', 'file_snapshot.go:397:500']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['api.go:850:925', 'raft.go:950:1035']。
定向补读：When snapshot persistence uses FileSnapshotSink, can takeSnapshot consume a nil result from a repeated Close after an earlier finalization failure as successful snapshot publication, or do the Persist contract and caller error handling prevent that interpretation?；关联 ['F5', 'B8', 'B9']；实际新增片段 ['snapshot.go:1:278']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['raft.go:1900:2241', 'state.go:1:174']。
定向补读：The question's source_ids contain field names rather than acquired material IDs. Consumer source raft.go:285:441 is supplied; producer source raft.go:1900:2241 is explicitly omitted. Acquire that exact missing range before repairing the question's source attribution and reassessing its unresolved discriminator. Preserve the selected Fact, consumption lifecycle, and existing counterarguments.；关联 ['campaign_vote_result', 'candidate_campaign_control', 'election_setup_and_self_vote', 'remote_vote_result']；实际新增片段 []。
定向补读：When runCandidate consumes campaign_vote_result, can a delayed result from a superseded election contribute to entering the leader role, or do invocation-specific channels and term handling restrict counted grants to the active election?；关联 ['campaign_vote_result', 'candidate_campaign_control', 'election_setup_and_self_vote', 'remote_vote_result']；实际新增片段 []。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['raft.go:1:100', 'transport.go:1:141', 'api.go:500:680']。
定向补读：For a command handled by applySingle with an attached future, does the documented caller sequence for awaiting successful completion and reading Response reliably consume the response established by F4? The discriminator is whether completion synchronization publishes that same future's assigned FSM response before the permitted caller read, or whether a permitted read can observe an unset or unrelated response.；关联 ['F4', 'B1', 'B6']；实际新增片段 ['future.go:1:180']。

## 候选问题与已有保护

候选解释是有来源的分析判断，不是性质证据或协议正确性证明。
候选受阻分类：evidence_blocked=1；workflow_blocked=0；resource_blocked=1
候选因证据/适用合同不足延期；未解释关闭，未确认缺陷，不是性质证据。
- 候选 `ac2179e4559d4eb49e9e02a9fbf82982`：Fact ['F5']；生命周期 consumption；状态 blocked / needs_specific_evidence；受阻分类 evidence_blocked。
  问题：Can an applicable FSMSnapshot.Persist implementation return nil after FileSnapshotSink.Close fails, allowing takeSnapshot to consume the repeated Close's nil result as completion and proceed to log compaction?；意义：Reclaiming logs after unsuccessful snapshot publication could leave restart recovery without necessary state or history. The supplied code establishes a conditional path to compaction, but neither an admissible callback execution nor actual recovery loss.。
  适用上下文：['Snapshot creation using the built-in file snapshot store', "An initial Close fails after setting the sink's closed flag", 'A subsequent Close on the same sink returns nil', 'Application callback error handling and its contractual admissibility remain unverified']；事件路径：['FileSnapshotSink.Close sets closed before fallible finalization and publication; a subsequent Close returns nil without retrying those operations.', 'If Persist propagates the initial Close error, takeSnapshot calls Cancel and returns before its own Close, metadata update, or compaction.', "If Persist instead returns nil, takeSnapshot's subsequent Close returns nil, allowing last-snapshot metadata update and compactLogs invocation.", 'If the first failing Close occurs in takeSnapshot itself, its error check prevents the metadata update and compaction.', 'Log deletion additionally requires a nonempty range permitted by the snapshot index and trailing-log retention, and successful DeleteRange execution.']；来源：['file_snapshot.go:397:500', 'fsm.go:1:80', 'snapshot.go:1:278']。
  已有保护/反证：['FSMSnapshot.Persist documentation assigns the callback responsibility for writing necessary state and calling Close when finished or Cancel on error; SnapshotSink documentation likewise assigns completion and cancellation to the FSM.', "takeSnapshot checks Persist's error before its own Close. Propagation of the initial Close failure prevents the proposed path to compaction.", 'takeSnapshot checks its own Close result before updating last-snapshot metadata or invoking compaction.', 'F5 establishes an in-memory closed flag and subsequent nil-return behavior, not successful publication.', 'Compaction preserves configured trailing logs and does not delete beyond the supplied snapshot index; reaching compaction alone does not demonstrate loss of necessary recovery history.', 'Directory synchronization and reaping failures can occur after rename, so a Close error alone does not establish snapshot unavailability.']；剩余判别与限制：['Which application-selected FSMSnapshot.Persist implementation is applicable and whether it propagates, suppresses, or retries a sink Close failure.', "Whether the applicable callback contract requires propagating Close failures through Persist's return value; the attached comments specify Close/Cancel ownership without expressly settling this requirement.", 'Whether returning nil after failed completion is an admissible execution within the intended library guarantee or violates an application responsibility.', 'The filesystem failure point, snapshot discoverability, older retained snapshots, and remaining logs necessary to establish a recovery consequence.']。
  选择/缩窄依据：Source review resolves the consumer discriminator: Persist and takeSnapshot's subsequent Close must both return nil before metadata update and compaction. Propagating the initial failure prevents that path. The remaining discriminator concerns applicable callback behavior and responsibility, which the supplied sources do not resolve.；历史问题版本：2。
  升级义务：未生成；候选结论或受阻原因：Retain the selected F5 consumption question as evidence-blocked. The acquired receipt is complete, and the supplied code establishes the conditional control flow and its error-propagation protection. Responsibility for reporting an initial sink Close failure through Persist remains unattributed. No supplied source identifies the selected callback implementation or an exact repository range that settles its applicable return-value contract. An arbitrary example callback or injected callback that suppresses errors would not establish admissibility. Further publication and recovery reads could characterize consequences but would not resolve this prerequisite. No obligation or executable check is justified from the current evidence; this disposition establishes neither an explanation nor a defect.。
- 候选 `fb1a27032fce4da48b6ef4793b71f912`：Fact ['campaign_vote_result']；生命周期 consumption；状态 explained / explained_by_existing_mechanism；受阻分类 无。
  问题：Can a delayed campaign_vote_result produced for a completed runCandidate invocation enter a later invocation's election tally?；意义：Counting support from a superseded election could establish local leadership without support for the current election context. The reviewed channel mechanism addresses cross-invocation tally contamination; broader leadership guarantees remain outside this conclusion.。
  适用上下文：['Delayed worker completion after election timeout', 'Candidate-loop exit followed by a new invocation', 'Direct election or election following successful pre-vote']；事件路径：['electSelf allocates channel -> worker captures that channel -> runCandidate returns -> later invocation allocates a different channel -> old worker sends only to its captured channel']；来源：['raft.go:285:441', 'raft.go:1900:2241']。
  已有保护/反证：["Every electSelf call allocates a fresh respCh. Each remote worker closes over that call's channel and request, and sends its result once to that channel.", 'runCandidate keeps voteCh and grantedVotes in invocation-local variables. Its election-timeout branch returns, so subsequent invocations do not inherit the prior channel or tally.', 'The pre-vote success branch disables prevoteCh before calling electSelf. The shown invocation therefore does not repeatedly replace its election channel while retaining accumulated vote grants.', 'A higher-term vote response causes a follower transition and return before grant counting. A role change observed at the next loop guard ends candidate processing.', 'Transport errors are converted to refusals. A self-vote persistence error returns a nil channel, which prevents that caller from consuming even results already produced on the abandoned channel.', 'The tally checks for higher response terms but does not require term equality. Channel isolation explains the selected cross-invocation delay scenario without establishing the semantics of every response received through the active transport call.']；剩余判别与限制：['Transport response correlation and remote voting semantics remain unread; channel isolation does not establish that a successful transport call returns support for its captured request.', 'Effects of processRPC on the term and role within a still-running candidate invocation remain unread. This conclusion does not establish that every counted grant matches the current term after such processing.', 'Quorum calculation, configuration identity uniqueness, dispatcher behavior, and completed leader initialization remain outside the attached evidence.']。
  选择/缩窄依据：Source review resolved the selected delayed-worker discriminator: producer closures retain their original channels, while subsequent candidate invocations have fresh channels and counters. This is a scoped mechanism explanation, not evidence of overall election correctness.；历史问题版本：1。
  升级义务：未生成；候选结论或受阻原因：The acquired producer and consumer declarations explain why delayed results from a completed invocation cannot enter a later invocation's tally through the shown channels. No obligation or executable check is needed for that suspicion. The conclusion is restricted to channel ownership across invocations; transport correlation and changes of protocol context within an invocation remain explicit gaps. The accepted inventory already represents these mechanisms and unknowns, so this review identifies no descriptive correction.。
- 候选 `86c45c1ac6074cbea5ca95e3ccd56f0d`：Fact ['F4']；生命周期 consumption；状态 active / explained_by_existing_mechanism；受阻分类 resource_blocked。
  问题：For F4's normally returning command application, how is the attached future's FSM response published to a caller that waits for its completion before calling Response? The local publication discriminator is resolved by response assignment followed by channel synchronization; end-to-end dispatch identity and competing completion ownership remain outside this explanation.；意义：A caller may use an operation's returned response to decide subsequent actions. Publishing completion before its associated response could expose an incorrect result despite the FSM callback having run.。
  适用上下文：['Single-entry command application with an attached initialized future', 'Normal FSM.Apply return', 'Completion received from this application path', 'Caller invokes Response after Error returns and does not call Error concurrently on the same future']；事件路径：["FSM.Apply returns -> applySingle assigns req.future.response -> respond sends completion and closes errCh -> Error receives completion -> Response reads the same future's response field"]；来源：['fsm.go:81:240', 'future.go:1:180', 'api.go:800:899']。
  已有保护/反证：['future.go:1:180 explicitly requires Response to be called only after Error returns and prohibits concurrent Error calls on the same future.', 'fsm.go:81:240 assigns the normally returned FSM.Apply value to req.future.response before invoking req.future.respond(nil). Both accesses use the same attached future.', 'future.go:1:180 shows respond sending on errCh and then closing it, while Error receives from errCh. Under Go channel synchronization semantics, the preceding response assignment is published to the receiving caller. Sequential repeated successful Error calls receive from the closed channel.', 'future.go:1:180 shows logFuture.Response returning its response field directly; an FSM-returned error remains that response rather than becoming the Raft completion error.', 'api.go:800:899 initializes a distinct command future and returns the same pointer sent to applyCh. Immediate enqueue or shutdown failures instead return errorFuture.']；剩余判别与限制：['The unread protocol-to-FSM dispatch path has not established that the future returned by ApplyLog is always the future attached to the corresponding command tuple.', 'Ownership and ordering of competing completion paths remain unread. The responded flag suppresses repeated responses but is not itself evidence of synchronization between concurrent producers.', 'This explanation does not establish response validity after an earlier error completion, callback panic, later mutation of application-owned response objects, or snapshot restoration.']。
  选择/缩窄依据：The acquired future implementation resolves the selected local visibility suspicion: completion from applySingle follows response assignment and supplies a synchronization boundary. This is a scoped source explanation, not execution evidence or an end-to-end completion guarantee.；历史问题版本：1。
  升级义务：未生成；候选结论或受阻原因：继续获取证据。

## 描述性理解演化

AuditSpec：v1 → v5；Behavior：10 → 27；Fact：5 → 11。
Surface 扩展任务：planned=3 / prepared=3 / sent=3 / semantic_result=3 / accepted=3；深度分析反馈任务：2（完成 1）。这些是描述性进度，不是正确性覆盖率。
- 扩展 ['Raft.Barrier / VerifyLeader / GetConfiguration']：completed；Expand one source-grounded implementation surface
- 扩展 ['Raft.runCandidate, electSelf, preElectSelf, and authority setters']：completed；Expand one source-grounded implementation surface
- 扩展 ['Raft.checkRPCHeader / Transport heartbeat dispatch']：completed；Expand one source-grounded implementation surface
- 高后果 Surface `surface:Raft.Apply / ApplyLog`：mapped；Maps enqueue semantics; downstream completion remains partial.
- 高后果 Surface `surface:Raft.runCandidate, electSelf, preElectSelf, and authority setters`：mapped；Maps the supplied main-thread orchestration and local setter semantics. Independent workers and persistence are separated below; mapping does not establish completed leader initialization.
- 高后果 Surface `surface:Raft.checkRPCHeader / Transport heartbeat dispatch`：deferred；NewRaft assigns trans.Consumer() to rpcCh and registers r.processHeartbeat through SetHeartbeatHandler before the skipStartup branch and background startup. The interface permits callback support or Consumer fallback. The processHeartbeat body, ordinary dispatch call sites, and concrete transport classification and callback execution remain unread, so validation enforcement and concurrent processing cannot yet be mapped.
- 高后果 Surface `surface:Raft.dispatchLogs / commitment.match / commitment.setConfiguration`：mapped；Local storage and report aggregation are mapped without asserting durable remote support.
- 高后果 Surface `surface:Raft.appendConfigurationEntry`：mapped；Visible dispatch and configuration replacement are mapped; admission and validation remain unresolved.
- 高后果 Surface `surface:Replication workers, AppendEntries handler, and processLogs`：deferred；These paths must establish follower support and the transition from commitment to queued FSM work; adjacent known endpoints do not resolve them.
- 高后果 Surface `surface:runFSM application closures`：mapped；Maps callback filtering and response association; queue ordering requires the remaining loop.
- 高后果 Surface `surface:runFSM snapshot and restore closures / fsmRestoreAndMeasure`：deferred；Closure bodies are partially supplied, but dispatch and the restore helper are needed before establishing capture or restore completion facts.
- 高后果 Surface `surface:Client FSM and FSMSnapshot callback implementations`：externalized；Application-specific callback implementations are outside the supplied library boundary; library scheduling and callback-result interpretation remain in scope.
- 高后果 Surface `surface:Raft.takeSnapshot / compactLogsWithTrailing / removeOldLogs`：mapped；Maps snapshot orchestration and its bounded deletion helper behavior; snapshot publication and recovery remain unresolved.
- 高后果 Surface `surface:FileSnapshotSink.Close`：mapped；Maps closed-state handling and fallible publication sequence without equating nil return with recoverability.
- 高后果 Surface `surface:File snapshot Create / Open / List / ReapSnapshots / writeMeta / Cancel`：deferred；High-consequence frontier for snapshot discoverability, first-close failure handling, retention, and recovery. Cancel is visible but needs its own lifecycle mapping.
- 高后果 Surface `surface:Raft.installSnapshot`：mapped；Maps receive, Close, restore wait, metadata changes, cleanup attempts, and RPC success ordering.
- 高后果 Surface `surface:Startup reconstruction, BootstrapCluster, user Restore, and constructor adapter selection`：deferred；Documented operations and observed injected fields establish a relevant frontier, but the actual entry-point implementations and startup selection are unread.
- 高后果 Surface `surface:Built-in storage and transport variants listed in the catalogue`：deferred；Catalogue paths are navigation hints. Concrete implementations and active variants must be read before assigning persistence or transport guarantees.
- 高后果 Surface `surface:Raft.Barrier`：mapped；API request construction and enqueue alternatives are sourced; execution and completion remain separately deferred.
- 高后果 Surface `surface:Raft.VerifyLeader`：mapped；API admission is sourced; verifyCh dispatch and asynchronous completion remain deferred.
- 高后果 Surface `surface:Raft.verifyLeader`：mapped；Separately maps immediate response and support-registration branches without inferring successful remote support.
- 高后果 Surface `surface:Raft.GetConfiguration`：mapped；Response construction is sourced; helper publication and future accessor semantics remain deferred.
- 高后果 Surface `surface:Raft.Barrier applyCh consumption and future completion`：deferred；Need the applyCh consumers and subsequent LogBarrier processing to determine rejection, ordering, and completion relative to FSM effects.
- 高后果 Surface `surface:Raft.VerifyLeader verifyCh dispatch and replication support completion`：deferred；Need verifyCh consumers, quorumSize, replication notification processing, and verifyFuture methods to recover support identity and completion semantics.
- 高后果 Surface `surface:Raft.GetConfiguration latest-configuration publication and future accessors`：deferred；Need getLatestConfiguration, its publishers, and configurationsFuture methods to establish the meaning and ownership of the returned representation.
- 高后果 Surface `surface:Raft.runSnapshots timer branch / Raft.shouldSnapshot`：mapped；Maps acquired timer filtering and synchronous snapshot invocation; timer implementation and restore interactions remain unresolved.
- 高后果 Surface `surface:Raft.runSnapshots userSnapshotCh branch`：mapped；Maps receipt, invocation, conditional opener assignment, and response. Public API production and future consumption remain unread.
- 高后果 Surface `surface:Raft.electSelf.askPeer goroutine`：mapped；Independent remote vote producer with explicit transport-error normalization.
- 高后果 Surface `surface:Raft.preElectSelf.askPeer goroutine`：mapped；Independent pre-vote result producer, including the compatibility-generated grant branch.
- 高后果 Surface `surface:Raft.persistVote`：mapped；Sequential store-call outcomes are mapped without claiming atomic or durable vote recovery.
- 高后果 Surface `surface:Raft.setLeader and post-candidate leader initialization`：deferred；The candidate calls are visible, but setLeader and role dispatch/leader initialization declarations are not attached. Local Leader publication cannot be equated with completed readiness.
- 高后果 Surface `surface:Raft.checkRPCHeader`：mapped；The supplied complete helper supports a local validation behavior and invocation-scoped success fact. Dispatch enforcement remains separate.

## 实现理解（支持信息）

| Activity | 适用性 | 义务 | 证据 | 未知 |
| --- | --- | --- | --- | --- |
| A1 | applicable | [] | [] | ['Follower match producers and commit notification consumers are unread.', 'Reported support is not independently established as durable replication.'] |
| A2 | applicable | [] | [] | ['The dispatch loop, leader initialization, setLeader implementation, and inbound vote handlers are not attached.', 'quorumSize implementation and configuration validation are not attached.', 'Transport selection and StableStore crash/error semantics remain unresolved.'] |
| A3 | applicable | [] | [] | ['Incremental resynchronization, startup replay, snapshot selection, and the restore helper are unread.'] |
| A4 | applicable | [] | [] | ['nextConfiguration validation, admission serialization, committed configuration advancement, and removal handling are unread.'] |
| A5 | applicable | [] | [] | ['The queue dispatch tail and processLogs producer are unread.', 'The supplied code does not independently establish that every received tuple is committed.'] |
| A6 | applicable | [] | [] | ['File snapshot creation, metadata writes, listing, opening, reaping, and startup selection require reading.', 'A sink Close result alone has not been mapped to crash-recoverable publication.'] |
| A7 | applicable | [] | [] | ['Future synchronization, leader-side rejection, restore abortion, VerifyLeader completion, and retry identity are unread.', 'No deduplication guarantee is established.'] |
未解释责任：Raft.checkRPCHeader / Transport heartbeat dispatch；NewRaft assigns trans.Consumer() to rpcCh and registers r.processHeartbeat through SetHeartbeatHandler before the skipStartup branch and background startup. The interface permits callback support or Consumer fallback. The processHeartbeat body, ordinary dispatch call sites, and concrete transport classification and callback execution remain unread, so validation enforcement and concurrent processing cannot yet be mapped.
未解释责任：Replication workers, AppendEntries handler, and processLogs；These paths must establish follower support and the transition from commitment to queued FSM work; adjacent known endpoints do not resolve them.
未解释责任：runFSM snapshot and restore closures / fsmRestoreAndMeasure；Closure bodies are partially supplied, but dispatch and the restore helper are needed before establishing capture or restore completion facts.
未解释责任：File snapshot Create / Open / List / ReapSnapshots / writeMeta / Cancel；High-consequence frontier for snapshot discoverability, first-close failure handling, retention, and recovery. Cancel is visible but needs its own lifecycle mapping.
未解释责任：Startup reconstruction, BootstrapCluster, user Restore, and constructor adapter selection；Documented operations and observed injected fields establish a relevant frontier, but the actual entry-point implementations and startup selection are unread.
未解释责任：Built-in storage and transport variants listed in the catalogue；Catalogue paths are navigation hints. Concrete implementations and active variants must be read before assigning persistence or transport guarantees.
未解释责任：Raft.Barrier applyCh consumption and future completion；Need the applyCh consumers and subsequent LogBarrier processing to determine rejection, ordering, and completion relative to FSM effects.
未解释责任：Raft.VerifyLeader verifyCh dispatch and replication support completion；Need verifyCh consumers, quorumSize, replication notification processing, and verifyFuture methods to recover support identity and completion semantics.
未解释责任：Raft.GetConfiguration latest-configuration publication and future accessors；Need getLatestConfiguration, its publishers, and configurationsFuture methods to establish the meaning and ownership of the returned representation.
未解释责任：Raft.setLeader and post-candidate leader initialization；The candidate calls are visible, but setLeader and role dispatch/leader initialization declarations are not attached. Local Leader publication cannot be equated with completed readiness.

| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |
| --- | --- | --- | --- |
| `9e2b1259` | 扩展职责/交接覆盖 | pending/read | Resolve decisive understanding gaps； |
| `bd32357e` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `14ddc43e` | 扩展职责/交接覆盖 | completed/done | B9 still records timer and public API callers as unread. The acquired runSnapshots implementation now identifies the snapshot goroutine's randomized timer branch with shouldSnapshot filtering, its userSnapshotCh branch, and shutdown handling. These are reusable trigger and execution-owner details missing from the inventory. The user-request branch also publishes an opener only after takeSnapshot succeeds and responds with the returned error; the public API producer of userSnapshotCh remains unread.； |
| `3fec3fd7` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `64dad393` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `fc5b0c3c` | 扩展职责/交接覆盖 | running/analyze | The inventory omits the now-observed caller-side consumer: Error receives completion through errCh, after which Response reads the attached logFuture.response. Add this consumption behavior with the documented caller ordering and nonconcurrent Error restriction, preserving the distinction between an FSM response that contains an error and a Raft completion error. Do not infer upstream tuple identity or exclusive completion ownership.； |

| 复核对象/版本 | 层面 | 判断 | 材料与推导 |
| --- | --- | --- | --- |
尚无已执行的语义复核；有来源的候选不因此变成已确认规范。

职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。

## 未受理草稿分析
尚未完成自主义务发现；未补入预置义务。

## 候选修复会话

原始候选、当前版本、修复 patch 与问题计数分开保存；调用完成不等于候选或语义已接受。
会话 `d59d240f4b4c48ff989513a7a061c06b`：accepted；候选版本 1；修复调用 1；原始候选 [original.json](repair-sessions/d59d240f4b4c48ff989513a7a061c06b/original.json)；当前候选 [candidate-1.json](repair-sessions/d59d240f4b4c48ff989513a7a061c06b/candidate-1.json)；问题 。
诊断及材料：[]；重复失败：{}；显式范围/语义计划：无。
会话 `578cae009af24135b8cce6b9a1d81e87`：accepted；候选版本 1；修复调用 2；原始候选 [original.json](repair-sessions/578cae009af24135b8cce6b9a1d81e87/original.json)；当前候选 [candidate-1.json](repair-sessions/578cae009af24135b8cce6b9a1d81e87/candidate-1.json)；问题 。
诊断及材料：[]；重复失败：{}；显式范围/语义计划：无。
会话 `131e4c88d620482f98b77269c64cc863`：accepted；候选版本 1；修复调用 1；原始候选 [original.json](repair-sessions/131e4c88d620482f98b77269c64cc863/original.json)；当前候选 [candidate-1.json](repair-sessions/131e4c88d620482f98b77269c64cc863/candidate-1.json)；问题 。
诊断及材料：[]；重复失败：{}；显式范围/语义计划：无。

## 实验能力与执行

| 能力 | 状态 | 执行依据 |
| --- | --- | --- |
| package_tests | probe_confirmed | c28b7173d5e34c3b9ca8a713853553e5：Package build and selected existing tests; not a full suite or scheduling probe |
| precise_schedule_replay | unavailable | 无执行确认：No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites |

默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。

| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |
| --- | --- | --- | --- | --- |
| Codex 版本检查：agent_probe `d104559b` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/d104559bdef54721922bbfd85c6c0e1e/stdout.log) / [stderr.log](logs/d104559bdef54721922bbfd85c6c0e1e/stderr.log) |
| Codex 参数检查：agent_capabilities `629f88c0` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/629f88c0e8444c61866b1e20f7a64c3f/stdout.log) / [stderr.log](logs/629f88c0e8444c61866b1e20f7a64c3f/stderr.log) |
| Java 版本检查：java_probe `15b337ac` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/15b337ac29c448c7a6d929b0b7e2e3ce/stdout.log) / [stderr.log](logs/15b337ac29c448c7a6d929b0b7e2e3ce/stderr.log) |
| 验证工具启动检查：verifier_probe `a1ed2bb2` | 正常完成 | 版本帮助已识别，工具可用；命令退出码 1 | 不适用：未检查性质 | [stdout.log](logs/a1ed2bb260944a19aec9b648691f3842/stdout.log) / [stderr.log](logs/a1ed2bb260944a19aec9b648691f3842/stderr.log) |
| 目标工具链版本检查：implementation_tool_probe `16f76721` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/16f76721feef4afb9683c722c2b9e349/stdout.log) / [stderr.log](logs/16f76721feef4afb9683c722c2b9e349/stderr.log) |
| 现有测试与实验能力探测：capability_probe `c28b7173` | 正常完成 | 所执行测试通过 | 仅限实际测试覆盖；不自动证明目标或确认违反 | [stdout.log](logs/c28b7173d5e34c3b9ca8a713853553e5/stdout.log) / [stderr.log](logs/c28b7173d5e34c3b9ca8a713853553e5/stderr.log) |
| Agent 分析或修复：agent `38cf0028` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/38cf00287cc148aa9a95084b338423bd/stdout.log) / [stderr.log](logs/38cf00287cc148aa9a95084b338423bd/stderr.log) / [response.json](agent/34d25c11439547d5be7813c406e6208b-read/response.json) |
| Agent 分析或修复：agent `2550ebd4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/2550ebd4fd5f493cb1e1ca672eeeb40f/stdout.log) / [stderr.log](logs/2550ebd4fd5f493cb1e1ca672eeeb40f/stderr.log) / [response.json](agent/884d9d63d6d24254addffec14dde3f83-discover/response.json) |
| 职责覆盖探索：agent `f0d71e82` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/f0d71e82f4bd45e89a065a71baf6e197/stdout.log) / [stderr.log](logs/f0d71e82f4bd45e89a065a71baf6e197/stderr.log) / [response.json](agent/8c947578597746bd8b314dd456a6a293-spec_refine/response.json) |
| 职责覆盖探索：agent `c79ef528` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/c79ef528e2c549468937c0f9e4c8bdc9/stdout.log) / [stderr.log](logs/c79ef528e2c549468937c0f9e4c8bdc9/stderr.log) / [response.json](agent/d13bd0c69ab24a7cba5328566b3fadce-spec_refine/response.json) |
| Agent 分析或修复：agent `412c1954` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/412c1954cac94089aafe289b9fc314d4/stdout.log) / [stderr.log](logs/412c1954cac94089aafe289b9fc314d4/stderr.log) / [response.json](agent/5cc1a20d7afe42a58be16f59c4a17d18-derive/response.json) / [graph-validation-error.txt](agent/5cc1a20d7afe42a58be16f59c4a17d18-derive/graph-validation-error.txt) |
| Agent 分析或修复：agent `1817c33c` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/1817c33cf14e4002ab3fd9247df633e1/stdout.log) / [stderr.log](logs/1817c33cf14e4002ab3fd9247df633e1/stderr.log) / [response.json](agent/d329b9a623e541f3aa9d51131c911be3-derive/response.json) |
| Agent 分析或修复：agent `056800ea` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/056800eaa7e7438ba979df011eb28e52/stdout.log) / [stderr.log](logs/056800eaa7e7438ba979df011eb28e52/stderr.log) / [response.json](agent/f6fa9635796f4a4a8f9c438d1c82c828-derive/response.json) |
| 职责覆盖探索：agent `9e62ea4e` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/9e62ea4e6f854c78a3583dd8862877b7/stdout.log) / [stderr.log](logs/9e62ea4e6f854c78a3583dd8862877b7/stderr.log) / [response.json](agent/f298c93c087341668d73dfeac37df232-spec_refine/response.json) |
| Agent 分析或修复：agent `5ec73e3b` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/5ec73e3b20e64e2a85b8f5e96c0a73b2/stdout.log) / [stderr.log](logs/5ec73e3b20e64e2a85b8f5e96c0a73b2/stderr.log) / [response.json](agent/731616469c674872b649fb3865c84e2c-derive/response.json) |
| 职责覆盖探索：agent `de90fcf9` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/de90fcf98e1a449bade1a12b0c4d88bb/stdout.log) / [stderr.log](logs/de90fcf98e1a449bade1a12b0c4d88bb/stderr.log) / [response.json](agent/c7a75fcde5f040fa93ab2bd439d9bae4-spec_refine/response.json) |
| 职责覆盖探索：agent `8af772fb` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/8af772fbdc4f4d58a04e85e1903bf497/stdout.log) / [stderr.log](logs/8af772fbdc4f4d58a04e85e1903bf497/stderr.log) / [response.json](agent/39827c2ec9354cca9db8224188d03da7-spec_refine/response.json) |
| Agent 分析或修复：agent `2a109ea8` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/2a109ea88ba34dc3ba0ad73a156aabc9/stdout.log) / [stderr.log](logs/2a109ea88ba34dc3ba0ad73a156aabc9/stderr.log) / [response.json](agent/764331adb6a14f879e234f1076605db2-derive/response.json) / [graph-validation-error.txt](agent/764331adb6a14f879e234f1076605db2-derive/graph-validation-error.txt) |
| Agent 分析或修复：agent `00023f8c` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/00023f8c750b49c1942a3f8f96dfa52d/stdout.log) / [stderr.log](logs/00023f8c750b49c1942a3f8f96dfa52d/stderr.log) / [response.json](agent/b86bd2dca940400789c22ecc12eac45a-derive/response.json) |
| Agent 分析或修复：agent `69582fd6` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/69582fd6f2454d7d91b2b90f77964ef6/stdout.log) / [stderr.log](logs/69582fd6f2454d7d91b2b90f77964ef6/stderr.log) / [response.json](agent/b5becda08bc444748b21707cca8abfb1-derive/response.json) |
| Agent 分析或修复：agent `e176f0ae` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/e176f0ae972442688646e1b24e04363f/stdout.log) / [stderr.log](logs/e176f0ae972442688646e1b24e04363f/stderr.log) / [response.json](agent/7777306b358d4c77bc16a17fcfd4b429-derive/response.json) |
| 职责覆盖探索：agent `2e50cbb4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/2e50cbb49a73479996889a4ba5f0afcf/stdout.log) / [stderr.log](logs/2e50cbb49a73479996889a4ba5f0afcf/stderr.log) / [response.json](agent/a19cc32653f9489f97ae9eb40c7d75a7-spec_refine/response.json) |
| 职责覆盖探索：agent `969411fa` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/969411fa3fdd4cb792a60736ae60ffe0/stdout.log) / [stderr.log](logs/969411fa3fdd4cb792a60736ae60ffe0/stderr.log) / [response.json](agent/1953e2d64bd24953af4c86f2f44af17b-spec_refine/response.json) |
| Agent 分析或修复：agent `3f0bcd65` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/3f0bcd659e57483a85b1c0a9c7b650c1/stdout.log) / [stderr.log](logs/3f0bcd659e57483a85b1c0a9c7b650c1/stderr.log) / [response.json](agent/108a210748434191a0f1a98040a01366-derive/response.json) / [graph-validation-error.txt](agent/108a210748434191a0f1a98040a01366-derive/graph-validation-error.txt) |
| Agent 分析或修复：agent `3cbe178c` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/3cbe178c05a94d50830cfb3bbb40e01b/stdout.log) / [stderr.log](logs/3cbe178c05a94d50830cfb3bbb40e01b/stderr.log) / [response.json](agent/17a47db585544fb884c33b6010ffadc9-derive/response.json) |
| Agent 分析或修复：agent `eb2a72cb` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/eb2a72cbdd8f4899a167dd35e7708d7d/stdout.log) / [stderr.log](logs/eb2a72cbdd8f4899a167dd35e7708d7d/stderr.log) / [response.json](agent/c0cb7f9843da4391a1ff434fe02bc96e-derive/response.json) |

逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）：

## 模型、校准与证据范围

尚未生成并执行局部模型；没有模型层检查结论。

## 候选发现与 F1—F4

本次尚无记录的候选违反。这不代表实现没有缺陷。
本次没有实际应用的语义修订；工具错误不冒充 F1—F4。

## 未决事项与停止原因

停止原因（原文）：Budget exhausted: agent_calls
控制器格式：selected-question-v6；阶段：new_run。
恢复位置：探索/复核任务 `fc5b0c3c2e3547398ba25e5dd4778fd3`；单元 `None`，模型 `None`，反例 `None`，下一动作 `select`。
- Only the two attached source ranges support this delta.
- Mapped surfaces represent partial understanding, not complete coverage or verified guarantees.
- No obligation, calibrated observation, or correctness conclusion is established.
- This delta establishes descriptive control flow only, not snapshot recoverability or correctness.
- The applicable Persist implementation, admissibility of suppressing Close errors, and actual recovery consequences remain unresolved.
- Public API production, future consumption, and broader shutdown coordination are not established by the attached source.
- All judgments are descriptive observations of the attached code, not independently validated protocol guarantees.
- Inbound vote/pre-vote handlers, quorum calculation, configuration validation, transport implementations, storage variants, and startup recovery remain unread.
- The attached snapshot and configuration helper code is outside this focused expansion.
- No execution, calibration, reproduction, or overall correctness assessment was performed.
- The constructor comment requires the heartbeat callback to be safe concurrently with a blocking RPC; the supplied code does not demonstrate that safety.
- Exact declarations and bodies for processHeartbeat, ordinary RPC dispatch, and concrete transport heartbeat dispatch are needed to expand the deferred remainder.
- No normative obligation, execution result, or overall compatibility guarantee is established.
- Budget exhausted: agent_calls
- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。
- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。

## 实际运行统计

累计执行时间：1353.09 秒；预算计数：`{'experiments': 1, 'agent_calls': 20, 'exploration_rounds': 3, 'targeted_reads': 5}`。
首个已保存模型前耗时：尚无模型；模型仍须通过实际工具检查。
审计单元 0；范围扩展 0；语义修订 0；校准 0。
完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。


## 材料、上下文与实际产物

字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。
唯一材料 89218/120000 字符；区间并集 19/40。广度当前可分配 30782、为深度保留 0；深度可分配 30782、为广度保留 0。
建模类执行记录 0；受理且非空 Bundle 回复 0；落盘模型版本 0（仅模型阶段 0，完整组件 0）；实际性质搜索记录 0（触达与校准另列）。

| 阶段 | 新调用记录 | 已记录时长（秒） |
| --- | --- | --- |
| agent_probe | 1 | 0.02（1 条有起止时间） |
| agent_capabilities | 1 | 0.02（1 条有起止时间） |
| java_probe | 1 | 0.10（1 条有起止时间） |
| verifier_probe | 1 | 0.16（1 条有起止时间） |
| implementation_tool_probe | 1 | 0.01（1 条有起止时间） |
| capability_probe | 1 | 11.89（1 条有起止时间） |
| read | 1 | 41.53（1 条有起止时间） |
| discover | 1 | 283.49（1 条有起止时间） |
| spec_refine | 7 | 508.29（7 条有起止时间） |
| derive | 11 | 484.18（11 条有起止时间） |
缓存复用/重附加记录 8 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。

| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |
| --- | --- | --- | --- | --- |
| read/a418b3eb | accepted | 119046/119046 | 1294 | 0/0 |
| discover/d399c146 | accepted | 87528/87528 | 13645 | 0/0 |
| spec_refine/456da9ad | accepted | 27435/27435 | 14584 | 0/0 |
| spec_refine/1b7e2023 | accepted | 34333/34333 | 14584 | 0/0 |
| derive/738e483b | executed | 36575/36577 | 16361 | 0/0 |
| derive/1bc51feb | accepted | 30327/30329 | 20305 | 0/0 |
| derive/74dcb6b6 | accepted | 65429/65431 | 16361 | 0/0 |
| spec_refine/f764f40a | accepted | 65575/65575 | 14584 | 0/0 |
| derive/6021e6aa | accepted | 66638/66640 | 16361 | 0/0 |
| spec_refine/005b8b86 | accepted | 26765/26765 | 14584 | 0/0 |
| spec_refine/3caa059f | accepted | 50212/50212 | 14584 | 0/0 |
| derive/37dc8722 | executed | 43146/43148 | 16361 | 0/0 |
| derive/74db341a | executed | 34292/34294 | 20305 | 0/0 |
| derive/a86f636b | accepted | 45638/45640 | 20305 | 0/0 |
| derive/a33e81f7 | accepted | 76107/76109 | 16361 | 0/0 |
| spec_refine/1231dda7 | accepted | 29729/29729 | 14584 | 0/0 |
| spec_refine/37e6ef30 | accepted | 47199/47199 | 14584 | 0/0 |
| derive/b155bcb1 | executed | 44581/44583 | 16361 | 0/0 |
| derive/2d18c67a | accepted | 35698/35700 | 20305 | 0/0 |
| derive/bd36a4db | accepted | 62778/62780 | 16361 | 0/0 |
| spec_refine/c656b9fe | prepared | 60828/60828 | 14584 | 0/0 |
复核接口修复会话 0；实际 F2 语义修订 0。二者不互相替代。

## 范围接回、复核复用与里程碑

里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。
- initial_graph：2026-09-20T04:13:28.232863+00:00
同语义复核复用记录 0；上下文准备失败 0；未发送包不消耗实际探索/复核轮数。
读取计划：当前 receipt 有新源 7、纯缓存 2；修复无进展次数 0。targeted_reads 按取得新源的逻辑计划计数，历史用量不重算；缓存发送仍消耗实际 agent 调用与时间。
技能加载 `a418b3ebfaa04bf5a7e409ec7476faae`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/activity-classes.md', 'tasks/read.md']；仅以实际发送状态为准。
技能加载 `d399c146cded4c35a572886d359d7a1b`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/discover.md']；仅以实际发送状态为准。
技能加载 `456da9adc42443fa8d4089d92b1dd778`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `1b7e202343804ec3b90df0d04db87b74`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `738e483b05e64de39d0dbe3b60fbec5c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `1bc51febad274875abde5205bc0aa42b`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `74dcb6b69d07496982c9f6e02db56872`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `f764f40ab8544df5b79208a012ee621a`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `6021e6aaaa224cabb605222bd52c9be3`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `005b8b86d31e41b0a608375f57f9fe5e`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `3caa059ff60643e0b233e40c0b738b33`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `37dc8722b61d455fa2833f13e6baaf5c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `74db341a8938420495caed0853ff6a7c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `a86f636b1ab24ca892f75a67fe66c6ba`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `a33e81f750f6488c84b2a5c4e388c205`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `1231dda797bb47c3b38b10629c6e78af`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `37e6ef30f52b465bb1424452f4312b4c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `b155bcb1c71849898bbb16f03ce9c699`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `2d18c67a65c8443689bf6efb526c245c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `bd36a4db3def4e019f8b7985c153d807`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `c656b9fef91b4459987511cc8ed7c78c`：版本 selected-question-v6，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
需接回且已取得新材料的计划 0；已接回 0；连接率 无可计算分母/历史未记录。这不是语义通过率或系统覆盖率。
实际发送包中源正文累计 222627 字符（跨调用重复发送会重复计入）；schema 累计 312774 字节。无真实 token/账单字段时不换算费用。