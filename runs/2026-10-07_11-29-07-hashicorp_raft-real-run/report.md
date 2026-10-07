# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **120.01 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 10 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 生产传输路径同样被该义务覆盖 | 已确认违反 | 回调契约、注册、形状判定与连接协程内的直接派发都属于库自身，而 NetworkTransport 正是库随附的快速路径实现，因此该义务覆盖生产传输；保留的条件只是指出应当修复哪一层，并不否任期上下文不得回退的要求。 | [c-adopted-term-never-regresses](#claim-c-adopted-term-never-regresses) |
| 2. 同一任期只投票一次的义务在本范围成立 | 已确认违反 | 持久化投票记录既是授予投票路径判定重复投票的依据，也是重启后节点所依据的投票状态，因此“同一任期不得记录两次不同投票”适用于写入该记录的候选路径；仓库内两条写路径的差异只说明义务未被一致落实并指出可能的修复位置，并不否定义务本身。 | [c-single-vote-per-term](#claim-c-single-vote-per-term) |
| 3. 同一任期只能有一个 leader 的义务覆盖整个任期 | 已确认违反 | 该义务在任期的整个存续期间都适用，而不仅限于产生领导权的那一刻；本场景通过隔离两个主张者并持续观测来检验它，第二个主张者中途退回 follower 说明义务在窗口内成立，结束重叠的正是库自身的租约检查，因此义务在实现侧也有执行点。 | [c-at-most-one-leader-per-term](#claim-c-at-most-one-leader-per-term) |
| 4. 已确认的客户端写入未被唯一副本持有 | 已确认违反 | leader 在索引 3 向客户端确认了命令 from-d 并提交（自身 FSM 已应用），而唯一可达的投票者在其日志同一索引、同一任期 3 下保存的是一条 noop、无数据、该索引没有应用值，且其提交索引同样为 3。测试以退出码 0 结束，违规体现在被判定的两处日志数据比较上；该链路依赖已构建的双 leader… | [c-committed-entry-stored-by-quorum](#claim-c-committed-entry-stored-by-quorum) |
| 5. 该确认义务在双非投票者布局下同样适用 | 已确认违反 | 法定多数按投票者计算，而确认注册覆盖全部复制状态（含非投票者），因此当两名其他投票者不可达、两名非投票者可达时，被接受的确认超过投票者多数；这正是该访问器承诺的多数确认，故义务在本布局下同样成立。把成功解释为“节点仍自认领导者”描述的是调用者要检验的状态，且没有来源表明非投票者的确认应当计入。 | [c-verify-leader-voter-quorum](#claim-c-verify-leader-voter-quorum) |
| 6. 运行中接受的请求同样属于完成义务范围 | 已确认违反 | Apply 返回的 future 就是完成通道，实现本身会对失去领导权的在途请求返回 ErrLeadershipLost、对无法入队的请求返回 ErrRaftShutdown；被留在缓冲通道中而在停机后无人应答的请求正处于同一义务之下，缓存、入队选择、停机 join 与 future 缺乏退出通道都由该库掌控。 | [c-client-request-completes-on-inactive-raft](#claim-c-client-request-completes-on-inactive-raft) |
| 7. 可达多数派下不得轻易让位的义务成立 | 已确认违反 | 租约检查自身的目的是检测失去连通性，因此当多数派可达时让位等于报告了不成立的条件；同时库自己掌握决定该检查能否满足的关系——租约在构造时固定并只与心跳超时比较，而接触刷新间隔由心跳与提交超时推导，且 ReloadConfig 会在校验后接受变更。默认值固然一致，但库通过公开 API 接受了使机制无法满足的组合，因此义务落在实现侧。 | [c-reachable-quorum-keeps-leadership](#claim-c-reachable-quorum-keeps-leadership) |
| 8. 配置 future 报告的索引始终为零 | 已确认违反 | 单投票者节点在引导后配置条目位于日志索引 1，而 GetConfiguration 返回的 future 报告的索引为 0，Stats 的 latest_configuration_index 同样为 "0"，尽管它返回的配置确实是当前配置（仍包含本节点）。测试以退出码 0… | [c-reported-configuration-index](#claim-c-reported-configuration-index) |
| 9. 该义务在真正发生日志截断时同样适用 | 已确认违反 | 安装方已把快照承载的状态作为已应用状态接受，而发布该值的仍是库自身的导出访问器；跟随者的提交索引在别处仅由 appendEntries 按 min(LeaderCommitIndex, lastIndex)… | [c-snapshot-install-commit-context](#claim-c-snapshot-install-commit-context) |
| 10. 该发布义务覆盖启动时的快照重建路径 | 已确认违反 | 该节点在启动时已把快照承载的状态重建并应用，而发布该值的正是库自身的导出访问器与 Stats；跟随者的提交索引在别处仅由 appendEntries 按 min(LeaderCommitIndex, lastIndex)… | [c-snapshot-restore-commit-context](#claim-c-snapshot-restore-commit-context) |

<a id="claim-c-adopted-term-never-regresses"></a>

### 1. 生产传输路径同样被该义务覆盖

**已确认违反**。要求原文：Once a node has adopted and persisted election term T as its current term, no later establishment of that term context may store a value lower than T, because vote granting, duplicate-vote rejection and the acceptance of newer-term RPCs are all evaluated against the adopted value; the requirement applies to every entry point that can update the term context, including a heartbeat-shaped AppendEntries processed outside the raft main goroutine.

决定性范围：A single Raft node using the in-module NetworkTransport (or any transport that honours SetHeartbeatHandler) with a heartbeat handler registered by NewRaft, while it is handling RPCs. Applies to the current-term context only, not to the log content, the commit index or the configuration.
the node is not shut down while the RPCs are processed；the StableStore accepts SetUint64 for the CurrentTerm key, since setCurrentTerm panics otherwise；an RPC with a term greater than the adopted term is a legal event, because appendEntries and requestVote adopt it。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/0e8547467dbe48a8bb38f86eec9a1dee/assurance_generated_test.go)；[条件与检查器](direct-checks/0e8547467dbe48a8bb38f86eec9a1dee/plan.json)；[原始观察](logs/78e4fd0d22b74afbbe4de6c6a912156d/stdout.log)；[assessment](direct-checks/0e8547467dbe48a8bb38f86eec9a1dee/78e4fd0d22b74afbbe4de6c6a912156d-assessment.json)；[对应性复核](submissions/1e9ccaa4c53e4742b35d6b119cd9a11e/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.74 秒；执行进程耗时 12.28 秒；[实际命令、工具版本与输入记录](logs/78e4fd0d22b74afbbe4de6c6a912156d/check.json)
执行边界：TestAssuranceHeartbeatTermContext: interleaved heartbeat callback versus main-loop higher-term AppendEntries on one node；StreamLayer is replaced by an in-process net.Pipe fabric (assurancePipeNet/assurancePipeLayer). NetworkTransport, its heartbeat classification in handleCommand, the SetHeartbeatHandler registration performed by NewRaft, Raft.processHeartbeat and Raft.appendEntries are the target's own code and are not re-implemented.；StableStore is an InmemStore wrapper whose SetUint64 holds exactly one CurrentTerm write. This is a latency injection on an injected dependency; it changes no term comparison, no branch condition and no write performed by the target.；The harness adds one external test file to the captured package and modifies no target file.
固定比较 `p-term-context-not-regressed`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | f1 |
| op | heartbeat-vs-append |
| context_term | 5 |
| admit.term | 6 |
| event | term_context_observed |
| leader_address | l1-pipe |
| leader_id | l1 |
| stale_term | 5 |
| stored_term | 5 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/598d601a4ccb457db2ca05572ae4bace/assurance_generated_test.go)；[条件与检查器](direct-checks/598d601a4ccb457db2ca05572ae4bace/plan.json)；[原始观察](logs/aeb40d35bddd4b2aabdc0491c3fde500/stdout.log)；[assessment](direct-checks/598d601a4ccb457db2ca05572ae4bace/aeb40d35bddd4b2aabdc0491c3fde500-assessment.json)；[对应性复核](submissions/938b14b4a4574165a30a45f420c28421/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.90 秒；执行进程耗时 12.26 秒；[实际命令、工具版本与输入记录](logs/aeb40d35bddd4b2aabdc0491c3fde500/check.json)
执行边界：TestAssuranceHeartbeatTermContextOverTCP: the term-context interleaving over the production TCP transport；No target file is modified; the harness adds one external test file to the captured package.；Both endpoints are NewTCPTransport instances bound to 127.0.0.1, so the transport, its heartbeat classification, the callback invocation on its connection goroutine and the wire encoding are the target's own code; the substitute fabric of the first scenario is absent.；StableStore is an InmemStore wrapper that holds exactly one CurrentTerm write inside SetUint64, the same latency injection the first scenario used.；The harness skips when the TCP transport cannot bind, so an environment without a usable loopback records an unavailable execution rather than a result.
固定比较 `p-term-context-over-tcp`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | tcp-follower |
| op | heartbeat-vs-append-over-tcp |
| context_term | 5 |
| admit.term | 6 |
| event | term_context_observed |
| local_addr | 127.0.0.1:42919 |
| transport | tcp |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-single-vote-per-term"></a>

### 2. 同一任期只投票一次的义务在本范围成立

**已确认违反**。要求原文：A node must not persist a second, different vote for a term in which it has already persisted a vote: once the durable record holds (T, C), any later write of the record for term T must be for C. The requirement binds every path that writes the record, including the candidate's own self-vote, and it must hold independently of how the node's published current term was established.

决定性范围：A single Raft node that is a voter in its configuration, over a caller-supplied StableStore whose writes may be delayed, while it handles a heartbeat-shaped AppendEntries on the transport callback and later runs its own election.
the StableStore accepts SetUint64 for the LastVoteTerm and CurrentTerm keys；the vote record is the durable record the node consults before granting a vote；the delayed store write is a legal environment for an injected dependency。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/6634f2c2ad764a7e8894ca2ab7f27e28/assurance_generated_test.go)；[条件与检查器](direct-checks/6634f2c2ad764a7e8894ca2ab7f27e28/plan.json)；[原始观察](logs/0c91abbf53c041b1969ea8c6f419e5d4/stdout.log)；[assessment](direct-checks/6634f2c2ad764a7e8894ca2ab7f27e28/0c91abbf53c041b1969ea8c6f419e5d4-assessment.json)；[对应性复核](submissions/e08c9ed79955463f992b14d49cf51c91/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.16 秒；执行进程耗时 12.74 秒；[实际命令、工具版本与输入记录](logs/0c91abbf53c041b1969ea8c6f419e5d4/check.json)
执行边界：TestAssuranceVoteRecordTermReuse: stale-term heartbeat held across a higher-term vote grant, then the node's own election；StreamLayer is replaced by an in-process net.Pipe fabric; NetworkTransport, its heartbeat classification, the SetHeartbeatHandler registration, requestVote, appendEntries and electSelf are the target's own code.；StableStore is an InmemStore wrapper that holds exactly one CurrentTerm write inside SetUint64. This is a latency injection on an injected dependency; no term comparison, vote rule or write order in the target is changed.；The harness reads the durable vote record directly from the StableStore instead of inferring it from RPC responses, and it reads the pair twice before accepting it so a concurrent election cannot tear the observation.；No target file is modified; the harness adds one external test file to the captured package.
固定比较 `p-single-vote-per-term`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | f1 |
| op | vote-record-term-reuse |
| stage | self-vote-from-own-election |
| term | 7 |
| first_vote.term | 7 |
| candidate | f1-pipe |
| context_term | 7 |
| distinct_from_first | true |
| event | second_vote_observed |
| first_candidate | d1-pipe |
| first_term | 7 |
| node_state | Candidate |
| same_candidate | false |
| saw_second_vote | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-at-most-one-leader-per-term"></a>

### 3. 同一任期只能有一个 leader 的义务覆盖整个任期

**已确认违反**。要求原文：A term must have at most one leader: when a node establishes itself as leader for term T - by counting a quorum of grants and recording itself as the known leader - no other node may already hold the leadership of T. The requirement binds the election, vote and authority-acquisition paths together, including the rule that a voter persists at most one vote per term and the path that accepts a leadership-transfer stimulus while another leader is known.

决定性范围：A cluster of voters in the captured module, exercising elections, a delayed term write from the heartbeat callback on the transport goroutine, and a leadership transfer initiated through the public API.
the transported RPCs may be delayed or lost, and the injected stores may be slow；the leadership-transfer API may be called by the operator at any time；a node that already voted in a term may be asked to vote again after its published term drops。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/f394a207699b44feb225e4d33fcd2d95/assurance_generated_test.go)；[条件与检查器](direct-checks/f394a207699b44feb225e4d33fcd2d95/plan.json)；[原始观察](logs/d2ecff1b6a4e48d9a2385c2d798524c3/stdout.log)；[assessment](direct-checks/f394a207699b44feb225e4d33fcd2d95/d2ecff1b6a4e48d9a2385c2d798524c3-assessment.json)；[对应性复核](submissions/adb08fa338894aac8a64c60dfdc47fdc/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.90 秒；执行进程耗时 13.54 秒；[实际命令、工具版本与输入记录](logs/d2ecff1b6a4e48d9a2385c2d798524c3/check.json)
执行边界：TestAssuranceTwoLeadersOneTerm: held stale term, abstaining voter, and a leadership transfer that proposes an already-voted term；StreamLayer is replaced by an in-process net.Pipe fabric with a per-endpoint block flag; NetworkTransport, its heartbeat classification, the SetHeartbeatHandler registration, requestVote, appendEntries, runCandidate, electSelf and the leadership transfer are the target's own code.；Two nodes' stores are seeded before NewRaft with the bootstrap configuration entry and CurrentTerm = 2, which is the state a node that already observed term 2 carries; the third node is bootstrapped normally, so the difference is initialization data, not modified protocol logic.；The lagging node's StableStore holds exactly one CurrentTerm write inside SetUint64 (a latency injection on an injected dependency), and one endpoint is blocked at the fabric for the duration of the first election (message loss).；The leader's reloadable intervals are lengthened through the public ReloadConfig once it is leader, so no further AppendEntries reaches the lagging node inside the observation window; the values used come from ReloadableConfig so no unrelated field is zeroed.；The harness registers an Observer with a nil channel on the transfer target; its filter runs synchronously on the emitting goroutine and reads the target's term and the other node's published state and term at that instant through the public accessors.；No target file is modified; the harness adds one external test file to the captured package.
固定比较 `p-one-leader-per-term`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | three-voter-stale-follower |
| op | two-leaders-one-term |
| witness_recorded | true |
| term | 3 |
| admit.term | 3 |
| event | second_leader_observed |
| final_voter_states | e=Follower d=Follower |
| node | t1 |
| other_node_now | Follower |
| other_node_state | Leader |
| other_node_term | 3 |
| other_node_term_now | 3 |
| second_leader_reached | true |
| state | Leader |
| term_after_release | 2 |
| transfer_error | <nil> |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/9895e2c340834932a62bc1051260a6fc/assurance_generated_test.go)；[条件与检查器](direct-checks/9895e2c340834932a62bc1051260a6fc/plan.json)；[原始观察](logs/b8cbda221cfc4002b186429cf70517ed/stdout.log)；[assessment](direct-checks/9895e2c340834932a62bc1051260a6fc/b8cbda221cfc4002b186429cf70517ed-assessment.json)；[对应性复核](submissions/10b8d12408f44a13a698d61c8344275b/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 35.87 秒；执行进程耗时 35.32 秒；[实际命令、工具版本与输入记录](logs/b8cbda221cfc4002b186429cf70517ed/check.json)
执行边界：TestAssuranceTwoLeadersOneTerm window variant: the overlap observed after several seconds of separation；StreamLayer is replaced by an in-process net.Pipe fabric with a per-destination block flag; NetworkTransport, its heartbeat classification, the SetHeartbeatHandler registration, requestVote, appendEntries, runCandidate, electSelf and checkLeaderLease are the target's own code.；Two nodes' stores are seeded before NewRaft with the bootstrap configuration entry and CurrentTerm = 2; the lagging node is bootstrapped normally and its StableStore holds exactly one CurrentTerm write inside SetUint64.；The leader's reloadable intervals are lengthened through ReloadConfig so the prefix's sequencing holds, and after the overlap both leaders are prevented from reaching each other through the fabric's per-destination block; the second leader's own replication to the third voter is left open, so its lease check can be satisfied or not on its own timing.；The harness records the sitting leader's claim immediately when the overlap is created and both nodes' published states and terms after a fixed window, using only public accessors.；No target file is modified; the harness adds one external test file to the captured package.
固定比较 `p-overlap-window`：有限检查未见违反；已比较 1 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 |
| --- | --- |
| cluster | three-voter-stale-follower |
| op | two-leaders-one-term |
| second_leader_state | Follower |
| event | persistence_observed |
| first_leader_node | d1 |
| first_leader_state | Leader |
| first_leader_term | 3 |
| second_leader_node | t1 |
| second_leader_term | 3 |
| third_voter_state | Follower |
| window_seconds | 11 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-committed-entry-stored-by-quorum"></a>

### 4. 已确认的客户端写入未被唯一副本持有

**已确认违反**。要求原文：An entry that a node reports as committed at index I must be the entry that a quorum of the voting configuration stores at I, so a client write may not be acknowledged at a position where the other voters hold a different entry. The requirement binds the commit rule and the acknowledgement path together, because committing by quorum assumes that entries with the same index and term are identical.

决定性范围：A cluster of voters in the captured module, with a client write issued to a leader while another leader holds the same term and both can reach a common voter.
the client treats a successful Apply future as an acknowledgement that the value is the one the configuration holds；the common voter is reachable from both leaders。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/404d2b52df234f37ba0839b3a65db627/assurance_generated_test.go)；[条件与检查器](direct-checks/404d2b52df234f37ba0839b3a65db627/plan.json)；[原始观察](logs/cee3bca381994c9baa3491dbcf1113e5/stdout.log)；[assessment](direct-checks/404d2b52df234f37ba0839b3a65db627/cee3bca381994c9baa3491dbcf1113e5-assessment.json)；[对应性复核](submissions/42e96bcef14c4117ad09352d6dfe84b4/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 30.81 秒；执行进程耗时 30.30 秒；[实际命令、工具版本与输入记录](logs/cee3bca381994c9baa3491dbcf1113e5/check.json)
执行边界：TestAssuranceTwoLeadersOneTerm: two-leader overlap, then a committed client write the other voter does not hold；StreamLayer is replaced by an in-process net.Pipe fabric with a per-destination block flag; NetworkTransport, its heartbeat classification, the SetHeartbeatHandler registration, requestVote, appendEntries, runCandidate, electSelf, the commitment bookkeeping and the leadership transfer are the target's own code.；Two nodes' stores are seeded before NewRaft with the bootstrap configuration entry and CurrentTerm = 2; the lagging node is bootstrapped normally and its StableStore holds exactly one CurrentTerm write inside SetUint64.；The harness uses the public Apply, and reads the leader's and the replica's log entries directly from the InmemStore instances it supplied (a lock-protected store read) and their applied values from the FSMs it supplied, which record the command data per index.；The leader's reloadable intervals are lengthened through ReloadConfig once it is leader, and after the overlap both leaders are prevented from reaching each other through the fabric's per-destination block, so the transient overlap persists long enough for the consequence to be observed.；No target file is modified; the harness adds one external test file to the captured package.
固定比较 `p-committed-entry-stored-by-quorum`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | three-voter-stale-follower |
| op | two-leaders-one-term |
| node | e1 |
| log_data |  |
| admit.command | from-d |
| applied_on_replica |  |
| event | replica_entry_observed |
| index | 3 |
| log_term | 3 |
| log_type | LogNoop |
| replica_commit | 3 |
| replica_last_index | 3 |
| replica_state | Follower |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-verify-leader-voter-quorum"></a>

### 5. 该确认义务在双非投票者布局下同样适用

**已确认违反**。要求原文：Raft.VerifyLeader may report success only when a quorum of the voting configuration of the leader's term has acknowledged within that verification: acknowledgements from servers that are not voters may not be counted toward that quorum, because the future is documented as the guard against returning stale data after leadership is lost.

决定性范围：A leader in the captured module whose latest configuration contains non-voters and whose only reachable peer is a non-voter, observed before any lease expiry or election changes its state.
the caller reads the future's error as the answer to whether the node is still the leader；the configuration used by quorumSize and the configuration whose replication states receive the future are the same latest configuration。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/3f6b6e42acab4e339300273a36002d2b/assurance_generated_test.go)；[条件与检查器](direct-checks/3f6b6e42acab4e339300273a36002d2b/plan.json)；[原始观察](logs/cc99cecfce9a453e81430792b77cee23/stdout.log)；[assessment](direct-checks/3f6b6e42acab4e339300273a36002d2b/cc99cecfce9a453e81430792b77cee23-assessment.json)；[对应性复核](submissions/766f6e4f6b7440029393189302f06345/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.86 秒；执行进程耗时 13.32 秒；[实际命令、工具版本与输入记录](logs/cc99cecfce9a453e81430792b77cee23/check.json)
执行边界：TestAssuranceVerifyLeaderVoterQuorum: the result of VerifyLeader on a leader that can reach only a non-voter；No target file is modified; the harness adds one external test file to the captured package and uses only public APIs (NewRaft, BootstrapCluster, State, Barrier, VerifyLeader, CurrentTerm, Stats, Shutdown) plus the module's own InmemTransport Connect and Disconnect for routing.；The configuration is a real two-voter configuration with one non-voter, bootstrapped on all three servers, so the quorum the leader computes is the voter majority and the non-voter is a genuine member.；The leader's route to the other voter is removed with the transport's own Disconnect; the non-voter keeps working normally, so the leader still sends and receives heartbeats.；Election and lease timeouts are long enough that the leader has not stepped down when the verification is issued, so the judged operation is the verification itself.
固定比较 `p-verify-leader-voter-quorum`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | c1 |
| op | verify-leader-voter-quorum |
| verification_result | success |
| event | verification_observed |
| leader_state | Leader |
| leader_stats_state | Leader |
| node | n2 |
| non_voter | n3 |
| nonvoters | 1 |
| other_voter | n1 |
| other_voter_reachable | false |
| quorum_size | 2 |
| verification_error |  |
| voters | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/23322adc8ae144e18340a2f41c28ed47/assurance_generated_test.go)；[条件与检查器](direct-checks/23322adc8ae144e18340a2f41c28ed47/plan.json)；[原始观察](logs/20ae923f46724801a4b9c3990fb949d7/stdout.log)；[assessment](direct-checks/23322adc8ae144e18340a2f41c28ed47/20ae923f46724801a4b9c3990fb949d7-assessment.json)；[对应性复核](submissions/acd824b6cc324a50adafab842c5eae04/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.57 秒；执行进程耗时 12.94 秒；[实际命令、工具版本与输入记录](logs/20ae923f46724801a4b9c3990fb949d7/check.json)
执行边界：TestAssuranceVerifyLeaderTwoNonvoters: the result of VerifyLeader on a leader that can reach only two non-voters；No target file is modified; the harness adds one external test file to the captured package and uses only public APIs plus the module's own InmemTransport Connect and Disconnect for routing.；The configuration is a real three-voter configuration with two non-voters, bootstrapped on all five servers, so the quorum the leader computes is the voter majority and both non-voters are genuine members.；The leader's routes to both other voters are removed with the transport's own Disconnect; the two non-voters keep working, so the leader still sends and receives heartbeats.；Election and lease timeouts are long enough that the leader has not stepped down when the verification is issued.
固定比较 `p-verify-leader-two-nonvoters`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | c1 |
| op | verify-leader-two-nonvoters |
| verification_result | success |
| event | verification_observed |
| leader_state | Leader |
| leader_stats_state | Leader |
| node | n2 |
| non_voters | n4,n5 |
| nonvoters | 2 |
| other_voter_reachable | false |
| quorum_size | 2 |
| verification_error |  |
| voters | 3 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-client-request-completes-on-inactive-raft"></a>

### 6. 运行中接受的请求同样属于完成义务范围

**已确认违反**。要求原文：A client request issued against an inactive Raft node must complete, either with ErrRaftShutdown or with a real result, and must not leave the caller's future permanently unresolved. In particular, once Shutdown has returned and the run, fsm and snapshot goroutines have exited, VerifyLeader - and ApplyLog or Barrier when applyCh is buffered - must not return a future whose Error() waits forever, because those calls take no timeout parameter and no handler remains that could ever respond.

决定性范围：A Raft node after Shutdown has completed, or the window in which a client call is raced with Shutdown. Applies to the client request paths whose destination channel is buffered (VerifyLeader always; ApplyLog and Barrier when BatchApplyCh is set). It does not cover the configuration-change, bootstrap, snapshot and restore channels, which are unbuffered in the captured source.
the caller waits on the returned future through Future.Error(), which is the documented completion channel；Shutdown().Error() has returned or is in progress, so no raft goroutine will process further requests；the caller does not add its own bound around the wait, because the API provides none。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/c0349b90c32e41fa87953e2c8b63b764/assurance_generated_test.go)；[条件与检查器](direct-checks/c0349b90c32e41fa87953e2c8b63b764/plan.json)；[原始观察](logs/fbb6404d8a05409a945aee193402861f/stdout.log)；[assessment](direct-checks/c0349b90c32e41fa87953e2c8b63b764/fbb6404d8a05409a945aee193402861f-assessment.json)；[对应性复核](submissions/9d125264491747c59f2b194d9985fd37/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.64 秒；执行进程耗时 11.15 秒；[实际命令、工具版本与输入记录](logs/fbb6404d8a05409a945aee193402861f/check.json)
执行边界：TestAssuranceInactiveRequestCompletion: VerifyLeader and batched Apply issued after Shutdown completed, with an unbuffered Barrier control；No target file is modified; the harness adds one external test file to the captured package. Nodes are created by the package's own NewRaft over the in-memory store and transport and are shut down through the public Shutdown().；The harness inspects each returned future's own completion channel non-blockingly instead of calling Error(), because Error() would block on exactly the futures under investigation. That read is sound here only because the writer is a raft handler and Shutdown().Error() has already joined every raft goroutine.；The bounded 250 ms wait corroborates the observation but is not the property; permanence rests on the shutdown join, which the plan states as the legality argument rather than as a measured timeout.；The third node is a diagnostic control that shares the select structure but has an unbuffered channel; it is not part of the asserted comparison.
固定比较 `p-inactive-requests-complete`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| setup | default-verify-with-batched-apply |
| op | after-shutdown |
| unresolved_total | 128 |
| calls_total | 256 |
| completed_other_total | 0 |
| completed_shutdown_total | 128 |
| control_barrier_calls | 8 |
| control_barrier_completed | 8 |
| control_barrier_unresolved | 0 |
| event | inactive_requests_observed |
| unresolved_apply | 64 |
| unresolved_verify | 64 |
| wait_millis | 250 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/501a29c9bb9542a4a1c19ad35a3d23f6/assurance_generated_test.go)；[条件与检查器](direct-checks/501a29c9bb9542a4a1c19ad35a3d23f6/plan.json)；[原始观察](logs/2464f92489d641b78350760c130f2029/stdout.log)；[assessment](direct-checks/501a29c9bb9542a4a1c19ad35a3d23f6/2464f92489d641b78350760c130f2029-assessment.json)；[对应性复核](submissions/27f0d343ea8147399176138a53394f97/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.47 秒；执行进程耗时 12.88 秒；[实际命令、工具版本与输入记录](logs/2464f92489d641b78350760c130f2029/check.json)
执行边界：TestAssuranceAcceptedRequestThenShutdown: requests accepted while the node leads, then an unresolved shutdown；No target file is modified; the harness adds one external test file to the captured package and uses the public NewRaft, BootstrapCluster, Apply and Shutdown.；The LogStore is an InmemStore wrapper that holds exactly one StoreLogs call until released, which is a latency injection on an injected dependency and changes no rule inside the target.；The harness classifies each request by the value the public API returned (a future for an accepted request, ErrRaftShutdown for a rejected one) and inspects the accepted futures' own completion channels instead of calling Error(), which would block on exactly the futures under investigation; that read is sound because the shutdown join has removed every writer.；The node is configured with the documented BatchApplyCh option so applyCh is buffered, and with short timeouts so the single voter elects itself promptly.
固定比较 `p-accepted-requests-complete`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| op | requests-accepted-before-shutdown |
| unresolved_total | 64 |
| accepted | 64 |
| blocker_result | leadership lost while committing log |
| completed_other | 0 |
| event | accepted_requests_observed |
| issued | 200 |
| log_last_index | 3 |
| node_state_after_shutdown | Shutdown |
| rejected_shutdown | 136 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-reachable-quorum-keeps-leadership"></a>

### 7. 可达多数派下不得轻易让位的义务成立

**已确认违反**。要求原文：A node that holds the leadership of a term must not leave it while a quorum of the voters of the current configuration is reachable and no higher term exists. The requirement binds the lease check and the configuration the library accepts together: the check exists to detect lost connectivity, so a configuration the library validates, including one applied through its reload API, must not make the check unsatisfiable with a reachable quorum.

决定性范围：A cluster of voters in the captured module whose lease timeout and heartbeat timeout are within the range ValidateConfig accepts, including changes applied at runtime through ReloadConfig.
the peers are reachable and in the leader's term；the lease timeout is fixed for the node's lifetime, as the captured implementation provides no reloadable lease。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/dff897cb014d4aa39c0bedb438a6e765/assurance_generated_test.go)；[条件与检查器](direct-checks/dff897cb014d4aa39c0bedb438a6e765/plan.json)；[原始观察](logs/d48e637cb8694b84bd567c2d80500ccb/stdout.log)；[assessment](direct-checks/dff897cb014d4aa39c0bedb438a6e765/d48e637cb8694b84bd567c2d80500ccb-assessment.json)；[对应性复核](submissions/91f7335befbe42e0b29afdfc90945dcf/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 26.03 秒；执行进程耗时 25.61 秒；[实际命令、工具版本与输入记录](logs/d48e637cb8694b84bd567c2d80500ccb/check.json)
执行边界：TestAssuranceLeaderLeaseCoherence: a leader leaves the leadership with its peers reachable and in its own term；No target file is modified; the harness adds one external test file to the captured package and uses the public NewRaft, BootstrapCluster, ReloadConfig, Apply-free paths, State, CurrentTerm and the transport's own AppendEntries for the probe.；The harness registers an Observer with a nil channel whose filter runs synchronously on the emitting goroutine and records the leader's first departure from the leadership together with the term it held then and, at that same instant, its peers' published states and terms through public accessors.；The probe is a heartbeat-shaped AppendEntries sent through a separate in-memory transport connected to all three voters, so it does not disturb the leader's own replication state.
固定比较 `p-reachable-quorum-keeps-leadership`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | n1 |
| op | leader-lease-refresh-coherence |
| leader_state_at_end | Follower |
| event | stepdown_observed |
| follower_states | n1=Follower/2 n3=Follower/2  |
| leader_node | n2 |
| leader_term_at_end | 2 |
| lease_timeout_ms | 5000 |
| peer1_state | Follower |
| peer1_term | 2 |
| peer2_state | Follower |
| peer2_term | 2 |
| probe_reachable | true |
| probe_term | 2 |
| stepdown_recorded | true |
| stepdown_state | Follower |
| stepdown_term | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-reported-configuration-index"></a>

### 8. 配置 future 报告的索引始终为零

**已确认违反**。要求原文：The configuration future returned by Raft.GetConfiguration must report, as its index, the log index at which the configuration it returns was established, so that a caller can relate the participant set it receives to a position in the replicated log and to the value the library publishes for the same future.

决定性范围：A node in the captured module answering a client's GetConfiguration call, with the configuration established either by bootstrap or by a configuration entry.
the caller reads the future's Index as the index of the configuration it received；the configuration copy read by the accessor is the latest one, as its own comment states。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/570a9a897e8e40f79783c59af539eba1/assurance_generated_test.go)；[条件与检查器](direct-checks/570a9a897e8e40f79783c59af539eba1/plan.json)；[原始观察](logs/50dfd2990fc84e9386252c784e75f7c5/stdout.log)；[assessment](direct-checks/570a9a897e8e40f79783c59af539eba1/50dfd2990fc84e9386252c784e75f7c5-assessment.json)；[对应性复核](submissions/c2aa2cdedffd44389abaac415f423bd5/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.69 秒；执行进程耗时 12.29 秒；[实际命令、工具版本与输入记录](logs/50dfd2990fc84e9386252c784e75f7c5/check.json)
执行边界：TestAssuranceConfigurationIndexReported: the configuration future's Index compared with the index at which the configuration was established；No target file is modified; the harness adds one external test file to the captured package and uses only public APIs (NewRaft, BootstrapCluster, GetConfiguration, Stats, LastIndex, State).；The harness reads the configuration future's Index directly and separately reads the configuration it returns, so a correct configuration with an unset index cannot be mistaken for an absent configuration.
固定比较 `p-reported-configuration-index`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| op | client-visible-configuration-index |
| reported_index | 0 |
| admit.index | 1 |
| configuration_has_self | true |
| event | configuration_index_observed |
| log_last_index | 1 |
| node_state | Follower |
| servers | 1 |
| stats_index | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-snapshot-install-commit-context"></a>

### 9. 该义务在真正发生日志截断时同样适用

**已确认违反**。要求原文：A node that installs a snapshot carrying state the source had committed and applied through index J must publish a commit context at least J: the value Raft.CommitIndex() reports may not name a commit point below the state the node has just taken as applied, because the accessor is documented as the committed index and as the basis for the read-index optimisation.

决定性范围：A node in the captured module that installs an InstallSnapshotRequest whose snapshot was produced by a leader that had committed and applied through the snapshot index, observed before any later AppendEntries advertises a commit index.
the installed snapshot carries entries the source had committed and applied, which is what the source's own Snapshot API produces；the receiving node's last index after the install is the snapshot index, so no legal commit index exceeds it。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/36112d06807549948a3563ac935b1256/assurance_generated_test.go)；[条件与检查器](direct-checks/36112d06807549948a3563ac935b1256/plan.json)；[原始观察](logs/d3999c33daf64a04949efbadb3e6f5e2/stdout.log)；[assessment](direct-checks/36112d06807549948a3563ac935b1256/d3999c33daf64a04949efbadb3e6f5e2-assessment.json)；[对应性复核](submissions/fc6df4874cf7459ead3cd9d8b37920fb/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.38 秒；执行进程耗时 13.92 秒；[实际命令、工具版本与输入记录](logs/d3999c33daf64a04949efbadb3e6f5e2/check.json)
执行边界：TestAssuranceSnapshotInstalledCommitContext: the commit index reported by a node that has installed a committed snapshot, compared with the index that snapshot established；No target file is modified; the harness adds one external test file to the captured package.；The snapshot is produced by a real single-voter leader through the public Snapshot API and is opened from that node's own SnapshotStore, so the installed index is an index the source reported as committed and applied.；The InstallSnapshot request is built from that snapshot's metadata and delivered through the module's own InmemTransport InstallSnapshot method, so installSnapshot, its sink handling, the FSM restore path and the log truncation are the target's own code.；Only the InstallSnapshot RPC is routed from the source transport to the receiver, and the receiver's election timeouts are long, so neither AppendEntries nor an election changes the receiver inside the observed prefix.
固定比较 `p-snapshot-install-commit-context`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | c1 |
| op | snapshot-installed-commit-context |
| commit_index | 0 |
| admit.index | 43 |
| applied_index | 43 |
| event | commit_context_observed |
| installed | true |
| last_index | 43 |
| node | n2 |
| node_state | Follower |
| snapshot_index | 43 |
| stats_applied | 43 |
| stats_commit | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/2a931bafeb4546e297fc5fe5b3e64168/assurance_generated_test.go)；[条件与检查器](direct-checks/2a931bafeb4546e297fc5fe5b3e64168/plan.json)；[原始观察](logs/3a8213e024084e508a18f5d28efae055/stdout.log)；[assessment](direct-checks/2a931bafeb4546e297fc5fe5b3e64168/3a8213e024084e508a18f5d28efae055-assessment.json)；[对应性复核](submissions/7ae985aec03e493ba747d59760b1977c/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.72 秒；执行进程耗时 14.26 秒；[实际命令、工具版本与输入记录](logs/3a8213e024084e508a18f5d28efae055/check.json)
执行边界：TestAssuranceSnapshotCompactedCommitContext: the commit index published by a node that installed a committed snapshot after its log was truncated there；No target file is modified; the harness adds one external test file to the captured package.；The receiving node is configured with no trailing logs, so the bootstrap entry it holds is really removed by the install's compaction, unlike the first scenario which left the log intact.；The snapshot is produced by a real single-voter leader through the public Snapshot API and delivered through the module's own InmemTransport install path, as in the first scenario.；Only the InstallSnapshot RPC is routed to the receiver and its election timeouts are long, so nothing else changes it inside the prefix.
固定比较 `p-snapshot-compacted-commit-context`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| cluster | c1 |
| op | snapshot-compacted-commit-context |
| commit_index | 0 |
| admit.index | 43 |
| applied_index | 43 |
| event | commit_context_observed |
| installed | true |
| last_index | 43 |
| node | n2 |
| node_state | Follower |
| snapshot_index | 43 |
| stats_applied | 43 |
| stats_commit | 0 |
| stats_last_log_index | 1 |
| stats_last_log_term | 1 |
| stats_last_snapshot_index | 43 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-c-snapshot-restore-commit-context"></a>

### 10. 该发布义务覆盖启动时的快照重建路径

**已确认违反**。要求原文：A node that reconstructs its state at startup from a stored snapshot through index J must publish a commit context at least J: the value Raft.CommitIndex() reports may not name a commit point below the snapshot state the node has itself restored and taken as applied.

决定性范围：A node in the captured module constructed by NewRaft over stores that already hold a snapshot which the same node produced, observed before any election or leader contact.
the stored snapshot is one the node itself took after committing and applying through its index；the restarted node's last index is the snapshot index, so no legal commit index exceeds it。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/1c1655d980134097af99e46865ea8ad8/assurance_generated_test.go)；[条件与检查器](direct-checks/1c1655d980134097af99e46865ea8ad8/plan.json)；[原始观察](logs/6c982b1fcb114ff7b3e4b22ace5a238b/stdout.log)；[assessment](direct-checks/1c1655d980134097af99e46865ea8ad8/6c982b1fcb114ff7b3e4b22ace5a238b-assessment.json)；[对应性复核](submissions/31767a9136944ef195c71c2622e35d8f/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.62 秒；执行进程耗时 14.08 秒；[实际命令、工具版本与输入记录](logs/6c982b1fcb114ff7b3e4b22ace5a238b/check.json)
执行边界：TestAssuranceRestoreCommitContext: the commit index reported by a node after it reconstructs its state from a stored snapshot at startup；No target file is modified; the harness adds one external test file to the captured package and uses only public APIs (NewRaft, BootstrapCluster, Apply, Barrier, Snapshot, Shutdown, CommitIndex, AppliedIndex, LastIndex, Stats, State).；The snapshot is produced by the node itself through the public Snapshot API, so the restored index is an index that node had committed and applied and had published as such.；The same LogStore, StableStore and SnapshotStore instances are reused across the restart, so the second construction restores the state the first one left rather than a fixture.；The restarted instance's election timers are long only so that nothing campaigns between construction and the read; the observation is taken immediately after NewRaft returns.
固定比较 `p-restore-commit-context`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | n1 |
| op | restart-restore-commit-context |
| commit_index | 0 |
| admit.index | 43 |
| applied_index | 43 |
| cluster | c1 |
| event | restore_context_observed |
| last_index | 43 |
| last_snapshot_index | 43 |
| node_state | Follower |
| restored | true |
| snapshot_index | 43 |
| stats_applied | 43 |
| stats_commit | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：Can the leader's own lease check depose it while a quorum of voters is reachable, and can that step-down be isolated from a peer's later election, given that the leader's contact refresh interval is…
[受理问题、条件与来源](submissions/337b5c7b311e4f71bf70d7e3618d1d37/accepted.json)；[固定输入](submissions/337b5c7b311e4f71bf70d7e3618d1d37/inputs/explore-harness-lease.go)
<a id="exploration-53c49ba7be424ad5aa710ad3a81b98e2"></a>
[探索执行 1](#exploration-53c49ba7be424ad5aa710ad3a81b98e2)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/53c49ba7be424ad5aa710ad3a81b98e2/check.json)；[实际输出](logs/53c49ba7be424ad5aa710ad3a81b98e2/stdout.log)；[诊断](logs/53c49ba7be424ad5aa710ad3a81b98e2/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 31.40 秒；执行进程耗时 30.98 秒；[实际命令、工具版本与输入记录](logs/53c49ba7be424ad5aa710ad3a81b98e2/check.json)
[执行输入文件清单](experiments/d49c24b29f8e46b2a88214b053242fc8/workspace-delta/manifest.json)
[执行后文件清单](experiments/d49c24b29f8e46b2a88214b053242fc8/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

条件探索：Does the interleaving that regressed the adopted term reproduce when the transport is the production NetworkTransport over the real TCP stream layer rather than the in-process substitute stream layer…
[受理问题、条件与来源](submissions/b0078ba62622460f928802497e60324b/accepted.json)；[固定输入](submissions/b0078ba62622460f928802497e60324b/inputs/explore-harness-tcp.go)
<a id="exploration-bdac45729182429ca999028e317d0b21"></a>
[探索执行 2](#exploration-bdac45729182429ca999028e317d0b21)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/bdac45729182429ca999028e317d0b21/check.json)；[实际输出](logs/bdac45729182429ca999028e317d0b21/stdout.log)；[诊断](logs/bdac45729182429ca999028e317d0b21/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 15.36 秒；执行进程耗时 14.94 秒；[实际命令、工具版本与输入记录](logs/bdac45729182429ca999028e317d0b21/check.json)
[执行输入文件清单](experiments/5e77f82fced54b7ea5b717ec9bcdfc02/workspace-delta/manifest.json)
[执行后文件清单](experiments/5e77f82fced54b7ea5b717ec9bcdfc02/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v13：概览、Behavior／Fact 与来源](audit-spec/v13.json)。
- 共识形成与推进（原文导航摘录）：Qualified support is gathered before a decision is formed. A candidate counts granted votes (or pre-vote grants) and only becomes leader when the count reaches quorumSize(); the leader then records each voter's…
- 上下文／权威转换（原文导航摘录）：The context that qualifies support and authority is the adopted term plus the known leader identity. Inbound AppendEntries/RequestVote/InstallSnapshot ignore older terms and adopt a strictly greater one by writing…
- 两条主线的连接（原文导航摘录）：The two lines meet at the term and at the own-term replication rule. A durable vote record is only re-granted for the same (term, candidate) and is otherwise superseded once a greater term is adopted, so support…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.89 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 14.70 分钟 · 实际执行：生产传输路径同样被该义务覆盖；执行完成；比较见 assessment。[执行记录](logs/78e4fd0d22b74afbbe4de6c6a912156d/check.json)

- 16.56 分钟 · 受理 review：心跳快速通道与主循环并发更新任期导致任期回退；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/1e9ccaa4c53e4742b35d6b119cd9a11e/accepted.json)

- 23.44 分钟 · 受理 obligation：Second Candidate for the captured hashicorp/raft snapshot, opened from the remaining frontier after the first obligation was confirmed in…。[完整交接](submissions/d018ec4f03d8427e8fe25e7954963796/accepted.json)

- 25.98 分钟 · 实际执行：运行中接受的请求同样属于完成义务范围；执行完成；比较见 assessment。[执行记录](logs/fbb6404d8a05409a945aee193402861f/check.json)

- 27.22 分钟 · 受理 review：停机后的客户端请求可永久不完成；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/9d125264491747c59f2b194d9985fd37/accepted.json)

- 34.68 分钟 · 实际执行：同一任期只投票一次的义务在本范围成立；执行完成；比较见 assessment。[执行记录](logs/0c91abbf53c041b1969ea8c6f419e5d4/check.json)

- 35.77 分钟 · 受理 review：同一任期内记录了两次不同投票；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/e08c9ed79955463f992b14d49cf51c91/accepted.json)

- 44.20 分钟 · 实际执行：同一任期只能有一个 leader 的义务覆盖整个任期；执行完成；比较见 assessment。[执行记录](logs/d2ecff1b6a4e48d9a2385c2d798524c3/check.json)

- 45.13 分钟 · 受理 review：同一任期出现两个 leader；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/adb08fa338894aac8a64c60dfdc47fdc/accepted.json)

- 49.76 分钟 · 实际执行：配置 future 报告的索引始终为零；执行完成；比较见 assessment。[执行记录](logs/50dfd2990fc84e9386252c784e75f7c5/check.json)

- 50.86 分钟 · 受理 review：配置 future 报告的索引始终为零；v1 checker_correspondence: no_issue_found。[完整交接](submissions/c2aa2cdedffd44389abaac415f423bd5/accepted.json)

- 57.32 分钟 · 实际执行：已确认的客户端写入未被唯一副本持有；执行完成；比较见 assessment。[执行记录](logs/cee3bca381994c9baa3491dbcf1113e5/check.json)

- 58.31 分钟 · 受理 review：已确认的客户端写入未被唯一副本持有；v1 checker_correspondence: no_issue_found。[完整交接](submissions/42e96bcef14c4117ad09352d6dfe84b4/accepted.json)

- 62.29 分钟 · 实际执行：运行中接受的请求同样属于完成义务范围；执行完成；比较见 assessment。[执行记录](logs/2464f92489d641b78350760c130f2029/check.json)

- 63.36 分钟 · 受理 review：运行中接受的请求在停机后仍未完成；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/27f0d343ea8147399176138a53394f97/accepted.json)

- 67.12 分钟 · 实际执行：同一任期只能有一个 leader 的义务覆盖整个任期；执行完成；比较见 assessment。[执行记录](logs/b8cbda221cfc4002b186429cf70517ed/check.json)

- 68.23 分钟 · 受理 review：双 leader 重叠在窗口内自行结束；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/10b8d12408f44a13a698d61c8344275b/accepted.json)

- 73.07 分钟 · 实际执行：Exploration, not a fixed check, to sharpen the last substantive lead on the frontier. Construction runs of this harness showed the sequence…；探索执行正常结束。[执行记录](logs/53c49ba7be424ad5aa710ad3a81b98e2/check.json)

- 75.84 分钟 · 实际执行：可达多数派下不得轻易让位的义务成立；执行完成；比较见 assessment。[执行记录](logs/d48e637cb8694b84bd567c2d80500ccb/check.json)

- 76.78 分钟 · 受理 review：可达多数派下 leader 因租约自行让位；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/91f7335befbe42e0b29afdfc90945dcf/accepted.json)

- 80.79 分钟 · 实际执行：Exploration, not a fixed check, for the last recorded unknown on the term-context line: whether the substitute stream layer is what let the…；探索执行正常结束。[执行记录](logs/bdac45729182429ca999028e317d0b21/check.json)

- 82.11 分钟 · 实际执行：生产传输路径同样被该义务覆盖；执行完成；比较见 assessment。[执行记录](logs/aeb40d35bddd4b2aabdc0491c3fde500/check.json)

- 85.89 分钟 · 受理 review：生产 TCP 传输同样复现任期回退；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/938b14b4a4574165a30a45f420c28421/accepted.json)

- 94.85 分钟 · 实际执行：该义务在真正发生日志截断时同样适用；执行完成；比较见 assessment。[执行记录](logs/d3999c33daf64a04949efbadb3e6f5e2/check.json)

- 96.54 分钟 · 受理 review：快照安装后提交索引低于已应用索引；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/fc6df4874cf7459ead3cd9d8b37920fb/accepted.json)

- 98.73 分钟 · 实际执行：该发布义务覆盖启动时的快照重建路径；执行完成；比较见 assessment。[执行记录](logs/6c982b1fcb114ff7b3e4b22ace5a238b/check.json)

- 99.70 分钟 · 受理 review：重启恢复快照后提交索引仍为零；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/31767a9136944ef195c71c2622e35d8f/accepted.json)

- 103.46 分钟 · 实际执行：该确认义务在双非投票者布局下同样适用；执行完成；比较见 assessment。[执行记录](logs/cc99cecfce9a453e81430792b77cee23/check.json)

- 104.38 分钟 · 受理 review：非投票者可满足领导权确认的法定多数；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/766f6e4f6b7440029393189302f06345/accepted.json)

- 113.11 分钟 · 实际执行：该确认义务在双非投票者布局下同样适用；执行完成；比较见 assessment。[执行记录](logs/20ae923f46724801a4b9c3990fb949d7/check.json)

- 113.91 分钟 · 受理 review：两个非投票者同样满足领导权确认的法定多数；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/acd824b6cc324a50adafab842c5eae04/accepted.json)

- 116.09 分钟 · 受理 check：Second scenario of the requirement already fixed for unit-c-snapshot-install-commit-context, answering the limitation both the artifact and…。[完整交接](submissions/2a931bafeb4546e297fc5fe5b3e64168/accepted.json)

- 116.36 分钟 · 实际执行：该义务在真正发生日志截断时同样适用；执行完成；比较见 assessment。[执行记录](logs/3a8213e024084e508a18f5d28efae055/check.json)

- 117.28 分钟 · 受理 review：日志被截断后提交索引仍低于已应用索引；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/7ae985aec03e493ba747d59760b1977c/accepted.json)

- 118.05 分钟 · 受理 research：Closing handoff for this run, updated with the two witnesses accepted since the earlier summary. Everything listed below was produced by a…。[完整交接](submissions/7ea533b0a5d74c918bc020a188b983d2/accepted.json)

- 118.68 分钟 · 受理 research：One additive refinement before the run expires, taken from the second commit-context execution rather than from exploration. The earlier…。[完整交接](submissions/54dd0a8a5f314c4b846f4e13b284d969/accepted.json)

- 120.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/21e2b41f9bbc4b388ce4c124bfef737f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

纯反馈重复受理 2 次，无新增认识，调用照常计数：[重复原稿](submissions/7effecaabe914f8192857df06c965c02/accepted.json) → [原交接](submissions/54dd0a8a5f314c4b846f4e13b284d969/accepted.json)；[重复原稿](submissions/7b02762f79c7467da88b3a8ce83fbb8d/accepted.json) → [原交接](submissions/54dd0a8a5f314c4b846f4e13b284d969/accepted.json)
已选检查／复核暂无待办；研究范围仍可开放。

2 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-53c49ba7be424ad5aa710ad3a81b98e2)；[探索执行 2](#exploration-bdac45729182429ca999028e317d0b21)

<details><summary>地图登记与研究交接</summary>

以下是地图 v13 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v13：概览、Behavior／Fact 与来源](audit-spec/v13.json)

- core_overview：The pre-vote grant path was read at the level needed for the context path; its interaction with a concurrently observed leader was not traced to completion.；Snapshot-driven log truncation was read at…
  尚无精确对应交接。

- b-heartbeat-fastpath：whether the production TCP scheduling, as opposed to the in-process substitute stream layer used to exercise this entry point, produces the same interleaving
  尚无精确对应交接。

- b-leader-lease-stepdown：how wide the interval relation must be before the step-down becomes certain rather than likely, since the lease can also be broken by the same accepted configuration applied at construction - the…
  尚无精确对应交接。

- b-client-apply-verify：which repair is intended for the accepted requests that a completed Shutdown leaves unresolved: draining the buffered channels, giving these futures a shutdown escape, or never offering the send case…
  相关交接：[交接 1](submissions/8d55a4fdd7be436dbf4e798ccf1de382/accepted.json)；[交接 2](submissions/c7d03abd44944694bd45907263ac4861/accepted.json)

- surface:Transport.SetHeartbeatHandler (any caller or third-party transport)：The interface lets a transport run the registered callback on its own goroutine; this module implements the fast path only in NetworkTransport and InmemTransport ignores the call, so the concurrency…
  尚无精确对应交接。

- surface:LogStore.MonotonicLogStore and snapshot compaction interplay：removeOldLogs and compactLogsWithTrailing were read only at the call sites used by the snapshot behaviors; the effect of a non-monotonic store on history reconstruction is not mapped here.
  尚无精确对应交接。

- surface:nested modules fuzzy/ and raft-compat/：These are separate Go modules with their own go.mod files and are outside the single module selected for execution.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 10 项；当前 Unit 10 项、义务 10 项、固定检查制品 15 项。正式执行尝试 15 次；已保存评估的义务 10 项，其中有实际比较 10 项。已确认违反 10 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、63 次 Agent 调用、19 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 7200.0 | 7200.35 | 0.00 |
| Agent 调用 | 120 | 57 | 63 |
| 控制器目标执行 | 36 | 17 | 19 |
| 新 Unit | 12 | 10 | 2 |
| 语义复核 | 24 | 15 | 9 |
| 修订 | 12 | 0 | 12 |

受控目标执行进程耗时（正式检查＋探索）：已记录 292.80 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 301.12 秒。

目标执行组成：正式检查 15 次＋探索 2 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/21e2b41f9bbc4b388ce4c124bfef737f/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`23.91474794899841`（配置值不表示触发了超时）。
[调用记录](logs/21e2b41f9bbc4b388ce4c124bfef737f/check.json)；[stdout](logs/21e2b41f9bbc4b388ce4c124bfef737f/stdout.log)；[stderr](logs/21e2b41f9bbc4b388ce4c124bfef737f/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：已记录完成事件；产物另行校验。

</details>

</details>

