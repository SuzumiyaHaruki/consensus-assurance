# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **39.73 分钟**；结束类型：**控制器记录的实际取消**。
已确认违反命题 5 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. For every FSM that implements ConfigurationStore, the library must invoke StoreConfiguration(index, configuration) for each…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-config-store-delivery](#claim-claim-config-store-delivery) |
| 2. Every AppendEntries RPC a server processes, including a pure heartbeat handled by the transport fast path, is subject to the same…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-heartbeat-header-gate](#claim-claim-heartbeat-header-gate) |
| 3. A TimeoutNow request is honoured only when its sender is attributed to the receiver's authority context, at minimum a voter of…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-timeout-now-attribution](#claim-claim-timeout-now-attribution) |
| 4. On a successful InstallSnapshot at index N, a receiver that no longer holds a log entry at N matching the snapshot's last…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-install-snapshot-alignment](#claim-claim-install-snapshot-alignment) |
| 5. Every client-facing future the library returns to a caller can complete: a request the library accepted is either responded by a…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-client-future-shutdown-escape](#claim-claim-client-future-shutdown-escape) |

<a id="claim-claim-config-store-delivery"></a>

### 1. For every FSM that implements ConfigurationStore, the library must invoke StoreConfiguration(index, configuration) for each…（原文摘录）

**已确认违反**。要求原文：For every FSM that implements ConfigurationStore, the library must invoke StoreConfiguration(index, configuration) for each committed configuration log entry that it delivers to the FSM, so that a persistent FSM can reconstruct configuration without an external snapshot.

决定性范围：A single Raft node whose FSM implements ConfigurationStore, processing a committed LogConfiguration entry. The obligation concerns delivery of the configuration entry to the FSM, not the correctness of the configuration value itself.
The entry has been committed (reached the FSM via processLogs).；The FSM implements ConfigurationStore as documented in configuration.go:44-52.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/c592aa3595304e6da012632e74662aca/assurance_generated_test.go)；[条件与检查器](direct-checks/c592aa3595304e6da012632e74662aca/plan.json)；[原始观察](logs/a898e05630e6440d97b856d7527274bd/stdout.log)；[assessment](direct-checks/c592aa3595304e6da012632e74662aca/a898e05630e6440d97b856d7527274bd-assessment.json)；[对应性复核](submissions/fc4fb4631ed345e1a85c1fa907a8ed79/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.79 秒；执行进程耗时 14.36 秒；[实际命令、工具版本与输入记录](logs/a898e05630e6440d97b856d7527274bd/check.json)
执行边界：TestAssuranceConfigStoreDeliveryForBatchingFSM builds a one-voter cluster (MakeClusterCustom with a custom FSM), waits for a stable leader, commits a LogConfiguration entry via AddNonvoter, then queues a Barrier so the FSM goroutine has processed the configuration entry before sampling. It emits CA_EVENT lines for the scenario declaration, the committed configuration entry, and the delivery observation (entry_delivered_to_fsm, applybatch_config_indices, store_configuration_calls, store_configuration_called).；No target protocol logic is altered. The harness only supplies an application FSM that implements FSM, BatchingFSM and ConfigurationStore, and observes what the library delivers to it.；No logging or helper initialization unrelated to the discriminator is added; SnapshotThreshold/SnapshotInterval are raised only so an automatic snapshot cannot interfere with the sampled FSM state.
固定比较 `c-store-config-called`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | cfg-1 |
| event | fsm_config_delivery |
| store_configuration_called | false |
| scenario.fsm_implements_batching | true |
| scenario.fsm_implements_configuration_store | true |
| cfg-committed.committed | true |
| config_index | 4 |
| entry_delivered_to_fsm | true |
| store_configuration_calls | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-heartbeat-header-gate"></a>

### 2. Every AppendEntries RPC a server processes, including a pure heartbeat handled by the transport fast path, is subject to the same…（原文摘录）

**已确认违反**。要求原文：Every AppendEntries RPC a server processes, including a pure heartbeat handled by the transport fast path, is subject to the same RPC-header compatibility check that the normal RPC path applies before appendEntries, so a peer outside the supported protocol-version window cannot step the server down, advance its persisted term, be adopted as the known leader or refresh its last contact.

决定性范围：A Raft node whose Transport implements the heartbeat fast path, receiving a pure AppendEntries heartbeat from a peer whose RPCHeader.ProtocolVersion is outside the window checkRPCHeader accepts. The obligation concerns the guard applied to that entry path, not the concurrency of the handler or the content of the heartbeat.
The transport classifies the request as a heartbeat exactly as net_transport does: Term != 0, a leader address present, PrevLogEntry/PrevLogTerm zero, no entries and LeaderCommitIndex zero.；checkRPCHeader is the authoritative protocol-version gate for AppendEntries on the normal path.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/1d0e6b56cf6648628baa736358192b4b/assurance_generated_test.go)；[条件与检查器](direct-checks/1d0e6b56cf6648628baa736358192b4b/plan.json)；[原始观察](logs/1987811182294bfbb372a36548be8d8b/stdout.log)；[assessment](direct-checks/1d0e6b56cf6648628baa736358192b4b/1987811182294bfbb372a36548be8d8b-assessment.json)；[对应性复核](submissions/521e0bbc7ea64f5585c904e3bfb9fb08/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.50 秒；执行进程耗时 12.07 秒；[实际命令、工具版本与输入记录](logs/1987811182294bfbb372a36548be8d8b/check.json)
执行边界：TestAssuranceHeartbeatFastPathProtocolGate builds three Raft nodes with all background goroutines disabled (conf.skipStartup), declares the out-of-window pure heartbeat, drives that request through processRPC on one node (recording rejection and whether any state changed) and through processHeartbeat on another (recording term/state/leader/last-contact before and after, and whether the guard was applied), and drives an in-window control request to show the difference is attributable to the header window rather than the request shape. CA_EVENT lines are emitted for the declaration, the normal-path result, the fast-path result and the control.；The heartbeat is delivered by invoking processHeartbeat directly. That is the body of the handler installed by transport.SetHeartbeatHandler, and the package's own integration test demonstrates the callback contract by calling r.processHeartbeat(rpc) from inside a custom heartbeat handler; net_transport's fast path is reached only over TCP and network access is disabled in the execution sandbox, so the transport classification is declared as a sourced premise instead of being reproduced.；Nodes are constructed with conf.skipStartup = true, the pattern used by the package's own tests, so no background goroutines run and the request handlers can be driven without racing the main loop.；No protocol logic is modified: the harness only constructs requests and reads existing state accessors.
固定比较 `c-hb-gate`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | hb-1 |
| event | fast_path_heartbeat_result |
| guard_applied | false |
| scenario.out_of_window_protocol_version | true |
| normal-rejected.rejected | true |
| normal-rejected.state_changed | false |
| error | <nil> |
| last_contact_refreshed | true |
| leader_after | ghost-leader |
| leader_before |  |
| leader_id_after | ghost-leader |
| out_of_window_protocol_version | true |
| path | processHeartbeat |
| state_after | Follower |
| state_before | Follower |
| term_after | 5 |
| term_before | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/c42cdaca88874c7896f30d73bd43a9df/assurance_generated_test.go)；[条件与检查器](direct-checks/c42cdaca88874c7896f30d73bd43a9df/plan.json)；[原始观察](logs/7628b537f51c4a868e8ebb80cf019fc2/stdout.log)；[assessment](direct-checks/c42cdaca88874c7896f30d73bd43a9df/7628b537f51c4a868e8ebb80cf019fc2-assessment.json)；[对应性复核](submissions/493276ea8b5b4581aa382315233ba583/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.89 秒；执行进程耗时 12.45 秒；[实际命令、工具版本与输入记录](logs/7628b537f51c4a868e8ebb80cf019fc2/check.json)
执行边界：TestAssuranceGhostHeartbeatSuppressesVote builds voter nodes with background goroutines disabled and a bootstrapped three-voter configuration. On the tested node it delivers a pure heartbeat with an out-of-window protocol version through the fast-path handler, then drives a RequestVote from a configured candidate through processRPC and records whether the receiver adopted the ghost as leader and whether the legitimate vote was granted; a second node that never saw the heartbeat answers the same request as a control. CA_EVENT lines report the declaration and both results.；The out-of-window heartbeat is delivered by calling processHeartbeat, the body of the handler installed by SetHeartbeatHandler (the library's own integration test calls r.processHeartbeat(rpc) from a custom heartbeat handler), because net_transport's fast path is TCP-only and the sandbox has network access disabled; the transport's heartbeat classification is a sourced premise.；Nodes are built with conf.skipStartup so no background goroutines run, and the vote is driven through processRPC, the production dispatch.；The vote request is constructed from the receiver's own last entry so the log-up-to-date condition is not what decides the outcome. No target code is modified.
固定比较 `c-ghost-heartbeat-vote`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| op_id | hbv-1 |
| event | vote_after_ghost_heartbeat |
| ghost_leader_adopted | true |
| legitimate_vote_granted | false |
| ghost-scenario.ghost_heartbeat_out_of_window | true |
| ghost-scenario.candidate_is_configured_voter | true |
| candidate | node2 |
| error |  |
| known_leader_id | ghost |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-timeout-now-attribution"></a>

### 3. A TimeoutNow request is honoured only when its sender is attributed to the receiver's authority context, at minimum a voter of…（原文摘录）

**已确认违反**。要求原文：A TimeoutNow request is honoured only when its sender is attributed to the receiver's authority context, at minimum a voter of the receiver's latest configuration, so that a peer outside that configuration cannot clear the receiver's known leader, force it into candidate state and hand it the transfer privilege that skips pre-vote and makes other voters grant votes despite having a leader.

决定性范围：A Raft node receiving a TimeoutNow request from a peer whose RPC header passes the version window. The obligation concerns the attribution required before the receiver abandons its leader context and raises the transfer privilege, not the election mechanics that follow.
The receiver already knows a leader or is otherwise eligible to be asked to campaign.；The version window enforced by processRPC is the only other precondition on this RPC.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/effe7bdd5700409db6058fed4b0139ce/assurance_generated_test.go)；[条件与检查器](direct-checks/effe7bdd5700409db6058fed4b0139ce/plan.json)；[原始观察](logs/554a0abcf056483ba255f00545e30713/stdout.log)；[assessment](direct-checks/effe7bdd5700409db6058fed4b0139ce/554a0abcf056483ba255f00545e30713-assessment.json)；[对应性复核](submissions/50ff0e7a0c3b4b03800a545aaf2795ec/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.31 秒；执行进程耗时 12.91 秒；[实际命令、工具版本与输入记录](logs/554a0abcf056483ba255f00545e30713/check.json)
执行边界：TestAssuranceTimeoutNowSenderAttribution builds Raft nodes with background goroutines disabled and a bootstrapped two-voter configuration, gives each a known leader, and drives the production dispatch seam processRPC with constructed TimeoutNow requests: one from a sender that is not a voter of the configuration, one control from a configured voter, and one control from a sender outside the RPC-header version window. CA_EVENT lines report the declared sender scope, the unattributed result (leader before/after, state, privilege before/after, whether the transfer privilege was granted), and the two controls.；Nodes are constructed with conf.skipStartup = true so no background goroutines run; the handler is driven through processRPC, which is the production dispatch for this RPC, with a response channel as the transport would supply.；Each node is bootstrapped with a two-voter configuration and then given a known leader through the same setLeader/setState accessors appendEntries uses, to represent the inter-heartbeat state in which such an RPC arrives. This is scenario setup, not protocol logic.；The sender is a fabricated identifier absent from the configuration; the harness does not simulate a full removed-node deployment, which is disclosed as an uncertainty.；No target code is modified.
固定比较 `c-timeout-now-attribution`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | tn-1 |
| event | timeout_now_result |
| sender_is_configured_voter | false |
| transfer_privilege_granted | true |
| unattributed-sender.sender_is_configured_voter | false |
| unattributed-sender.configuration_nonempty | true |
| error | <nil> |
| leader_after |  |
| leader_before | node2 |
| privilege_after | true |
| privilege_before | false |
| rejected | false |
| rpc_header_in_window | true |
| sender_id | intruder |
| state_after | Candidate |
| state_before | Follower |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/7cad426588d34a9c85ac8e8e6da007e9/assurance_generated_test.go)；[条件与检查器](direct-checks/7cad426588d34a9c85ac8e8e6da007e9/plan.json)；[原始观察](logs/ec71e08710e746bbbe6e7268f032377e/stdout.log)；[assessment](direct-checks/7cad426588d34a9c85ac8e8e6da007e9/ec71e08710e746bbbe6e7268f032377e-assessment.json)；[对应性复核](submissions/6c9ccc2495ef4c0f9e8c4d812cc1d37a/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.18 秒；执行进程耗时 12.77 秒；[实际命令、工具版本与输入记录](logs/ec71e08710e746bbbe6e7268f032377e/check.json)
执行边界：TestAssuranceLeadershipTransferVotePrivilege builds voter nodes with background goroutines disabled, each with a bootstrapped three-voter configuration and a known leader, and drives RequestVote through processRPC: the privileged case (configured candidate, LeadershipTransfer true) and two controls (the same request without the flag, and the flag with a candidate absent from the configuration). CA_EVENT lines report the declaration and each result.；Nodes are built with conf.skipStartup so no background goroutines run, and the vote is driven through processRPC, the production dispatch for RequestVote, with a response channel as the transport supplies.；Each node is bootstrapped with the same configuration and given a known leader through the setLeader/setState accessors appendEntries uses, representing the state in which a transfer vote arrives.；No target code is modified.
固定比较 `c-transfer-vote-privilege`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| op_id | vote-1 |
| event | privileged_vote_result |
| granted | true |
| privileged-vote.transfer_privilege_set | true |
| privileged-vote.candidate_is_configured_voter | true |
| privileged-vote.receiver_has_leader | true |
| candidate_is_configured_voter | true |
| error |  |
| transfer_privilege_set | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-install-snapshot-alignment"></a>

### 4. On a successful InstallSnapshot at index N, a receiver that no longer holds a log entry at N matching the snapshot's last…（原文摘录）

**已确认违反**。要求原文：On a successful InstallSnapshot at index N, a receiver that no longer holds a log entry at N matching the snapshot's last included term must discard the log entries above N, so that its effective last entry and its later vote comparisons and replication decisions are not based on a branch the snapshot did not confirm.

决定性范围：A Raft node receiving an InstallSnapshot whose last included index is below log entries the node already holds. The obligation concerns the receiver's log after the snapshot is installed, not the snapshot transport or the FSM restore.
The FSM restore succeeds and lastApplied and the snapshot index are adopted from the request.；The receiver's log store is not a monotonic store that removes all old logs (that branch empties the store but still leaves the in-memory last log as it was).。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/03494cb7b7a54ebf9d7f80aa108c8a90/assurance_generated_test.go)；[条件与检查器](direct-checks/03494cb7b7a54ebf9d7f80aa108c8a90/plan.json)；[原始观察](logs/3d53c8e244184b0490a87411aabe15f4/stdout.log)；[assessment](direct-checks/03494cb7b7a54ebf9d7f80aa108c8a90/3d53c8e244184b0490a87411aabe15f4-assessment.json)；[对应性复核](submissions/03f317f50a3b4baf863bea0284cc203d/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.20 秒；执行进程耗时 11.81 秒；[实际命令、工具版本与输入记录](logs/3d53c8e244184b0490a87411aabe15f4/check.json)
执行边界：TestAssuranceInstallSnapshotLogTailAlignment seeds a log with a configuration entry at index 1 and command entries through index 5, builds a node with background goroutines disabled (conf.skipStartup, TrailingLogs 0) whose only configured voter is another server, installs a snapshot at index 3 through the production handler installSnapshot, and reports the declared state before the install (last entry, raw log last index, whether entries above the installed index are held) and the result afterwards (rejection, lastApplied, snapshot index, effective last entry, raw log last index, how many log entries remain, and whether the effective last entry is within the installed snapshot index).；The handler installSnapshot is invoked directly on the main-thread code path (there is no running main loop because skipStartup is set), with an RPC whose Reader carries the snapshot bytes; in production processRPC dispatches it the same way from the transport consumer channel.；Because runFSM is not running with skipStartup, an explicit substitute goroutine drains fsmMutateCh and answers restore futures with success. The proposition concerns the handler's log/snapshot bookkeeping, for which a successful restore is a premise; the substitute never inspects or modifies log or snapshot state.；The log content is written directly to the caller-owned LogStore before NewRaft, and the snapshot payload is synthetic bytes, because the FSM in this harness ignores snapshot content.；conf.TrailingLogs is set to 0 so compaction actually runs at the snapshot index instead of being skipped by the trailing-log guard. No target code is modified.
固定比较 `c-install-snapshot-align`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | snap-1 |
| event | snapshot_install_result |
| within_installed_snapshot | false |
| longer-tail.holds_entries_above_installed_index | true |
| error | <nil> |
| installed_index | 3 |
| last_applied | 3 |
| log_entries_remaining | 2 |
| log_raw_last_index_after | 5 |
| node_last_index_after | 5 |
| node_last_term_after | 1 |
| rejected | false |
| snapshot_index | 3 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/9bc15166fa1a40bbb7005377f756410f/assurance_generated_test.go)；[条件与检查器](direct-checks/9bc15166fa1a40bbb7005377f756410f/plan.json)；[原始观察](logs/b9d811ad439049be9c19247ec7db97b2/stdout.log)；[assessment](direct-checks/9bc15166fa1a40bbb7005377f756410f/b9d811ad439049be9c19247ec7db97b2-assessment.json)；[对应性复核](submissions/0844aa61811c4fd59cc234feafc82554/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.51 秒；执行进程耗时 11.94 秒；[实际命令、工具版本与输入记录](logs/b9d811ad439049be9c19247ec7db97b2/check.json)
执行边界：TestAssuranceInstallSnapshotTailReplacedByAppendEntries seeds a log through index 5, installs a snapshot at index 3 through the production handler, reports the retained tail, then delivers the AppendEntries a leader would send next - anchored at the snapshot index with entries conflicting with the tail - and reports whether it was accepted, the resulting last entry, term and commit index.；installSnapshot and appendEntries are invoked directly on their main-thread code paths because skipStartup leaves no main loop; in production processRPC dispatches both from the transport consumer channel.；An explicit substitute goroutine answers restore futures with success because runFSM is not running; it never inspects or modifies log, snapshot or term state.；The log content is written to the caller-owned LogStore before NewRaft and the snapshot payload is synthetic because the harness FSM ignores content; conf.TrailingLogs is 0 so compaction runs at the snapshot index.；No target code is modified.
固定比较 `c-tail-anchor-accepted`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | tail-1 |
| event | tail_after_append_entries |
| append_success | false |
| tail-retained.tail_retained | true |
| committed_index | 0 |
| leader_last_term | 2 |
| log_raw_last_index | 5 |
| node_last_index | 5 |
| node_last_term | 1 |
| tail_replaced | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-client-future-shutdown-escape"></a>

### 5. Every client-facing future the library returns to a caller can complete: a request the library accepted is either responded by a…（原文摘录）

**已确认违反**。要求原文：Every client-facing future the library returns to a caller can complete: a request the library accepted is either responded by a raft loop, or its future carries the node's shutdown channel so that Error() returns ErrRaftShutdown when the node shuts down before the request is handled.

决定性范围：A Raft node with a buffered apply channel (BatchApplyCh) that accepts an Apply/ApplyLog/Barrier request and is then shut down before a loop dequeues it. The obligation concerns the caller's future completing, not the fate of the log entry.
The request was accepted, i.e. the send into the apply channel succeeded.；Shutdown closes the node without draining the apply channel.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/9fe6856c9b18495fb2b88b0c441987a2/assurance_generated_test.go)；[条件与检查器](direct-checks/9fe6856c9b18495fb2b88b0c441987a2/plan.json)；[原始观察](logs/e69bc2007c144a7fb7e950e3827d2cb4/stdout.log)；[assessment](direct-checks/9fe6856c9b18495fb2b88b0c441987a2/e69bc2007c144a7fb7e950e3827d2cb4-assessment.json)；[对应性复核](submissions/6c7a237b759d4fa3bf98285ce9742486/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.21 秒；执行进程耗时 12.76 秒；[实际命令、工具版本与输入记录](logs/e69bc2007c144a7fb7e950e3827d2cb4/check.json)
执行边界：TestAssuranceClientFutureShutdownEscape builds a node with background goroutines disabled, BatchApplyCh enabled and a buffered apply channel, calls Apply so the request is accepted, then calls Shutdown and probes the returned future without blocking: it records whether a response is available on the future's channel and whether the future carries the shutdown channel, and reports whether the caller can complete. A control node served by a running loop performs the same call and reports that it completes.；Conf.skipStartup is set so no loop can dequeue the request, which is what makes an accepted-then-dropped request observable deterministically instead of relying on a shutdown race; Shutdown is called directly on that node.；BatchApplyCh and MaxAppendEntries are set so the apply channel is buffered, which the library documents as a supported option and is the configuration in which a request can be accepted before a loop takes it.；The probe reads the future's own fields non-blockingly rather than calling Error(), which would block; this is a state observation of the mechanism, not a timing observation.；The control uses a single-node cluster with a running loop and a real FSM. No target code is modified.
固定比较 `c-client-future-completion`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | shutdown-1 |
| event | apply_future_after_shutdown |
| caller_can_complete | false |
| accepted.request_accepted | true |
| request_accepted | true |
| responded_after_shutdown | false |
| shutdown_escape | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/21ae861bcc4f4065a0ecd182f2ab3e25/assurance_generated_test.go)；[条件与检查器](direct-checks/21ae861bcc4f4065a0ecd182f2ab3e25/plan.json)；[原始观察](logs/e6a53d74753d4e2b880be03c0fe20b0d/stdout.log)；[assessment](direct-checks/21ae861bcc4f4065a0ecd182f2ab3e25/e6a53d74753d4e2b880be03c0fe20b0d-assessment.json)；[对应性复核](submissions/94b0fae95873496aa1c984cbd4e3cac3/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.44 秒；执行进程耗时 13.07 秒；[实际命令、工具版本与输入记录](logs/e6a53d74753d4e2b880be03c0fe20b0d/check.json)
执行边界：TestAssuranceVerifyFutureShutdownEscape builds a node with background goroutines disabled, calls VerifyLeader so the request is accepted into its buffered channel, then calls Shutdown and probes the returned future without blocking, reporting whether a response is available, whether the future carries the shutdown escape and whether the caller can complete. A control node served by a running loop performs the same call and reports that it completes.；Conf.skipStartup is set so no loop can dequeue the verify request, which makes an accepted-then-dropped request deterministic rather than dependent on a shutdown race; Shutdown is called directly on that node.；VerifyLeader's channel is buffered by the library itself (capacity 64), so no extra configuration is needed for the request to be accepted.；The probe reads the future's own fields non-blockingly rather than calling Error(), which would block; this is a state observation of the mechanism, not a timing observation.；The control uses a single-node cluster with a running loop. No target code is modified.
固定比较 `c-verify-future-completion`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | verify-1 |
| event | verify_future_after_shutdown |
| caller_can_complete | false |
| accepted.request_accepted | true |
| request_accepted | true |
| responded_after_shutdown | false |
| shutdown_escape | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：When a FSM implements both BatchingFSM and ConfigurationStore and a LogConfiguration entry is committed, does the library call ConfigurationStore.StoreConfiguration, or does the entry only reach…
[受理问题、条件与来源](submissions/bcaa06c272bf4890bff151ccfd995340/accepted.json)；[固定输入](submissions/bcaa06c272bf4890bff151ccfd995340/inputs/harness_configstore_test.go)
<a id="exploration-a55fcacbd6224839904320183312312e"></a>
[探索执行 1](#exploration-a55fcacbd6224839904320183312312e)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/a55fcacbd6224839904320183312312e/check.json)；[实际输出](logs/a55fcacbd6224839904320183312312e/stdout.log)；[诊断](logs/a55fcacbd6224839904320183312312e/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.86 秒；执行进程耗时 14.42 秒；[实际命令、工具版本与输入记录](logs/a55fcacbd6224839904320183312312e/check.json)
[执行输入文件清单](experiments/2eae3aa90fe849aeb67f558a090da902/workspace-delta/manifest.json)
[执行后文件清单](experiments/2eae3aa90fe849aeb67f558a090da902/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v19：概览、Behavior／Fact 与来源](audit-spec/v19.json)。
- 共识形成与推进（原文导航摘录）：A follower whose heartbeat timer expires while it is an eligible voter transitions to Candidate and runCandidate starts a pre-vote campaign (preElectSelf) that proposes currentTerm+1 without touching the term. Each…
- 上下文／权威转换（原文导航摘录）：Authority is the durable current term plus the durable per-term vote; there is no global leader identity. setCurrentTerm persists a term before it is exposed and setState clears the known leader on every transition. A…
- 两条主线的连接（原文导航摘录）：The two lines meet in three places. (1) Eligibility for formation is read from the configuration context: only voters of the latest configuration are asked for votes and only their match indexes count for commitment,…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.24 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 5.91 分钟 · 受理 obligation：First Candidate, grounded on the accepted map. Reading the previously unmapped FSM/apply path (fsm.go) surfaced a sourced discrepancy:…。[完整交接](submissions/180169d9f6754d0db9292bb81f4c9fad/accepted.json)

- 7.86 分钟 · 实际执行：Construction-guided execution for the accepted unit unit-claim-config-store-delivery. Source reading says the only StoreConfiguration call…；探索执行正常结束。[执行记录](logs/a55fcacbd6224839904320183312312e/check.json)

- 8.94 分钟 · 修订前 v1：目标进程执行成功；保存的机械比较：结果未确定；复核与修订见各自后续节点。[原固定输入](direct-checks/f609e2b676a340baab88452ded14f7e7/plan.json)；[原执行记录](logs/41bb5656bcc7426dab29aae5e648536f/check.json)；[原保存评估](direct-checks/f609e2b676a340baab88452ded14f7e7/41bb5656bcc7426dab29aae5e648536f-assessment.json)

- 10.02 分钟 · 受理 review：Checker-correspondence and applicability review of direct check 3052d8d8 (unit-claim-config-store-delivery), resolving the two open…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/41b0763b64ee4fd9b53d1f9e8982c9cd/accepted.json)

- 11.03 分钟 · 受理 revise_check：F4 repair of an unreached experiment prerequisite. The first fixed check (3052d8d823d14854a617fe006f2a30a5) executed and its correspondence…。[完整交接](submissions/c592aa3595304e6da012632e74662aca/accepted.json)

- 11.27 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/a898e05630e6440d97b856d7527274bd/check.json)

- 11.72 分钟 · 受理 review：Review of revised direct check d37a13c5 (version 2 of the unit-claim-config-store-delivery artifact), whose fresh execution…；v2 checker_correspondence: no_issue_found、v2 applicability: no_issue_found。[完整交接](submissions/fc4fb4631ed345e1a85c1fa907a8ed79/accepted.json)

- 14.09 分钟 · 受理 obligation：Second obligation, grounded on the accepted map. The heartbeat fast path is the only entry into appendEntries that skips checkRPCHeader,…。[完整交接](submissions/e66e3c692a314321855af0ea7cacb9b9/accepted.json)

- 16.16 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/1987811182294bfbb372a36548be8d8b/check.json)

- 16.70 分钟 · 受理 review：Review of direct check a7ab7f88 (unit-claim-heartbeat-header-gate), whose fresh execution 1987811182294bfbb372a36548be8d8b completed the…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/521e0bbc7ea64f5585c904e3bfb9fb08/accepted.json)

- 18.46 分钟 · 受理 obligation：Third candidate, grounded on the accepted map. The TimeoutNow receive handler is the only route that grants the vote-while-a-leader-exists…。[完整交接](submissions/75cb0e649dc041a9897548dc10ba1ec6/accepted.json)

- 19.69 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/554a0abcf056483ba255f00545e30713/check.json)

- 20.16 分钟 · 受理 review：Review of direct check 7815ca48 (unit-claim-timeout-now-attribution), whose fresh execution 554a0abcf056483ba255f00545e30713 completed the…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/50ff0e7a0c3b4b03800a545aaf2795ec/accepted.json)

- 24.31 分钟 · 受理 obligation：Fourth candidate, grounded on the accepted map. The snapshot receive path adopts the installed snapshot's index and term but never aligns…。[完整交接](submissions/1019b638881546d280dc346289306ac3/accepted.json)

- 24.96 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/3d53c8e244184b0490a87411aabe15f4/check.json)

- 25.42 分钟 · 受理 review：Review of direct check 495d49f1 (unit-claim-install-snapshot-alignment), whose fresh execution 3d53c8e244184b0490a87411aabe15f4 completed…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/03f317f50a3b4baf863bea0284cc203d/accepted.json)

- 29.15 分钟 · 实际执行：机械比较：有限检查未见违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/ec71e08710e746bbbe6e7268f032377e/check.json)

- 29.62 分钟 · 受理 review：Review of the second-scenario direct check 38aa8959 (unit-claim-timeout-now-attribution), whose fresh execution…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/6c9ccc2495ef4c0f9e8c4d812cc1d37a/accepted.json)

- 30.72 分钟 · 实际执行：机械比较：有限检查未见违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/7628b537f51c4a868e8ebb80cf019fc2/check.json)

- 31.14 分钟 · 受理 review：Review of the second-scenario direct check f8caf123 (unit-claim-heartbeat-header-gate), whose fresh execution…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/493276ea8b5b4581aa382315233ba583/accepted.json)

- 34.10 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/b9d811ad439049be9c19247ec7db97b2/check.json)

- 34.52 分钟 · 受理 review：Review of the second-scenario direct check 5a560c55 (unit-claim-install-snapshot-alignment), whose fresh execution…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/0844aa61811c4fd59cc234feafc82554/accepted.json)

- 36.34 分钟 · 受理 obligation：Fifth candidate, grounded on the accepted map. The library wires a shutdown escape into some futures but not into the logFuture returned by…。[完整交接](submissions/7e46b38a0d934557b9d772fb6cb499d7/accepted.json)

- 37.11 分钟 · 受理 check：Fixed direct check for unit-claim-client-future-shutdown-escape (obligation claim-client-future-shutdown-escape). The harness declares an…。[完整交接](submissions/9fe6856c9b18495fb2b88b0c441987a2/accepted.json)

- 37.33 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/e69bc2007c144a7fb7e950e3827d2cb4/check.json)

- 37.79 分钟 · 受理 review：Review of direct check 54e71939 (unit-claim-client-future-shutdown-escape), whose fresh execution e69bc2007c144a7fb7e950e3827d2cb4…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/6c7a237b759d4fa3bf98285ce9742486/accepted.json)

- 38.36 分钟 · 受理 research：Research handoff recording the fifth confirmed in-scope violation (client future completion after shutdown) and the sourced exposure of the…。[完整交接](submissions/9fc379e5daf847fbbe4e45b7d88adea9/accepted.json)

- 38.93 分钟 · 受理 check：Second scenario for the already-accepted requirement unit-claim-client-future-shutdown-escape, kept with the same obligation and executing…。[完整交接](submissions/21ae861bcc4f4065a0ecd182f2ab3e25/accepted.json)

- 39.16 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/e6a53d74753d4e2b880be03c0fe20b0d/check.json)

- 39.59 分钟 · 受理 review：Review of the second-scenario direct check 46a56958 (unit-claim-client-future-shutdown-escape), whose fresh execution…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/94b0fae95873496aa1c984cbd4e3cac3/accepted.json)

- 39.72 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/55ec57dc93554b238efcba19469e7e9b/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-a55fcacbd6224839904320183312312e)

<details><summary>地图登记与研究交接</summary>

以下是地图 v19 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v19：概览、Behavior／Fact 与来源](audit-spec/v19.json)

- core_overview：appendEntries has an explicit TODO (raft.go:1541): if StoreLogs fails after a truncation, lastLog is left stale. Whether any real store can fail there, and its consequence, is unresolved.；electSelf…
  尚无精确对应交接。

- b-prevote-campaign：whether treating a non-pre-vote peer as granted can itself delay a legitimate election was not modelled
  尚无精确对应交接。

- b-vote-grant：interaction of the 'has a leader' rejection with an equal-term competing leader was not fully traced
  尚无精确对应交接。

- b-fsm-apply-committed：Whether a FSM implementing both BatchingFSM and ConfigurationStore is a supported configuration, i.e. which interface is expected to own configuration persistence, is not stated by either doc…
  相关交接：[交接 1](submissions/80175045278242a0a258766c5b0fcfa3/accepted.json)；[交接 2](submissions/7a1185fc025c43cf87a81a58998f38b2/accepted.json)

- b-heartbeat-fast-path：Whether a peer outside the supported protocol-version window can deliver a pure heartbeat in a legal deployment, and whether the missing guard is deliberate design, are unresolved; that the fast path…
  相关交接：[交接 1](submissions/e0aba13d5ce743538af1b92465ebc588/accepted.json)；[交接 2](submissions/0a08129a8e41457eb986dc99612f6030/accepted.json)；[交接 3](submissions/b1175421d69c47379dec966efed21c11/accepted.json)；[交接 4](submissions/7a1185fc025c43cf87a81a58998f38b2/accepted.json)；[交接 5](submissions/bded47505ce744ddb0ffbf039c280e1f/accepted.json)

- b-timeout-now：Whether a peer outside the receiver's configuration can reach this handler in a real deployment (the observation uses a fabricated identifier), and whether leaving it unguarded is deliberate design,…
  相关交接：[交接 1](submissions/73e87b0def0f4aaea8bf94dc658ddb2c/accepted.json)；[交接 2](submissions/7a1185fc025c43cf87a81a58998f38b2/accepted.json)；[交接 3](submissions/bded47505ce744ddb0ffbf039c280e1f/accepted.json)

- b-stable-position-reconstruction：whether any accessor or caller bypasses these two and reads the raw log index instead was not exhaustively searched
  相关交接：[交接 1](submissions/70dc2989d458407ab58c40fc69c542a4/accepted.json)

- b-install-snapshot-align：Whether a real leader drives a follower into this state (the check seeded the tail), how long the retained tail persists before the next AppendEntries truncates it, and whether any vote or election…
  相关交接：[交接 1](submissions/059d7d80cb3f441daf4d2d9c16ee20c8/accepted.json)；[交接 2](submissions/f4315370470f47da9be4f6ee5a279b62/accepted.json)；[交接 3](submissions/7a1185fc025c43cf87a81a58998f38b2/accepted.json)；[交接 4](submissions/7efcd413317c4d9caef6e258b717f30d/accepted.json)

- f-campaign-tally：No distinct consumer Behavior is mapped in this partial map; the tally is consumed inline by the runCandidate select loop.
  尚无精确对应交接。

- f-fsm-configuration-state：Whether implementing both BatchingFSM and ConfigurationStore is a supported combination, and therefore which written contract governs configuration persistence for batching FSMs, remains unresolved;…
  相关交接：[交接 1](submissions/80175045278242a0a258766c5b0fcfa3/accepted.json)

- f-leader-transfer-privilege：The privilege is granted for any in-window TimeoutNow request, including one whose sender the receiver's configuration does not contain (observed, execution 554a0abc); whether that reachability is…
  相关交接：[交接 1](submissions/73e87b0def0f4aaea8bf94dc658ddb2c/accepted.json)

- f-stable-log-position：none recorded: the max-of-two accessors explain the empty-log-with-newer-snapshot case that would otherwise look like index reuse
  相关交接：[交接 1](submissions/70dc2989d458407ab58c40fc69c542a4/accepted.json)

- f-log-snapshot-agreement：The receiver keeps an unconfirmed tail after an accepted install and can then reject the very AppendEntries that would have truncated it (observed, executions 3d53c8e2 and b9d811ad). Reachability…
  相关交接：[交接 1](submissions/059d7d80cb3f441daf4d2d9c16ee20c8/accepted.json)；[交接 2](submissions/f4315370470f47da9be4f6ee5a279b62/accepted.json)；[交接 3](submissions/7efcd413317c4d9caef6e258b717f30d/accepted.json)

- f-client-completion-escape：The absence of a completion path is confirmed for Apply with a buffered apply channel (execution e69bc2007). Reading shows verifyCh is buffered with capacity 64, so VerifyLeader can likewise accept a…
  相关交接：[交接 1](submissions/9fc379e5daf847fbbe4e45b7d88adea9/accepted.json)

- surface:installSnapshot：Body (raft.go:1814+) was only skimmed; snapshot receive path and its configuration handling are unread.
  尚无精确对应交接。

- surface:sendLatestSnapshot / sendSnapshot：Leader-side snapshot shipping (replication.go:299-386) was read after this Surface was saved: it lists snapshots, opens the newest, sends InstallSnapshot with the snapshot's configuration and index,…
  尚无精确对应交接。

- surface:runFSM / fsmMutateCh：FSM application goroutine (fsm.go:86-130) was located but not read.
  尚无精确对应交接。

- surface:runSnapshots / snapshot.go：Snapshot lifecycle (snapshot.go:72-120) was located but not read.
  尚无精确对应交接。

- surface:RecoverCluster：Manual recovery path (api.go:313-360) not read beyond its doc comment.
  尚无精确对应交接。

- surface:net_transport.go / tcp_transport.go：Wire framing and connection handling (net_transport.go:81-100) are transport infrastructure, not Raft responsibility.
  尚无精确对应交接。

- surface:observer.go：Read (observer.go:58-140). The observer carries no protocol responsibility: Raft only emits Observations from existing protocol paths, and the delivery policy is the caller's, since the channel and…
  尚无精确对应交接。

- surface:config.go / ValidateConfig：Config validation and reload paths (config.go:333-360) not read.
  尚无精确对应交接。

- surface:runFSM/applyBatch (ConfigurationStore delivery for batching FSMs)：Sourced discrepancy: ConfigurationStore documents StoreConfiguration is invoked for each committed configuration entry (configuration.go:44-52), but the only call site is in applySingle (fsm.go:118),…
  尚无精确对应交接。

- surface:ReloadConfig notification scope：Read while looking for a new lead (api.go:713-741, config.go:267-...): ReloadConfig stores the new configuration and notifies leaderNotifyCh/followerNotifyCh only when HeartbeatTimeout decreases, so…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 5 项；当前 Unit 5 项、义务 5 项、固定检查制品 9 项。正式执行尝试 10 次；已保存评估的义务 5 项，其中有实际比较 5 项。已确认违反 5 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1216.21 秒、75 次 Agent 调用、25 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 3600.0 | 2383.79 | 1216.21 |
| Agent 调用 | 120 | 45 | 75 |
| 控制器目标执行 | 36 | 11 | 25 |
| 新 Unit | 12 | 5 | 7 |
| 语义复核 | 24 | 10 | 14 |
| 修订 | 12 | 1 | 11 |

受控目标执行进程耗时（正式检查＋探索）：已记录 141.20 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 145.91 秒。

目标执行组成：正式检查 10 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/55ec57dc93554b238efcba19469e7e9b/check.json)。

停止依据（记录摘录）：Agent stopped: User cancelled action；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`cancelled`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/55ec57dc93554b238efcba19469e7e9b/check.json)；[stdout](logs/55ec57dc93554b238efcba19469e7e9b/stdout.log)；[stderr](logs/55ec57dc93554b238efcba19469e7e9b/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

