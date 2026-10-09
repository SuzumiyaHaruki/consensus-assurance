# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **60.01 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 6 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 跟随者日志身份一致性检查的对应性审查 | 已确认违反 | 在忠实实现但 StoreLogs 于 DeleteRange 成功后失败一次的 LogStore 下，跟随者截断冲突后缀后缓存最后索引仍为 3 而存储最后索引为 1，随后的合法 AppendEntries 被拒绝（accepted=false）；该比较在本义务范围内成立，生产存储可达性与集群后果仍待定。 | [C-append-log-identity-consistency](#claim-C-append-log-identity-consistency) |
| 2. 快照安装后日志身份一致性检查的对应性审查 | 已确认违反 | 在单调日志存储的跟随者上，真实 InstallSnapshot 成功安装索引 2 的快照后，日志存储被清空（stored_index=0）而缓存身份仍为 5（last_entry_index=5），随后领导者自快照索引继续的 AppendEntries… | [C-snapshot-install-log-identity](#claim-C-snapshot-install-log-identity) |
| 3. 引导写入部分失败后重试被阻止的对应性审查 | 已确认违反 | 在一次性 StoreLog 失败的干净存储上，BootstrapCluster 首次失败后 HasExistingState 报告为已有状态，随后的重试被拒绝（bootstrap only works on new clusters），日志索引仍为 0，即未写入任何引导配置条目；该比较在本恢复义务范围内成立，生产存储可达性与… | [C-bootstrap-partial-state](#claim-C-bootstrap-partial-state) |
| 4. 用户快照恢复中止语义检查的对应性审查 | 已确认违反 | 在受控调度下，领导者先以 ErrAbortedByRestore 中止在途客户端future，随后快照创建失败而未发生恢复；此时该条目仍在日志中且被 commitment 记为已提交（commitment_index=1, entry_present=true,… | [C-restore-abort-outcome](#claim-C-restore-abort-outcome) |
| 5. 快照列表排序契约检查的对应性审查 | 已确认违反 | 在保留两个（term 与 index 反向排序）快照的真实 FileSnapshotStore 上，List() 返回的首个 index 为 50 而实际最大 index 为 80（highest_first=false），与接口所述“最高 index 在前”不符；该比较针对写入的接口契约成立，运行中是否会出现这种保留组合仍待定。 | [C-snapshot-list-order](#claim-C-snapshot-list-order) |
| 6. 启动恢复快照选择检查的对应性审查 | 已确认违反 | 在保留两个（term 与 index 反向排序）快照、日志与稳定存储为空的节点上，启动恢复采用了先列出的索引 50 快照，而存储中最高索引为 80（applied_index=50, newest_adopted=false），即恢复基线低于存储所持有的最新状态；该比较在本恢复义务范围内成立，运行中是否会出现这种保留组合仍待定。 | [C-startup-recovery-newest](#claim-C-startup-recovery-newest) |
| Under a leadership change that races the leader's commit notification, is every index counted as committed by… | 源码解释（研究者处置，未经性质执行） | Source reading answers this Candidate's specific suspicion, so the question is disposed as explained by existing mechanisms rather than escalated. The leaderLoop… | [受理解释](submissions/37d2f5435f2b47b88f530ee4d02d61d2/accepted.json) |
| During a leadership transfer, is the election the old leader provokes constrained the same way an ordinary election is - is the… | 源码解释（研究者处置，未经性质执行） | Closing the leadership-transfer surface with a sourced explanation rather than a check. The question selects the authority-establishment lifecycle of F-leadership… | [受理解释](submissions/812a01db71ef4f7bb5567de3c19bc371/accepted.json) |
| In pipelined replication mode, can the optimistic advancement of the send index cause an entry to be skipped or double-counted in… | 源码解释（研究者处置，未经性质执行） | Closing the last deferred surface, the pipelined append path, with a sourced explanation while recording it in the map. The map maps the pipeline surface to… | [受理解释](submissions/245ba59f16fe4e9c98c86b1f5ac50634/accepted.json) |
| Does VerifyLeader confirm that the node still holds current-term authority before a caller serves a read - is the future… | 源码解释（研究者处置，未经性质执行） | Classifying and closing the last remaining unclassified surface, VerifyLeader, with a sourced explanation while recording it in the map. The map changes the surface from… | [受理解释](submissions/2d77eeaa285e4b6d83c66e5eb93926c8/accepted.json) |

<a id="claim-C-append-log-identity-consistency"></a>

### 1. 跟随者日志身份一致性检查的对应性审查

**已确认违反**。要求原文：When the follower append handler removes a conflicting log suffix via DeleteRange and a subsequent store or configuration-decode step returns an error, the node's cached last log identity (raftState.lastLogIndex/lastLogTerm, surfaced through AppendEntriesResponse.LastLog and the RequestVote up-to-date comparison) must not continue to describe removed entries in a way that makes the node reject every subsequent AppendEntries for that range; the node must either update the cached identity on the error path or otherwise re-derive its reported identity so that replication can proceed.

决定性范围：Follower main goroutine handling an AppendEntries whose first incoming entry conflicts with the stored suffix, with a faithfully implemented LogStore that returns an error from StoreLogs after DeleteRange has already succeeded (or from the deprecated peer decode after StoreLogs succeeded).
The injected LogStore implements the LogStore interface faithfully, so DeleteRange may succeed and a later StoreLogs may return an error (for example an I/O failure).；The node is a voter in the latest configuration and stays in Follower state while the divergence persists.。
范围参数：{"truncated_range": "[entry.Index, previous lastLogIndex]", "cached_identity_fields": "raftState.lastLogIndex, raftState.lastLogTerm"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：跟随者日志身份一致性检查的对应性审查；在忠实实现但 StoreLogs 于 DeleteRange 成功后失败一次的 LogStore 下，跟随者截断冲突后缀后缓存最后索引仍为 3 而存储最后索引为 1，随后的合法 AppendEntries 被拒绝（accepted=false）；该比较在本义务范围内成立，生产存储可达性与集群后果仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/8785c8a5226440a68dc7f232725caf37/assurance_generated_test.go)；[条件与检查器](direct-checks/8785c8a5226440a68dc7f232725caf37/plan.json)；[原始观察](logs/e4bd66d32b28489f8bec1ed743957c41/stdout.log)；[assessment](direct-checks/8785c8a5226440a68dc7f232725caf37/e4bd66d32b28489f8bec1ed743957c41-assessment.json)；[对应性复核](submissions/6d182b9d4c844b1eab300ce72c0c51a5/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.02 秒；执行进程耗时 12.54 秒；[实际命令、工具版本与输入记录](logs/e4bd66d32b28489f8bec1ed743957c41/check.json)
执行边界：In-package Go test that seeds a log suffix, injects a LogStore whose StoreLogs fails once, drives appendEntries through the real handler, and observes the follower's cached last log identity and its acceptance of a later request. Uses only real target code and a faithfully failing LogStore; no protocol logic is altered.；skipStartup is set so the main goroutine does not run; appendEntries is invoked directly with a real RPC struct, so the handler logic under test is unchanged.；The LogStore wrapper fails exactly one StoreLogs call to expose the error path; all other store behaviour is the in-repository InmemStore.
固定比较 `P-append-accepted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| accepted | false |
| conflict.truncated_to | 1 |
| conflict.node | n1 |
| conflict.store_logs_failed | true |
| failure.node | n1 |
| failure.truncated_to | 1 |
| cached_index | 3 |
| event | append_probe |
| stored_index | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：追加条目配置解析失败路径的对应性审查；在协议版本 2 的跟随者上，冲突的弃用成员条目被成功写入后解析失败并提前返回，缓存最后索引仍为 3 而存储最后索引为 2，随后对该区间的合法 AppendEntries 被拒绝（accepted=false）；该比较在本义务范围内成立，真实领导者是否产生该条目仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/30dfceb0d3de429785c1eaf11d94b0d4/assurance_generated_test.go)；[条件与检查器](direct-checks/30dfceb0d3de429785c1eaf11d94b0d4/plan.json)；[原始观察](logs/ccb85562ee7c49d0baf496535dc6a151/stdout.log)；[assessment](direct-checks/30dfceb0d3de429785c1eaf11d94b0d4/ccb85562ee7c49d0baf496535dc6a151-assessment.json)；[对应性复核](submissions/c62caa699ace45afb7283cedef7f74a3/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.64 秒；执行进程耗时 12.31 秒；[实际命令、工具版本与输入记录](logs/ccb85562ee7c49d0baf496535dc6a151/check.json)
执行边界：In-package Go test that seeds a log suffix, drives appendEntries with a conflicting LogAddPeerDeprecated entry whose payload cannot be decoded, and then drives the next valid AppendEntries, observing the cached identity, the store contents, the RPC error and the acceptance result.；skipStartup is set so the main goroutine does not run; the append handler is driven directly with a real RPC struct.；ProtocolVersion 2 is used so the deprecated peer-entry type is legal and its configuration handling runs; with protocol version < 3 the LocalID must be the network address, which the harness sets.；The deprecated entry carries an undecodable payload to make the configuration step fail after the store call succeeded; no protocol logic is altered.
固定比较 `P-errorpath-accepted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| accepted | false |
| configerror.node | n1 |
| configerror.success | false |
| cached_index | 3 |
| event | error_path_probe |
| stored_index | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：截断失败后拒绝投票检查的对应性审查；在截断冲突后缀且 StoreLogs 失败后，缓存最后条目仍为 (index 3, term 2) 而真实日志止于 (index 1, term 1)；对日志为 (index 2, term 2) 的候选者（实际更新）投票被拒绝（granted=false），说明同一缓存偏差也会扣留选票；该比较在本义务范围内成立，集群级后果仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e6df2bcef9ee469f8fa031ef66de1955/assurance_generated_test.go)；[条件与检查器](direct-checks/e6df2bcef9ee469f8fa031ef66de1955/plan.json)；[原始观察](logs/7fad4550db46469aa90fcb2d5de79b3e/stdout.log)；[assessment](direct-checks/e6df2bcef9ee469f8fa031ef66de1955/7fad4550db46469aa90fcb2d5de79b3e-assessment.json)；[对应性复核](submissions/e59c3c92b69442f0b955a209c5847170/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.63 秒；执行进程耗时 12.24 秒；[实际命令、工具版本与输入记录](logs/7fad4550db46469aa90fcb2d5de79b3e/check.json)
执行边界：In-package Go test that drives the confirmed truncation-then-StoreLogs-failure premise, then calls the real requestVote handler with a candidate whose log is more up to date than the node's real log, reporting the cached and real identities and the granted result.；skipStartup is set so the main goroutine does not run; appendEntries and requestVote are driven directly with real RPC structs.；The store wrapper fails exactly one StoreLogs call to produce the stale cached identity, and no other store behaviour is changed.
固定比较 `P-vote-granted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| granted | false |
| truncated.node | n1 |
| truncated.cached_index | 3 |
| truncated.real_index | 1 |
| cached_index | 3 |
| candidate_index | 2 |
| candidate_term | 2 |
| event | vote_decision |
| real_index | 1 |
| real_term | null |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C-snapshot-install-log-identity"></a>

### 2. 快照安装后日志身份一致性检查的对应性审查

**已确认违反**。要求原文：When a follower installs a remote snapshot whose index is below its cached last log index and its LogStore is monotonic (IsMonotonic true, so installSnapshot resets the log store), the node must re-derive or update its cached last log identity so that the leader's subsequent AppendEntries from the snapshot index are accepted; leaving the cache naming entries the emptied store no longer holds must not make the follower reject recovery replication indefinitely.

决定性范围：Follower main goroutine handling a valid InstallSnapshot RPC while raftState.lastLogIndex is above the incoming snapshot index and the injected LogStore implements MonotonicLogStore with IsMonotonic() true.
The InstallSnapshot request is legal: supported snapshot version, term not older than currentTerm, size matching the streamed bytes.；The LogStore faithfully implements the LogStore interface and reports IsMonotonic() true, so the install path calls removeOldLogs.；The leader continues to replicate from snapshotIndex+1 after a successful install (as sendLatestSnapshot does).。
范围参数：{"cached_identity_fields": "raftState.lastLogIndex, raftState.lastLogTerm", "reset_call": "removeOldLogs -> compactLogsWithTrailing(lastLogIdx,lastLogIdx,0)"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：快照安装后日志身份一致性检查的对应性审查；在单调日志存储的跟随者上，真实 InstallSnapshot 成功安装索引 2 的快照后，日志存储被清空（stored_index=0）而缓存身份仍为 5（last_entry_index=5），随后领导者自快照索引继续的 AppendEntries 被拒绝（accepted=false）；该比较在本恢复义务范围内成立，非单调分支与集群级后果仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/47f090bba2a64a828b39d7e732b9d3e8/assurance_generated_test.go)；[条件与检查器](direct-checks/47f090bba2a64a828b39d7e732b9d3e8/plan.json)；[原始观察](logs/080acf9a25e5464ba043a52f4ce3eb9d/stdout.log)；[assessment](direct-checks/47f090bba2a64a828b39d7e732b9d3e8/080acf9a25e5464ba043a52f4ce3eb9d-assessment.json)；[对应性复核](submissions/416b5b76ba574fb085384e6e2010c10b/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.73 秒；执行进程耗时 12.33 秒；[实际命令、工具版本与输入记录](logs/080acf9a25e5464ba043a52f4ce3eb9d/check.json)
执行边界：In-package Go test that seeds a log suffix, marks the LogStore monotonic, drives the real InstallSnapshot handler with a real RPC reader, then drives the real appendEntries handler with the leader's post-install request and observes the follower's cached identity, the emptied store and the acceptance result.；skipStartup is set and only the FSM goroutine is started, so the install handler runs without the main loop; installSnapshot's restore step therefore reaches the real FSM goroutine and the FSM is a no-op stub that ignores the snapshot bytes.；The single-voter configuration is installed directly rather than bootstrapped, so the handler's peer-set update and log reset run without real peers.；The snapshot payload is three arbitrary bytes with a matching Size; the content is irrelevant because the stub FSM performs no restore work.
固定比较 `P-recovery-accepted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| accepted | false |
| install.node | n1 |
| install.success | true |
| identity.node | n1 |
| cached_index | 5 |
| event | recovery_probe |
| snapshot_index | 2 |
| stored_index | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C-bootstrap-partial-state"></a>

### 3. 引导写入部分失败后重试被阻止的对应性审查

**已确认违反**。要求原文：BootstrapCluster must not leave a store reporting existing state unless the bootstrap configuration entry was durably stored: after a store call fails, the server must remain bootstrappable - either the partial term write is not treated as existing state by the bootstrap guard, or the write order otherwise keeps a retry possible.

决定性范围：A fresh store (no current term, log entry or snapshot) on which BootstrapCluster runs with a caller-supplied LogStore whose StoreLog fails once, followed by a retry on the same store.
The server config and the initial configuration pass their validations.；The LogStore implements the interface faithfully, so StoreLog may return an error while the StableStore write has already succeeded.。
范围参数：{"write_order": "setCurrentTerm (StableStore) then StoreLog (LogStore)", "guard_input": "keyCurrentTerm > 0"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：引导写入部分失败后重试被阻止的对应性审查；在一次性 StoreLog 失败的干净存储上，BootstrapCluster 首次失败后 HasExistingState 报告为已有状态，随后的重试被拒绝（bootstrap only works on new clusters），日志索引仍为 0，即未写入任何引导配置条目；该比较在本恢复义务范围内成立，生产存储可达性与 RecoverCluster 补救仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/001251da2f894aa3990796de85d56ea0/assurance_generated_test.go)；[条件与检查器](direct-checks/001251da2f894aa3990796de85d56ea0/plan.json)；[原始观察](logs/e71729d1bfeb458d8cf946df87654d08/stdout.log)；[assessment](direct-checks/001251da2f894aa3990796de85d56ea0/e71729d1bfeb458d8cf946df87654d08-assessment.json)；[对应性复核](submissions/1fd5fd6be3d749e687eac1c5a50acc87/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.95 秒；执行进程耗时 12.56 秒；[实际命令、工具版本与输入记录](logs/e71729d1bfeb458d8cf946df87654d08/check.json)
执行边界：In-package Go test that runs BootstrapCluster on a fresh in-memory store with a single simulated StoreLog failure, checks HasExistingState afterwards, then retries BootstrapCluster on the now-healthy store and reports both outcomes.；The LogStore wrapper fails exactly one StoreLog call to expose the ordering between the term write and the configuration-entry write; all other store behaviour is the in-repository InmemStore.；Protocol version 3 is used so the seeded entry is a LogConfiguration entry; no protocol logic is altered.
固定比较 `P-retry-allowed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| retry_allowed | false |
| partial.node | n1 |
| partial.first_error | true |
| partial.store_log_failed | true |
| event | bootstrap_outcome |
| existing_state | true |
| log_index_after_retry | 0 |
| second_error | bootstrap only works on new clusters |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：引导部分失败后恢复路径对照检查的对应性审查；在同一存储上，一次 StoreLog 失败导致引导部分完成后，采用文档所述 RecoverCluster 返回 nil 错误并留下一个快照（recover_succeeded=true, snapshots_after=1），说明操作员恢复路径可用，从而把已确认的引导缺陷限定为“普通重试被阻止，直至执行恢复路径”；该对照不改变主结论。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/2c846473e2db4422a0fd1bfba09530c5/assurance_generated_test.go)；[条件与检查器](direct-checks/2c846473e2db4422a0fd1bfba09530c5/plan.json)；[原始观察](logs/753e79264b87444b847f26c8b16c3dd9/stdout.log)；[assessment](direct-checks/2c846473e2db4422a0fd1bfba09530c5/753e79264b87444b847f26c8b16c3dd9-assessment.json)；[对应性复核](submissions/d18334bf12864b6b9d9a81d0c009e5cf/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.85 秒；执行进程耗时 12.43 秒；[实际命令、工具版本与输入记录](logs/753e79264b87444b847f26c8b16c3dd9/check.json)
执行边界：In-package Go test that fails one StoreLog call during BootstrapCluster, confirms the store now reports existing state, then calls RecoverCluster on the same store and reports the error, the resulting log index and the snapshot count.；The LogStore wrapper fails exactly one StoreLog call to reproduce the partial bootstrap; RecoverCluster itself runs unchanged.；The FSM is a no-op stub, so RecoverCluster's snapshot steps exercise raft's bookkeeping only.
固定比较 `P-recover-succeeds`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| node | n1 |
| recover_succeeded | true |
| partial.node | n1 |
| partial.first_error | true |
| partial.store_log_failed | true |
| event | recover_control |
| existing_state | true |
| log_index_after | 18446744073709551615 |
| recover_error | <nil> |
| snapshots_after | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C-restore-abort-outcome"></a>

### 4. 用户快照恢复中止语义检查的对应性审查

**已确认违反**。要求原文：On the leader, answering inflight Apply/Barrier futures with ErrAbortedByRestore must not precede a user snapshot restore that then fails: the documented meaning of ErrAbortedByRestore ('the write effectively failed since its effects will not be present in the FSM after the restore') requires either a completed restore or that the entries behind those futures can no longer be committed and applied, otherwise a client receives a definite failure signal for an operation that may still be committed and consumed.

决定性范围：The leader's own user-triggered restore path (Raft.Restore -> userRestoreCh -> restoreUserSnapshot) when one or more client futures are still inflight and the caller-supplied SnapshotStore fails at Create, write or close after the inflight abort loop has already run.
The injected SnapshotStore implements the SnapshotStore interface faithfully, so Create, the sink Write or Close may return an error.；The node is Leader and the configuration guard (committedIndex == latestIndex) passes, so the handler proceeds past its early return.；The aborted futures correspond to entries already appended to the leader's LogStore.。
范围参数：{"aborted_error": "ErrAbortedByRestore", "failure_point": "r.snapshots.Create / io.Copy(sink, reader) / sink.Close after the inflight loop"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：用户快照恢复中止语义检查的对应性审查；在受控调度下，领导者先以 ErrAbortedByRestore 中止在途客户端future，随后快照创建失败而未发生恢复；此时该条目仍在日志中且被 commitment 记为已提交（commitment_index=1, entry_present=true, effects_absent=false），与文档所述“写入实际失败”不符，该比较在本义务范围内成立。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/38be332ebcd94218acf4f2f38ff2440c/assurance_generated_test.go)；[条件与检查器](direct-checks/38be332ebcd94218acf4f2f38ff2440c/plan.json)；[原始观察](logs/75816d44bd434307a9a9b2d13bc6ae13/stdout.log)；[assessment](direct-checks/38be332ebcd94218acf4f2f38ff2440c/75816d44bd434307a9a9b2d13bc6ae13-assessment.json)；[对应性复核](submissions/3ff83baa6fe9422a8d1efc68765546eb/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.47 秒；执行进程耗时 12.13 秒；[实际命令、工具版本与输入记录](logs/75816d44bd434307a9a9b2d13bc6ae13/check.json)
执行边界：In-package Go test that places a real dispatched client entry inflight on a single-voter leader, injects a SnapshotStore whose Create fails, calls restoreUserSnapshot with a real SnapshotMeta, and observes the aborted future's error, the entry's presence in the LogStore and the commitment's commit decision.；skipStartup is set so the main goroutine does not run; leaderState is set up directly and the restore handler is called with the committed==latest configuration guard satisfied.；The single-voter configuration is installed directly rather than by bootstrapping a cluster, so a dispatched entry reaches the commitment's quorum without real peers.；The commit decision is read from the commitment object (commitment.getCommitIndex) because no leader loop consumes commitCh in this controlled schedule.
固定比较 `P-effects-absent`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| effects_absent | false |
| abort.node | n1 |
| abort.restore_failed | true |
| commitment_index | 1 |
| committed | true |
| committed_after | 0 |
| committed_before | 0 |
| entry_present | true |
| event | abort_outcome |
| future_error | snapshot restored while committing log |
| restore_failed | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C-snapshot-list-order"></a>

### 5. 快照列表排序契约检查的对应性审查

**已确认违反**。要求原文：SnapshotStore.List must return the retained snapshots in descending applied-index order, with the first element being the snapshot with the highest Index, so that a consumer taking the first element - the leader's sendLatestSnapshot and the startup restore - obtains the most advanced snapshot the store holds.

决定性范围：The in-repository FileSnapshotStore with retention at least two, holding two snapshots whose last-entry terms and indexes are ordered in opposite directions, listed through List.
Both snapshots are created through the public Create/Write/Close path and are retained, so List returns both.；The store is otherwise healthy: metadata readable and versions supported.。
范围参数：{"order_contract": "descending by Index, highest first", "implementation_comparator": "snapMetaSlice.Less compares Term before Index under sort.Reverse"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：快照列表排序契约检查的对应性审查；在保留两个（term 与 index 反向排序）快照的真实 FileSnapshotStore 上，List() 返回的首个 index 为 50 而实际最大 index 为 80（highest_first=false），与接口所述“最高 index 在前”不符；该比较针对写入的接口契约成立，运行中是否会出现这种保留组合仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/2356a79a46de4567bc875b62cff0b67c/assurance_generated_test.go)；[条件与检查器](direct-checks/2356a79a46de4567bc875b62cff0b67c/plan.json)；[原始观察](logs/e27757af32cb4fafa83607039ca43755/stdout.log)；[assessment](direct-checks/2356a79a46de4567bc875b62cff0b67c/e27757af32cb4fafa83607039ca43755-assessment.json)；[对应性复核](submissions/43cbccfb63d548bb80e813e9144a9b8f/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.68 秒；执行进程耗时 12.30 秒；[实际命令、工具版本与输入记录](logs/e27757af32cb4fafa83607039ca43755/check.json)
执行边界：In-package Go test that creates two real snapshots through FileSnapshotStore.Create/Write/Close with inverted (term, index), lists them, and reports the first index, the second index and the maximum index held by the store.；The snapshots use an empty Configuration and a real in-memory transport only to satisfy the Create signature; the ordering under test does not depend on them.；The store is a real FileSnapshotStore rooted in the test's temporary directory with retention 2, so both snapshots are retained.
固定比较 `P-order-highest-first`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| highest_first | false |
| created.node | n1 |
| created.both_retained | true |
| event | list_order |
| first_index | 50 |
| first_term | 9 |
| max_index | 80 |
| second_index | 80 |
| second_term | 4 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

本场景复核摘录：领导者快照发送选择检查的对应性审查；在保留两个（term 与 index 反向排序）快照的领导者上，sendLatestSnapshot 实际发送的 LastLogIndex 为 50（term 9），而存储中最高索引为 80（sent=true, newest_sent=false），即向落后跟随者发送了较旧的快照；该比较在本排序义务范围内成立，运行中是否会出现这种保留组合仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/f0f35981df8040b292aeaaed1a8de79a/assurance_generated_test.go)；[条件与检查器](direct-checks/f0f35981df8040b292aeaaed1a8de79a/plan.json)；[原始观察](logs/c3121fc595214d499f50ab6b48b49ed9/stdout.log)；[assessment](direct-checks/f0f35981df8040b292aeaaed1a8de79a/c3121fc595214d499f50ab6b48b49ed9-assessment.json)；[对应性复核](submissions/46b076af1dc648f69d2f2fda876ab37b/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.01 秒；执行进程耗时 11.73 秒；[实际命令、工具版本与输入记录](logs/c3121fc595214d499f50ab6b48b49ed9/check.json)
执行边界：In-package Go test that seeds two real snapshots through FileSnapshotStore.Create/Write/Close in inverse order, then calls the leader's sendLatestSnapshot with a follower replication state and a transport that records the InstallSnapshot metadata instead of forwarding it.；The transport wrapper records the InstallSnapshot request and answers success instead of sending it to a peer, so no real follower is needed; all other transport methods delegate to the in-memory transport.；skipStartup is set and leaderState is created directly, so the send path runs without the main loop or a real election.；The snapshots use an empty Configuration and a real in-memory transport only to satisfy the Create signature.
固定比较 `P-newest-sent`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| newest_sent | false |
| prepared.node | n1 |
| prepared.retained | 2 |
| event | snapshot_sent |
| max_index | 80 |
| sent | true |
| sent_index | 50 |
| sent_term | 9 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-C-startup-recovery-newest"></a>

### 6. 启动恢复快照选择检查的对应性审查

**已确认违反**。要求原文：NewRaft's startup recovery must adopt the retained snapshot with the highest applied index, so that a restart does not set its applied baseline below the most advanced state the snapshot store holds; a consumer that takes the first listed snapshot must therefore be given the highest-index one.

决定性范围：A node starting with an empty log and stable store and a FileSnapshotStore retaining two snapshots whose terms and indexes are ordered in opposite directions, so the restore path must choose between them.
Both snapshots are readable and load successfully, so the choice is decided by the order alone.；The node has no log or stable state that could pin its applied baseline independently.。
范围参数：{"retained_pair": "(term 9, index 50) and (term 4, index 80)", "selection_rule": "restoreSnapshot keeps the first listed snapshot that loads"}
[完整要求、假设与排除范围](state.json)

本场景复核摘录：启动恢复快照选择检查的对应性审查；在保留两个（term 与 index 反向排序）快照、日志与稳定存储为空的节点上，启动恢复采用了先列出的索引 50 快照，而存储中最高索引为 80（applied_index=50, newest_adopted=false），即恢复基线低于存储所持有的最新状态；该比较在本恢复义务范围内成立，运行中是否会出现这种保留组合仍待定。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/d905e1d481eb45ae91cae346b90d5134/assurance_generated_test.go)；[条件与检查器](direct-checks/d905e1d481eb45ae91cae346b90d5134/plan.json)；[原始观察](logs/0182ff14f9b54ae49bcf0517c2e548ee/stdout.log)；[assessment](direct-checks/d905e1d481eb45ae91cae346b90d5134/0182ff14f9b54ae49bcf0517c2e548ee-assessment.json)；[对应性复核](submissions/5687957f6ece4abfa217855da8dace60/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.24 秒；执行进程耗时 12.83 秒；[实际命令、工具版本与输入记录](logs/0182ff14f9b54ae49bcf0517c2e548ee/check.json)
执行边界：In-package Go test that seeds two real snapshots through FileSnapshotStore.Create/Write/Close in inverse (term, index) order, lists them, then constructs Raft with skipStartup and an empty log, and reports the applied index, the adopted snapshot index and the highest retained index.；skipStartup is set so NewRaft performs validation, term/log reads and the snapshot restore but does not start the background goroutines; the restore path under test is unchanged.；The FSM is a no-op stub, so the restored contents are irrelevant and only raft's own recovery bookkeeping is observed.；The snapshots use an empty Configuration and a real in-memory transport only to satisfy the Create signature.
固定比较 `P-newest-adopted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| newest_adopted | false |
| prepared.node | n1 |
| prepared.retained | 2 |
| applied_index | 50 |
| event | startup_recovery |
| max_index | 80 |
| snapshot_index | 50 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v17：概览、Behavior／Fact 与来源](audit-spec/v17.json)。
- 共识形成与推进（原文导航摘录）：A client command enters the leader's applyCh (B-apply-api) and is dispatched by the leader main loop (B-leader-dispatch), which assigns (Index,Term), stores it in the local LogStore, marks its own matchIndex and…
- 上下文／权威转换（原文导航摘录）：Authority is a per-term value. Each node persists its current term and any vote through StableStore before acting (B-term-vote-persist). A follower whose heartbeat timer expires starts a candidate campaign, soliciting…
- 两条主线的连接（原文导航摘录）：The two core lines meet at the startIndex rule and at the voter set. A leader may only advance commitIndex once a quorum of the current configuration has stored the first entry of the leader's term (B-commit-term-rule…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.81 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 6.40 分钟 · 受理 continue：First Candidate on the accepted v1 map, selected from the A1/A2 connection. The commit index is advanced by the commitment object…。[完整交接](submissions/facb126a49f04df382986669687732bd/accepted.json)

- 7.26 分钟 · 受理 explained：Source reading answers this Candidate's specific suspicion, so the question is disposed as explained by existing mechanisms rather than…。[完整交接](submissions/37d2f5435f2b47b88f530ee4d02d61d2/accepted.json)

- 8.06 分钟 · 受理 continue：Second Candidate, selected from the accepted map's own surfaced lead: B-follower-append carries the explicit implementation unknown…。[完整交接](submissions/f9b51e52a2024589a531da65378d4671/accepted.json)

- 9.16 分钟 · 受理 obligation：Source reading supports fixing one attributed responsibility for this Candidate without presuming a violation. appendEntries updates…。[完整交接](submissions/2c40168fdab94bc28be9a8d9de9e5229/accepted.json)

- 11.37 分钟 · 实际执行：跟随者日志身份一致性检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/e4bd66d32b28489f8bec1ed743957c41/check.json)

- 12.36 分钟 · 受理 review：跟随者日志身份一致性检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/6d182b9d4c844b1eab300ce72c0c51a5/accepted.json)

- 14.46 分钟 · 受理 continue：New Candidate selected from an unread surface (Raft.restoreUserSnapshot, previously recorded as deferred) and from the same family of…。[完整交接](submissions/447145cf265b4ccbb7a0c6418661b08f/accepted.json)

- 15.20 分钟 · 受理 obligation：Source reading supports fixing one attributed responsibility for this Candidate without presuming a violation. restoreUserSnapshot answers…。[完整交接](submissions/539cb6ff333349c48454ee0b796216a7/accepted.json)

- 16.65 分钟 · 实际执行：用户快照恢复中止语义检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/75816d44bd434307a9a9b2d13bc6ae13/check.json)

- 17.12 分钟 · 受理 review：用户快照恢复中止语义检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/3ff83baa6fe9422a8d1efc68765546eb/accepted.json)

- 18.70 分钟 · 受理 continue：New Candidate on the recovery responsibility (A3) that the map recorded as a deferred surface. The principal Fact is F-log-persisted, whose…。[完整交接](submissions/0a210d6b740c4b11939689f2d8521962/accepted.json)

- 20.89 分钟 · 受理 obligation：Source reading plus construction in a scratch copy supports fixing one attributed responsibility for this Candidate. installSnapshot…。[完整交接](submissions/4c0444c0831f4a17abbebb84fd0647a1/accepted.json)

- 22.02 分钟 · 实际执行：快照安装后日志身份一致性检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/080acf9a25e5464ba043a52f4ce3eb9d/check.json)

- 22.42 分钟 · 受理 review：快照安装后日志身份一致性检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/416b5b76ba574fb085384e6e2010c10b/accepted.json)

- 25.85 分钟 · 实际执行：追加条目配置解析失败路径的对应性审查；执行完成；比较见 assessment。[执行记录](logs/ccb85562ee7c49d0baf496535dc6a151/check.json)

- 26.31 分钟 · 受理 review：追加条目配置解析失败路径的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/c62caa699ace45afb7283cedef7f74a3/accepted.json)

- 28.93 分钟 · 受理 continue：Map addition plus first Candidate for the snapshot-store listing responsibility recorded as sourced feedback last turn. The map adds…。[完整交接](submissions/4e017eddff204de1877ba5e8f943edc8/accepted.json)

- 30.37 分钟 · 实际执行：快照列表排序契约检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/e27757af32cb4fafa83607039ca43755/check.json)

- 30.88 分钟 · 受理 review：快照列表排序契约检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/43cbccfb63d548bb80e813e9144a9b8f/accepted.json)

- 32.76 分钟 · 受理 explained：Closing the leadership-transfer surface with a sourced explanation rather than a check. The question selects the authority-establishment…。[完整交接](submissions/812a01db71ef4f7bb5567de3c19bc371/accepted.json)

- 34.41 分钟 · 受理 explained：Closing the last deferred surface, the pipelined append path, with a sourced explanation while recording it in the map. The map maps the…。[完整交接](submissions/245ba59f16fe4e9c98c86b1f5ac50634/accepted.json)

- 35.02 分钟 · 受理 explained：Classifying and closing the last remaining unclassified surface, VerifyLeader, with a sourced explanation while recording it in the map.…。[完整交接](submissions/2d77eeaa285e4b6d83c66e5eb93926c8/accepted.json)

- 36.07 分钟 · 受理 continue：Map addition plus a new Candidate on the bootstrap responsibility. The map adds B-bootstrap-config (A4), the Behavior that seeds a…。[完整交接](submissions/2139948c38c444348ac106d64b5ac9bd/accepted.json)

- 37.56 分钟 · 实际执行：引导写入部分失败后重试被阻止的对应性审查；执行完成；比较见 assessment。[执行记录](logs/e71729d1bfeb458d8cf946df87654d08/check.json)

- 38.10 分钟 · 受理 review：引导写入部分失败后重试被阻止的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/1fd5fd6be3d749e687eac1c5a50acc87/accepted.json)

- 42.68 分钟 · 实际执行：启动恢复快照选择检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/0182ff14f9b54ae49bcf0517c2e548ee/check.json)

- 43.17 分钟 · 受理 review：启动恢复快照选择检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/5687957f6ece4abfa217855da8dace60/accepted.json)

- 45.67 分钟 · 实际执行：领导者快照发送选择检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/c3121fc595214d499f50ab6b48b49ed9/check.json)

- 46.19 分钟 · 受理 review：领导者快照发送选择检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/46b076af1dc648f69d2f2fda876ab37b/accepted.json)

- 51.37 分钟 · 实际执行：截断失败后拒绝投票检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/7fad4550db46469aa90fcb2d5de79b3e/check.json)

- 51.84 分钟 · 受理 review：截断失败后拒绝投票检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/e59c3c92b69442f0b955a209c5847170/accepted.json)

- 52.37 分钟 · 受理 research：Final map handoff recording the third confirmed scenario for the append-log-identity relationship: the vote path. B-follower-append's…。[完整交接](submissions/5bb5c062ed194a09ab3c4078ac61fd9e/accepted.json)

- 54.25 分钟 · 受理 check：Second scenario for unit-C-bootstrap-partial-state, submitted as a diagnostic control to bound the confirmed finding's severity. It…。[完整交接](submissions/2c846473e2db4422a0fd1bfba09530c5/accepted.json)

- 54.48 分钟 · 实际执行：引导部分失败后恢复路径对照检查的对应性审查；执行完成；比较见 assessment。[执行记录](logs/753e79264b87444b847f26c8b16c3dd9/check.json)

- 54.99 分钟 · 受理 review：引导部分失败后恢复路径对照检查的对应性审查；v1 checker_correspondence: no_issue_found。[完整交接](submissions/d18334bf12864b6b9d9a81d0c009e5cf/accepted.json)

- 55.44 分钟 · 受理 research：Final map handoff recording the bounding control for the bootstrap finding. B-bootstrap-config's unknown now states that the executed…。[完整交接](submissions/56070b30cee743c6b796032b79cff8f5/accepted.json)

- 60.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/1b3d2de0d9ee4deaa0555f81a2a683c5/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<details><summary>地图登记与研究交接</summary>

以下是地图 v17 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v17：概览、Behavior／Fact 与来源](audit-spec/v17.json)

- core_overview：The FSM batch manager is an unmapped alternative mechanism for the same facts.；Startup reconstruction in NewRaft is only partially read: the snapshot selection and the configuration scan are traced…
  尚无精确对应交接。

- B-leader-dispatch：The exact timeline between leaderLoop's commitCh handling and concurrent dispatch of later entries is not asserted here
  尚无精确对应交接。

- B-follower-append：Sourced conditional relationship with three confirmed in-scope direct checks: on the two appendEntries error returns the raftState last-log cache is not updated, so the node can keep reporting an…
  尚无精确对应交接。

- B-quorum-commit：The exact set of matchIndexes after a configuration change that removes voters is not asserted here
  尚无精确对应交接。

- B-commit-term-rule：Interaction with a leadership transfer that reseeds leaderState mid-term is not asserted
  尚无精确对应交接。

- B-leader-apply：Sourced explanation: the FSM manager's apply paths are now read - a LogBarrier is never sent to the FSM itself and resolves after its batch is applied, a LogConfiguration without a ConfigurationStore…
  尚无精确对应交接。

- B-term-vote-persist：Whether a vote persisted without a subsequent successful RPC is later reused correctly after restart is not asserted
  尚无精确对应交接。

- B-election：Exact interplay of candidateFromLeadershipTransfer with RequestVote.LeadershipTransfer is not fully traced
  尚无精确对应交接。

- B-authority-loss：Whether every replication goroutine observes the stale term before a new term is installed is not asserted
  尚无精确对应交接。

- B-leader-lease：Exact formula for the lease check interval is not restated here
  尚无精确对应交接。

- B-config-eligibility：Staging/non-voter promotion is not traced
  尚无精确对应交接。

- B-snapshot-install：Sourced conditional relationship: on the monotonic-store branch the install path empties the log store without updating the cached last log identity, so a follower whose cached last index exceeds the…
  尚无精确对应交接。

- B-apply-api：Exact semantics of the optional per-call timeout for post-enqueue waiting are externalised to deferError and not traced
  尚无精确对应交接。

- B-restore-abort：Sourced conditional relationship: the handler answers inflight futures with ErrAbortedByRestore before the fallible snapshot creation, so a failed restore leaves a definite 'write effectively failed'…
  尚无精确对应交接。

- B-snapshot-store-list：Sourced conditional relationship with three confirmed in-scope direct checks: the interface documents descending order with the highest index first, while snapMetaSlice.Less orders by term first, and…
  尚无精确对应交接。

- B-bootstrap-config：Sourced conditional relationship with a confirmed in-scope direct check and a bounding control: the current-term write and the configuration-entry write are not atomic and run in that order with no…
  尚无精确对应交接。

- F-log-persisted：Concrete LogStore fsync semantics are external to this module
  尚无精确对应交接。

- F-committed：The precise follower commitIndex after a snapshot install is not asserted here
  尚无精确对应交接。

- F-term-vote：Recovery ordering relative to LogStore at NewRaft is not traced in this map
  尚无精确对应交接。

- F-leadership：How leadership transfer interacts with the persisted vote is not asserted
  尚无精确对应交接。

- F-snapshot-list-order：Whether the term-first comparator is intended as authority ordering rather than index recency, in which case only the interface wording disagrees
  尚无精确对应交接。

- surface:Raft.Restore error reporting after a completed restore：Raft.Restore returns the confirmation no-op's error, so a leadership loss or enqueue timeout that prevents the no-op from committing is reported the same way as a restore that failed before replacing…
  尚无精确对应交接。

- surface:Raft.Apply/ApplyLog future completion at shutdown：A logFuture returned by Apply/ApplyLog is initialized without a shutdown channel, so its Error() selects only on the response channel, while the main run loop exits when shutdownCh closes without…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 10 项；当前 Unit 6 项、义务 6 项、固定检查制品 10 项。正式执行尝试 10 次；已保存评估的义务 6 项，其中有实际比较 6 项。已确认违反 6 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 4 项。受理、执行与结论分别计数。

剩余 0.00 秒、36 次 Agent 调用、26 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 3600.0 | 3600.31 | 0.00 |
| Agent 调用 | 120 | 84 | 36 |
| 控制器目标执行 | 36 | 10 | 26 |
| 新 Unit | 12 | 6 | 6 |
| 语义复核 | 24 | 10 | 14 |
| 修订 | 12 | 0 | 12 |

受控目标执行进程耗时（正式检查＋探索）：已记录 123.40 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 127.21 秒。

目标执行组成：正式检查 10 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v59`；展示版本 `audit-products-v59`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/1b3d2de0d9ee4deaa0555f81a2a683c5/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`7.87470589899749`（配置值不表示触发了超时）。
[调用记录](logs/1b3d2de0d9ee4deaa0555f81a2a683c5/check.json)；[stdout](logs/1b3d2de0d9ee4deaa0555f81a2a683c5/stdout.log)；[stderr](logs/1b3d2de0d9ee4deaa0555f81a2a683c5/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：已记录完成事件；产物另行校验。

</details>

</details>

