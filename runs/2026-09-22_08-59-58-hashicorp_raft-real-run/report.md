# 共识义务驱动局部审计报告

运行标识：`0834b76247584cfbaf0c8d7878b27c61`；模式：**真实工具运行**。

问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。

分析入口：`autonomous`。regression 表示预设开发回归，不能计为自主发现验收。


## 义务与有界审计结论
尚无已受理的有界审计问题或结论。

## 本次流程进度

工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。

| 阶段 | 已记录的进度 |
| --- | --- |
| 材料阅读 | 已完成首轮阅读；保存 37 个片段 |
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
快照：`d6edaaeee38847bdadf072d9d23af294`，纳入 88 个文件；读取 37 个材料片段，仍有未读范围的文件 82 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。
候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。

## 义务与选择依据

领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考：
- `configured_reference`：未提供协议参考清单
定向补读：Read material；关联 []；实际新增片段 ['README.md:1:80', 'docs/README.md:1:80', 'api.go:1:80', 'transport.go:1:80', 'observer.go:1:80', 'log.go:1:80', 'config.go:1:80', 'fsm.go:1:80']。
定向补读：Prioritize distinct responsibility areas before deeper dependency tracing. These eight nonoverlapping requests contain 935 previously unread lines and avoid all supplied cached intervals. A planning estimate of 50 characters per line gives 46,750 unique characters, below the 52,917-character breadth allowance; exact cost requires framework preflight because source line lengths are unavailable. The reads support candidate question selection, not predetermined obligations or correctness conclusions.；关联 []；实际新增片段 ['commitment.go:1:104', 'raft.go:285:441', 'raft.go:1203:1291', 'fsm.go:86:245', 'api.go:807:895', 'api.go:631:708', 'snapshot.go:125:278', 'file_snapshot.go:397:500']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['replication.go:1:665', 'transport.go:1:141']。
定向补读：When takeSnapshot consumes a successful sink.Close return, can a prior failed Close or cancellation on the same FileSnapshotSink make that return insufficient to justify proceeding to log compaction, or do the Persist contract and orchestration error paths exclude that history?；关联 ['F_snapshot_close_accepted', 'B_take_snapshot', 'B_file_sink_close', 'B_file_sink_cancel', 'B_compact_logs']；实际新增片段 ['fsm.go:1:85', 'snapshot.go:1:278', 'file_snapshot.go:397:551']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['raft.go:1390:1602', 'net_transport.go:600:810']。
定向补读：When pipeline decoding produces a replication_match_report, does receiving a future establish successful response completion sufficiently to consume its response fields, or can an errored or incomplete future produce a match report that ordinary replication would reject?；关联 ['replication_match_report', 'replication_pipeline_sender', 'replication_pipeline_decoder', 'replication_ordinary_append', 'replication_commitment_consumer']；实际新增片段 ['net_transport.go:750:912']。
定向补读：When pipeline decoding produces a replication_match_report, does receiving a future establish successful response completion sufficiently to consume its response fields, or can an errored or incomplete future produce a match report that ordinary replication would reject?；关联 ['replication_match_report', 'replication_pipeline_sender', 'replication_pipeline_decoder', 'replication_ordinary_append', 'replication_commitment_consumer']；实际新增片段 ['future.go:1:314', 'raft.go:1380:1660']。
定向补读：When pipeline decoding produces a replication_match_report, does receiving a future establish successful response completion sufficiently to consume its response fields, or can an errored or incomplete future produce a match report that ordinary replication would reject?；关联 ['replication_match_report', 'replication_pipeline_sender', 'replication_pipeline_decoder', 'replication_ordinary_append', 'replication_commitment_consumer']；实际新增片段 ['net_transport.go:350:600', 'go.mod:1:26']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['raft.go:950:1030']。
定向补读：Can heartbeat-produced replication_contact_record observations that lack a current-term guarantee sustain the leader's lease, or do the contact consumer and alternate authority-transition mechanisms exclude that interpretation?；关联 ['replication_contact_record', 'replication_heartbeat', 'replication_ordinary_append', 'replication_stepdown_request']；实际新增片段 ['raft.go:1030:1105']。
定向补读：Can heartbeat-produced replication_contact_record observations that lack a current-term guarantee sustain the leader's lease, or do the contact consumer and alternate authority-transition mechanisms exclude that interpretation?；关联 ['replication_contact_record', 'replication_heartbeat', 'replication_ordinary_append', 'replication_stepdown_request']；实际新增片段 []。
定向补读：Can heartbeat-produced replication_contact_record observations that lack a current-term guarantee sustain the leader's lease, or do the contact consumer and alternate authority-transition mechanisms exclude that interpretation?；关联 ['replication_contact_record', 'replication_heartbeat', 'replication_ordinary_append', 'replication_stepdown_request']；实际新增片段 ['config.go:200:225']。
定向补读：Can heartbeat-produced replication_contact_record observations that lack a current-term guarantee sustain the leader's lease, or do the contact consumer and alternate authority-transition mechanisms exclude that interpretation?；关联 ['replication_contact_record', 'replication_heartbeat', 'replication_ordinary_append', 'replication_stepdown_request']；实际新增片段 []。

## 候选问题与已有保护

候选解释是有来源的分析判断，不是性质证据或协议正确性证明。
候选受阻分类：evidence_blocked=2；workflow_blocked=0；resource_blocked=0
候选因证据/适用合同不足延期；未解释关闭，未确认缺陷，不是性质证据。
- 候选 `72e496f50aba411ab45ba5e2df4b935a`：Fact ['F_snapshot_close_accepted']；生命周期 consumption；状态 blocked / needs_specific_evidence；受阻分类 evidence_blocked。
  问题：When takeSnapshot consumes a successful sink.Close return, can a prior failed Close or cancellation on the same FileSnapshotSink make that return insufficient to justify proceeding to log compaction, or do the Persist contract and orchestration error paths exclude that history?；意义：Accepting an unusable snapshot before deleting recovery-relevant logs could compromise subsequent reconstruction. This consequence requires a reachable callback history that returns success after unsuccessful snapshot completion, actual deletion of needed logs, and insufficient alternative recovery evidence; none is established here.。
  适用上下文：['Repository FileSnapshotStore selected as the snapshot adapter', 'Snapshot persistence with a prior Close failure or cancellation', 'Subsequent orchestration Close and possible compaction']；事件路径：['Persist invokes Close or Cancel -> sink becomes closed before completion -> Persist returns an unresolved success or error -> takeSnapshot either exits on error or invokes Close again -> possible metadata update and compaction']；来源：['fsm.go:1:85', 'snapshot.go:1:278', 'file_snapshot.go:397:551']。
  已有保护/反证：["takeSnapshot checks Persist's error before its own Close. A propagated persistence or initial Close error prevents this invocation from updating snapshot metadata or compacting logs.", 'If Persist has not already closed the sink, takeSnapshot checks the first Close error directly and stops before metadata update and compaction.', 'FSMSnapshot.Persist explicitly assigns the callback responsibility for dumping necessary state and calling Close when finished or Cancel on error. A callback returning success after cancellation or failed closure cannot simply be assumed to satisfy that contract.', 'Successful first closure performs finalization, metadata writing, directory rename, applicable synchronization and reaping before returning nil.', 'Compaction deletes only through min(snapshot index, last log index minus trailing logs), and can perform no deletion. Reaching compaction alone does not establish loss of necessary recovery history.', 'Close errors after rename differ from prepublication failures: an error return does not universally establish that the snapshot is unavailable.']；剩余判别与限制：['No selected client FSMSnapshot.Persist implementation or correlated execution establishes whether it can return nil after an earlier failed Close or Cancel.', 'The attached Persist contract specifies closure and cancellation responsibilities but does not explicitly specify propagation of a Close error or the permissibility of retrying Close after failure. Whether the proposed success-returning callback history is contract-conforming remains unresolved.', 'FileSnapshotStore creation, discovery, opening and retention implementations are not attached; recoverability after each partial publication branch remains unresolved.', 'Actual adapter activation, retained alternative snapshots and logs, and restart behavior are not established for a concrete deployment.']。
  选择/缩窄依据：Source confirms that Close and Cancel set closed before completion and subsequent Close returns nil without checking the prior outcome. It also confirms that takeSnapshot proceeds only after Persist returns nil. Thus the remaining discriminator is the legality and reachability of that callback success after unsuccessful completion, rather than the already-resolved closed-flag behavior.；历史问题版本：1。
  升级义务：未生成；候选结论或受阻原因：Continue the same Fact consumption question. The acquired ranges establish the sink's ambiguous terminal flag, the orchestration error checks, and exact compaction bounds. They do not establish a conforming path connecting failed or cancelled completion to Persist success. Assuming callback error propagation would prematurely explain the candidate; assuming swallowed errors are permitted would manufacture its failing prehistory. The missing evidence is the selected client's Persist implementation and applicable error-handling contract, or an actual correlated callback trace with justified legality. No identified repository range can settle that external client's behavior. Additional publication-helper reading would clarify consequences but would not resolve this prerequisite, so retain this candidate as evidence-blocked without deriving an obligation.。
候选因证据/适用合同不足延期；未解释关闭，未确认缺陷，不是性质证据。
- 候选 `0d4998a258054b89ad225b9744296752`：Fact ['replication_match_report']；生命周期 establishment；状态 blocked / needs_specific_evidence；受阻分类 evidence_blocked。
  问题：When pipeline decoding produces a replication_match_report, does receiving a future establish successful response completion sufficiently to consume its response fields, or can an errored or incomplete future produce a match report that ordinary replication would reject?；意义：An unsupported match report could contribute to commitment as follower progress. The attached sources establish an error-handling differential, but do not establish erroneous follower progress, incorrect commitment, or loss of committed data.。
  适用上下文：['Pipeline replication enabled', 'NetworkTransport implementation when selected', 'Transport completion or error', 'Ordinary replication as a comparison path', 'Caller-selected transport with other repository variants unresolved']；事件路径：['Pipeline submission -> decodeResponse -> future.respond(err) -> doneCh publication -> Response field checks -> possible commitment.match', 'Ordinary AppendEntries call -> genericRPC -> decodeResponse error -> rejection before response field consumption', 'Follower response encoding -> interrupted response delivery -> concrete decoder mutation and error -> future publication']；来源：['transport.go:1:141', 'replication.go:200:330', 'replication.go:430:665', 'net_transport.go:750:912', 'future.go:1:314', 'raft.go:1380:1660', 'net_transport.go:350:600', 'go.mod:1:26']。
  已有保护/反证：['netPipeline.decodeResponses completes decodeResponse and calls future.respond(err) before publishing the future. Network publication therefore establishes that the decoding attempt finished, although it does not establish success.', 'pipelineSend allocates a fresh response object. An error leaving Success at its zero value cannot produce a match report.', 'pipelineDecode rejects higher response terms and Success=false before updateLastAppended.', 'appendFuture retains the submitted request and response pointers, preserving the request identity used to select the reported index.', 'The attached Raft.appendEntries handler initializes Success=false and returns from its explicit rpcErr branch before the final Success=true assignment. Its normal paths do not supply Success=true together with a nonnil RPC error.', 'Follower lookup, truncation, and StoreLogs failure exits retain Success=false.', 'An interrupted decode of a legitimate successful acknowledgement would not itself demonstrate false follower progress; the follower may already have established the acknowledged state.', 'NetworkTransport.AppendEntriesPipeline rejects pipeline creation when maxInFlight is below minInFlightForPipelining. The differential requires the enabled pipeline variant.']；剩余判别与限制：["Whether the concrete decoder can return an error after setting Success=true and a term passing pipelineDecode's guard under a legal interrupted wire history remains unresolved.", "NetworkTransport.getConn constructs codec.NewDecoder with a default MsgpackHandle, and go.mod requires github.com/hashicorp/go-msgpack/v2 v2.1.2. The dependency's actual decoding implementation and partial-mutation semantics are not attached; the version declaration alone cannot establish them.", 'The active transport variant is unknown. Other repository transport implementations remain uninspected, and network publication ordering cannot be generalized to them.', 'Follower persistence establishment, peer replacement, and downstream commitment consequences remain outside the established evidence.', 'The AppendFuture contract requires Error to return before Response access and limits response validity to success. The practical match-report consequence of the observed access-contract mismatch remains unestablished.', 'No actual correlated execution demonstrates an errored future with accepting response fields or demonstrates that such a report overstates follower progress.']。
  选择/缩窄依据：The latest reads identify the decoder construction and declared serialization version. They also establish that ordinary genericRPC returns decodeResponse's error to replicateTo, which rejects it, whereas pipeline publication carries the completed future regardless of that error. These findings sharpen the same discriminator but do not settle partial response mutation or its semantic consequence. Retain the candidate as evidence-blocked rather than assuming decoder behavior or equating an access-contract mismatch with false replication progress.；历史问题版本：3。
  升级义务：未生成；候选结论或受阻原因：Continue the existing candidate without changing its Fact, lifecycle, or fault scope. The remaining decisive evidence is the applicable go-msgpack/v2 v2.1.2 decoding implementation, or a correlated execution using that implementation and legitimately encoded follower responses interrupted at controlled boundaries. Such evidence must record the decode error, resulting response fields, and any ensuing match report; a false-progress consequence additionally requires evidence about the follower's established state. No exact dependency source range is located in the supplied snapshot metadata, so no speculative file request is issued. The known interface mismatch is insufficient to resolve the original establishment question, and narrowing it to method-call ordering would leave that question unanswered. This blocks this candidate provisionally and does not exhaust other inventory questions.。
- 候选 `b49107ac9fef4283a6443318eadc4793`：Fact ['replication_contact_record']；生命周期 consumption；状态 explained / explained_by_existing_mechanism；受阻分类 无。
  问题：Can heartbeat-produced replication_contact_record observations that lack a current-term guarantee sustain the leader's lease, or do the contact consumer and alternate authority-transition mechanisms exclude that interpretation?；意义：Heartbeat rejection responses can conditionally maintain the connectivity count used by the lease check. This does not establish current authority. Prolonged Leader state could affect availability or caller interpretation, but the supplied evidence establishes neither a violated authority contract nor a client-completion or decision-safety consequence.。
  适用上下文：['Heartbeat response processing', 'Peer term greater than the heartbeat request term', 'Concurrent ordinary replication and heartbeat processing', 'Leader lease evaluation']；事件路径：["Older-term heartbeat reaches appendEntries -> rejection carries the receiver's term with nil rpcErr -> if transport returns nil error, heartbeat refreshes contact despite Success=false.", 'Recent timestamps for enough latest-configuration voters, including the local voter -> checkLeaderLease counts quorum contact -> this invocation does not request Follower state.', 'verifyLeader receives a verification future -> registers it with replication workers and triggers heartbeats -> notifyAll votes only on the detached pending set; aggregation and its consumer remain unresolved.', 'CommitTimeout or replication trigger -> replicateTo -> a nil-error higher-term response invokes handleStaleTerm and returns shouldStop=true; completed authority transition remains unresolved.']；来源：['config.go:200:225', 'raft.go:950:1030', 'raft.go:1030:1105', 'raft.go:1380:1602', 'replication.go:1:199', 'replication.go:200:330', 'replication.go:360:450']。
  已有保护/反证：['config.go:200:225 defines LeaderLeaseTimeout in terms of quorum contact, without requiring successful or current-term acknowledgements.', 'replication.go:1:199 explicitly describes lastContact as recording successful or unsuccessful responses. Its connectivity meaning is consistent with the documented lease criterion.', 'raft.go:1030:1105 implements that criterion by counting recent contact from latest-configuration voters and requesting Follower state below quorum. It does not interpret timestamps as a current-term acknowledgement.', 'raft.go:950:1030 explicitly distinguishes this lease from a lease used for read-only queries. This supports the limited applicability of the connectivity contract; it is not proof of broader authority correctness.', 'raft.go:950:1030 shows verifyLeader registering a supplied future and triggering heartbeats. Together with notifyAll in replication.go:1:199, this establishes that heartbeat votes operate on registered requests, not that every rejection independently initiates verification.', 'replication.go:200:330 checks higher response terms before refreshing ordinary-replication contact. replication.go:1:199 supplies a periodic ordinary-replication trigger and retires the heartbeat loop when replicate returns.', 'replication.go:360:450 does not refresh contact on transport errors and checks stop while awaiting triggers or backing off.']；剩余判别与限制：['Whether the selected transport delivers a newer-term rejection as a nil-error AppendEntries return.', 'Whether ordinary replication or another authority mechanism necessarily completes a leadership transition while heartbeats continue; periodic dispatch does not establish RPC completion.', "Verification activation callers, vote aggregation, and the consumer's authority-transition behavior remain unread.", 'Scheduling and completion of stepdown signaling, lease checks, worker retirement, and in-flight heartbeat RPCs remain unresolved.', 'Applicable timing and configuration constraints beyond the documented connectivity lease and observed CommitTimeout trigger remain unresolved.', 'No attached contract establishes a stronger authority guarantee for this contact timestamp, or a client operation that relies on it as sufficient current-authority evidence.']。
  选择/缩窄依据：The attached verification and leadership-transfer range resolves the selected consumption discriminator: the documented lease is a connectivity mechanism, and its actual consumer counts connectivity without asserting current-term authority. Rejection contact can satisfy that local criterion conditionally. This explains the suspected strengthening at this consumer without assuming an unavoidable alternate stepdown mechanism or declaring broader authority behavior correct.；历史问题版本：4。
  升级义务：未生成；候选结论或受阻原因：Continue the same candidate and dispose only its suspected contact-to-authority strengthening. The source establishes a connectivity contract and a matching consumer; the newly attached commentary also expressly separates this lease from read-authority leases. Verification registration does not establish automatic rejection-driven stepdown, so that possibility remains unresolved rather than serving as an assumed protection. No obligation is justified by treating the connectivity lease as a stronger authority promise. Broader leadership duration, transport delivery, and client consequences remain open and would require a separately grounded discriminator. This disposition neither exhausts the inventory nor resolves the previously recorded snapshot and pipeline candidates.。

## 描述性理解演化

AuditSpec：v1 → v5；Behavior：16 → 33；Fact：7 → 14。
Surface 扩展任务：planned=3 / prepared=3 / sent=3 / semantic_result=3 / accepted=3；深度分析反馈任务：0（完成 0）。这些是描述性进度，不是正确性覆盖率。
- 扩展 ['Replication workers and AppendEntriesPipeline results']：completed；Expand one source-grounded implementation surface
- 扩展 ['processRPC, AppendEntries, RequestVote, InstallSnapshot and heartbeat fast-pass']：completed；Expand one source-grounded implementation surface
- 扩展 ['VerifyLeader completion and leadership transfer']：completed；Expand one source-grounded implementation surface
- 高后果 Surface `surface:Apply, ApplyLog and Barrier`：mapped；Enqueue and candidate rejection are recovered; leader admission and full completion remain partial.
- 高后果 Surface `surface:runCandidate and election-result channels`：mapped；Campaign loop is mapped; election helpers and persistent voting remain deferred dependencies.
- 高后果 Surface `surface:dispatchLogs and commitment`：mapped；Local storage reporting and index calculation are recovered without assuming remote evidence validity.
- 高后果 Surface `surface:appendConfigurationEntry`：mapped；Encoding and update sequence are observed; request legality and activation lifecycle remain incomplete.
- 高后果 Surface `surface:runFSM application closures`：mapped；Callback filtering, progress changes and response correlation are recovered; complete queue processing is unread.
- 高后果 Surface `surface:Client FSM implementation`：externalized；Interface explicitly assigns implementation to clients; library callback scheduling remains mapped.
- 高后果 Surface `surface:FSM snapshot capture and takeSnapshot`：mapped；Capture, configuration coordination and persistence orchestration are observed.
- 高后果 Surface `surface:FileSnapshotSink.Close, Cancel and finalize`：mapped；Flag handling and partial failure branches are observed; publication helper and reader semantics remain deferred.
- 高后果 Surface `surface:compactLogsWithTrailing and removeOldLogs`：mapped；Deletion bounds are recovered; caller prerequisites and store failure behavior remain incomplete.
- 高后果 Surface `surface:restoreSnapshot and runFSM restore closure`：mapped；Startup and runtime restoration are distinct mapped paths with unresolved helper and adapter dependencies.
- 高后果 Surface `surface:Snapshot store Create, List, Open, writeMeta and ReapSnapshots`：deferred；These methods establish publication, discoverability, validation and retention semantics needed to connect snapshots to recovery.
- 高后果 Surface `surface:Constructor, stable storage and built-in storage variants`：deferred；Selection and startup wiring are unread. Catalogue-listed built-in implementations remain within the audit frontier.
- 高后果 Surface `surface:User Restore, BootstrapCluster and processLogs`：deferred；Restore interruption, startup eligibility and committed-log scheduling are described or referenced but implementation bodies are unread.
- 高后果 Surface `surface:Replication workers and AppendEntriesPipeline results: local workers and commitment reporting`：mapped；Attached source supports local execution ownership, request construction, response branches, submission and decoding separation, snapshot fallback, shared contact updates, signaling, and immediate match consumption. Mapping does not establish remote guarantees or completed authority transitions.
- 高后果 Surface `surface:Replication workers and AppendEntriesPipeline results: concrete adapter future completion`：deferred；Resolve how available concrete adapters populate responses, complete errors, publish futures, order results, and cancel or close pipelines. The decoder's Response access without Error cannot be interpreted beyond the observed interface discrepancy until those implementations are read.
- 高后果 Surface `surface:NetworkTransport.handleConn / handleCommand ingress and response routing`：mapped；Attached code establishes decoding, heartbeat classification, callback versus consumer-channel routing, response waiting, encoding, and flushing. Handler activation and caller scheduling remain explicit unknowns.
- 高后果 Surface `surface:Raft.processRPC / processHeartbeat / appendEntries local processing`：mapped；Attached code supports local dispatch and AppendEntries branch behavior, including storage ordering and partial-error effects. This mapping does not establish helper semantics or actual execution serialization.
- 高后果 Surface `surface:RPC ingress remainder: handler wiring, header validation, vote and snapshot handlers, and AppendEntries dependencies`：deferred；Read callback registration and consumer-loop ownership to resolve fast-pass execution; checkRPCHeader to establish validation semantics; requestVote, requestPreVote, installSnapshot, and timeoutNow bodies for their independent outcomes; and AppendEntries storage, metadata, processLogs, and response consumers before asserting stronger lifecycle facts.
- 高后果 Surface `surface:Raft.VerifyLeader API admission`：mapped；The supplied API body establishes initialization, channel admission and shutdown return paths.
- 高后果 Surface `surface:Raft.verifyLeader initialization`：mapped；The supplied function establishes the singleton response shortcut and non-singleton request registration.
- 高后果 Surface `surface:Raft.leadershipTransfer worker`：mapped；The worker's replication wait, cancellation, RPC invocation and result delivery are attached; caller and receiver semantics remain separate.
- 高后果 Surface `surface:VerifyLeader vote aggregation and final completion`：deferred；Read verifyCh dispatch, replication notification consumers, verifyFuture voting/respond implementation and role-loss cleanup to recover what completed verification establishes.
- 高后果 Surface `surface:Leadership transfer orchestration and authority transition completion`：deferred；Read the worker caller and doneCh consumer, replication-progress producers, and TimeoutNow receiver to distinguish worker completion, cancellation and completed authority transition.
- 高后果 Surface `surface:Raft.checkLeaderLease`：mapped；Attached implementation establishes voter filtering, timestamp-age counting, quorum calculation, and the below-quorum call to setState(Follower). Caller scheduling and completed transition semantics remain unknown.

## 实现理解（支持信息）

| Activity | 适用性 | 义务 | 证据 | 未知 |
| --- | --- | --- | --- | --- |
| A1 | applicable | [] | [] | ['Follower acknowledgement meaning and leader commit processing are unresolved.'] |
| A2 | applicable | [] | [] | ['Vote persistence, result-channel provenance, lease handling and leadership-transfer completion are unresolved.'] |
| A3 | applicable | [] | [] | ['InstallSnapshot handling, incremental catch-up and post-restore log reconciliation remain unread.'] |
| A4 | applicable | [] | [] | ['Admission serialization, nextConfiguration checks, committed-configuration transitions and replication-worker replacement remain unread.'] |
| A5 | applicable | [] | [] | ['The complete channel dispatch loop and processLogs producer are unread; queue receipt is not treated as proof of commitment.'] |
| A6 | applicable | [] | [] | ['Snapshot metadata writing, listing, opening, reaping and other built-in store implementations are unread.'] |
| A7 | applicable | [] | [] | ['Future synchronization, leader verification completion, read integration and caller retry identity are unread.'] |
未解释责任：Snapshot store Create, List, Open, writeMeta and ReapSnapshots；These methods establish publication, discoverability, validation and retention semantics needed to connect snapshots to recovery.
未解释责任：Constructor, stable storage and built-in storage variants；Selection and startup wiring are unread. Catalogue-listed built-in implementations remain within the audit frontier.
未解释责任：User Restore, BootstrapCluster and processLogs；Restore interruption, startup eligibility and committed-log scheduling are described or referenced but implementation bodies are unread.
未解释责任：Observer delivery；Observer types and blocking option are visible; actual send sites and effects on protocol execution are unread.
未解释责任：Replication workers and AppendEntriesPipeline results: concrete adapter future completion；Resolve how available concrete adapters populate responses, complete errors, publish futures, order results, and cancel or close pipelines. The decoder's Response access without Error cannot be interpreted beyond the observed interface discrepancy until those implementations are read.
未解释责任：RPC ingress remainder: handler wiring, header validation, vote and snapshot handlers, and AppendEntries dependencies；Read callback registration and consumer-loop ownership to resolve fast-pass execution; checkRPCHeader to establish validation semantics; requestVote, requestPreVote, installSnapshot, and timeoutNow bodies for their independent outcomes; and AppendEntries storage, metadata, processLogs, and response consumers before asserting stronger lifecycle facts.
未解释责任：VerifyLeader vote aggregation and final completion；Read verifyCh dispatch, replication notification consumers, verifyFuture voting/respond implementation and role-loss cleanup to recover what completed verification establishes.
未解释责任：Leadership transfer orchestration and authority transition completion；Read the worker caller and doneCh consumer, replication-progress producers, and TimeoutNow receiver to distinguish worker completion, cancellation and completed authority transition.

| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |
| --- | --- | --- | --- |
| `984160a7` | 扩展职责/交接覆盖 | pending/read | Resolve decisive understanding gaps； |
| `16fee94d` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `b5ecb56f` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `b0068d43` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `fc830240` | 扩展职责/交接覆盖 | completed/done | The previously unknown contact consumer is now located: checkLeaderLease reads LastContact for remote voters in the latest configuration, counts timestamps within LeaderLeaseTimeout together with the local voter, and requests Follower state below quorum. The inventory can record this consumer without strengthening the contact Fact into current-term authority evidence.； |

| 复核对象/版本 | 层面 | 判断 | 材料与推导 |
| --- | --- | --- | --- |
尚无已执行的语义复核；有来源的候选不因此变成已确认规范。

职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。

## 未受理草稿分析
尚未完成自主义务发现；未补入预置义务。

## 候选修复与模型续写

模型续写保存原稿、当前工作草稿及错误，返回完整修订稿；其他对象按具体字段修复。未完成草稿不等于受理模型，调用完成也不等于语义问题已解决。

## 实验能力与执行

| 能力 | 状态 | 执行依据 |
| --- | --- | --- |
| package_build | probe_confirmed | c2432176bac64f6dac9e165fb3e04d3c：Offline package compilation; no protocol correctness or scheduling claim |
| precise_schedule_replay | unavailable | 无执行确认：No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites |

默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。

| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |
| --- | --- | --- | --- | --- |
| Codex 版本检查：agent_probe `5298b4d8` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/5298b4d8033a4d96b7fa0010d7c15aac/stdout.log) / [stderr.log](logs/5298b4d8033a4d96b7fa0010d7c15aac/stderr.log) |
| Codex 参数检查：agent_capabilities `338bee39` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/338bee39e0e64e0f8833fc75be4e06ea/stdout.log) / [stderr.log](logs/338bee39e0e64e0f8833fc75be4e06ea/stderr.log) |
| Java 版本检查：java_probe `c913bfd7` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/c913bfd7018e45b9ac7552a391cd1f22/stdout.log) / [stderr.log](logs/c913bfd7018e45b9ac7552a391cd1f22/stderr.log) |
| 验证工具启动检查：verifier_probe `2342d04b` | 正常完成 | 版本帮助已识别，工具可用；命令退出码 1 | 不适用：未检查性质 | [stdout.log](logs/2342d04b674b440480ad27828dd903cb/stdout.log) / [stderr.log](logs/2342d04b674b440480ad27828dd903cb/stderr.log) |
| 目标工具链版本检查：implementation_tool_probe `7eb8525d` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/7eb8525db30a43e28579d3ae4c2b6725/stdout.log) / [stderr.log](logs/7eb8525db30a43e28579d3ae4c2b6725/stderr.log) |
| 现有测试与实验能力探测：capability_probe `c2432176` | 正常完成 | 不适用 | 仅限实际测试覆盖；不自动证明目标或确认违反 | [stdout.log](logs/c2432176bac64f6dac9e165fb3e04d3c/stdout.log) / [stderr.log](logs/c2432176bac64f6dac9e165fb3e04d3c/stderr.log)；原因（原文）：Compile probe only |
| Agent 分析或修复：agent `0076a8e3` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/0076a8e3aac742718542fe08c2426d13/stdout.log) / [stderr.log](logs/0076a8e3aac742718542fe08c2426d13/stderr.log) / [response.json](agent/cc6778e7f5f847e8b6e0857fa40abeed-read/response.json) |
| Agent 分析或修复：agent `ef2f58ae` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/ef2f58ae486943c59d216a0c1dd50b71/stdout.log) / [stderr.log](logs/ef2f58ae486943c59d216a0c1dd50b71/stderr.log) / [response.json](agent/814684584e2c4e3390df92be80933134-discover/response.json) |
| 职责覆盖探索：agent `4ba8a268` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/4ba8a268b06e4fa28286c99d8b26f48a/stdout.log) / [stderr.log](logs/4ba8a268b06e4fa28286c99d8b26f48a/stderr.log) / [response.json](agent/e180d082abb745b8b8dbde93ccf720f1-spec_refine/response.json) |
| 职责覆盖探索：agent `7b2d980f` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/7b2d980f1e0b4cefb1a15d9ff402837e/stdout.log) / [stderr.log](logs/7b2d980f1e0b4cefb1a15d9ff402837e/stderr.log) / [response.json](agent/1a81947154594356a976d01d17533529-spec_refine/response.json) |
| Agent 分析或修复：agent `a893605f` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/a893605f75a24068ad20c4ac66151acd/stdout.log) / [stderr.log](logs/a893605f75a24068ad20c4ac66151acd/stderr.log) / [response.json](agent/f51c87181168440f8bc0c7380760b769-derive/response.json) |
| Agent 分析或修复：agent `00637b53` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/00637b53b2664748a3e3542c424e6e0a/stdout.log) / [stderr.log](logs/00637b53b2664748a3e3542c424e6e0a/stderr.log) / [response.json](agent/8b1b911c811140c58a183b84eed9fd58-derive/response.json) |
| 职责覆盖探索：agent `ba6d68bd` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/ba6d68bd61c646c48e2f3249277adfa8/stdout.log) / [stderr.log](logs/ba6d68bd61c646c48e2f3249277adfa8/stderr.log) / [response.json](agent/4f7a8a84a392451c9853fa03df16a9dd-spec_refine/response.json) |
| 职责覆盖探索：agent `648ef39e` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/648ef39e54c941788232de3436a986c5/stdout.log) / [stderr.log](logs/648ef39e54c941788232de3436a986c5/stderr.log) / [response.json](agent/f34a1225942e451b84769621ec62aaa7-spec_refine/response.json) |
| Agent 分析或修复：agent `da76bbc8` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/da76bbc83339438fb338f1cedea23b48/stdout.log) / [stderr.log](logs/da76bbc83339438fb338f1cedea23b48/stderr.log) / [response.json](agent/504287a5bb9843938454f9fa909d4e7d-derive/response.json) |
| Agent 分析或修复：agent `fba1dbe3` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/fba1dbe3ac2048a6b780c4dd1b7aa29e/stdout.log) / [stderr.log](logs/fba1dbe3ac2048a6b780c4dd1b7aa29e/stderr.log) / [response.json](agent/7e746747a22f461e8f7eba1d2dacce72-derive/response.json) |
| Agent 分析或修复：agent `4193360b` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/4193360b594d4299b56533f881c34f21/stdout.log) / [stderr.log](logs/4193360b594d4299b56533f881c34f21/stderr.log) / [response.json](agent/1a566aec9bcd4064bc63c96fbe13b844-derive/response.json) |
| Agent 分析或修复：agent `9e4d75e7` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/9e4d75e77aac4b7bbe9563c3d0784ee1/stdout.log) / [stderr.log](logs/9e4d75e77aac4b7bbe9563c3d0784ee1/stderr.log) / [response.json](agent/8310aff4e8b74babac387fbadd4e0db9-derive/response.json) |
| 职责覆盖探索：agent `309adff4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/309adff4116344078c9def0350e51b20/stdout.log) / [stderr.log](logs/309adff4116344078c9def0350e51b20/stderr.log) / [response.json](agent/67543237d26d4684a7dc6649ae6314be-spec_refine/response.json) |
| 职责覆盖探索：agent `38cbf919` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/38cbf919d2d24ff6b0e085d52c3423e9/stdout.log) / [stderr.log](logs/38cbf919d2d24ff6b0e085d52c3423e9/stderr.log) / [response.json](agent/f0b78c0b95f44e3c99b55fe653380389-spec_refine/response.json) |
| Agent 分析或修复：agent `bada9583` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/bada958323614634a1bbe9c6a364f254/stdout.log) / [stderr.log](logs/bada958323614634a1bbe9c6a364f254/stderr.log) / [response.json](agent/bbfff49eddcf4767a2d785b5a307d172-derive/response.json) |
| Agent 分析或修复：agent `14dd2bbe` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/14dd2bbe20e54f0b81099443ee388de8/stdout.log) / [stderr.log](logs/14dd2bbe20e54f0b81099443ee388de8/stderr.log) / [response.json](agent/c7a70a683f7745dd91c3064cec1299d7-derive/response.json) |
| Agent 分析或修复：agent `fa007313` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/fa007313ffe64d1f8984e5fb0857232a/stdout.log) / [stderr.log](logs/fa007313ffe64d1f8984e5fb0857232a/stderr.log) / [response.json](agent/5445243c90094128ace40f15158bb288-derive/response.json) |
| Agent 分析或修复：agent `7331906e` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/7331906e4abe454a9f6e7a00651855b6/stdout.log) / [stderr.log](logs/7331906e4abe454a9f6e7a00651855b6/stderr.log) / [response.json](agent/63cc003d7f22483ab7a702fdfc34ac55-derive/response.json) |
| Agent 分析或修复：agent `04a840cd` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/04a840cdb4b14b9db1fda2cf0ed9bf58/stdout.log) / [stderr.log](logs/04a840cdb4b14b9db1fda2cf0ed9bf58/stderr.log) / [response.json](agent/661fb68db71e49f08a6cd37d01793dfa-derive/response.json) |
| 职责覆盖探索：agent `de7fee4f` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/de7fee4f96d0435eace426b252bf667e/stdout.log) / [stderr.log](logs/de7fee4f96d0435eace426b252bf667e/stderr.log) / [response.json](agent/0870f76aff86429d875de85cad9c9ca0-spec_refine/response.json) |

逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）：

## 模型、校准与证据范围

尚未生成并执行局部模型；没有模型层检查结论。

## 候选发现与 F1—F4

本次尚无记录的候选违反。这不代表实现没有缺陷。
本次没有实际应用的语义修订；工具错误不冒充 F1—F4。

## 未决事项与停止原因

停止原因（原文）：Insufficient calls for another candidate
控制器格式：check-continuation-v11；阶段：new_run。
恢复位置：探索/复核任务 `None`；单元 `None`，模型 `None`，反例 `None`，下一动作 `select`。
- Only the three attached source ranges support these additions; navigation hints supply no implementation guarantees.
- Concrete transports, future implementations, follower handlers, storage variants, verification aggregation, lease checks, and leadership lifecycle callers remain unread.
- No obligation, executable check, calibrated observation, or confirmed defect is established by this descriptive refinement.
- Only attached source ranges support this refinement; declaration hints and earlier provenance were not treated as semantic evidence.
- Actual heartbeat callback wiring and serialization remain unresolved despite main-thread comments on the Raft handlers.
- Persistence-before-success is observed as method-call ordering, not demonstrated crash durability.
- No tests, execution, calibration, correctness conclusion, or confirmed defect are claimed.
- Only the two attached exact source ranges support this refinement.
- Mapped children describe local code paths, not complete verification or transfer coverage.
- Future implementation, notification consumers, replication-progress establishment, transfer orchestration and TimeoutNow receiver semantics remain unread.
- No execution, calibration or correctness conclusion is supplied.
- Existing producer descriptions are retained inventory, not newly verified from attached producer code.
- The attached source supports descriptive consumption and a state-change request, not completed authority loss, a normative obligation, or a confirmed defect.
- This refinement does not resolve the contact Fact's remaining authority-semantics question.
- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。
- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。

## 实际运行统计

累计执行时间：1847.05 秒；预算计数：`{'experiments': 1, 'agent_calls': 20, 'exploration_rounds': 3}`。
首个已保存模型前耗时：尚无模型；模型仍须通过实际工具检查。
审计单元 0；范围扩展 0；语义修订 0；校准 0。
完整命令、时间、版本与制品关联见 [state.json](state.json)，图、规格和计划视图在结束或生成报告时导出；事件见 [events.jsonl](events.jsonl)。


## 材料、上下文与实际产物

字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。
唯一材料 119268/120000 字符；区间并集 22/40。广度当前可分配 732、为深度保留 0；深度可分配 732、为广度保留 0。
建模类执行记录 0；受理且非空 Bundle 回复 0；落盘模型版本 0（仅模型阶段 0，完整组件 0）；实际性质搜索记录 0（触达与校准另列）。

| 阶段 | 新调用记录 | 已记录时长（秒） |
| --- | --- | --- |
| agent_probe | 1 | 0.01（1 条有起止时间） |
| agent_capabilities | 1 | 0.01（1 条有起止时间） |
| java_probe | 1 | 0.06（1 条有起止时间） |
| verifier_probe | 1 | 0.14（1 条有起止时间） |
| implementation_tool_probe | 1 | 0.01（1 条有起止时间） |
| capability_probe | 1 | 13.93（1 条有起止时间） |
| read | 1 | 54.61（1 条有起止时间） |
| discover | 1 | 360.42（1 条有起止时间） |
| spec_refine | 7 | 675.77（7 条有起止时间） |
| derive | 11 | 729.55（11 条有起止时间） |
缓存复用/重附加记录 11 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。

| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |
| --- | --- | --- | --- | --- |
| read/47fca27a | accepted | 119058/119058 | 1294 | 0/0 |
| discover/dbf58ed2 | accepted | 85611/85611 | 13645 | 0/0 |
| spec_refine/9885e03b | accepted | 31989/31989 | 14584 | 0/0 |
| spec_refine/52df41e9 | accepted | 66064/66064 | 14584 | 0/0 |
| derive/504c7e19 | accepted | 43743/43743 | 17070 | 0/0 |
| derive/fb44ba59 | accepted | 71979/71979 | 17070 | 0/0 |
| spec_refine/63a163fe | accepted | 32538/32538 | 14584 | 0/0 |
| spec_refine/bcf92ff8 | accepted | 53322/53322 | 14584 | 0/0 |
| derive/1f634caa | accepted | 47935/47935 | 17070 | 0/0 |
| derive/c7228ebd | accepted | 93978/93978 | 17070 | 0/0 |
| derive/4dedae3a | accepted | 119107/119107 | 17070 | 0/0 |
| derive/efae1aef | accepted | 131894/131894 | 17070 | 0/0 |
| spec_refine/ee3b2542 | accepted | 29261/29261 | 14584 | 0/0 |
| spec_refine/d2cfe727 | accepted | 33953/33953 | 14584 | 0/0 |
| derive/250009cc | accepted | 51468/51468 | 17070 | 0/0 |
| derive/129e97e5 | accepted | 65760/65760 | 17070 | 0/0 |
| derive/20611911 | accepted | 80742/80742 | 17070 | 0/0 |
| derive/69bbc1dd | accepted | 92334/92334 | 17070 | 0/0 |
| derive/1e6937a1 | accepted | 95421/95421 | 17070 | 0/0 |
| spec_refine/7e48f7eb | accepted | 46670/46670 | 14584 | 0/0 |
复核接口修复会话 0；实际 F2 语义修订 0。二者不互相替代。

## 范围接回、复核复用与里程碑

里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。
- initial_graph：2026-09-22T01:07:08.061331+00:00
同语义复核复用记录 0；上下文准备失败 0；未发送包不消耗实际探索/复核轮数。
读取计划：当前 receipt 有新源 11、纯缓存 2；修复无进展次数 0。读取次数仅从回执统计；材料总量、上下文、Agent 调用与时间仍有限制。
技能加载 `47fca27a08d3449c8da3be95f006fb0b`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/activity-classes.md', 'tasks/read.md']；仅以实际发送状态为准。
技能加载 `dbf58ed2d7de4d9d8c0646c121e0c368`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/discover.md']；仅以实际发送状态为准。
技能加载 `9885e03bf3bd4b539f0d0daa46880060`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `52df41e916a048f493b1da00f0dff96b`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `504c7e190f894d47a637bc7f23b88acf`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `fb44ba59b7204cda88baf1a6dbad5e90`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `63a163fe6fe24ae3a2cbd77d9f73d91c`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `bcf92ff80a344041818302161f197fe3`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `1f634caaf9ea451eb569ff11313f3771`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `c7228ebda273482ca23b1da7fb8ff561`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `4dedae3ab5004eae886437d536362355`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `efae1aef728746c0a23348846b30a0ce`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `ee3b2542fcee4147b45b89a79cbfa0fd`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `d2cfe727f4484b1ebc5ab11f7e688e32`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `250009cc581a43f0b41f8d883b8b77af`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `129e97e5a40b468d8f85a3fc6e7aeb0d`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `20611911bd1f44aa820dda225ef67900`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `69bbc1dda7c24b2ab0d7ae8bd523bcfc`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `1e6937a13be141589eb7884653159c5f`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `7e48f7ebf1924feabf3cdbff88a4256e`：版本 check-continuation-v11，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
需接回且已取得新材料的计划 0；已接回 0；连接率 无可计算分母/历史未记录。这不是语义通过率或系统覆盖率。
实际发送包中源正文累计 318351 字符（跨调用重复发送会重复计入）；schema 累计 304797 字节。无真实 token/账单字段时不换算费用。