# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **103.26 分钟**；结束类型：**控制器记录的实际取消**。
已确认违反命题 10 项；检查／复核待办 3 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 范围澄清后 C1 检查复现一致 | 已确认违反；另有场景尚未完成 | 在 C1 声明的当前版本（scope 文本新增“义务止于采纳已报告向量，应用层一致性属…；当前检查尚未完整处置；机械比较：观察到违反；对应性意见：no_issue_found；Direct-check semantic inputs changed; execution requires rechecking；机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与原因](direct-checks/019d50e0557445cab876c45711c3fa7c/be74405317044c1fa5f5151c7815c026-assessment.json)；[完整评估与原因](direct-checks/d41a6af803374db7babd6414603f818e/d5769994f11746fba640e2057fbd13b8-assessment.json)；[完整评估与原因](direct-checks/37b4ebfa5820403cb1454ce673afb1c8/23cff5113484421c9d76595f272184e1-assessment.json)；[完整评估与原因](direct-checks/5628b95927624dba87e9ecd98e1c835d/36887d5bfbc643efbd4ed40b1e1cb4d5-assessment.json)；[争议 ef6b54abce294555b31a3c9a6ca606ac](#issue-ef6b54abce294555b31a3c9a6ca606ac)（继续核对）；[完整评估与原因](direct-checks/a17a0d57124240b4910a375e39863f25/2f186bc17e13432fae3b653b42e46941-assessment.json)；[完整评估与原因](direct-checks/8b7f0c50fdf14ec2ad637ce1cdb3a7a6/4e63644f9e95492cabfea5f571c9c359-assessment.json) | [C1-recovery-adopts-committed-vector](#claim-C1-recovery-adopts-committed-vector) |
| 2. 同一实例在不同副本产生不同的已应用效果 | 已确认违反 | 每个副本用自己的已提交记录执行后，对端状态机读到 04，而恢复者与第三副本读到 (void)，applied_match=false：同一实例在不同副本的状态机效果不同，说明记录层的不一致确实成为可观察的应用层分叉。该结论属于新义务 C3（其范围包含执行该实例），用于确认 C3；它不用于确认 C1。 | [C3-applied-effect-follows-committed-vector](#claim-C3-applied-effect-follows-committed-vector) |
| 3. 被提升为 leader 的副本同样忽略已提交回复 | 已确认违反 | 在提升变体下（IsLeader=true、maxRecvBallot=5），恢复者的新 ballot 为 6 并作为自身 VBallot 上报，对端 vbal=0 的 COMMITTED 回复被跳过（adopted_committed=false），接受轮完成（accept_oks 0→1），恢复者以 NOOP 提交而对端保持… | [C6-recovery-ignores-committed-reply-when-promoted](#claim-C6-recovery-ignores-committed-reply-when-promoted) |
| 4. NOOP 提交使实例所有者空指针崩溃 | 已确认违反 | 由消息创建记录（无 leader bookkeeping）的实例所有者收到一条合法的单 NONE 命令 Commit 后，handleCommit 在重提议分支解引用 inst.lb.clientProposals 触发空指针 panic（事件 panic_value 为 invalid memory address or nil… | [C4-noop-commit-without-bookkeeping](#claim-C4-noop-commit-without-bookkeeping) |
| 5. 接受轮的高 ballot 回复未被记为拒绝 | 已确认违反 | leader 处于 ACCEPTED 轮（lastTriedBallot=3）时收到 ballot=5 的 AcceptReply，处理结果 nacks=0、accept_oks=0、未发出任何消息、状态不变：ballot 相等性判断先返回，使得其后的 nack 分支永远不会执行，副本因此不会因为被拒绝而重新… | [C7-accept-reply-higher-ballot-is-a-rejection](#claim-C7-accept-reply-higher-ballot-is-a-rejection) |
| 6. 本地地址探测失败导致副本无法构造 | 已确认违反 | 在无法访问固定探测地址的环境中，本地地址辅助函数解引用失败的连接并 panic（local_address_probe: panicked=true、nil pointer dereference、未产出地址）。由于副本构造把该调用作为参数内联求值，此类环境下任何副本都无法完成构造；源码层面的缺陷（丢弃 dial… | [C11-replica-startup-avoids-external-probe](#claim-C11-replica-startup-avoids-external-probe) |
| 7. 稳定存储元数据记录丢失 bal 字段 | 已确认违反 | 启用 Durable 后，recordInstanceMetadata 产出的头部为 04030201\|03\|100f0e0d\|deps：偏移 0 处是 vbal 的四个字节，写入的 bal 值不在记录中（bal_field_present=false），Status 落在第 4 字节、Seq 位于… | [C2-durable-record-preserves-written-fields](#claim-C2-durable-record-preserves-written-fields) |
| 8. 恢复主导的阶段一按自身行记录元数据 | 已确认违反 | 在 Durable=true 且恢复者自身行没有该实例的情况下，startPhase1 为他人实例写入记录：实例已安装在所有者行（owner_record_written=true），但元数据记录调用解引用恢复者自身行的实例（own_row_record_written=false）并以空指针 panic… | [C9-durable-recorder-uses-the-instance-row](#claim-C9-durable-recorder-uses-the-instance-row) |
| 9. 命令值长度在网络上被静默截断 | 已确认违反 | 经真实编解码往返：声明 70000 字节的值在线上写出 70013 字节，解码仅得 4464 字节（70000 mod 65536），且只消费 4477 字节，value_matches=false；剩余字节留在流中会错位后续消息边界。该结论成立的前提是“调用方可以构造超过 65535… | [C10-command-value-length-survives-the-wire](#claim-C10-command-value-length-survives-the-wire) |
| 10. 传递冲突跳过开关未生效 | 已确认违反 | 在开启 transconf 的情况下，已提交实例的命令与唯一依赖（另一键上的未提交命令）互不冲突（commands_commute=true），但执行器仍未执行该实例（executed=false，依赖仍为… | [C12-transitive-skip-executes-commuting-command](#claim-C12-transitive-skip-executes-commuting-command) |
| 11. 执行器超时会将被阻塞实例入队恢复 | 有限检查未见违反 | 行 1 被一条无命令且未提交的记录阻塞时（前置事件：status 0、has_commands false、crtInstance 0、ExecedUpTo -1），执行器在约 12.6 秒后把该实例入队：enqueued true、enqueued_replica 1、enqueued_instance… | [C8-timeout-enqueues-blocked-instance](#claim-C8-timeout-enqueues-blocked-instance) |
| 12. When a replica that owns an instance and still holds an admitted client operation for it receives a commit carrying a single NONE…（原文摘录） | 待调查线索 | 机械比较：有限检查未见违反；对应性意见：尚未记录；待当前版本复核；[完整评估与原因](direct-checks/9b615e3c5b0c4808a50c9eee56cc92b2/6baf5b7715294d88a8f4a36e085ebd04-assessment.json) | [C5-noop-commit-reproposes-admitted-operation](#claim-C5-noop-commit-reproposes-admitted-operation) |
| When a replica receives PreAccept for instance (Replica, Instance) while its local record for that instance already has Status >=… | 暂停调查，尚无正式义务 | semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit… | [候选 1](#candidate-d8fd7f585e054fdba265f29c8f7bff4d) |
| handlePreAcceptReply commits when preAcceptOKs >= FastQuorumSize-1 and inst.lb.allEqual && allCommitted && isInitialBallot, but… | 暂停调查，尚无正式义务 | semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit… | [候选 2](#candidate-7f783892c49e46fc82948aa0546d3db7) |
| handleAccept stores Deps, Seq, bal and vbal for instance (Replica, Instance) and never writes inst.Status, so a replica in the… | 暂停调查，尚无正式义务 | semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit… | [候选 3](#candidate-229322fc84e94259a5609cbcad40732d) |
| startRecoveryForInstance seeds LeaderBookkeeping with lb.ballot = the record's old vbal, then makes a new ballot and sets… | 暂停调查，尚无正式义务 | semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit… | [候选 4](#candidate-41661c6204434eb0a8f00129ac08d438) |
| When recovery commits a NOOP vector for an instance owned by another replica, the client operation that was attached to the… | 暂停调查，尚无正式义务 | semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit… | [候选 8](#candidate-b7160e779313408b8d1f7e88b35e71c5) |

<a id="claim-C1-recovery-adopts-committed-vector"></a>

### 1. 范围澄清后 C1 检查复现一致

**已确认违反**。要求原文：When recovery runs for instance (Replica, Instance) and a slow-quorum PrepareReply reports that instance COMMITTED with a command vector, the recovering replica must adopt that committed vector (Status COMMITTED carrying the committed commands) rather than continuing from its own record and restarting phase 1 with a different command.

决定性范围：Recovery decision for a single instance on the captured snapshot: N=3 with Thrifty and IsLeader false, the recovering replica holding only a default NONE record, one peer holding a COMMITTED record with a real command, and no third replica reply required. The obligation ends at adopting the reported committed vector; what each replica then applies is a separate obligation (claim C3).
the recovering replica's own record carries no commands；a slow quorum (its own entry plus one reply) is sufficient to resolve；messages are delivered through the real wire format。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/019d50e0557445cab876c45711c3fa7c/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/019d50e0557445cab876c45711c3fa7c/plan.json)；[原始观察](logs/be74405317044c1fa5f5151c7815c026/stdout.log)；[assessment](direct-checks/019d50e0557445cab876c45711c3fa7c/be74405317044c1fa5f5151c7815c026-assessment.json)；[对应性复核](submissions/b05bee9060d54f7a9a74c709330af5e4/accepted.json)

当前争议／阻塞：当前检查尚未完整处置；机械比较：观察到违反；对应性意见：no_issue_found；Direct-check semantic inputs changed; execution requires rechecking；[完整评估与阻塞](direct-checks/019d50e0557445cab876c45711c3fa7c/be74405317044c1fa5f5151c7815c026-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.21 秒；执行进程耗时 7.88 秒；[实际命令、工具版本与输入记录](logs/be74405317044c1fa5f5151c7815c026/check.json)
执行边界：In-package Go test building two real Replica values and delivering Prepare/PrepareReply through their real Marshal/Unmarshal form.；harness-only scaffolding: two Replica values are constructed in-package instead of through New(), per-peer buffers replace the TCP transport, and the recovery is entered directly through startRecoveryForInstance instead of the execution timeout; all protocol messages still travel through the real Marshal/Unmarshal form and all decisions are made by the unmodified handlers；prepared history: the peer's record for the instance is installed as COMMITTED with a real PUT command and the recovering replica's record is a default NONE record, because the check discriminates the resolution step rather than the proposal round that produced the commit
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/d41a6af803374db7babd6414603f818e/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/d41a6af803374db7babd6414603f818e/plan.json)；[原始观察](logs/d5769994f11746fba640e2057fbd13b8/stdout.log)；[assessment](direct-checks/d41a6af803374db7babd6414603f818e/d5769994f11746fba640e2057fbd13b8-assessment.json)

当前争议／阻塞：机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与阻塞](direct-checks/d41a6af803374db7babd6414603f818e/d5769994f11746fba640e2057fbd13b8-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.81 秒；执行进程耗时 7.46 秒；[实际命令、工具版本与输入记录](logs/d5769994f11746fba640e2057fbd13b8/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-accept-round-counted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | accept_round_after_commit |
| reply_counted | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks_after | 0 |
| accept_oks_before | 0 |
| committed_at_recoverer | false |
| instance_status_after | ACCEPTED |
| last_tried_ballot | 3 |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/37b4ebfa5820403cb1454ce673afb1c8/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/37b4ebfa5820403cb1454ce673afb1c8/plan.json)；[原始观察](logs/23cff5113484421c9d76595f272184e1/stdout.log)；[assessment](direct-checks/37b4ebfa5820403cb1454ce673afb1c8/23cff5113484421c9d76595f272184e1-assessment.json)；[对应性复核](submissions/caf0f7ba5dc04822ae4c44e33e283670/accepted.json)

当前争议／阻塞：当前检查尚未完整处置；机械比较：观察到违反；对应性意见：no_issue_found；Direct-check semantic inputs changed; execution requires rechecking；[完整评估与阻塞](direct-checks/37b4ebfa5820403cb1454ce673afb1c8/23cff5113484421c9d76595f272184e1-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.52 秒；执行进程耗时 7.26 秒；[实际命令、工具版本与输入记录](logs/23cff5113484421c9d76595f272184e1/check.json)
执行边界：In-package Go test building two real Replica values and delivering Prepare/PrepareReply through their real Marshal/Unmarshal form.；harness-only scaffolding: two Replica values are constructed in-package instead of through New(), per-peer buffers replace the TCP transport, and the recovery is entered directly through startRecoveryForInstance instead of the execution timeout; all protocol messages still travel through the real Marshal/Unmarshal form and all decisions are made by the unmodified handlers；prepared history: the peer's record for the instance is installed as COMMITTED with a real PUT command and the recovering replica's record is a default NONE record, because the check discriminates the resolution step rather than the proposal round that produced the commit；the harness drives the queued rounds explicitly and in order (PreAccept, its reply, Accept, its reply) and re-reads InstanceSpace after every delivery, because startPhase1 replaces the record object
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/5628b95927624dba87e9ecd98e1c835d/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/5628b95927624dba87e9ecd98e1c835d/plan.json)；[原始观察](logs/36887d5bfbc643efbd4ed40b1e1cb4d5/stdout.log)；[assessment](direct-checks/5628b95927624dba87e9ecd98e1c835d/36887d5bfbc643efbd4ed40b1e1cb4d5-assessment.json)；[对应性复核](submissions/0538f396b6f14c09bfd5153dcb8025c5/accepted.json)

当前争议／阻塞：当前检查尚未完整处置；机械比较：观察到违反；对应性意见：no_issue_found；Direct-check semantic inputs changed; execution requires rechecking；[完整评估与阻塞](direct-checks/5628b95927624dba87e9ecd98e1c835d/36887d5bfbc643efbd4ed40b1e1cb4d5-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.46 秒；执行进程耗时 7.07 秒；[实际命令、工具版本与输入记录](logs/36887d5bfbc643efbd4ed40b1e1cb4d5/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | NONE |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：观察到违反；对应性意见：revision_needed；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/a17a0d57124240b4910a375e39863f25/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/a17a0d57124240b4910a375e39863f25/plan.json)；[原始观察](logs/2f186bc17e13432fae3b653b42e46941/stdout.log)；[assessment](direct-checks/a17a0d57124240b4910a375e39863f25/2f186bc17e13432fae3b653b42e46941-assessment.json)；[对应性复核](submissions/6ee2ff2f40f34b9bacfc24eacc4d95be/accepted.json)

当前争议／阻塞：已有复核争议，处理要求见对应争议；机械比较：观察到违反；对应性意见：revision_needed；[争议 ef6b54abce294555b31a3c9a6ca606ac](#issue-ef6b54abce294555b31a3c9a6ca606ac)（继续核对）；[完整评估与阻塞](direct-checks/a17a0d57124240b4910a375e39863f25/2f186bc17e13432fae3b653b42e46941-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.91 秒；执行进程耗时 7.56 秒；[实际命令、工具版本与输入记录](logs/2f186bc17e13432fae3b653b42e46941/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | NONE |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH4-applied-state`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | applied_state_divergence |
| applied_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| peer_value | 04 |
| recoverer_value | (void) |
| third_value | (void) |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/8b7f0c50fdf14ec2ad637ce1cdb3a7a6/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/8b7f0c50fdf14ec2ad637ce1cdb3a7a6/plan.json)；[原始观察](logs/4e63644f9e95492cabfea5f571c9c359/stdout.log)；[assessment](direct-checks/8b7f0c50fdf14ec2ad637ce1cdb3a7a6/4e63644f9e95492cabfea5f571c9c359-assessment.json)；[对应性复核](submissions/0909fc33bcf84c1d897da2518c7c8136/accepted.json)

当前争议／阻塞：当前检查尚未完整处置；机械比较：观察到违反；对应性意见：no_issue_found；Direct-check semantic inputs changed; execution requires rechecking；[完整评估与阻塞](direct-checks/8b7f0c50fdf14ec2ad637ce1cdb3a7a6/4e63644f9e95492cabfea5f571c9c359-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.26 秒；执行进程耗时 6.98 秒；[实际命令、工具版本与输入记录](logs/4e63644f9e95492cabfea5f571c9c359/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | NONE |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：范围澄清后 C1 检查复现一致；在 C1 声明的当前版本（scope 文本新增“义务止于采纳已报告向量，应用层一致性属 C3”）下重新执行同一驱动：解析处未采纳（adopted_committed=false）、恢复者与已提交副本向量不同（vectors_match=false）、提交广播后三副本不一致（all_committed_match=false），与既有结论一致。增量仅是范围文字，义务、条件、前置、身份与驱动轮次未变。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/1814c432ed61402685390aac90035264/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/1814c432ed61402685390aac90035264/plan.json)；[原始观察](logs/32aff0d098454dc78bec6a3916753fa9/stdout.log)；[assessment](direct-checks/1814c432ed61402685390aac90035264/32aff0d098454dc78bec6a3916753fa9-assessment.json)；[对应性复核](submissions/b209d81a642341709ae243a5fb6fb9b9/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.70 秒；执行进程耗时 7.48 秒；[实际命令、工具版本与输入记录](logs/32aff0d098454dc78bec6a3916753fa9/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | NONE |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：完整历史下仍忽略已提交回复并提交 NOOP；先由所有者（副本 1）真实提案并被快速路径提交（proposal_committed: leader_status=4、third_status=4、command_is_put=true，提交仅投递给副本 2），随后副本 0 以默认记录恢复同一实例：仍未采纳 COMMITTED 回复（adopted_committed=false），接受轮完成后以 NOOP 提交（vectors_match=false、all_committed_match=false），应用状态分叉（recoverer (void) 对 peer/third 04）。因此在由真实提案与提交产生的历史中同样成立，先前“已提交记录为预备状态”的限制不再适用。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/7cb7efc6e1864f7ba3bd5fc6738253de/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/7cb7efc6e1864f7ba3bd5fc6738253de/plan.json)；[原始观察](logs/e8ad6c82f0134b81adb2ed772108ab78/stdout.log)；[assessment](direct-checks/7cb7efc6e1864f7ba3bd5fc6738253de/e8ad6c82f0134b81adb2ed772108ab78-assessment.json)；[对应性复核](submissions/d1cf9ae8895b4b0da049e736e8f4ab9c/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.18 秒；执行进程耗时 7.82 秒；[实际命令、工具版本与输入记录](logs/e8ad6c82f0134b81adb2ed772108ab78/check.json)
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | PUT |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C3-applied-effect-follows-committed-vector"></a>

### 2. 同一实例在不同副本产生不同的已应用效果

**已确认违反**。要求原文：When several replicas each hold the same instance committed and each applies it to its own copy of the state machine, the effect they apply for the instance's key must be the same, because the applied effect is determined by the committed command vector of that instance.

决定性范围：One instance held committed at three replicas on the captured snapshot, each applied through Exec.executeCommand with a GET probe reading the instance's key from the replicated store.
each replica's record for the instance is COMMITTED and its dependencies are already satisfied locally；the key is the one the committed commands touch。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：同一实例在不同副本产生不同的已应用效果；每个副本用自己的已提交记录执行后，对端状态机读到 04，而恢复者与第三副本读到 (void)，applied_match=false：同一实例在不同副本的状态机效果不同，说明记录层的不一致确实成为可观察的应用层分叉。该结论属于新义务 C3（其范围包含执行该实例），用于确认 C3；它不用于确认 C1。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/98429ce4bce9483eb774290e61719361/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/98429ce4bce9483eb774290e61719361/plan.json)；[原始观察](logs/ef136d1e25924ce59ccedc4fe9e2af2e/stdout.log)；[assessment](direct-checks/98429ce4bce9483eb774290e61719361/ef136d1e25924ce59ccedc4fe9e2af2e-assessment.json)；[对应性复核](submissions/880ad24d41e14ba5a2bf8c75fb5c8bdc/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.79 秒；执行进程耗时 7.41 秒；[实际命令、工具版本与输入记录](logs/ef136d1e25924ce59ccedc4fe9e2af2e/check.json)
执行边界：In-package Go test that drives the recovery path, applies each replica's committed instance through the real executor and compares the applied values for the instance's key.；harness-only scaffolding: Replica values are constructed in-package, per-peer buffers replace the transport, and the recovery and execution are entered directly (startRecoveryForInstance, Exec.executeCommand) instead of through the execution loop; the handlers, executor and state application are unmodified；prepared history: the already-committed record is installed directly, as in the earlier checks
固定比较 `CH1-applied-effect`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | applied_state_divergence |
| applied_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| peer_value | 04 |
| recoverer_value | (void) |
| third_value | (void) |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：真实历史下应用层效果同样分叉；先是所有者真实提案并被快速路径提交（proposal_committed: leader_status=4、third_status=4），随后未见过该实例的副本恢复并提交 NOOP 向量；各副本用自身已提交记录执行后，恢复者对实例键没有任何效果，而另外两个副本应用了真实 PUT（applied_match=false，peer/third 均为 04、recoverer 为 (void)）。因此应用层分叉不再依赖预备的已提交记录，而是由真实提案、提交与恢复历史产生。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/17a28afd6963422f8adcd2945d928c97/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/17a28afd6963422f8adcd2945d928c97/plan.json)；[原始观察](logs/3843884f43014d8fb768c85ea38f11d8/stdout.log)；[assessment](direct-checks/17a28afd6963422f8adcd2945d928c97/3843884f43014d8fb768c85ea38f11d8-assessment.json)；[对应性复核](submissions/42a3014a58dc4f1a8d05d446989937e3/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.80 秒；执行进程耗时 7.40 秒；[实际命令、工具版本与输入记录](logs/3843884f43014d8fb768c85ea38f11d8/check.json)
固定比较 `CH1-applied-effect`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | applied_state_divergence |
| applied_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| peer_value | 04 |
| recoverer_value | (void) |
| third_value | 04 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C6-recovery-ignores-committed-reply-when-promoted"></a>

### 3. 被提升为 leader 的副本同样忽略已提交回复

**已确认违反**。要求原文：When a replica that the deployment promoted to leader (IsLeader true, with a ballot history) recovers an instance and a slow-quorum reply reports that instance COMMITTED with a command vector, the recovering replica must adopt that committed vector rather than restarting phase 1 with a different command.

决定性范围：Promoted-leader variant on the captured snapshot: N=3 with Thrifty, the recovering replica has IsLeader true and a maxRecvBallot above its own ballot base, one peer holds the instance COMMITTED with a real command, and the recovering replica holds a default record for it.
the recovering replica is the replica the master designated through Replica.BeTheLeader；a slow quorum (its own entry plus one reply) is sufficient to resolve。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：被提升为 leader 的副本同样忽略已提交回复；在提升变体下（IsLeader=true、maxRecvBallot=5），恢复者的新 ballot 为 6 并作为自身 VBallot 上报，对端 vbal=0 的 COMMITTED 回复被跳过（adopted_committed=false），接受轮完成（accept_oks 0→1），恢复者以 NOOP 提交而对端保持 PUT（vectors_match=false、all_committed_match=false），应用状态同样分叉。该结论属于 C6（仅限提升变体），C1 的已确认范围保持不变。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/d990d0e9d1d64f6d8059bd859a27ad38/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/d990d0e9d1d64f6d8059bd859a27ad38/plan.json)；[原始观察](logs/4e8a4b74d9404772b366f3f2af6a075c/stdout.log)；[assessment](direct-checks/d990d0e9d1d64f6d8059bd859a27ad38/4e8a4b74d9404772b366f3f2af6a075c-assessment.json)；[对应性复核](submissions/b8f5fc5236364e2fbd19adf43b8f0cfe/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.83 秒；执行进程耗时 7.48 秒；[实际命令、工具版本与输入记录](logs/4e8a4b74d9404772b366f3f2af6a075c/check.json)
执行边界：In-package Go test building two real Replica values and delivering Prepare/PrepareReply through their real Marshal/Unmarshal form.；harness-only scaffolding: two Replica values are constructed in-package, per-peer buffers replace the transport, and recovery is entered directly through startRecoveryForInstance; handlers are unmodified；variant: the recovering replica has IsLeader true and maxRecvBallot set above its ballot base, modelling the replica the master promoted after it had already seen traffic
固定比较 `CH1-recovery-adopts-committed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_resolution |
| adopted_committed | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| command_after | NONE |
| instance_status | PREACCEPTED |
| preaccept_sent | true |
| recoverer | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH2-recovery-outcome`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | recovery_outcome |
| vectors_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| accept_oks | 1 |
| peer_committed_command | PUT |
| recoverer_command | NONE |
| recoverer_committed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `CH3-commit-propagation`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | commit_propagation_divergence |
| all_committed_match | false |
| committed_reply.status | COMMITTED |
| committed_reply.has_command | true |
| replica0_command | NONE |
| replica1_command | PUT |
| replica2_command | NONE |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C4-noop-commit-without-bookkeeping"></a>

### 4. NOOP 提交使实例所有者空指针崩溃

**已确认违反**。要求原文：When a replica receives a legal Commit carrying a single NONE command for an instance it owns, and its record for that instance was created by a message so that it has no leader bookkeeping, handleCommit must process the commit (install it as committed) without dereferencing the absent bookkeeping and without terminating the replica.

决定性范围：One replica owning instance (0,0) whose record was created by a recovery-led PreAccept, receiving one Commit with a single NONE command at a ballot at or above its own.
the record exists only because a message created it (newInstanceDefault leaves leader bookkeeping nil)；the commit is well formed for that instance。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：NOOP 提交使实例所有者空指针崩溃；由消息创建记录（无 leader bookkeeping）的实例所有者收到一条合法的单 NONE 命令 Commit 后，handleCommit 在重提议分支解引用 inst.lb.clientProposals 触发空指针 panic（事件 panic_value 为 invalid memory address or nil pointer dereference），且该提交未生效（no_effect=true）。运行循环对该处理器没有 recover，因此该 panic 会终止副本进程；这一推断属于限制说明，harness 只观察到 panic 本身。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/2e078ae6694f422b9c95a5de620b02fe/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/2e078ae6694f422b9c95a5de620b02fe/plan.json)；[原始观察](logs/117697084648408998b24f05ce690f68/stdout.log)；[assessment](direct-checks/2e078ae6694f422b9c95a5de620b02fe/117697084648408998b24f05ce690f68-assessment.json)；[对应性复核](submissions/6606835070d34626a5ae5707069eea29/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 6.99 秒；执行进程耗时 6.81 秒；[实际命令、工具版本与输入记录](logs/117697084648408998b24f05ce690f68/check.json)
执行边界：In-package Go test that creates the message-made record with the real handler and then delivers a legal NOOP Commit, recovering the panic so the observation is reported instead of killing the test process.；harness-only scaffolding: the Replica is constructed in-package, peer writers are buffers, and the two handlers are called directly; the handlers are unmodified；the harness wraps the commit delivery in recover() purely to observe a panic; production runs the handler inside the run loop where no recover exists
固定比较 `CH1-noop-commit`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 0.0 |
| event | handle_commit_result |
| panicked | true |
| message_record.bookkeeping_nil | true |
| instance_status_after | 2 |
| no_effect | true |
| panic_value | runtime error: invalid memory address or nil pointer dereference |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：重启历史下 NOOP 提交同样使所有者崩溃；先由所有者真实接纳一条客户端操作（proposal_before_restart: 有 bookkeeping、pending=1、status=PREACCEPTED），随后以“新的空副本”模拟重启（after_restart: 无记录），恢复主导的 PreAccept 再建记录（bookkeeping_nil=true），最后合法的单 NONE Commit 触发空指针 panic（panicked=true、no_effect=true）。因此该崩溃不再依赖“消息创建的孤立记录”，而是完整历史的结果；进程终止仍是从运行循环没有 recover 推出的限制项。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/591771a0e72e477e8385e62f0f3aaeb5/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/591771a0e72e477e8385e62f0f3aaeb5/plan.json)；[原始观察](logs/ae38ca8c77904887841a0e73145db7f5/stdout.log)；[assessment](direct-checks/591771a0e72e477e8385e62f0f3aaeb5/ae38ca8c77904887841a0e73145db7f5-assessment.json)；[对应性复核](submissions/be61a71b21da4a498be1873838911112/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.50 秒；执行进程耗时 8.19 秒；[实际命令、工具版本与输入记录](logs/ae38ca8c77904887841a0e73145db7f5/check.json)
固定比较 `CH1-noop-commit`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 0.0 |
| event | handle_commit_result |
| panicked | true |
| message_record.bookkeeping_nil | true |
| instance_status_after | 2 |
| no_effect | true |
| panic_value | runtime error: invalid memory address or nil pointer dereference |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C7-accept-reply-higher-ballot-is-a-rejection"></a>

### 5. 接受轮的高 ballot 回复未被记为拒绝

**已确认违反**。要求原文：When a replica leading the accept phase for an instance receives an AcceptReply whose ballot is higher than the ballot of that round, the reply must be treated as a rejection: the leader must count it as a nack and, once a majority has nacked, make a new ballot and run prepare again, instead of leaving the round unchanged.

决定性范围：One leader in the ACCEPTED state for instance (1,0) at ballot 3 receives one AcceptReply with ballot 5 from a peer that has promised a higher ballot; N=3 with Thrifty and IsLeader true.
the reply is the one a peer sends when its stored bal exceeds the accept round's ballot；the leader's round is otherwise unchanged。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：接受轮的高 ballot 回复未被记为拒绝；leader 处于 ACCEPTED 轮（lastTriedBallot=3）时收到 ballot=5 的 AcceptReply，处理结果 nacks=0、accept_oks=0、未发出任何消息、状态不变：ballot 相等性判断先返回，使得其后的 nack 分支永远不会执行，副本因此不会因为被拒绝而重新 prepare。该结论的后果限于碰撞路径上的延迟，因为 10s 执行超时仍可驱动恢复。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/5819488989f747918187d3a781c197b5/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/5819488989f747918187d3a781c197b5/plan.json)；[原始观察](logs/1da816760c9246ee99d9dd60e19d85cb/stdout.log)；[assessment](direct-checks/5819488989f747918187d3a781c197b5/1da816760c9246ee99d9dd60e19d85cb-assessment.json)；[对应性复核](submissions/c64768fe69b44a82a7607c5baed7d1ad/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.13 秒；执行进程耗时 7.82 秒；[实际命令、工具版本与输入记录](logs/1da816760c9246ee99d9dd60e19d85cb/check.json)
执行边界：In-package Go test that prepares an ACCEPTED leader round and delivers one higher-ballot AcceptReply to the real handler, reporting the counters and any emitted message.；harness-only scaffolding: the Replica is constructed in-package with buffer peer writers, the round is built with the package's own instance and bookkeeping constructors, and the reply is delivered directly to the handler；the reply is the value handleAccept produces for a peer with a higher stored bal; no protocol code is modified
固定比较 `CH1-accept-reply`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | accept_reply_higher_ballot |
| nacks | 0 |
| accept_round.status | 3 |
| accept_round.last_tried_ballot | 3 |
| accept_oks | 0 |
| prepare_sent | false |
| reply_ballot | 5 |
| status_after | 3 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C11-replica-startup-avoids-external-probe"></a>

### 6. 本地地址探测失败导致副本无法构造

**已确认违反**。要求原文：Constructing a replica must not depend on reaching a fixed external probe address: when that address cannot be dialled, the startup path must still produce a replica (or fail deliberately) instead of dereferencing a failed connection.

决定性范围：Replica construction on the captured snapshot in an environment where the fixed probe address cannot be dialled: the constructor's inline local-address helper is evaluated as an argument to the latency table.
the probe address is fixed in the helper rather than taken from configuration；the constructor evaluates the helper unconditionally, whatever the latency configuration。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：本地地址探测失败导致副本无法构造；在无法访问固定探测地址的环境中，本地地址辅助函数解引用失败的连接并 panic（local_address_probe: panicked=true、nil pointer dereference、未产出地址）。由于副本构造把该调用作为参数内联求值，此类环境下任何副本都无法完成构造；源码层面的缺陷（丢弃 dial 错误并解引用连接）与环境无关，观察只是在该类环境中给出实例。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/1d2e0b84ef284890841b627cd1196b30/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/1d2e0b84ef284890841b627cd1196b30/plan.json)；[原始观察](logs/c1d2d57fdb7b468ca92aedca9f620d83/stdout.log)；[assessment](direct-checks/1d2e0b84ef284890841b627cd1196b30/c1d2d57fdb7b468ca92aedca9f620d83-assessment.json)；[对应性复核](submissions/ad9eb64bc1094fc7a5d776cc6f9fd244/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.88 秒；执行进程耗时 7.47 秒；[实际命令、工具版本与输入记录](logs/c1d2d57fdb7b468ca92aedca9f620d83/check.json)
执行边界：In-package Go test that calls the implementation's local-address helper and reports whether it returns or panics.；harness-only scaffolding: no replica is constructed; the helper is called directly；the call is wrapped in recover() to observe a panic; the replica constructor has no recover around it
固定比较 `CH1-probe`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| subject | local-address |
| event | local_address_probe |
| panicked | true |
| panic_value | runtime error: invalid memory address or nil pointer dereference |
| value_len | 0 |
| value_nonempty | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C2-durable-record-preserves-written-fields"></a>

### 7. 稳定存储元数据记录丢失 bal 字段

**已确认违反**。要求原文：When Durable is enabled, recordInstanceMetadata writes the current bal, vbal, Status, Seq and Deps of an instance into the stable store; the record it produces must let each field it writes be recovered at the offset where the writer placed it, so that no value it wrote is silently replaced by another field of the same record.

决定性范围：One call to recordInstanceMetadata with Durable true, N=3, and distinct values for bal, vbal, Status and Seq, followed by sync.
the field order the writer uses is bal, vbal, Status, Seq, then Deps；the record begins at the current end of the stable store。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：稳定存储元数据记录丢失 bal 字段；启用 Durable 后，recordInstanceMetadata 产出的头部为 04030201|03|100f0e0d|deps：偏移 0 处是 vbal 的四个字节，写入的 bal 值不在记录中（bal_field_present=false），Status 落在第 4 字节、Seq 位于 [5:9)。该观察只针对一次真实写入所产出的记录，读取方缺失与默认配置 durable=false 属于限制而非本次判定的一部分。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/ec0b2c5424a544cfa69fc816a17acdf2/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/ec0b2c5424a544cfa69fc816a17acdf2/plan.json)；[原始观察](logs/310d33db15394688a5ee2d808ed3a4a3/stdout.log)；[assessment](direct-checks/ec0b2c5424a544cfa69fc816a17acdf2/310d33db15394688a5ee2d808ed3a4a3-assessment.json)；[对应性复核](submissions/9bbaf65f5135439580d764e38328fccd/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.09 秒；执行进程耗时 7.76 秒；[实际命令、工具版本与输入记录](logs/310d33db15394688a5ee2d808ed3a4a3/check.json)
执行边界：In-package Go test that runs the real metadata recorder against a temp stable store and reports the resulting header bytes.；harness-only scaffolding: the Replica is constructed in-package instead of through New(), the stable store is a harness temp file, and the instance is built directly with distinct field values; the recorder and sync under test are the unmodified implementation
固定比较 `CH1-durable-record`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 0.0 |
| event | durable_record_header |
| bal_field_present | false |
| write_request.durable | true |
| bal_at_0 | false |
| header_hex | 0403020103100f0e0d020000000300000004000000 |
| header_len | 21 |
| record_len | 21 |
| seq_at_5 | true |
| status_at_4 | true |
| vbal_at_0 | true |
| written_bal | 168496141 |
| written_seq | 219025168 |
| written_status | 3 |
| written_vbal | 16909060 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C9-durable-recorder-uses-the-instance-row"></a>

### 8. 恢复主导的阶段一按自身行记录元数据

**已确认违反**。要求原文：When a replica starts phase 1 for an instance owned by another replica (the recovery-led case) with Durable enabled, the metadata recorder must be given the record of that instance, and the call must not dereference a record the recovering replica does not hold.

决定性范围：Recovery-led startPhase1 on the captured snapshot: Durable true, the recovering replica is not the instance owner, and its own row holds no record at that instance number.
the recovering replica's row has no instance at that number, which is the state after a restart；the recorder is enabled through the Durable flag。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：恢复主导的阶段一按自身行记录元数据；在 Durable=true 且恢复者自身行没有该实例的情况下，startPhase1 为他人实例写入记录：实例已安装在所有者行（owner_record_written=true），但元数据记录调用解引用恢复者自身行的实例（own_row_record_written=false）并以空指针 panic 结束（panicked=true）。因此记录的坐标与实际写入的实例不一致；该结论的后果限于启用 Durable 的调用方（默认配置为 false），槽位恰好存在时的错误记录仍是未验证的隐含问题。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/b2d21668f98b4b2d980c6efacdb1fb0a/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/b2d21668f98b4b2d980c6efacdb1fb0a/plan.json)；[原始观察](logs/f7a553d13ff640088cdf4c145842172f/stdout.log)；[assessment](direct-checks/b2d21668f98b4b2d980c6efacdb1fb0a/f7a553d13ff640088cdf4c145842172f-assessment.json)；[对应性复核](submissions/acbedec9212f4b04b3c616e890f0b465/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.77 秒；执行进程耗时 7.37 秒；[实际命令、工具版本与输入记录](logs/f7a553d13ff640088cdf4c145842172f/check.json)
执行边界：In-package Go test that runs the real startPhase1 for another replica's instance with recording enabled and reports whether the metadata call terminates.；harness-only scaffolding: the Replica is constructed in-package, the stable store is a harness temp file, and startPhase1 is called directly with the owner's coordinates instead of through the prepare resolution；the harness wraps the call in recover() to observe a panic; production runs it inside the prepare path
固定比较 `CH1-phase1-record`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | durable_phase1_result |
| panicked | true |
| leader_row.durable | true |
| leader_row.own_row_record_present | false |
| own_row_record_written | false |
| owner_record_written | true |
| panic_value | runtime error: invalid memory address or nil pointer dereference |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：自身行已占用时记录了他实例的元数据；当恢复者自身行在同一编号已存在另一实例（own_row_seq 858993459、ACCEPTED）时，阶段一为所有者实例写记录：写入的 seq 等于自身行的 seq 而非新实例的 seq 0（recorded_matches_new_instance=false、recorded_matches_own_row=true，状态为自身行的 ACCEPTED），即稳定存储收到的是另一实例的 ballot 上下文，且不会 panic。该结论限于启用记录的调用方（默认 durable=false），解码使用记录器自身布局这一限制也已注明。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/697df300b08f4120bcd530a1d7691f87/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/697df300b08f4120bcd530a1d7691f87/plan.json)；[原始观察](logs/9519d0683f344690959f2d64bac8f404/stdout.log)；[assessment](direct-checks/697df300b08f4120bcd530a1d7691f87/9519d0683f344690959f2d64bac8f404-assessment.json)；[对应性复核](submissions/7f96b08929304f188a3f7ffba873f9e0/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.74 秒；执行进程耗时 7.46 秒；[实际命令、工具版本与输入记录](logs/9519d0683f344690959f2d64bac8f404/check.json)
执行边界：In-package Go test that seeds the recovering replica's own row, runs the real phase-1 entry with recording enabled and decodes the metadata the recorder wrote.；harness-only scaffolding: the Replica is constructed in-package with a harness temp stable store and startPhase1 is called directly with the owner's coordinates；the own row is seeded with a synthetic instance so the two rows differ; protocol code is unmodified
固定比较 `CH2-wrong-row-record`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| instance | 1.0 |
| event | durable_wrong_row_recorded |
| recorded_matches_new_instance | false |
| two_rows.durable | true |
| bytes_written | 35 |
| new_instance_seq | 0 |
| own_row_seq | 858993459 |
| recorded_matches_own_row | true |
| recorded_seq | 858993459 |
| recorded_status | 3 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C10-command-value-length-survives-the-wire"></a>

### 9. 命令值长度在网络上被静默截断

**已确认违反**。要求原文：The command codec must carry the value length the client's configured command size permits: a command value that the client can build must either survive a marshal/unmarshal round trip unchanged or be rejected, never silently shortened.

决定性范围：One command with a value of 70000 bytes marshalled and unmarshalled through the real codec, on a deployment whose client command size is configurable (aws.conf sets 1000).
the client's command size is a configuration value, so larger values are constructible；the codec is the only framing between a client or peer and the replica's readers。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：命令值长度在网络上被静默截断；经真实编解码往返：声明 70000 字节的值在线上写出 70013 字节，解码仅得 4464 字节（70000 mod 65536），且只消费 4477 字节，value_matches=false；剩余字节留在流中会错位后续消息边界。该结论成立的前提是“调用方可以构造超过 65535 字节的值”，这一点由命令大小是配置项支持（默认配置为 1000 字节，未触及该边界）。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/1fca856651484f6f84622b020b2e96d3/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/1fca856651484f6f84622b020b2e96d3/plan.json)；[原始观察](logs/ede08d08061d4663863db222122bcce3/stdout.log)；[assessment](direct-checks/1fca856651484f6f84622b020b2e96d3/ede08d08061d4663863db222122bcce3-assessment.json)；[对应性复核](submissions/099496e399f742ebb4fc813faf2510b9/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.19 秒；执行进程耗时 6.86 秒；[实际命令、工具版本与输入记录](logs/ede08d08061d4663863db222122bcce3/check.json)
执行边界：In-package Go test that round-trips one oversized command value through the real codec and reports the decoded length and consumed bytes.；harness-only scaffolding: no replica is constructed; the test calls the state codec directly；the harness wraps the already-buffered wire bytes in a fresh reader, which is what the unmarshal expects
固定比较 `CH1-value-roundtrip`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| subject | value |
| event | value_roundtrip |
| value_matches | false |
| value_built.declared_bytes | 70000 |
| declared_bytes | 70000 |
| decoded_bytes | 4464 |
| decoded_key | 1 |
| decoded_op | 1 |
| wire_bytes_consumed | 4477 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：超长值之后的命令解码为垃圾数据；同一缓冲中先写 70000 字节值的命令、再写一条小命令，解码第一条只取回 4464 字节后，第二条被解码为 op 197、任意键与 53198 字节值（second_matches=false，剩余 12341 字节）：被截断的值不仅自身缩短，还破坏了其后的命令边界。该结论适用于记录器那种无框架的命令级联（recordCommands 逐条 Marshal），默认 1000 字节命令不会触达该边界。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/da5322d138d3428b96592d26151e08a8/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/da5322d138d3428b96592d26151e08a8/plan.json)；[原始观察](logs/8628f4fc82b34c7996a440979531b3ff/stdout.log)；[assessment](direct-checks/da5322d138d3428b96592d26151e08a8/8628f4fc82b34c7996a440979531b3ff-assessment.json)；[对应性复核](submissions/d5c13631f975429382fbf686715983ec/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.49 秒；执行进程耗时 7.21 秒；[实际命令、工具版本与输入记录](logs/8628f4fc82b34c7996a440979531b3ff/check.json)
执行边界：In-package Go test that writes two commands into one stream and decodes them in order, reporting what the second one becomes.；harness-only scaffolding: no replica is constructed; the test calls the state codec directly on a buffer holding two commands；two commands in one buffer model a batch or a recorder that appends commands, which is how the implementation writes them
固定比较 `CH2-stream-shift`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| stream | batch |
| event | stream_shifted |
| second_matches | false |
| stream_built.second_key | 2 |
| stream_built.first_bytes | 70000 |
| bytes_left | 12341 |
| error |  |
| first_decoded_bytes | 4464 |
| second_key | -3617292328856139834 |
| second_op | 197 |
| second_value_len | 53198 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：超大值使接收方解码 panic；真实 PreAccept（两条命令，首条值 70000 字节）编码为 70063 字节，用实现自身的解码器解析时 panic：makeslice: len out of range，缓冲区剩余 15700 字节（panicked=true、second_matches=false）。接收端读取路径没有 recover，因此该 panic 会终止该副本进程；结论限于命令大小可配置超过 65535 的场景（默认 1000 字节不会触达）。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/47fd9044969b4755870bce0940c7c541/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/47fd9044969b4755870bce0940c7c541/plan.json)；[原始观察](logs/22e83a7c099744d9b38d11252bb31365/stdout.log)；[assessment](direct-checks/47fd9044969b4755870bce0940c7c541/22e83a7c099744d9b38d11252bb31365-assessment.json)；[对应性复核](submissions/12c66d847038429e831b96907280b36d/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.71 秒；执行进程耗时 8.41 秒；[实际命令、工具版本与输入记录](logs/22e83a7c099744d9b38d11252bb31365/check.json)
执行边界：In-package Go test that marshals a PreAccept with an oversized first command value and decodes it with the real unmarshaller.；harness-only scaffolding: no replica is constructed; the message and command codecs are called directly；the decode is wrapped in recover() to observe a panic; the replica reader in production has no recover around its unmarshal
固定比较 `CH3-message-shift`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| message | PreAccept |
| event | message_shifted |
| panicked | true |
| message_built.commands | 2 |
| message_built.first_bytes | 70000 |
| bytes_left | 15700 |
| panic_value | runtime error: makeslice: len out of range |
| second_matches | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C12-transitive-skip-executes-commuting-command"></a>

### 10. 传递冲突跳过开关未生效

**已确认违反**。要求原文：When transitive-conflict skipping is enabled, executing an instance must not wait for a prior command it commutes with: the executor's transitive-conflict branch must let the commuting dependency be skipped instead of halting on it.

决定性范围：One replica with the transconf flag set: a committed instance whose command touches one key and whose only dependency is an uncommitted command on a different key, both reachable by the executor.
the flag is the switch the implementation provides for this behaviour；the two commands commute under the state package's conflict relation。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：传递冲突跳过开关未生效；在开启 transconf 的情况下，已提交实例的命令与唯一依赖（另一键上的未提交命令）互不冲突（commands_commute=true），但执行器仍未执行该实例（executed=false，依赖仍为 PREACCEPTED），即标志位没有改变任何行为；实现自述的“跳过先前可交换命令”优化实际无效。该结论限于显式开启该开关的调用方，默认启动配置传入 false，因此后果是性能而非安全。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/ddc78e6f85df410c8f22e5e86686834c/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/ddc78e6f85df410c8f22e5e86686834c/plan.json)；[原始观察](logs/006f3e586edf4d7ab51b58245214dd37/stdout.log)；[assessment](direct-checks/ddc78e6f85df410c8f22e5e86686834c/006f3e586edf4d7ab51b58245214dd37-assessment.json)；[对应性复核](submissions/82cbc96caa39436986a0bd70a5209fb4/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.71 秒；执行进程耗时 7.32 秒；[实际命令、工具版本与输入记录](logs/006f3e586edf4d7ab51b58245214dd37/check.json)
执行边界：In-package Go test that prepares a commuting uncommitted dependency and asks the real executor to run the committed instance with the flag set.；harness-only scaffolding: the Replica is constructed in-package with the flag set and the two records are built directly with the package's types；the harness calls the executor entry directly instead of the execution loop
固定比较 `CH1-transconf`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| dependency_status | 1 |
| event | transconf_execution |
| executed | false |
| transconf_case.transconf | true |
| transconf_case.commands_commute | true |
| status_after | 4 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C8-timeout-enqueues-blocked-instance"></a>

### 11. 执行器超时会将被阻塞实例入队恢复

**有限检查未见违反**。要求原文：When a replica's executor finds an instance it cannot apply (no commands, not committed) at the head of a row, it must enqueue that instance for recovery once the configured grace period has elapsed, so the row does not stay blocked on that replica.

决定性范围：One replica whose row 1 is blocked at instance 0 by a record with no commands and no commit, with the executor goroutine running as in the launched configuration.
crtInstance for the row is at the blocked instance and the executed watermark is behind it；no other instance in the row is ready to apply。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：执行器超时会将被阻塞实例入队恢复；行 1 被一条无命令且未提交的记录阻塞时（前置事件：status 0、has_commands false、crtInstance 0、ExecedUpTo -1），执行器在约 12.6 秒后把该实例入队：enqueued true、enqueued_replica 1、enqueued_instance 0。即被拒绝的接受轮所依赖的时间驱动恢复路径确实存在，代价是一次约 12.6 秒的等待（该值随后台循环计数方式而定，属诊断而非规格）。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/14523b865f39421fa61b175ebb971769/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/14523b865f39421fa61b175ebb971769/plan.json)；[原始观察](logs/f01d61d7454b4aaea29b663366d5d2b6/stdout.log)；[assessment](direct-checks/14523b865f39421fa61b175ebb971769/f01d61d7454b4aaea29b663366d5d2b6-assessment.json)；[对应性复核](submissions/ecb803b940fb4ce2a099a1c6409a78f0/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 20.14 秒；执行进程耗时 19.83 秒；[实际命令、工具版本与输入记录](logs/f01d61d7454b4aaea29b663366d5d2b6/check.json)
执行边界：In-package Go test that blocks one row and waits for the executor's recovery enqueue, reading only the recovery channel.；harness-only scaffolding: the Replica is constructed in-package and executeCommands is started directly instead of by New(); the loop itself is unmodified；the harness reads instancesToRecover rather than letting the run loop consume it
固定比较 `CH1-recovery-enqueued`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| instance | 1.0 |
| event | recovery_enqueued |
| enqueued | true |
| blocked_instance.status | 0 |
| blocked_instance.has_commands | false |
| enqueued_instance | 0 |
| enqueued_replica | 1 |
| waited_ms | 12615 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：超时入队后恢复确实启动；执行器超时把阻塞实例入队（约 12.9 秒）后，把该条目交给恢复入口即可看到恢复真实启动：记录进入 preparing 状态、自身 PrepareReply 已入账（prepare_replies=1）且已发出 34 字节的 Prepare（preparing=true）。因此超时路径不仅发出信号，还确实推进到恢复尝试，这正是被拒绝的接受轮（C7）所依赖的后续。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/0e5c459c02cf4d9f875eac14cab3ee9c/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/0e5c459c02cf4d9f875eac14cab3ee9c/plan.json)；[原始观察](logs/bbf0e191b3e94aaf94ea1a170acacdb4/stdout.log)；[assessment](direct-checks/0e5c459c02cf4d9f875eac14cab3ee9c/bbf0e191b3e94aaf94ea1a170acacdb4-assessment.json)；[对应性复核](submissions/b8a68e92b1c84d11b21718e5abd0d119/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 21.30 秒；执行进程耗时 20.97 秒；[实际命令、工具版本与输入记录](logs/bbf0e191b3e94aaf94ea1a170acacdb4/check.json)
执行边界：In-package Go test that drives the executor timeout, then the recovery entry, and reports whether recovery started.；harness-only scaffolding: the Replica is constructed in-package, the executor goroutine is started directly and the recovery entry is called with the enqueued coordinates instead of by the run loop；peer writers are buffers kept by the harness so the emitted Prepare is observable
固定比较 `CH2-recovery-started`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| instance | 1.0 |
| event | recovery_started |
| preparing | true |
| enqueued.enqueued | true |
| bytes_sent | 34 |
| prepare_replies | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C5-noop-commit-reproposes-admitted-operation"></a>

### 12. When a replica that owns an instance and still holds an admitted client operation for it receives a commit carrying a single NONE…（原文摘录）

**待调查线索**。要求原文：When a replica that owns an instance and still holds an admitted client operation for it receives a commit carrying a single NONE command for that instance, the replica must install the commit and re-propose the pending operation onto its propose path, so the admitted operation is not silently dropped.

决定性范围：Owner-alive case: one replica owns instance (0,0), admitted one client operation for it, and receives one legal single-NONE Commit for that instance.
the owner's record still holds its leader bookkeeping and the admitted proposal；the commit is well formed for that instance。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：所有者存活时 NOOP 提交会重新提议已接纳操作；在所有者仍持有该操作的情况下，handlePropose 接纳操作后（bookkeeping=true，pending=1），一条合法的单 NONE Commit 使实例进入 COMMITTED，pending 清零且提案被重新放回提议通道（reproposed_on_channel=1），即操作未被丢弃而是重新进入决策流程；该结论仅覆盖所有者存活情形，重启后无 bookkeeping 的情形属于 C4 的崩溃结论。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e52be05fa91d40c69965cf0031fac903/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/e52be05fa91d40c69965cf0031fac903/plan.json)；[原始观察](logs/975ffcb0bece435a98472895b130db06/stdout.log)；[assessment](direct-checks/e52be05fa91d40c69965cf0031fac903/975ffcb0bece435a98472895b130db06-assessment.json)；[对应性复核](submissions/dc8062bd32c7425584afd60c28fda975/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.45 秒；执行进程耗时 7.09 秒；[实际命令、工具版本与输入记录](logs/975ffcb0bece435a98472895b130db06/check.json)
执行边界：In-package Go test that admits one proposal with the real handler and delivers one legal NOOP commit, reporting the pending counts and the propose channel.；harness-only scaffolding: the Replica is constructed in-package with buffer peer writers and the two handlers are called directly; the handlers are unmodified；the commit is delivered directly instead of through the run loop, so only the handler's effect on the proposal is observed
固定比较 `CH1-repropose`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| instance | 0.0 |
| event | noop_commit_at_owner |
| reproposed_on_channel | 1 |
| admitted_proposal.has_bookkeeping | true |
| admitted_proposal.pending | 1 |
| instance_status | 4 |
| pending_after | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；机械比较：有限检查未见违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/9b615e3c5b0c4808a50c9eee56cc92b2/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/9b615e3c5b0c4808a50c9eee56cc92b2/plan.json)；[原始观察](logs/6baf5b7715294d88a8f4a36e085ebd04/stdout.log)；[assessment](direct-checks/9b615e3c5b0c4808a50c9eee56cc92b2/6baf5b7715294d88a8f4a36e085ebd04-assessment.json)

当前争议／阻塞：机械比较：有限检查未见违反；对应性意见：尚未记录；待当前版本复核；[完整评估与阻塞](direct-checks/9b615e3c5b0c4808a50c9eee56cc92b2/6baf5b7715294d88a8f4a36e085ebd04-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.09 秒；执行进程耗时 7.72 秒；[实际命令、工具版本与输入记录](logs/6baf5b7715294d88a8f4a36e085ebd04/check.json)
执行边界：In-package Go test that drives admit, NOOP commit, re-propose, commit of the re-proposed instance and execution, reporting the client's reply bytes.；harness-only scaffolding: two Replica values are constructed in-package with buffer peer writers; the handlers are unmodified and messages travel through the real codec；the client's reply writer is a harness buffer, so the observation is the bytes the implementation wrote
固定比较 `CH2-client-reply`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| instance | 0.0 |
| event | client_reply_after_recovery |
| replied | true |
| admitted.pending | 1 |
| bytes_written | 17 |
| executed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="issue-ef6b54abce294555b31a3c9a6ca606ac"></a>
[争议 ef6b54abce294555b31a3c9a6ca606ac](#issue-ef6b54abce294555b31a3c9a6ca606ac)（继续核对）；对象 `05dc6a3632954371911663108e7e18e8` v1：Requirement versus predicate: the accepted claim requires that a reply reporting the instance COMMITTED be adopted; the added property instead asserts that, after each replica applies the instance it holds committed, the state machines…
[完整复核、反证与来源](submissions/6ee2ff2f40f34b9bacfc24eacc4d95be/accepted.json)

条件探索：For instance (1,0), with a recovering replica 0 whose record is a default NONE record and a peer 1 whose record is COMMITTED at vbal 0 with a real command: what VBallot does the recovering replica…
[受理问题、条件与来源](submissions/0990c3217e1241089d33ca415d650f51/accepted.json)；[固定输入](submissions/0990c3217e1241089d33ca415d650f51/inputs/explore_recvbal_test.go)
<a id="exploration-60f600bb17a047a5807e4dc72a5cd89c"></a>
[探索执行 1](#exploration-60f600bb17a047a5807e4dc72a5cd89c)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/60f600bb17a047a5807e4dc72a5cd89c/check.json)；[实际输出](logs/60f600bb17a047a5807e4dc72a5cd89c/stdout.log)；[诊断](logs/60f600bb17a047a5807e4dc72a5cd89c/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.72 秒；执行进程耗时 7.36 秒；[实际命令、工具版本与输入记录](logs/60f600bb17a047a5807e4dc72a5cd89c/check.json)
[执行输入文件清单](experiments/373f4eee1cc5433ab5f52af12ddfcc2b/workspace-delta/manifest.json)
[执行后文件清单](experiments/373f4eee1cc5433ab5f52af12ddfcc2b/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-52d2733218d44f54b5b7c4044dca3e5d)

条件探索：A peer reader is handed a stream whose first byte is not a registered message id, which is what the displaced stream of a truncated command value produces. What does the reader do - does it continue,…
[受理问题、条件与来源](submissions/50f1da3ccf734410a0c47bfd7e0aa91e/accepted.json)；[固定输入](submissions/50f1da3ccf734410a0c47bfd7e0aa91e/inputs/explore_reader_test.go)
<a id="exploration-5b9267ea51d742f9a6fdcfb7a6594990"></a>
[探索执行 2](#exploration-5b9267ea51d742f9a6fdcfb7a6594990)：已进入测试，执行失败；性质归因另核；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/5b9267ea51d742f9a6fdcfb7a6594990/check.json)；[实际输出](logs/5b9267ea51d742f9a6fdcfb7a6594990/stdout.log)；[诊断](logs/5b9267ea51d742f9a6fdcfb7a6594990/stderr.log)
固定执行包 `./replica`；主文件 `replica/assurance_generated_test.go`；目标动作总耗时 8.22 秒；执行进程耗时 7.86 秒；[实际命令、工具版本与输入记录](logs/5b9267ea51d742f9a6fdcfb7a6594990/check.json)
[执行输入文件清单](experiments/1270009ac066409e8e55ddab47cc891b/workspace-delta/manifest.json)
[执行后文件清单](experiments/1270009ac066409e8e55ddab47cc891b/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 2](#exploration-feedback-df5c0d86ceb244a0b7b59a3192cd10cb)
后续受理交接原文导航：[交接 3](#exploration-feedback-51fe1ce8392a4e1ca0c6153bf1def6af)
后续受理交接原文导航：[交接 4](#exploration-feedback-f9f9fad70c994727a5ae0106a899e93e)

条件探索：What does the execution environment permit for socket operations? Specifically, can a harness bind a loopback port and an all-interfaces port, and what error does the runtime report when it cannot?
[受理问题、条件与来源](submissions/b0f7d72ca7964683a1a49ed75104c495/accepted.json)；[固定输入](submissions/b0f7d72ca7964683a1a49ed75104c495/inputs/explore_listen_test.go)
<a id="exploration-f83012e7adef45afb5ac4c97b3095d5d"></a>
[探索执行 3](#exploration-f83012e7adef45afb5ac4c97b3095d5d)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/f83012e7adef45afb5ac4c97b3095d5d/check.json)；[实际输出](logs/f83012e7adef45afb5ac4c97b3095d5d/stdout.log)；[诊断](logs/f83012e7adef45afb5ac4c97b3095d5d/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 8.21 秒；执行进程耗时 7.79 秒；[实际命令、工具版本与输入记录](logs/f83012e7adef45afb5ac4c97b3095d5d/check.json)
[执行输入文件清单](experiments/ff0a97c358b2452495b6b6ba365b9c8d/workspace-delta/manifest.json)
[执行后文件清单](experiments/ff0a97c358b2452495b6b6ba365b9c8d/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 4](#exploration-feedback-f9f9fad70c994727a5ae0106a899e93e)

<a id="exploration-feedback-52d2733218d44f54b5b7c4044dca3e5d"></a>
[交接 1](#exploration-feedback-52d2733218d44f54b5b7c4044dca3e5d) · 后续说明；关联：[探索执行 1](#exploration-60f600bb17a047a5807e4dc72a5cd89c)
后续受理交接原文（摘录，不是各次执行的独立观察）：In a clean copy the harness reported: recovery_seed with seed_lb_ballot -1, record_vbal_reported_by_self 3 and instance_vbal_after_seed 3 (so the self PrepareReply announces the newly made ballot, not the record's old vbal, and self_status is NONE);…
[完整交接；精确引用不表示已解决或已正式化](submissions/52d2733218d44f54b5b7c4044dca3e5d/accepted.json)

<a id="exploration-feedback-df5c0d86ceb244a0b7b59a3192cd10cb"></a>
[交接 2](#exploration-feedback-df5c0d86ceb244a0b7b59a3192cd10cb) · 后续说明；关联：[探索执行 2](#exploration-5b9267ea51d742f9a6fdcfb7a6594990)
后续受理交接原文（摘录，不是各次执行的独立观察）：The codec finding's last unread consequence is now observed rather than inferred: an exploration drove the real peer reader (execution 5b9267ea51d742f9a6fdcfb7a6594990, exit 1) with a stream whose first byte is not a registered message id, which is what a…
[完整交接；精确引用不表示已解决或已正式化](submissions/df5c0d86ceb244a0b7b59a3192cd10cb/accepted.json)

<a id="exploration-feedback-51fe1ce8392a4e1ca0c6153bf1def6af"></a>
[交接 3](#exploration-feedback-51fe1ce8392a4e1ca0c6153bf1def6af) · 后续说明；关联：[探索执行 2](#exploration-5b9267ea51d742f9a6fdcfb7a6594990)
后续受理交接原文（摘录，不是各次执行的独立观察）：The run's work is complete as far as its remaining authorization allows. Every file in the analysis roots has been read, the map is current at version 20, and twelve claim families were established with executed artifacts: nine confirmed violations or…
[完整交接；精确引用不表示已解决或已正式化](submissions/51fe1ce8392a4e1ca0c6153bf1def6af/accepted.json)

<a id="exploration-feedback-f9f9fad70c994727a5ae0106a899e93e"></a>
[交接 4](#exploration-feedback-f9f9fad70c994727a5ae0106a899e93e) · 共同后续说明；关联：[探索执行 2](#exploration-5b9267ea51d742f9a6fdcfb7a6594990)、[探索执行 3](#exploration-f83012e7adef45afb5ac4c97b3095d5d)
后续受理交接原文（摘录，不是各次执行的独立观察）：The run's last observation settles the environment class behind two earlier caveats: socket creation is denied in this execution environment ('socket: operation not permitted' for both a loopback and an all-interfaces bind), which is why the startup-probe…
[完整交接；精确引用不表示已解决或已正式化](submissions/f9f9fad70c994727a5ae0106a899e93e/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v21：概览、Behavior／Fact 与来源](audit-spec/v21.json)。
- 共识形成与推进（原文导航摘录）：A command becomes a decision in two stages. First the owner replica allocates instance (r.Id, ++crtInstance[r.Id]) in handlePropose and startPhase1 derives the initial (seq, deps) from its conflict index and…
- 上下文／权威转换（原文导航摘录）：The authority context of an instance is a pair of ballots on the per-instance record: bal is the highest ballot promised to any leader for that instance and vbal is the ballot at which the record's current attributes…
- 两条主线的连接（原文导航摘录）：The two lines meet at the per-instance record. Formation consumes the dependency and sequence facts the conflict index (A6) establishes and produces the committed attribute vector; the authority line decides which…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.86 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 11.26 分钟 · 受理 explained：Source review resolved the Candidate's discriminator without needing execution. The wrong-slot write at epaxos/epaxos.go:809 assigns the…。[完整交接](submissions/9a16835451b241b38887d531e8ae3b88/accepted.json)

- 13.54 分钟 · 受理 continue：The understood frontier is unchanged and usable, so this product opens a new Candidate instead of re-describing it. Source review resolved…。[完整交接](submissions/9bbd6206ea8a4fa580fa7db92d2cc5ab/accepted.json)

- 18.90 分钟 · 受理 explained：Sourced review answers the Candidate's discriminator instead of leaving it open. updateAttributes only raises the dependency components it…。[完整交接](submissions/34c1c71d86944362bf482c8dffced976/accepted.json)

- 19.64 分钟 · 受理 continue：The frontier is without an open Candidate and the two recovery reachability questions are disposed, so this product opens the next one on…。[完整交接](submissions/5502aa634a4c4a318d7fd7a78b6437b0/accepted.json)

- 21.21 分钟 · 受理 continue：Reading the recovery entry while working the accept-status premise produced a separate, sharper lead that belongs to its own question:…。[完整交接](submissions/6d79296cf1f647f79f088f7dbe5ce244/accepted.json)

- 22.70 分钟 · 实际执行：Construction run for the active recovery-vbal Candidate. The harness builds two real Replica values (a recovering replica holding only a…；探索执行正常结束。[执行记录](logs/60f600bb17a047a5807e4dc72a5cd89c/check.json)

- 25.46 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/be74405317044c1fa5f5151c7815c026/check.json)

- 26.38 分钟 · 受理 review：恢复阶段忽略已提交回复；v1 checker_correspondence: no_issue_found。[完整交接](submissions/b05bee9060d54f7a9a74c709330af5e4/accepted.json)

- 27.57 分钟 · 实际执行：机械比较：观察到违反；对应性意见：尚未记录；执行完成；比较见 assessment。[执行记录](logs/d5769994f11746fba640e2057fbd13b8/check.json)

- 30.13 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/23cff5113484421c9d76595f272184e1/check.json)

- 31.09 分钟 · 受理 review：恢复提交与已提交命令不一致；v1 checker_correspondence: no_issue_found。[完整交接](submissions/caf0f7ba5dc04822ae4c44e33e283670/accepted.json)

- 32.36 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/36887d5bfbc643efbd4ed40b1e1cb4d5/check.json)

- 33.17 分钟 · 受理 review：提交广播后同一实例出现两个已提交命令；v1 checker_correspondence: no_issue_found。[完整交接](submissions/0538f396b6f14c09bfd5153dcb8025c5/accepted.json)

- 35.09 分钟 · 受理 continue：Resumes the paused accept-status Candidate with its proposition unchanged and sharper unknowns, now that the surrounding reachability…。[完整交接](submissions/6915e7534c264212b576aa11fcf86a3d/accepted.json)

- 35.80 分钟 · 受理 pause：Pauses the resumed accept-status Candidate after its observable half resolved negatively: the recovery value selection skips every reply…。[完整交接](submissions/744c2adcdd0e4c14bcf7f335e2b150f2/accepted.json)

- 37.16 分钟 · 实际执行：稳定存储元数据记录丢失 bal 字段；执行完成；比较见 assessment。[执行记录](logs/310d33db15394688a5ee2d808ed3a4a3/check.json)

- 37.91 分钟 · 受理 review：稳定存储元数据记录丢失 bal 字段；v1 checker_correspondence: no_issue_found。[完整交接](submissions/9bbaf65f5135439580d764e38328fccd/accepted.json)

- 39.91 分钟 · 实际执行：机械比较：观察到违反；对应性意见：revision_needed；执行完成；比较见 assessment。[执行记录](logs/2f186bc17e13432fae3b653b42e46941/check.json)

- 40.62 分钟 · 受理 review：应用层不一致属性超出已接受义务范围；v1 checker_correspondence: revision_needed。[完整交接](submissions/6ee2ff2f40f34b9bacfc24eacc4d95be/accepted.json)

- 41.48 分钟 · 实际执行：同一实例在不同副本产生不同的已应用效果；执行完成；比较见 assessment。[执行记录](logs/ef136d1e25924ce59ccedc4fe9e2af2e/check.json)

- 42.10 分钟 · 受理 review：同一实例在不同副本产生不同的已应用效果；v1 checker_correspondence: no_issue_found。[完整交接](submissions/880ad24d41e14ba5a2bf8c75fb5c8bdc/accepted.json)

- 43.61 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/4e63644f9e95492cabfea5f571c9c359/check.json)

- 44.27 分钟 · 受理 review：C1 检查集已仅含范围内属性；v1 checker_correspondence: no_issue_found。[完整交接](submissions/0909fc33bcf84c1d897da2518c7c8136/accepted.json)

- 45.20 分钟 · 受理 continue：Opens the next substantive question on a different responsibility: client completion after a recovery commits a NOOP for another replica's…。[完整交接](submissions/2588a04947d7495bb49875bce21cd9c6/accepted.json)

- 47.60 分钟 · 实际执行：NOOP 提交使实例所有者空指针崩溃；执行完成；比较见 assessment。[执行记录](logs/117697084648408998b24f05ce690f68/check.json)

- 48.12 分钟 · 受理 review：NOOP 提交使实例所有者空指针崩溃；v1 checker_correspondence: no_issue_found。[完整交接](submissions/6606835070d34626a5ae5707069eea29/accepted.json)

- 49.70 分钟 · 实际执行：所有者存活时 NOOP 提交会重新提议已接纳操作；执行完成；比较见 assessment。[执行记录](logs/975ffcb0bece435a98472895b130db06/check.json)

- 50.20 分钟 · 受理 review：所有者存活时 NOOP 提交会重新提议已接纳操作；v1 checker_correspondence: no_issue_found。[完整交接](submissions/dc8062bd32c7425584afd60c28fda975/accepted.json)

- 50.79 分钟 · 受理 pause：Pauses the client-completion Candidate with its two halves answered: the owner-alive half is a confirmed protection (claim C5) and the…。[完整交接](submissions/80a20b5998274975accaa21b535ead64/accepted.json)

- 54.27 分钟 · 实际执行：被提升为 leader 的副本同样忽略已提交回复；执行完成；比较见 assessment。[执行记录](logs/4e8a4b74d9404772b366f3f2af6a075c/check.json)

- 54.81 分钟 · 受理 review：被提升为 leader 的副本同样忽略已提交回复；v1 checker_correspondence: no_issue_found。[完整交接](submissions/b8f5fc5236364e2fbd19adf43b8f0cfe/accepted.json)

- 55.94 分钟 · 实际执行：接受轮的高 ballot 回复未被记为拒绝；执行完成；比较见 assessment。[执行记录](logs/1da816760c9246ee99d9dd60e19d85cb/check.json)

- 56.38 分钟 · 受理 review：接受轮的高 ballot 回复未被记为拒绝；v1 checker_correspondence: no_issue_found。[完整交接](submissions/c64768fe69b44a82a7607c5baed7d1ad/accepted.json)

- 59.71 分钟 · 实际执行：执行器超时会将被阻塞实例入队恢复；执行完成；比较见 assessment。[执行记录](logs/f01d61d7454b4aaea29b663366d5d2b6/check.json)

- 60.24 分钟 · 受理 review：执行器超时会将被阻塞实例入队恢复；v1 checker_correspondence: no_issue_found。[完整交接](submissions/ecb803b940fb4ce2a099a1c6409a78f0/accepted.json)

- 61.46 分钟 · 实际执行：恢复主导的阶段一按自身行记录元数据；执行完成；比较见 assessment。[执行记录](logs/f7a553d13ff640088cdf4c145842172f/check.json)

- 61.97 分钟 · 受理 review：恢复主导的阶段一按自身行记录元数据；v1 checker_correspondence: no_issue_found。[完整交接](submissions/acbedec9212f4b04b3c616e890f0b465/accepted.json)

- 63.40 分钟 · 实际执行：自身行已占用时记录了他实例的元数据；执行完成；比较见 assessment。[执行记录](logs/9519d0683f344690959f2d64bac8f404/check.json)

- 63.80 分钟 · 受理 review：自身行已占用时记录了他实例的元数据；v1 checker_correspondence: no_issue_found。[完整交接](submissions/7f96b08929304f188a3f7ffba873f9e0/accepted.json)

- 66.16 分钟 · 实际执行：命令值长度在网络上被静默截断；执行完成；比较见 assessment。[执行记录](logs/ede08d08061d4663863db222122bcce3/check.json)

- 66.71 分钟 · 受理 review：命令值长度在网络上被静默截断；v1 checker_correspondence: no_issue_found。[完整交接](submissions/099496e399f742ebb4fc813faf2510b9/accepted.json)

- 68.19 分钟 · 实际执行：超长值之后的命令解码为垃圾数据；执行完成；比较见 assessment。[执行记录](logs/8628f4fc82b34c7996a440979531b3ff/check.json)

- 68.86 分钟 · 受理 review：超长值之后的命令解码为垃圾数据；v1 checker_correspondence: no_issue_found。[完整交接](submissions/d5c13631f975429382fbf686715983ec/accepted.json)

- 70.70 分钟 · 实际执行：范围澄清后 C1 检查复现一致；执行完成；比较见 assessment。[执行记录](logs/32aff0d098454dc78bec6a3916753fa9/check.json)

- 71.19 分钟 · 受理 review：范围澄清后 C1 检查复现一致；v1 checker_correspondence: no_issue_found。[完整交接](submissions/b209d81a642341709ae243a5fb6fb9b9/accepted.json)

- 73.27 分钟 · 实际执行：超大值使接收方解码 panic；执行完成；比较见 assessment。[执行记录](logs/22e83a7c099744d9b38d11252bb31365/check.json)

- 73.79 分钟 · 受理 review：超大值使接收方解码 panic；v1 checker_correspondence: no_issue_found。[完整交接](submissions/12c66d847038429e831b96907280b36d/accepted.json)

- 75.43 分钟 · 实际执行：完整历史下仍忽略已提交回复并提交 NOOP；执行完成；比较见 assessment。[执行记录](logs/e8ad6c82f0134b81adb2ed772108ab78/check.json)

- 76.09 分钟 · 受理 review：完整历史下仍忽略已提交回复并提交 NOOP；v1 checker_correspondence: no_issue_found。[完整交接](submissions/d1cf9ae8895b4b0da049e736e8f4ab9c/accepted.json)

- 78.18 分钟 · 实际执行：本地地址探测失败导致副本无法构造；执行完成；比较见 assessment。[执行记录](logs/c1d2d57fdb7b468ca92aedca9f620d83/check.json)

- 78.79 分钟 · 受理 review：本地地址探测失败导致副本无法构造；v1 checker_correspondence: no_issue_found。[完整交接](submissions/ad9eb64bc1094fc7a5d776cc6f9fd244/accepted.json)

- 81.55 分钟 · 实际执行：超时入队后恢复确实启动；执行完成；比较见 assessment。[执行记录](logs/bbf0e191b3e94aaf94ea1a170acacdb4/check.json)

- 82.14 分钟 · 受理 review：超时入队后恢复确实启动；v1 checker_correspondence: no_issue_found。[完整交接](submissions/b8a68e92b1c84d11b21718e5abd0d119/accepted.json)

- 84.67 分钟 · 实际执行：重启历史下 NOOP 提交同样使所有者崩溃；执行完成；比较见 assessment。[执行记录](logs/ae38ca8c77904887841a0e73145db7f5/check.json)

- 85.21 分钟 · 受理 review：重启历史下 NOOP 提交同样使所有者崩溃；v1 checker_correspondence: no_issue_found。[完整交接](submissions/be61a71b21da4a498be1873838911112/accepted.json)

- 87.56 分钟 · 实际执行：传递冲突跳过开关未生效；执行完成；比较见 assessment。[执行记录](logs/006f3e586edf4d7ab51b58245214dd37/check.json)

- 88.05 分钟 · 受理 review：传递冲突跳过开关未生效；v1 checker_correspondence: no_issue_found。[完整交接](submissions/82cbc96caa39436986a0bd70a5209fb4/accepted.json)

- 89.40 分钟 · 实际执行：真实历史下应用层效果同样分叉；执行完成；比较见 assessment。[执行记录](logs/3843884f43014d8fb768c85ea38f11d8/check.json)

- 90.02 分钟 · 受理 review：真实历史下应用层效果同样分叉；v1 checker_correspondence: no_issue_found。[完整交接](submissions/42a3014a58dc4f1a8d05d446989937e3/accepted.json)

- 93.18 分钟 · 实际执行：机械比较：有限检查未见违反；对应性意见：尚未记录；执行完成；比较见 assessment。[执行记录](logs/6baf5b7715294d88a8f4a36e085ebd04/check.json)

- 95.96 分钟 · 实际执行：Construction run for the last unread item of the codec finding's consequence. The listener is unexported in the replica package, so the…；已进入测试，执行失败；性质归因另核。[执行记录](logs/5b9267ea51d742f9a6fdcfb7a6594990/check.json)

- 96.63 分钟 · 受理 research：Map handoff for the reader-side observation obtained by exploration: the codec detail now records what the real peer reader does with a…。[完整交接](submissions/df5c0d86ceb244a0b7b59a3192cd10cb/accepted.json)

- 98.51 分钟 · 受理 research：Records why the run-loop observation did not reach the panic and what it did reveal: a roughly ten-second peer-measurement phase before the…。[完整交接](submissions/0a0b0517f72645e6a04183d490bb0d9d/accepted.json)

- 100.84 分钟 · 受理 research：Records the second loop-exercise attempt: the roughly ten-second startup phase is confirmed by the timing of both panics, and the…。[完整交接](submissions/c0d7feeeba5142eb9942d66787f4cdd9/accepted.json)

- 101.61 分钟 · 实际执行：Two recorded caveats depend on this environment fact and were previously inferred rather than observed: the startup-probe finding (a…；探索执行正常结束。[执行记录](logs/f83012e7adef45afb5ac4c97b3095d5d/check.json)

- 103.25 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/36ed09de953946648bb1a98e897636db/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-C1-recovery-adopts-committed-vector](research.json)：[C1-recovery-adopts-committed-vector](#claim-C1-recovery-adopts-committed-vector)；具体进度与缺口见对应义务
- [unit-C5-noop-commit-reproposes-admitted-operation](research.json)：[C5-noop-commit-reproposes-admitted-operation](#claim-C5-noop-commit-reproposes-admitted-operation)；具体进度与缺口见对应义务
- [ef6b54abce294555b31a3c9a6ca606ac](research.json)：[争议 ef6b54abce294555b31a3c9a6ca606ac](#issue-ef6b54abce294555b31a3c9a6ca606ac)（继续核对）

<a id="candidate-d8fd7f585e054fdba265f29c8f7bff4d"></a>

暂停调查：When a replica receives PreAccept for instance (Replica, Instance) while its local record for that instance already has Status >= ACCEPTED but stores no commands, handlePreAccept writes the received command into InstanceSpace[preAccept.LeaderId][Instance] instead of the addressed instance InstanceSpace[preAccept.Replica][Instance]. Is any legal history able to put a replica in that state with preAccept.LeaderId != preAccept.Replica, and if so does the addressed record (Replica, Instance) stay without commands (halting its row's execution and the recovery replies about it) while an unrelated record (LeaderId, Instance) acquires a command that no quorum committed for it?
[候选原文与历史](state.json)
保存的语义未知：whether the accept phase is required to record an ACCEPTED status on the acceptor that stores accepted attributes, since the guards in handlePreAccept and findPreAcceptConflicts and recovery sub-case 2 presuppose that some replica reports ACCEPTED；whether handlePrepareReply's value selection may adopt a reply whose Status is NONE at the highest vbal (an acceptor that stored no commands) instead of an equal-vbal reply that carries the pre-accepted value
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-7f783892c49e46fc82948aa0546d3db7"></a>

暂停调查：handlePreAcceptReply commits when preAcceptOKs >= FastQuorumSize-1 and inst.lb.allEqual && allCommitted && isInitialBallot, but for r.N <= 3 with Thrifty the reply-wise equality result is discarded (the allEqual accumulator is never updated), so with N = 3 the leader fast-commits its own (seq, deps) after a single reply whose recomputed attributes may differ. Can such a commit leave two attribute vectors for one instance at the same vbal -- the leader's committed vector and the fast-quorum peer's pre-accepted vector -- so that a later recovery, which selects the reply with the highest vbal by iterating the reply slice with element.VBallot >= lb.ballot, can adopt the peer's vector instead of the committed one; and does the legal crash point between the leader's local fast commit and bcastCommit make that reachable while some replica has already executed the committed vector?
[候选原文与历史](state.json)
保存的语义未知：whether a recovery-led phase 1 can leave the merged committed vector's leader-row component below the peer's record, and whether the peer's larger component can be re-committed by a recovery that reaches the peer rather than the committed leader (S7-attributes, S10-handlePreAcceptReply, S15-handlePrepareReply)；whether that requires the recovering leader to have lost its own row knowledge, which the launched configuration permits only through a restart because Durable is false and no reader of the stable store exists (S19-durable-record, S24-runReplica-epaxos)
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-229322fc84e94259a5609cbcad40732d"></a>

暂停调查：handleAccept stores Deps, Seq, bal and vbal for instance (Replica, Instance) and never writes inst.Status, so a replica in the accept quorum that never saw the PreAccept holds accepted attributes with Status NONE, and one that did see it keeps PREACCEPTED or PREACCEPTED_EQ. Does any decision depend on an accepted record carrying status ACCEPTED: can a later PreAccept for the same instance overwrite the accepted attributes because handlePreAccept's >= ACCEPTED guard cannot fire, and can a recovery that should re-accept an already accepted value instead take the phase-1 restart path because handlePrepareReply's sub-case 2 needs a reply whose Status is ACCEPTED?
[候选原文与历史](state.json)
保存的语义未知：whether any decision still depends on an acceptor recording ACCEPTED, now that findPreAcceptConflicts' shortcut is unreachable, recovery sub-case 2 is reachable only through a leader's own record, and the recovery value selection skips every reply below the newly made ballot so an accept-only acceptor's command-less reply cannot win the tie (S11-handleAccept, S15-handlePrepareReply, S17-find-conflicts)；whether the intended acceptor discipline is normative rather than observable here, i.e. whether the omission is a deviation from the corrected EPaxos acceptor rules even though no read path changes a decision (S2-instance-bookkeeping, S11-handleAccept)
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-41661c6204434eb0a8f00129ac08d438"></a>

暂停调查：startRecoveryForInstance seeds LeaderBookkeeping with lb.ballot = the record's old vbal, then makes a new ballot and sets inst.bal and inst.vbal to that new ballot before constructing its own PrepareReply, so the self entry's VBallot is the new ballot. handlePrepareReply keeps the attributes of every reply with element.VBallot >= lb.ballot while lb.ballot is raised to each accepted VBallot. Does that ordering make the recovering replica's own entry raise the running ballot past every remote reply that holds the committed or accepted value at an older vbal, so that the selection ignores a committed value announced by another replica and the resolution proceeds from the local record (sub-case 6 restart, NOOP when no local command is known) instead of re-proposing the committed vector?
[候选原文与历史](state.json)
保存的语义未知：whether the recovery that ignores a COMMITTED reply can ever finish: the accept phase it enters needs a majority of acceptOKs while a replica that already committed the instance refuses to store the new attributes and answers with its own bal, which the leader drops (S11-handleAccept, S12-handleAcceptReply)；whether the consequence is a permanently blocked row and state machine at the recovering replica rather than two divergent committed vectors, which decides whether importance is agreement or progress；whether a legal history that starts from a real proposal, accept round and commit broadcast (instead of a prepared COMMITTED record) reaches the same recovering-replica state, including the execution timeout that starts recovery (S4-execute-loop, S14-recovery-start-prepare)
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-982511b6beed4aeda3f4959eb987d4b6"></a>

暂停调查：When recovery runs for instance (Replica, Instance) and a slow-quorum PrepareReply reports that instance COMMITTED with a command vector, does the recovering replica adopt that committed vector, or does it continue from its own record and restart phase 1 with a different command (NOOP when its record has no commands)?
[候选原文与历史](state.json)
保存的语义未知：whether a full legal history reaches the same state；whether the recovering replica's accept phase can still complete when the committed replica refuses to store the new attributes (S11-handleAccept, S12-handleAcceptReply)
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-fbd4feafe1f64bd8a1205b3aac4d6aca"></a>

暂停调查：When Durable is enabled, recordInstanceMetadata writes the current bal, vbal, Status, Seq and Deps of an instance into the stable store. Does the record it produces preserve the value written for bal at the offset where the recorder wrote it, or does a later write of the same record replace it, and does Status land inside the bytes a reader would use for vbal?
[候选原文与历史](state.json)
保存的语义未知：whether any external tool parses the stable store and expects a particular layout；whether a recovery path from the stable store is intended for a later revision
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-db43ddb56be142f6b87104d17c00c319"></a>

暂停调查：When one instance is held committed at three replicas with different committed commands for it, does applying each record through the executor leave the same effect for the instance's key, or do the replicas' state machines end up holding different effects for the same instance?
[候选原文与历史](state.json)
保存的语义未知：the production execution loop, watermark advancement and the recovery timeout are not exercised by the harness；only one instance and one key are compared
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-b7160e779313408b8d1f7e88b35e71c5"></a>

暂停调查：When recovery commits a NOOP vector for an instance owned by another replica, the client operation that was attached to the original leader's bookkeeping has no owner left: handleCommit re-proposes pending proposals only when the commit lands on the replica's own row (commit.Replica == r.Id) and the commit carries exactly one NONE command, while the recovering replica's instance never held those proposals. Does any in-repository mechanism complete the client's operation after such a recovery, or does the client wait for a reply that no replica owes?
[候选原文与历史](state.json)
保存的语义未知：whether the replica implementation is expected to complete another replica's admitted proposal, which no read path supports because proposals are never transmitted (S13-handleCommit, S8-handlePropose-startPhase1)；whether the captured driver client's absence of retry is in scope for the audited contract (S28-client-waitreplies, S29-client-sendproposal)
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-4c0aeda6155846e088e60b7a8a39789e"></a>

暂停调查：A replica owns instance (0,0) but holds a record for it that a message created (no leader bookkeeping), because the instance was proposed before a restart and a recovery-led PreAccept reached it again. When a recoverer commits that instance as a single NONE command and the Commit arrives, does the handler process the commit, or does it dereference bookkeeping the record does not have and terminate the replica?
[候选原文与历史](state.json)
保存的语义未知：whether the run loop's dispatcher contains any recover that would keep the process alive (none was found in the loop)；whether a real deployment reaches a restarted owner with an outstanding instance in its own row
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-b384347a62374d808bb595210b13537e"></a>

暂停调查：In the owner-alive case, when a replica that admitted a client operation for instance (0,0) receives a legal single-NONE Commit for that instance, does it install the commit and put the operation back on its propose path, or does the admitted operation remain dropped?
[候选原文与历史](state.json)
保存的语义未知：whether the re-proposed operation's later commit and execution complete the client's reply, which is not driven here；the restarted-owner case with no bookkeeping is claim C4's crash and is excluded
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-2d57785604004f8dbf2cfc1ab848cf39"></a>

暂停调查：When the replica the deployment promoted to leader (IsLeader true, and a ballot history above its ballot base) recovers an instance and a slow-quorum reply reports that instance COMMITTED, does it adopt the committed vector, or does raising the new ballot past maxRecvBallot make its own VBallot outrank the committed reply so the recovery restarts phase 1 with NOOP?
[候选原文与历史](state.json)
保存的语义未知：whether a real deployment's ballot history changes anything beyond the ballot value, which the harness models as one maxRecvBallot value；whether the promoted replica being the recovery leader is common in practice, which the master's promotion rules suggest but no run was executed
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-407cfe42fc5f4027bf3f2c9f7e4ca119"></a>

暂停调查：When a peer answers an accept round with an AcceptReply whose ballot is higher than the round's ballot, does the leader count that reply as a rejection (and, past a majority, make a new ballot and prepare again), or does the ballot-equality gate return first so the rejection is never recorded?
[候选原文与历史](state.json)
保存的语义未知：whether the pre-accept side has any rejection signal at all, since PreAcceptReply copies the request's ballot and handlePreAccept returns silently when the request's ballot is too small；whether the intended rejection path is the timeout-driven recovery in this implementation
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-fd839334c8f7464cadb00ee735cfd461"></a>

暂停调查：With one row blocked at an instance whose record the replica holds but which has no commands and no commit, does the executor enqueue that instance for recovery after its grace period, and roughly how long does that take in wall-clock terms?
[候选原文与历史](state.json)
保存的语义未知：whether the same enqueue happens for a row whose head is committed but whose dependencies are missing, which the check does not exercise；the exact wall-clock grace period in a deployment, since the counter advances per loop iteration rather than per clock tick
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-7864db2ae70e4954ba9cb7c1f15dfe48"></a>

暂停调查：With Durable enabled and phase 1 started for another replica's instance, does the metadata recorder receive the record of that instance, or does it dereference the recovering replica's own row (which need not hold an instance at that number) and terminate the call?
[候选原文与历史](state.json)
保存的语义未知：whether the slot-exists case records another instance's metadata, which the source implies but the check does not exercise；whether any caller enables recording in practice
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-4552a98a09cd44df9d657f56ef093edc"></a>

暂停调查：A command value of 70000 bytes is marshalled and unmarshalled through the implementation's own codec. Does the value survive unchanged, or does the two-byte length field store it modulo 65536 so the decoder recovers a shorter value and leaves the rest of the bytes in the stream?
[候选原文与历史](state.json)
保存的语义未知：whether the client library caps the command size it builds；what a replica reader does on the following message once the stream is shifted, which no check exercised
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-4a9c3877b1da4543b61a9a102c9ecb7a"></a>

暂停调查：In an environment that cannot reach the fixed probe address, does the helper a replica construction evaluates inline return a local address, or does it discard the dial error and dereference a nil connection so that no replica can be constructed?
[候选原文与历史](state.json)
保存的语义未知：whether the probe address is reachable in the deployments the project uses
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<a id="candidate-5e3f0456fd904974a04e4158ee90580c"></a>

暂停调查：With the transitive-skip flag enabled, a committed instance whose command commutes with its only dependency (an uncommitted command on another key) is given to the executor. Does execution proceed by skipping that commuting dependency, or does it wait for it exactly as if the flag were off?
[候选原文与历史](state.json)
保存的语义未知：whether the intended pruning was to drop the dependency from the closure or to relax the ready check, which the empty body leaves open
恢复条件：semantic review capacity for the executed end-to-end client-reply artifact (6baf5b7715294d88a8f4a36e085ebd04)；audit unit and review capacity to fix the reader-side exit observation (exploration 5b9267ea51d742f9a6fdcfb7a6594990) as a claim with its own artifact；deployment configurations that enable the latency file, durable recording or transitive-skip flag, which decide whether C2, C10's slow path and C12 are live；a mechanism the validator accepts for the scope issue on the superseded C1 artifact, or a decision to leave it permanently visible

<details><summary>地图登记与研究交接</summary>

以下是地图 v21 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v21：概览、Behavior／Fact 与来源](audit-spec/v21.json)

- core_overview：handlePreAccept's status >= ACCEPTED branch stores the incoming command in InstanceSpace[preAccept.LeaderId][Instance] while every other access in the same handler uses preAccept.Replica…
  尚无精确对应交接。

- B1-admit-propose：client-side retry behaviour is not implemented here (TODO comment in handlePropose)
  相关交接：[交接 1](submissions/90b34e641912400eb595c1c5d941266c/accepted.json)；[交接 2](submissions/80a20b5998274975accaa21b535ead64/accepted.json)

- B3-preaccept-recipient：whether the accept phase is required to record an ACCEPTED status on an acceptor; while it does not, this handler's status >= ACCEPTED branch is unreachable (S11-handleAccept)
  相关交接：[交接 1](submissions/9a16835451b241b38887d531e8ae3b88/accepted.json)；[交接 2](submissions/61a451c751a2470d96f66b3ce82794ab/accepted.json)；[交接 3](submissions/5502aa634a4c4a318d7fd7a78b6437b0/accepted.json)；[交接 4](submissions/6915e7534c264212b576aa11fcf86a3d/accepted.json)

- B4-fast-path-decision：resolved for the owner-led case and confined to one component otherwise: mergeAttributes ignores the leader's own dependency row, and a pre-accepting peer only raises components it is given while…
  相关交接：[交接 1](submissions/9bbd6206ea8a4fa580fa7db92d2cc5ab/accepted.json)；[交接 2](submissions/dbc4d55345e2468ba0cab082fb8e731b/accepted.json)；[交接 3](submissions/61a451c751a2470d96f66b3ce82794ab/accepted.json)；[交接 4](submissions/34c1c71d86944362bf482c8dffced976/accepted.json)

- B5-slow-path-accept：whether the missing ACCEPTED status transition on acceptors changes any decision, given that handlePreAccept's >= ACCEPTED guard, findPreAcceptConflicts' already-ACCEPTED shortcut and recovery…
  相关交接：[交接 1](submissions/5502aa634a4c4a318d7fd7a78b6437b0/accepted.json)；[交接 2](submissions/6915e7534c264212b576aa11fcf86a3d/accepted.json)；[交接 3](submissions/744c2adcdd0e4c14bcf7f335e2b150f2/accepted.json)；[交接 4](submissions/ed656193042e4de79b9dbb77a92beece/accepted.json)；[交接 5](submissions/b09abf14ae8944b0aff1dd78946d578f/accepted.json)

- B6-commit-install：whether the run loop's dispatcher recovers from a handler panic; no recover was found in the loop, so a panic in a handler is inferred to end the replica process (S3-run-dispatch, S13-handleCommit)
  相关交接：[交接 1](submissions/6d79296cf1f647f79f088f7dbe5ce244/accepted.json)；[交接 2](submissions/9815328fb7524024acc42e5366f052c8/accepted.json)；[交接 3](submissions/80a20b5998274975accaa21b535ead64/accepted.json)；[交接 4](submissions/aacfa43145fa458f8599d28a7928b119/accepted.json)

- B7-execute-scheduler：whether the row scan can apply an instance before an earlier same-row instance when Deps[row] is -1
  相关交接：[交接 1](submissions/c054db1ffefa4636bec292c2f6d6de72/accepted.json)；[交接 2](submissions/e737a578bdec4cda824c75ede9c7010c/accepted.json)

- B8-scc-closure：whether an empty same-row dependency entry is reachable for an instance whose row prefix is not yet committed
  相关交接：[交接 1](submissions/54a304eb76a441a6a11a6eca4cfc2661/accepted.json)

- B9-recovery-trigger：the confirmed checks for claim C1-recovery-adopts-committed-vector fix the resolution and accept rounds from a prepared COMMITTED record; whether the execution-timeout trigger (S4-execute-loop) and a…
  相关交接：[交接 1](submissions/61a451c751a2470d96f66b3ce82794ab/accepted.json)；[交接 2](submissions/6d79296cf1f647f79f088f7dbe5ce244/accepted.json)；[交接 3](submissions/52d2733218d44f54b5b7c4044dca3e5d/accepted.json)；[交接 4](submissions/e35eea72b8104d2fadfecd15147ca43b/accepted.json)

- B11-prepare-resolution：resolved as unreachable: sub-cases 3 and 4 carry identical guards so sub-case 3 always wins, and everything reachable only from sub-case 4 is dead code; the open question is only whether the intended…
  相关交接：[交接 1](submissions/9bbd6206ea8a4fa580fa7db92d2cc5ab/accepted.json)；[交接 2](submissions/dbc4d55345e2468ba0cab082fb8e731b/accepted.json)；[交接 3](submissions/61a451c751a2470d96f66b3ce82794ab/accepted.json)；[交接 4](submissions/5502aa634a4c4a318d7fd7a78b6437b0/accepted.json)；[交接 5](submissions/6d79296cf1f647f79f088f7dbe5ce244/accepted.json)；[交接 6](submissions/52d2733218d44f54b5b7c4044dca3e5d/accepted.json)；[交接 7](submissions/e35eea72b8104d2fadfecd15147ca43b/accepted.json)；[交接 8](submissions/6915e7534c264212b576aa11fcf86a3d/accepted.json)；[交接 9](submissions/744c2adcdd0e4c14bcf7f335e2b150f2/accepted.json)；[交接 10](submissions/4ca29d1e4bbf42be881aa9c7eee7e562/accepted.json)；[交接 11](submissions/540032678d6a42a287ef32609725edd2/accepted.json)；[交接 12](submissions/270a294130af48ba9f338922a7aef0a5/accepted.json)

- B12-try-preaccept：resolved as unreachable: this handler is entered only from the dead sub-case 4, so the defer-cycle guard and its possibleQuorum[tpar.AcceptorId] counting error have no reachable consequence
  相关交接：[交接 1](submissions/9bbd6206ea8a4fa580fa7db92d2cc5ab/accepted.json)；[交接 2](submissions/dbc4d55345e2468ba0cab082fb8e731b/accepted.json)

- B14-ballot-monotonicity：resolved to a sourced relationship: the master designates a leader at registration (the configured Leader alias, or the replica with the lowest ping RTT when no Leader is configured) and calls…
  相关交接：[交接 1](submissions/28b858d492424817841c1a5ef7b396e1/accepted.json)；[交接 2](submissions/86a7cef38fb446e7b340e77f3512eac0/accepted.json)；[交接 3](submissions/540032678d6a42a287ef32609725edd2/accepted.json)；[交接 4](submissions/ed656193042e4de79b9dbb77a92beece/accepted.json)

- B15-durable-record：whether any external tool or later revision reads the stable store; no reader exists in the captured snapshot, so the intended offsets are inferred from the writes themselves (S19-durable-record)
  相关交接：[交接 1](submissions/57454b6541cb4f7ea5b3862380edd5f6/accepted.json)；[交接 2](submissions/c054db1ffefa4636bec292c2f6d6de72/accepted.json)；[交接 3](submissions/afc896ee4f18403bab1b9874fe1851be/accepted.json)

- B16-client-reply：whether the client library requires a reply for the original CommandId when the command was replaced by NOOP
  相关交接：[交接 1](submissions/90b34e641912400eb595c1c5d941266c/accepted.json)；[交接 2](submissions/aacfa43145fa458f8599d28a7928b119/accepted.json)

- F1-instance-record：whether replacing bal, vbal, Seq and Deps on a record that already stored accepted attributes can lose an accepted value a later recovery depends on
  相关交接：[交接 1](submissions/9a16835451b241b38887d531e8ae3b88/accepted.json)；[交接 2](submissions/5502aa634a4c4a318d7fd7a78b6437b0/accepted.json)；[交接 3](submissions/6915e7534c264212b576aa11fcf86a3d/accepted.json)；[交接 4](submissions/744c2adcdd0e4c14bcf7f335e2b150f2/accepted.json)

- F2-committed-decision：whether every ordering of committed attributes a follower can install is also reachable as a decision by some quorum
  相关交接：[交接 1](submissions/9bbd6206ea8a4fa580fa7db92d2cc5ab/accepted.json)；[交接 2](submissions/dbc4d55345e2468ba0cab082fb8e731b/accepted.json)；[交接 3](submissions/61a451c751a2470d96f66b3ce82794ab/accepted.json)；[交接 4](submissions/34c1c71d86944362bf482c8dffced976/accepted.json)；[交接 5](submissions/b09abf14ae8944b0aff1dd78946d578f/accepted.json)

- F4-conflict-index：whether a restart with empty instance space and empty conflict tables is a supported configuration
  尚无精确对应交接。

- F5-pending-proposal：whether the re-proposal path can duplicate a command that was already committed
  相关交接：[交接 1](submissions/90b34e641912400eb595c1c5d941266c/accepted.json)；[交接 2](submissions/80a20b5998274975accaa21b535ead64/accepted.json)

- F6-ballot-priority：whether the recovering leader's own record is adequately represented when its vbal was just overwritten with the new ballot
  相关交接：[交接 1](submissions/6d79296cf1f647f79f088f7dbe5ce244/accepted.json)；[交接 2](submissions/52d2733218d44f54b5b7c4044dca3e5d/accepted.json)；[交接 3](submissions/e35eea72b8104d2fadfecd15147ca43b/accepted.json)

- F7-durable-bytes：the confirmed check for claim C2-durable-record-preserves-written-fields shows the produced record does not carry the value written for bal and places Status inside the bytes a reader would use for…
  相关交接：[交接 1](submissions/57454b6541cb4f7ea5b3862380edd5f6/accepted.json)

- surface:client/client.go and client/buffer.go：client-side invocation, pipelining and reply matching were not read; A7 completion and retry semantics depend on them. The wire contract they speak (PROPOSE and STATS requests, ProposeReplyTS…
  尚无精确对应交接。

- surface:master/master.go：participant set and leader assignment registration were not read; registration supplies ReplicaId and nodeList to every replica through run.go registerWithMaster and can therefore change eligibility…
  尚无精确对应交接。

- surface:config/config.go and config/proxy.go：supplies N, protocol flags and the client-to-proxy mapping from configuration files; it injects values the epaxos code itself does not validate.
  尚无精确对应交接。

- surface:replica/defs/latency.go：injects per-peer delays for peer message delivery and client proposals (replicaListener and clientListener sleep before handing a message to its channel) and provides the local-address helper that…
  尚无精确对应交接。

- surface:rpc/rpc.go：byte-tagged message table used for registration and dispatch of every protocol message.
  尚无精确对应交接。

- surface:sibling protocol packages (swift, curp, n2paxos, paxos, fastpaxos)：separate protocol implementations outside this run's analysis roots; they share replica/ and state/ helpers but implement different responsibilities, and run.go selects epaxos for this target.
  尚无精确对应交接。

- surface:README.md protocol claims：the repository README asserts that the bundled EPaxos is the corrected version and that thriftiness is required for correct recovery; it is project documentation, not a verification source.
  尚无精确对应交接。

- surface:replica/sender.go：channel-based sender helper (Sender channel type with Send* methods) defined in the shared replica package; no caller outside its own file was found in the snapshot, so it carries no responsibility…
  尚无精确对应交接。

- surface:replica/mset.go：message-set helper (MsgSet with quorum-based Add/Free) defined in the shared replica package; no caller outside its own file was found in the snapshot, so it carries no responsibility for the epaxos…
  尚无精确对应交接。

- surface:hook/hook.go and hook/cond.go：process-level helpers (a SIGUSR1 hook and a condition variable helper) with no reference from the replica, epaxos or client packages in the snapshot; they do not participate in the protocol.
  尚无精确对应交接。

- surface:state/state.go value and command codec：the value and command wire codecs frame every command a replica sends or receives; they carry no protocol decision, but the direct checks for claim C10-command-value-length-survives-the-wire…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 17 项；当前 Unit 12 项、义务 12 项、固定检查制品 26 项。正式执行尝试 26 次；已保存评估的义务 12 项，其中有实际比较 12 项。已确认违反 10 项、有限检查未见违反 1 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1004.58 秒、18 次 Agent 调用、7 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 7200.0 | 6195.42 | 1004.58 |
| Agent 调用 | 120 | 102 | 18 |
| 控制器目标执行 | 36 | 29 | 7 |
| 新 Unit | 12 | 12 | 0 |
| 语义复核 | 24 | 24 | 0 |
| 修订 | 12 | 1 | 11 |

受控目标执行进程耗时（正式检查＋探索）：已记录 243.10 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 252.83 秒。

目标执行组成：正式检查 26 次＋探索 3 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v57`；展示版本 `audit-products-v57`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/36ed09de953946648bb1a98e897636db/check.json)。

停止依据（记录摘录）：Agent stopped: User cancelled action；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`cancelled`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/36ed09de953946648bb1a98e897636db/check.json)；[stdout](logs/36ed09de953946648bb1a98e897636db/stdout.log)；[stderr](logs/36ed09de953946648bb1a98e897636db/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

- 失败／未完成：[exploration](logs/5b9267ea51d742f9a6fdcfb7a6594990/stdout.log)；[stderr](logs/5b9267ea51d742f9a6fdcfb7a6594990/stderr.log)；[执行记录](logs/5b9267ea51d742f9a6fdcfb7a6594990/check.json)
