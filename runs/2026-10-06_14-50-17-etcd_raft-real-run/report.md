# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 2 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **30.58 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 565.16 秒、31 次 Agent 调用、12 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1834.84 | 565.16 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 61.37 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 66.43 秒。

目标执行组成：正式检查 2 次＋探索 2 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v54`；展示版本 `audit-products-v54`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/5d960578fa104cd3bb13b35d9fb6428f/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`620.3476788180014`（配置值不表示触发了超时）。
[调用记录](logs/5d960578fa104cd3bb13b35d9fb6428f/check.json)；[stdout](logs/5d960578fa104cd3bb13b35d9fb6428f/stdout.log)；[stderr](logs/5d960578fa104cd3bb13b35d9fb6428f/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移超时后，自动退出联合配置丢失后续触发 | 已确认违反 | 隐式联合配置在索引 5 应用时与领导权转移重叠，转移超时后仍停留在联合状态。正式执行记录了处理 20 次心跳及 20 次回复后协议状态完全重复、无待处理工作；追加普通提案才触发退出。该结果限定于自动配置收尾的进展责任，不表示共识安全性被破坏。 | [C-autoleave-continuation](#claim-C-autoleave-continuation) |
| 2. Can a leader demoted to learner with StepDownOnRemoval=false incorrectly use the singleton ReadIndex shortcut and authorize a…（原文摘录） | 待调查线索 | 机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与原因](direct-checks/c8fec023943b4aa4b465b58e2f305b10/0d5c9fcae9044f3b8c68b0ab30823f49-assessment.json) | [C-demoted-read-linearizability](#claim-C-demoted-read-linearizability) |

<a id="claim-C-autoleave-continuation"></a>

### 1. 领导权转移超时后，自动退出联合配置丢失后续触发

**已确认违反**。要求原文：For an applied implicit-joint configuration with automatic exit enabled, Raft must retain or re-establish its own continuation to propose and complete safe exit after an overlapping leadership transfer fails, when an eligible leader and both required quorums remain available and the caller continues required ticking, message delivery, persistence and application. Completion must not depend on an unrelated new caller proposal or a caller-supplied explicit leave-joint change.

决定性范围：Automatic membership-finalization responsibility after transfer rejection of the application-triggered exit attempt. Stable current leader remains a voter; configuration is committed and applied, transfer is no longer pending, and reliable delivery resumes after loss of the transfer request. No numeric completion deadline is asserted.
Non-Byzantine nodes and permitted network message loss followed by reliable delivery.；Caller processes every Ready with persistence and in-order application, calls Advance, ticks all nodes, and applies each committed configuration entry exactly once.；A current-term entry is already committed and the implicit configuration itself has completed application.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/ce61ad30b2844ce1ac0fb60e9e81dca1/assurance_generated_test.go)；[条件与检查器](direct-checks/ce61ad30b2844ce1ac0fb60e9e81dca1/plan.json)；[原始观察](logs/90b52d071c5c4272b13d717b4bfd1160/stdout.log)；[assessment](direct-checks/ce61ad30b2844ce1ac0fb60e9e81dca1/90b52d071c5c4272b13d717b4bfd1160-assessment.json)；[对应性复核](submissions/be390bf9260349d2baa81886df798fa0/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 17.52 秒；执行进程耗时 16.21 秒；[实际命令、工具版本与输入记录](logs/90b52d071c5c4272b13d717b4bfd1160/check.json)
执行边界：Construct real RawNodes and MemoryStorage using Bootstrap, persist every Ready before sending messages, apply all committed configuration entries in order and Advance. The hook runs between ApplyConfChange of the committed implicit entry and Advance of that same Ready. Read-only reflection snapshots record current complete reachable protocol data, including mutex fields, unstable work, Ready completion responses, timers, function identities and capacities, omitting only diagnostic storage counters and logger sinks. No target mutation or fabricated reply. Fixed no-transfer control and post-result rescue retain contrary evidence.；Transport is a deterministic FIFO simulated network with one policy-selected loss of the transfer TimeoutNow; after the initial drain every generated message is delivered.；MemoryStorage supplies synchronous stable-storage semantics without simulating crashes; no source or protocol state is rewritten.；All RawNode calls, storage changes, message delivery and sampling occur on the test goroutine.；Read-only structural snapshot traversal excludes only raft/raftLog/unstable logger sinks, raft.traceLogger, and MemoryStorage.callStats.
固定比较 `P-autoleave-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | implicit-remove-3 |
| overlap | true |
| forbidden_cycle | true |
| admit.change_index | 5 |
| admit.term | 2 |
| admit.overlap | true |
| admit.auto_leave | true |
| admit.transferee | 2 |
| admit.original_committed | true |
| settled.overlap | true |
| settled.change_index | 5 |
| settled.term | 2 |
| settled.transferee | 0 |
| settled.role | StateLeader |
| settled.original_applied | true |
| settled.dropped_timeout_now | 1 |
| settled.queue_length | 0 |
| settled.ready | false |
| applied | 5 |
| change_index | 5 |
| completed | false |
| cycle_messages.MsgHeartbeat | 20 |
| cycle_messages.MsgHeartbeatResp | 20 |
| drained | true |
| dropped_timeout_now | 1 |
| event | continuation_result |
| joint_throughout | true |
| last | 5 |
| only_heartbeats | true |
| state_equal | true |
| term | 2 |
| transferee | 0 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-C-demoted-read-linearizability"></a>

### 2. Can a leader demoted to learner with StepDownOnRemoval=false incorrectly use the singleton ReadIndex shortcut and authorize a…（原文摘录）

**待调查线索**。要求原文：With ReadOnlySafe, a caller using a fresh request context and a matching returned ReadState, and waiting until local application is strictly beyond its index, must not complete a read that omits a write completed before that read invocation when there is no intervening overwriting write. This remains required when a voter is legally demoted to a learner with StepDownOnRemoval disabled.

决定性范围：Linearizable single-register read from a retained learner after legal joint demotion of its prior leader, with StepDownOnRemoval=false. A new singleton voter has completed a write before read admission; network delays can make the learner unaware of the new term until after the local ReadState is returned.
Fresh unique ReadIndex context and matching returned context.；Caller applies entries in log order, processes Ready persistence before messages, and consumes the read only with applied>ReadState.Index.；One completed register write and no later overwriting write.；CFT network may delay/drop genuine messages without forging, editing or dropping local completion responses.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/c8fec023943b4aa4b465b58e2f305b10/assurance_generated_test.go)；[条件与检查器](direct-checks/c8fec023943b4aa4b465b58e2f305b10/plan.json)；[原始观察](logs/0d5c9fcae9044f3b8c68b0ab30823f49/stdout.log)；[assessment](direct-checks/c8fec023943b4aa4b465b58e2f305b10/0d5c9fcae9044f3b8c68b0ab30823f49-assessment.json)

当前争议／阻塞：机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与阻塞](direct-checks/c8fec023943b4aa4b465b58e2f305b10/0d5c9fcae9044f3b8c68b0ab30823f49-assessment.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 15.87 秒；执行进程耗时 14.67 秒；[实际命令、工具版本与输入记录](logs/0d5c9fcae9044f3b8c68b0ab30823f49/check.json)
执行边界：Single-goroutine deterministic register application and real RawNode/MemoryStorage processing. Each application is consecutive and updates the register only for nonempty normal entries. Sender messages are generated by target code, queued FIFO, then selected for delivery/drop by declared phase and entry index. Appends with a higher commit hint but only the allowed prefix are delivered unchanged; follower maybeAppend bounds commitment. The stepdown=true scenario is a diagnostic control.；Simulated unreliable transport: normal delivery for all configuration work, full isolation during new election/write/read-barrier acquisition, then drop entries above the selected actual no-op prefix and heartbeats whose commit exceeds that prefix. No message bytes or target state are altered.；In-memory stable storage models successful persistence, without crashes.；Application is a deterministic one-register state machine; all reads and mutations occur on the same goroutine.
固定比较 `P-demoted-read`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | demoted-read-after-completed-write |
| request_ctx | fresh-read-after-write |
| stepdown | false |
| observed_value | old |
| written.write_value | new |
| written.history_seq | 3 |
| admit.history_seq | 4 |
| barrier.history_seq | 5 |
| barrier.read_index | 5 |
| written.stepdown | false |
| written.write_id | write-new |
| written.write_applied | true |
| admit.stepdown | false |
| admit.write_completion_seq | 3 |
| admit.old_is_learner | true |
| admit.old_role | StateLeader |
| barrier.stepdown | false |
| barrier.read_admission_seq | 4 |
| serve.stepdown | false |
| serve.barrier_seq | 5 |
| serve.read_index | 5 |
| serve.strict_application_boundary | true |
| drops | 6 |
| event | read_completed |
| history_seq | 26 |
| new_applied | 7 |
| new_role | StateLeader |
| new_term | 3 |
| new_value | new |
| old_applied | 6 |
| old_is_learner | true |
| old_role | StateFollower |
| old_term | 3 |
| old_value | old |
| prefix_index | 6 |
| read_count | 1 |
| read_index | 5 |
| serve_seq | 25 |
| write_index | 7 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：After an implicit-joint change is committed and applied, does a transfer overlapping its application acknowledgement leave automatic exit without a continuation after transfer timeout, when all…
所选问题／策略（原文摘录）：Source-only review finds application completion as the retry trigger and transfer timeout as only clearing leadTransferee. Actual legal overlap and ordinary heartbeat/Ready behavior are the remaining construction uncertainty. The…
[受理问题、条件与来源](submissions/d3aec44f3d2b443892c71a7a5a83cb06/accepted.json)；[固定输入](submissions/d3aec44f3d2b443892c71a7a5a83cb06/inputs/autoleave_explore_test.go)
<a id="exploration-861953bdd0e545bf959d3d4cf9b1c090"></a>
[探索执行 1](#exploration-861953bdd0e545bf959d3d4cf9b1c090)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/861953bdd0e545bf959d3d4cf9b1c090/check.json)；[实际输出](logs/861953bdd0e545bf959d3d4cf9b1c090/stdout.log)；[诊断](logs/861953bdd0e545bf959d3d4cf9b1c090/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 16.84 秒；执行进程耗时 15.40 秒；[实际命令、工具版本与输入记录](logs/861953bdd0e545bf959d3d4cf9b1c090/check.json)
[执行输入文件清单](experiments/e1fe96a065544c75b0ec9e1e8a244b12/workspace-delta/manifest.json)
[执行后文件清单](experiments/e1fe96a065544c75b0ec9e1e8a244b12/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-3ed9b24032c74bf4bfc7d53419a72ed2)

条件探索：Can legal implicit demotion of leader 1 to learner leave singleton ReadIndex authority on that node with StepDownOnRemoval=false, and can an already returned local ReadState authorize an actually…
所选问题／策略（原文摘录）：The source-based candidate retains a precise consumer gap: a low returned index alone does not complete a read. This driver produces demotion, new election, write and read through real RawNode calls; then permits only an actual earlier…
[受理问题、条件与来源](submissions/47770e8b855c4d5781bd19e82bf34f24/accepted.json)；[固定输入](submissions/47770e8b855c4d5781bd19e82bf34f24/inputs/demoted_read_explore_test.go)
<a id="exploration-ffa48fdd7b904ab3b91aa6c0db02b712"></a>
[探索执行 2](#exploration-ffa48fdd7b904ab3b91aa6c0db02b712)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/ffa48fdd7b904ab3b91aa6c0db02b712/check.json)；[实际输出](logs/ffa48fdd7b904ab3b91aa6c0db02b712/stdout.log)；[诊断](logs/ffa48fdd7b904ab3b91aa6c0db02b712/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 16.20 秒；执行进程耗时 15.09 秒；[实际命令、工具版本与输入记录](logs/ffa48fdd7b904ab3b91aa6c0db02b712/check.json)
[执行输入文件清单](experiments/957cfa90747a4b76b0726ed5cc6594c8/workspace-delta/manifest.json)
[执行后文件清单](experiments/957cfa90747a4b76b0726ed5cc6594c8/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 2](#exploration-feedback-c8fec023943b4aa4b465b58e2f305b10)

<a id="exploration-feedback-3ed9b24032c74bf4bfc7d53419a72ed2"></a>
[交接 1](#exploration-feedback-3ed9b24032c74bf4bfc7d53419a72ed2) · 后续说明；关联：[探索执行 1](#exploration-861953bdd0e545bf959d3d4cf9b1c090)
后续受理交接原文（摘录，不是各次执行的独立观察）：The legal RawNode overlap was reached. Control automatically left joint at index 6. Overlap discarded one emitted TimeoutNow, completed the joint entry at index 5, timed out transfer, and remained leader in term 2 with applied=committed=last=5 and…
[完整交接；精确引用不表示已解决或已正式化](submissions/3ed9b24032c74bf4bfc7d53419a72ed2/accepted.json)

<a id="exploration-feedback-c8fec023943b4aa4b465b58e2f305b10"></a>
[交接 2](#exploration-feedback-c8fec023943b4aa4b465b58e2f305b10) · 后续说明；关联：[探索执行 2](#exploration-ffa48fdd7b904ab3b91aa6c0db02b712)
后续受理交接原文（摘录，不是各次执行的独立观察）：The exploration completed legal demotion to learner, retained StateLeader with StepDownOnRemoval=false, elected remaining voter 2 in term 3 and applied new at index 7 before the read. Node 1 returned ReadState index 5, later applied the new leader no-op…
[完整交接；精确引用不表示已解决或已正式化](submissions/c8fec023943b4aa4b465b58e2f305b10/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Node serializes incoming proposals, ticks and messages, or caller serializes RawNode. A leader assigns term/index and emits replication. Followers match predecessor history and defer positive append support until…
- 上下文／权威转换（原文导航摘录）：Eligible voters campaign only after committed configuration work is applied. Real elections increment term and record durable votes; pre-vote probes without incrementing local term. Log freshness and voter quorums…
- 两条主线的连接（原文导航摘录）：Term/role and installed configuration determine which support the leader consumes. Reset discards vote tallies, remote Match estimates and acknowledged read queue but preserves log/commit history; new leaders append a…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.07 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 7.72 分钟 · 实际执行：Source-only review finds application completion as the retry trigger and transfer timeout as only clearing leadTransferee. Actual legal…；探索执行正常结束。[执行记录](logs/861953bdd0e545bf959d3d4cf9b1c090/check.json)

- 10.38 分钟 · 受理 obligation：Sourced implicit-joint contract grounds automatic finalization; the exploration reaches the disputed overlap and justifies a separately…。[完整交接](submissions/3ed9b24032c74bf4bfc7d53419a72ed2/accepted.json)

- 14.44 分钟 · 实际执行：领导权转移超时后，自动退出联合配置丢失后续触发；执行完成；比较见 assessment。[执行记录](logs/90b52d071c5c4272b13d717b4bfd1160/check.json)

- 18.77 分钟 · 受理 review：领导权转移超时后，自动退出联合配置丢失后续触发；v1 checker_correspondence: no_issue_found。[完整交接](submissions/be390bf9260349d2baa81886df798fa0/accepted.json)

- 23.80 分钟 · 受理 continue：Investigate a separate safety-oriented read-authority consumer after demotion, with its precise caller and history gaps intact; update…。[完整交接](submissions/e4e266e516d045c199b56cbcc55c1f89/accepted.json)

- 26.18 分钟 · 实际执行：The source-based candidate retains a precise consumer gap: a low returned index alone does not complete a read. This driver produces…；探索执行正常结束。[执行记录](logs/ffa48fdd7b904ab3b91aa6c0db02b712/check.json)

- 29.37 分钟 · 受理 check：Register the applicable read obligation and fix a separate fresh execution now that exploration closed the legal-history and…。[完整交接](submissions/c8fec023943b4aa4b465b58e2f305b10/accepted.json)

- 29.63 分钟 · 实际执行：Can a leader demoted to learner with StepDownOnRemoval=false incorrectly use the singleton ReadIndex shortcut and authorize a…（原文摘录）；执行完成；比较见 assessment。[执行记录](logs/0d5c9fcae9044f3b8c68b0ab30823f49/check.json)

- 30.57 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/5d960578fa104cd3bb13b35d9fb6428f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项


已选检查／复核待办：
- [unit-C-demoted-read-linearizability](research.json)：[C-demoted-read-linearizability](#claim-C-demoted-read-linearizability)；具体进度与缺口见对应义务

<a id="candidate-5209d9e49f24439d8efc2884c5d1630e"></a>

研究中问题：Can a leader demoted to learner with StepDownOnRemoval=false incorrectly use the singleton ReadIndex shortcut and authorize a stale local read after the remaining voter completes a later write, even if the caller advances strictly beyond the returned read index?
[候选原文与历史](state.json)

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Legal reachability of first current-term commitment through configuration application with pending reads.；Pre-commit read queue lifetime across authority changes.；Detailed snapshot/flow-control…
  尚无精确对应交接。

- B-authority：pendingReadIndexMessages is separate from reset readOnly state; the intended lifetime of pre-commit requests across leadership changes needs focused investigation.
  相关交接：[交接 1](submissions/3ed9b24032c74bf4bfc7d53419a72ed2/accepted.json)；[交接 2](submissions/be390bf9260349d2baa81886df798fa0/accepted.json)

- B-config：Can commitment through switchToConfig be the first current-term commit with queued pre-commit reads under a legal application/election history? Campaign exclusion is substantial counterevidence.
  尚无精确对应交接。

- B-read：Can a demoted leader return an unsafe read barrier after a new singleton leader completes a write, even when the caller later waits until local applied index is strictly greater than the returned…
  相关交接：[交接 1](submissions/e4e266e516d045c199b56cbcc55c1f89/accepted.json)；[交接 2](submissions/c8fec023943b4aa4b465b58e2f305b10/accepted.json)

- surface:raft.pendingReadIndexMessages across reset：reset replaces readOnly but does not visibly clear the pre-commit queue; inspect request identity and subsequent release before alleging a defect.
  尚无精确对应交接。

- surface:MemoryStorage mutation and compaction：Storage interface read; concrete mutation and compaction methods remain to be inspected.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
