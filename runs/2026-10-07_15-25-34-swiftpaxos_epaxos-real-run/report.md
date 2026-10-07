# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 持久化元数据丢失 ballot | 已确认违反 | 固定输入 bal=7、vbal=2 下，recordInstanceMetadata 写出的 21 字节记录前四字节为 2（即 vbal），bal 未写入；事件 bal_persisted=false、field0_equals_vbal=true，测试因该断言失败而退出码 1。 | [CLM-DURABLE-BAL](#claim-CLM-DURABLE-BAL) |
| Does the TryPreAccept recovery path's defer-cycle guard ever fire, and if it cannot, can a recovering coordinator stay deferred… | 源码解释，未经性质执行 | The notInQuorum guard is still written and still inert for two independent reasons (possibleQuorum never set true; constant loop index), so a reader could mistake it for… | [候选原文与来源](state.json) |
| Can a Commit that carries a single NOOP for the receiver's own row reach handleCommit while the local instance is a placeholder… | 源码解释，未经性质执行 | handleCommit returns early when inst.Status >= COMMITTED or commit.Ballot < inst.bal, but a placeholder has Status NONE and bal -1, so those guards do not protect this… | [候选原文与来源](state.json) |
| When a coordinator's Accept replies report a higher ballot than lb.lastTriedBallot, does the coordinator ever escalate (count a… | 源码解释，未经性质执行 | The escalation block is still structurally unreachable, so the protection is not the handler's own nack logic but the independent recovery timer.；makeBallot does not… | [候选原文与来源](state.json) |
| Does the client's observed-completion path require and check that a reply answers the specific outstanding request… | 源码解释，未经性质执行 | The client's identity is not discarded: ReqReply.Seqnum carries the CommandId and is used to index c.reqTime, so the match could be made but is not.；The source comment… | [候选原文与来源](state.json) |
| For an even replica count, do FastQuorumSize = F + (F+1)/2 and SlowQuorumSize = (N+1)/2 still describe sets whose intersection is… | 暂停调查，尚无正式义务 | Read the membership/liveness activity (A4): master registration, Alive transitions and reconnect handling, to determine whether a replica can advance crtInstance for a… | [候选 1](#candidate-0922502bc12a4af68ee74cb77942fd72) |

<a id="claim-CLM-DURABLE-BAL"></a>

### 1. 持久化元数据丢失 ballot

**已确认违反**。要求原文：For any instance whose ballot and pre-accept ballot differ, the per-instance metadata record written by recordInstanceMetadata in a Durable replica must carry bal in its own field, distinct from vbal, so that the persisted record can distinguish the current ballot from the pre-accept ballot.

决定性范围：Package epaxos records written by recordInstanceMetadata while Durable is true, for instances whose bal and vbal differ; the record layout is the 9+r.N*4 byte form the function builds.
The second PutUint32 in recordInstanceMetadata is not intended to overwrite the first, i.e. the function intends to persist both bal and vbal.；StableStore accepts the write as given; the obligation is about the bytes produced, not about fsync ordering.。
范围参数：{"function": "recordInstanceMetadata", "file": "epaxos/epaxos.go"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：持久化元数据丢失 ballot；固定输入 bal=7、vbal=2 下，recordInstanceMetadata 写出的 21 字节记录前四字节为 2（即 vbal），bal 未写入；事件 bal_persisted=false、field0_equals_vbal=true，测试因该断言失败而退出码 1。

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/91b8f11cbf44454a8e4633a16cb2d0b2/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/91b8f11cbf44454a8e4633a16cb2d0b2/plan.json)；[原始观察](logs/f298950cf3b549d781b884912385770a/stdout.log)；[assessment](direct-checks/91b8f11cbf44454a8e4633a16cb2d0b2/f298950cf3b549d781b884912385770a-assessment.json)；[对应性复核](submissions/4a83d0f622f646eebac0ba86be4b0bf3/accepted.json)

原执行非零退出（1）保留；上述复核对本次执行的指定违反见证作了独立失败归因。当前确认、其他缺口分别按评估列示。

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.86 秒；执行进程耗时 7.43 秒；[实际命令、工具版本与输入记录](logs/f298950cf3b549d781b884912385770a/check.json)
执行边界：Internal package-epaxos Go test that emits a durable_meta_case prerequisite event and a durable_meta_record result event carrying the case identity, the raw first four bytes and the bal_persisted boolean.；Test-only harness file added under epaxos/assurance_generated_test.go; no target source or protocol logic is modified.；StableStore is provided as an os.Pipe so the record bytes can be read without touching the filesystem.；The harness calls recordInstanceMetadata directly rather than driving a full replica, because the obligation constrains the bytes this function writes.
固定比较 `CHK-DURABLE-BAL`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case | bal7_vbal2 |
| event | durable_meta_record |
| bal_persisted | false |
| setup.durable | true |
| setup.bal | 7 |
| setup.vbal | 2 |
| durable | true |
| len | 21 |
| field0_4 | 2 |
| status | 3 |
| seq | 5 |
| field0_equals_vbal | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：For an instance with bal=7 and vbal=2 and Durable=true, which value does the record produced by recordInstanceMetadata carry in its first four bytes, and does that value equal bal or vbal?
[受理问题、条件与来源](submissions/bfa7ade4f0e144f18389f96dcc13b289/accepted.json)；[固定输入](submissions/bfa7ade4f0e144f18389f96dcc13b289/inputs/explore_durable_meta_test.go)
<a id="exploration-8933f1bb9e8b452ca7b10f5bfbf24c60"></a>
[探索执行 1](#exploration-8933f1bb9e8b452ca7b10f5bfbf24c60)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/8933f1bb9e8b452ca7b10f5bfbf24c60/check.json)；[实际输出](logs/8933f1bb9e8b452ca7b10f5bfbf24c60/stdout.log)；[诊断](logs/8933f1bb9e8b452ca7b10f5bfbf24c60/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.18 秒；执行进程耗时 6.88 秒；[实际命令、工具版本与输入记录](logs/8933f1bb9e8b452ca7b10f5bfbf24c60/check.json)
[执行输入文件清单](experiments/d7f489f658ad460397497d1162997049/workspace-delta/manifest.json)
[执行后文件清单](experiments/d7f489f658ad460397497d1162997049/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)。
- 共识形成与推进（原文导航摘录）：A coordinator pre-accepts a batch in its own row (B-PROPOSE/B-PHASE1), then aggregates PreAcceptReply: if the fast quorum agrees on seq/deps (allEqual), the trial ballot is the initial ballot, and (for N>7) all…
- 上下文／权威转换（原文导航摘录）：Authority is per instance, carried by bal/vbal (F-BALLOT). A coordinator acquires the trial ballot in startPhase1; acceptors only accept a ballot >= their stored bal, so a higher-ballot message transfers authority away…
- 两条主线的连接（原文导航摘录）：Recovery and formation share the same per-instance facts: a recovering coordinator rebuilds F-PREACCEPT-STATE from the highest-VBallot Prepare replies and then either takes the slow Accept path, TryPreAccept (guarded by…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.37 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.01 分钟 · 受理 continue：Second pass: with the core map accepted (audit_spec_version 1), I investigated the recovery sub-case classifier and TryPreAccept path…。[完整交接](submissions/744172e271234b22825d495be20336c2/accepted.json)

- 9.21 分钟 · 受理 explained：Source investigation answers the Candidate's suspicion by unreachability rather than by the guard working. handlePrepareReply sets subCase…。[完整交接](submissions/3e715deca2464f4e88af8af0dafc4fc8/accepted.json)

- 10.61 分钟 · 受理 continue：New sourced discrepancy on the decision-consumption path (A5). handleCommit (epaxos/epaxos.go:1066-1113) may create a placeholder instance…。[完整交接](submissions/b36b50494b25477e999d1092aaee9b17/accepted.json)

- 11.68 分钟 · 受理 explained：Source investigation answers the reachability premise negatively for the fault model this code implements, so the Candidate is explained…。[完整交接](submissions/81ada17180ae4a918a0038690b75b687/accepted.json)

- 12.88 分钟 · 受理 continue：New sourced discrepancy on the slow Accept path. handlePreAcceptReply acts on a reply carrying a higher ballot than the coordinator's: it…。[完整交接](submissions/747348720ffc442ebcf34adbd6968668/accepted.json)

- 16.76 分钟 · 受理 explained：Source investigation answers the remaining discriminator as a bounded delay rather than an unbounded stall, so the Candidate is explained…。[完整交接](submissions/77fb31e79cf8408d9f960942234b7510/accepted.json)

- 19.95 分钟 · 受理 continue：Promotes the A7 client path from a bare Surface to sourced Behavior/Fact objects and opens a correlation-duty Candidate on it. The map now…。[完整交接](submissions/cb334ea6c71743afb92eba4c478f3dec/accepted.json)

- 21.01 分钟 · 受理 explained：Source investigation answers the pairing premise negatively for this server, so the Candidate is explained rather than escalated. The…。[完整交接](submissions/907903d160ca4670b5d8fb4fb6082c22/accepted.json)

- 22.66 分钟 · 受理 continue：New sourced discrepancy on the durability path (A6) that links to the A2 authority context, and one that is deterministic enough to execute…。[完整交接](submissions/f9c37975b5234dc58dfdf8e245259a5e/accepted.json)

- 23.63 分钟 · 实际执行：Construction exploration for the active Candidate 2347fc91e49249aa8fca5330bbed6102. The harness is an internal (package epaxos) Go test…；探索执行正常结束。[执行记录](logs/8933f1bb9e8b452ca7b10f5bfbf24c60/check.json)

- 24.53 分钟 · 受理 obligation：The exploration executed in the clean copy and produced a deterministic observation: for an instance with bal=7, vbal=2,…。[完整交接](submissions/cb6ec101e4384d5c9dcf3a594e51c459/accepted.json)

- 26.03 分钟 · 修订前 v1：已进入测试，执行失败；性质归因另核；保存的机械比较：结果未确定；复核与修订见各自后续节点。[原固定输入](direct-checks/decbfaafa14d40938532bd389e8bc974/plan.json)；[原执行记录](logs/cbbd8780f7d34c36b5dcdfb1c7b60ba9/check.json)；[原保存评估](direct-checks/decbfaafa14d40938532bd389e8bc974/cbbd8780f7d34c36b5dcdfb1c7b60ba9-assessment.json)

- 27.28 分钟 · 受理 revise_check：The first execution of this direct check (CheckRun cbbd8780f7d34c36b5dcdfb1c7b60ba9) completed and exited 1 as expected, but the recorded…。[完整交接](submissions/91b8f11cbf44454a8e4633a16cb2d0b2/accepted.json)

- 27.41 分钟 · 实际执行：持久化元数据丢失 ballot；已进入测试，执行失败；性质归因另核。[执行记录](logs/f298950cf3b549d781b884912385770a/check.json)

- 28.45 分钟 · 受理 review：持久化元数据丢失 ballot；v2 checker_correspondence: no_issue_found。[完整交接](submissions/4a83d0f622f646eebac0ba86be4b0bf3/accepted.json)

- 30.55 分钟 · 受理 continue：Second, independent core question raised before the run's time boundary, from the quorum arithmetic in replica/replica.go:121-133.…。[完整交接](submissions/1be9c2de76144148a20eb763c777cd2c/accepted.json)

- 32.90 分钟 · 受理 stop：Releasing local work on the quorum-arithmetic Candidate 0922502bc12a4af68ee74cb77942fd72 at the run's time boundary. The question is…。[完整交接](submissions/e57eaf5e2f0e49f48c4d59d6454213eb/accepted.json)

- 33.80 分钟 · 受理 research：Small final source step on the recorded resume condition (membership/liveness) for the paused quorum candidate. The aliveness that gates…。[完整交接](submissions/dd1d4a421bac4fd2a91125e73becfb0c/accepted.json)

- 34.63 分钟 · 受理 research：Final sourced observation on the durability path (A6), recorded because the run's only confirmed violation lives there.…。[完整交接](submissions/2c704c4703fb490e912c2362e466eac9/accepted.json)

- 40.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/b7b4b5f1f3594834babd2d3ec3e2b58f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

纯反馈重复受理 15 次，无新增认识，调用照常计数：[重复原稿](submissions/a80f0fdde680437385306036557e8a58/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/a036d00d6aff4ecb82b54e72d5ca9856/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/e157cfcdd9a64433a38c91fa7eaafb94/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/391ee462f4a649d6ac7b765a1e6c6c53/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/266f15bf34594e2fbd0110200ff6e257/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/9bde62b9cbc6459da4cda9bedea040fe/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/c45039b45ce947f185196bd7777ced4a/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/177fb37bd90f4490af493127b2848671/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/805b6184a8864faa8767236a8a7397c5/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/491cf0f4622d4e998e776446df23a7cd/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/a24514244ccd4c2d8b52dff477d16f6e/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/d09354005750485f85c981ffe0f1eeb9/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/384d9f20ef464aae956f541f378d826f/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/f6c9dcb93826498a8d5ef913f6e75973/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)；[重复原稿](submissions/5bda0b1cc9404f87ac5de84f5aba3e97/accepted.json) → [原交接](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)
已选检查／复核暂无待办；研究范围仍可开放。

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-8933f1bb9e8b452ca7b10f5bfbf24c60)

<a id="candidate-0922502bc12a4af68ee74cb77942fd72"></a>

暂停调查：For an even replica count, do FastQuorumSize = F + (F+1)/2 and SlowQuorumSize = (N+1)/2 still describe sets whose intersection is guaranteed, or can the fast path and recovery decide from non-intersecting sets because neither formula yields a majority for even N?
[候选原文与历史](state.json)
保存的语义未知：Whether N is validated to be odd anywhere at startup (master registration, config parsing) or simply assumed.；Whether the fast path's allEqual and initial-ballot conditions make non-intersecting fast quorums safe even for even N.；Whether recovery's Accept phase restores the majority requirement before committing.
恢复条件：Read the membership/liveness activity (A4): master registration, Alive transitions and reconnect handling, to determine whether a replica can advance crtInstance for a row while being skipped by the Commit broadcast.；Determine whether N parity is enforced outside the captured files (deployment tooling), since the code does not reject even N.；Read handlePrepareReply's restart-with-NOOP branch together with the Accept majority requirement (acceptOKs+1 > N/2) for N=4 to see whether a conflicting commit is prevented in every branch.；After that, decide whether the quorum arithmetic warrants an obligation or whether the Accept majority already covers even N.

<details><summary>地图登记与研究交接</summary>

以下是地图 v6 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)

- core_overview：CommittedUpTo is reported as PreAcceptReply.CommittedDeps and merged only when N>7; for smaller N the coordinator relies on local CommittedUpTo. Whether this is sufficient is a local question, not a…
  尚无精确对应交接。

- B-PROPOSE：Client retry/dedup (TODO in source) is unwritten; not claimed.
  相关交接：[交接 1](submissions/2c704c4703fb490e912c2362e466eac9/accepted.json)

- B-PREACCEPT-ACCEPTOR：The Status>=ACCEPTED && Cmds==nil branch writes r.InstanceSpace[preAccept.LeaderId][preAccept.Instance].Cmds while the local inst is InstanceSpace[preAccept.Replica][preAccept.Instance]; whether…
  尚无精确对应交接。

- B-ACCEPT-REPLY-LEADER：A reply reporting a ballot higher than lb.lastTriedBallot is dropped at the equality gate without counting a nack or calling makeBallot/bcastPrepare, so this handler does not escalate on a higher…
  相关交接：[交接 1](submissions/747348720ffc442ebcf34adbd6968668/accepted.json)；[交接 2](submissions/6d6e424314e745638a850b796e24a055/accepted.json)；[交接 3](submissions/2ef8a727969c4ee0b5a26e048c4e46f2/accepted.json)；[交接 4](submissions/77fb31e79cf8408d9f960942234b7510/accepted.json)；[交接 5](submissions/e5d7c285aca54175897f9f027db77f79/accepted.json)

- B-PREPARE-REPLY-LEADER：The Class-3 vs Class-4 branch conditions are textually identical, so the TryPreAccept path may be unreachable; impact on recovery completeness is unresolved.
  相关交接：[交接 1](submissions/744172e271234b22825d495be20336c2/accepted.json)；[交接 2](submissions/3e715deca2464f4e88af8af0dafc4fc8/accepted.json)；[交接 3](submissions/b36b50494b25477e999d1092aaee9b17/accepted.json)；[交接 4](submissions/81ada17180ae4a918a0038690b75b687/accepted.json)；[交接 5](submissions/77fb31e79cf8408d9f960942234b7510/accepted.json)；[交接 6](submissions/1be9c2de76144148a20eb763c777cd2c/accepted.json)；[交接 7](submissions/e5d7c285aca54175897f9f027db77f79/accepted.json)；[交接 8](submissions/abddd8387e05419f8972ba78a5112f2b/accepted.json)

- B-TPA-REPLY-LEADER：notInQuorum always re-tests the same AcceptorId slot, so the defer-cycle guard may not observe the per-replica quorum; whether a real cycle occurs is unresolved.
  相关交接：[交接 1](submissions/744172e271234b22825d495be20336c2/accepted.json)；[交接 2](submissions/3e715deca2464f4e88af8af0dafc4fc8/accepted.json)

- B-DURABLE-META：Whether any in-repository reader parses the record; no replay path was found in the captured files.
  相关交接：[交接 1](submissions/bfa7ade4f0e144f18389f96dcc13b289/accepted.json)；[交接 2](submissions/cb6ec101e4384d5c9dcf3a594e51c459/accepted.json)；[交接 3](submissions/decbfaafa14d40938532bd389e8bc974/accepted.json)；[交接 4](submissions/91b8f11cbf44454a8e4633a16cb2d0b2/accepted.json)；[交接 5](submissions/21055826ba804d2493688cddd43d2d32/accepted.json)；[交接 6](submissions/2c704c4703fb490e912c2362e466eac9/accepted.json)；[交接 7](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)

- F-DURABLE-META：No consumer of this record was found in the captured files, so how a restart would read bal/vbal is unread.；Whether the missing bal has any observable consequence, given that no replay path exists in…
  相关交接：[交接 1](submissions/bfa7ade4f0e144f18389f96dcc13b289/accepted.json)；[交接 2](submissions/cb6ec101e4384d5c9dcf3a594e51c459/accepted.json)；[交接 3](submissions/decbfaafa14d40938532bd389e8bc974/accepted.json)；[交接 4](submissions/91b8f11cbf44454a8e4633a16cb2d0b2/accepted.json)；[交接 5](submissions/21055826ba804d2493688cddd43d2d32/accepted.json)；[交接 6](submissions/2c704c4703fb490e912c2362e466eac9/accepted.json)；[交接 7](submissions/5ef7276d43f24e8ba232b4ddbb543f7e/accepted.json)

- F-CLIENT-REPLY-LINK：The reply identity is carried but not used to match a reply to a request; whether the client contract requires that match is unread.
  相关交接：[交接 1](submissions/907903d160ca4670b5d8fb4fb6082c22/accepted.json)

- F-EXECUTED：No behavior is recorded as consuming F-EXECUTED; whether any path re-reads executed state (execution ordering, restart replay) is unread.
  尚无精确对应交接。

- F-RECOVERY-DECISION：Recorded as established by the recovery handlers but no explicit consumer is recorded; the resulting bcastAccept/startPhase1 side effects are not modeled as a consuming behavior.
  相关交接：[交接 1](submissions/744172e271234b22825d495be20336c2/accepted.json)；[交接 2](submissions/3e715deca2464f4e88af8af0dafc4fc8/accepted.json)

- surface:replica.Replica.Thrifty / FastQuorumSize / SlowQuorumSize and config-driven quorum files：Which quorum sizes are active (thrifty vs quorum file) determines the fast/slow thresholds used above; membership and quorum selection are unread.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 6 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 2 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 4 项。受理、执行与结论分别计数。

剩余 0.00 秒、76 次 Agent 调用、33 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.16 | 0.00 |
| Agent 调用 | 120 | 44 | 76 |
| 控制器目标执行 | 36 | 3 | 33 |
| 新 Unit | 12 | 1 | 11 |
| 语义复核 | 24 | 1 | 23 |
| 修订 | 12 | 1 | 11 |

受控目标执行进程耗时（正式检查＋探索）：已记录 21.87 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 22.87 秒。

目标执行组成：正式检查 2 次＋探索 1 次，其中执行工具失败／未完成 2 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v57`；展示版本 `audit-products-v57`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/b7b4b5f1f3594834babd2d3ec3e2b58f/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`8.900913598001353`（配置值不表示触发了超时）。
[调用记录](logs/b7b4b5f1f3594834babd2d3ec3e2b58f/check.json)；[stdout](logs/b7b4b5f1f3594834babd2d3ec3e2b58f/stdout.log)；[stderr](logs/b7b4b5f1f3594834babd2d3ec3e2b58f/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：已记录完成事件；产物另行校验。

</details>

</details>

- 失败／未完成：[direct_check](logs/cbbd8780f7d34c36b5dcdfb1c7b60ba9/stdout.log)；[stderr](logs/cbbd8780f7d34c36b5dcdfb1c7b60ba9/stderr.log)；[执行记录](logs/cbbd8780f7d34c36b5dcdfb1c7b60ba9/check.json)
- 失败／未完成：[direct_check](logs/f298950cf3b549d781b884912385770a/stdout.log)；[stderr](logs/f298950cf3b549d781b884912385770a/stderr.log)；[执行记录](logs/f298950cf3b549d781b884912385770a/check.json)
