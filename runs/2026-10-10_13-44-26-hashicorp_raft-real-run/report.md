# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 3 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. Whenever VerifyLeader completes successfully on a leader, the leader must have observed successful responses sufficient to meet…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-verifyleader-voter-quorum-only](#claim-claim-verifyleader-voter-quorum-only) |
| 2. If appendEntries deletes a conflicting log suffix and the subsequent StoreLogs fails, the follower's cached last log must remain…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-append-failure-cached-lastlog](#claim-claim-append-failure-cached-lastlog) |
| 3. For any FSM that implements ConfigurationStore, once a configuration log entry is committed and applied, StoreConfiguration must…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-configstore-batch-callback](#claim-claim-configstore-batch-callback) |
| Can a stale or delayed TimeoutNow request cause a follower to campaign and perturb or displace a newly established leader because… | 暂停调查，尚无正式义务 | Resume when a controlled transport can hold a TimeoutNow from an old leader and release it after a new leader is established.；Retain the recipient follower's state… | [候选 1](#candidate-78d696f7669e4f7b9063d9743a4d70c3) |

<a id="claim-claim-verifyleader-voter-quorum-only"></a>

### 1. Whenever VerifyLeader completes successfully on a leader, the leader must have observed successful responses sufficient to meet…（原文摘录）

**已确认违反**。要求原文：Whenever VerifyLeader completes successfully on a leader, the leader must have observed successful responses sufficient to meet the voter quorum of its latest configuration; confirmations from servers whose suffrage is not Voter must not contribute to that quorum.

决定性范围：A leader with a committed configuration containing both voters and at least one non-voter, a reachable transport path to the non-voter, and insufficient successful voter confirmations after VerifyLeader is admitted.
The mixed configuration is committed before VerifyLeader is admitted.；The leader is still in Leader state when VerifyLeader is admitted.；The non-voter can answer the verification heartbeat successfully.。
范围参数：{"voter_count": 3, "nonvoter_count": 1, "quorum_size": 2}
[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/b19ea898391f49e5afb8374add6f23dd/assurance_generated_test.go)；[条件与检查器](direct-checks/b19ea898391f49e5afb8374add6f23dd/plan.json)；[原始观察](logs/3c9d7e6ae7a04f4f9ce7a782e755960a/stdout.log)；[assessment](direct-checks/b19ea898391f49e5afb8374add6f23dd/3c9d7e6ae7a04f4f9ce7a782e755960a-assessment.json)；[对应性复核](submissions/1c4aa40cf57c4558bd05b3912457343b/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 18.07 秒；执行进程耗时 17.62 秒；[实际命令、工具版本与输入记录](logs/3c9d7e6ae7a04f4f9ce7a782e755960a/check.json)
执行边界：Construct a real in-memory Raft cluster, commit a voter-to-non-voter configuration change, partition the two non-leader voters, and observe the leader's VerifyLeader result together with successful AppendEntries confirmations by suffrage.；Uses the real BootstrapCluster, NewRaft, DemoteVoter, transport Disconnect and VerifyLeader paths.；Wraps the captured in-memory transport only to observe successful AppendEntries confirmations per target address.；Declines the optional AppendEntriesPipeline fast path so every confirmation is observable through the documented fallback path; no Raft protocol logic is replaced.；The observation window resets immediately before VerifyLeader and counts only confirmations after that point.
固定比较 `nonvoter_cannot_complete_verify_quorum`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| leader_id | assurance-node-2 |
| event | verify_outcome |
| voter_quorum_met | false |
| result | confirmed |
| error |  |
| nonvoter_confirmation_count | 1 |
| operation | VerifyLeader |
| quorum_size | 2 |
| voter_confirmation_count | 0 |
| voter_contact_count | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-append-failure-cached-lastlog"></a>

### 2. If appendEntries deletes a conflicting log suffix and the subsequent StoreLogs fails, the follower's cached last log must remain…（原文摘录）

**已确认违反**。要求原文：If appendEntries deletes a conflicting log suffix and the subsequent StoreLogs fails, the follower's cached last log must remain equal to the durable LogStore's last index or be restored before the handler returns.

决定性范围：A follower with a conflicting suffix applies an AppendEntries request, deletes the suffix, and then receives a permitted StoreLogs failure before any restart or successful repair.
The request contains an entry conflicting with the stored suffix.；StoreLogs returns an error after DeleteRange has succeeded.。
范围参数：{"initial_last_index": 3, "conflict_index": 2, "failure_point": "StoreLogs"}
[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e423cc26b88b4bafa86b34cbc8bdfc78/assurance_generated_test.go)；[条件与检查器](direct-checks/e423cc26b88b4bafa86b34cbc8bdfc78/plan.json)；[原始观察](logs/5bdc6c3bc1564d24b5f14485b45f2924/stdout.log)；[assessment](direct-checks/e423cc26b88b4bafa86b34cbc8bdfc78/5bdc6c3bc1564d24b5f14485b45f2924-assessment.json)；[对应性复核](submissions/d67d4c70313740fdb0277ea7193ca5c2/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.11 秒；执行进程耗时 11.56 秒；[实际命令、工具版本与输入记录](logs/5bdc6c3bc1564d24b5f14485b45f2924/check.json)
执行边界：Use real NewRaft initialization, a real appendEntries handler call, and an injected StoreLogs failure after conflicting suffix deletion to compare cached and durable last-log state.；Uses the real BootstrapCluster, NewRaft, appendEntries, DeleteRange, and StoreLogs paths.；Submits one controlled AppendEntries request directly to the handler and injects a permitted StoreLogs failure after suffix deletion.；Suppresses background loops with the existing skipStartup path so the handler observation is deterministic; this is a controlled conditional probe, not a distributed deployment prefix.
固定比较 `append_failure_keeps_cached_last_log_consistent`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node_id | assurance-append-failure-follower |
| event | append_failure |
| store_logs_failed | true |
| cached_matches_store | false |
| actual_last_index | 1 |
| actual_last_index_error | <nil> |
| cached_last_index | 3 |
| cached_last_term | 2 |
| conflicting_entry_readable | false |
| operation | AppendEntriesStoreFailure |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

<a id="claim-claim-configstore-batch-callback"></a>

### 3. For any FSM that implements ConfigurationStore, once a configuration log entry is committed and applied, StoreConfiguration must…（原文摘录）

**已确认违反**。要求原文：For any FSM that implements ConfigurationStore, once a configuration log entry is committed and applied, StoreConfiguration must be invoked for that committed entry with its index and configuration value, including when the same FSM value also implements BatchingFSM.

决定性范围：One FSM value implements both ConfigurationStore and BatchingFSM, and a committed LogConfiguration entry is applied through Raft's FSM batch path.
The configuration entry is committed before the observation.；The combined FSM's ApplyBatch returns one response per received log entry.。
范围参数：{"entry_type": "LogConfiguration", "batch_path": true}
[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/452b924d8af44ffa80053cb8ab4a1551/assurance_generated_test.go)；[条件与检查器](direct-checks/452b924d8af44ffa80053cb8ab4a1551/plan.json)；[原始观察](logs/84aeffcaf772412e93f040b18483d2b5/stdout.log)；[assessment](direct-checks/452b924d8af44ffa80053cb8ab4a1551/84aeffcaf772412e93f040b18483d2b5-assessment.json)；[对应性复核](submissions/de37388d12d041fa8e90b58452aa2ad2/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.59 秒；执行进程耗时 12.12 秒；[实际命令、工具版本与输入记录](logs/84aeffcaf772412e93f040b18483d2b5/check.json)
执行边界：Start a real in-memory Raft cluster with a combined FSM, commit the bootstrap configuration entry, and count configuration deliveries through ApplyBatch and StoreConfiguration.；Uses the real BootstrapCluster, NewRaft, runFSM, and Barrier paths.；The single FSM value implements FSM, BatchingFSM, and ConfigurationStore so the batch branch is selected while the configuration-store callback is applicable.；The harness only counts LogConfiguration entries in ApplyBatch and invocations of StoreConfiguration; it does not replace protocol logic.
固定比较 `configuration_store_callback_required`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| fsm_id | batch-config-fsm |
| event | config_delivery |
| config_entry_delivered_to_batch | true |
| store_config_count | 0 |
| apply_batch_config_count | 1 |
| operation | FSMConfigDelivery |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
尚无受理地图。
尚未登记双主线概览；局部调查可以先行，现有结果不代表整体覆盖。
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 10.26 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/3c9d7e6ae7a04f4f9ce7a782e755960a/check.json)

- 13.04 分钟 · 受理 research：Review the retained direct check against its sourced obligation, then resolve the four open applicability conditions generated from the…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/1c4aa40cf57c4558bd05b3912457343b/accepted.json)

- 15.62 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/84aeffcaf772412e93f040b18483d2b5/check.json)

- 16.78 分钟 · 受理 research：Review the retained batch-configuration direct check against the ConfigurationStore and BatchingFSM contracts, then resolve the four open…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/de37388d12d041fa8e90b58452aa2ad2/accepted.json)

- 18.00 分钟 · 受理 research：At the end of the available execution window, hand off the two confirmed implementation obligations with their exact retained CheckRuns and…。[完整交接](submissions/7e99bc8eef4b4ae5ae8d8b9d345285d8/accepted.json)

- 19.08 分钟 · 受理 research：Dispose of the AddNonvoter treatment-of-existing-voter lead with a source-only negative result, while retaining the three unexecuted…。[完整交接](submissions/5b7c3677f93c426186c988d61085f416/accepted.json)

- 20.43 分钟 · 受理 research：Dispose of the installSnapshot post-snapshot-log lead with a source-only negative result, retaining the two execution-heavy leads that…。[完整交接](submissions/de008918d575485ab4d3488a7ddc2257/accepted.json)

- 23.38 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/5bdc6c3bc1564d24b5f14485b45f2924/check.json)

- 24.34 分钟 · 受理 research：Review the retained append-failure direct check against its cached-last-log consistency obligation and resolve the four open applicability…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/d67d4c70313740fdb0277ea7193ca5c2/accepted.json)

- 25.16 分钟 · 受理 research：Close the run with three confirmed findings and one explicitly unconfirmed sourced lead, preserving the exact TimeoutNow source path and…。[完整交接](submissions/d786e9c4177348b28fea56a7f8d9d88c/accepted.json)

- 26.00 分钟 · 受理 continue：Preserve the sole remaining sourced lead as an active investigation for a future run instead of attempting a rushed delayed-delivery…。[完整交接](submissions/edb4577752e74c73a27d59ebb70dbef0/accepted.json)

- 26.83 分钟 · 受理 pause：Pause the remaining TimeoutNow lead locally because the run is at its time boundary and a sound delayed-delivery experiment cannot be…。[完整交接](submissions/cb7fe40f72004d028868c3b34554351c/accepted.json)

- 27.76 分钟 · 受理 research：Refine the paused TimeoutNow Candidate with the exact unknowns, observation identities, and resume conditions needed for a sound future…。[完整交接](submissions/3b35f1c213a04ac0a10dda9ef7318ee8/accepted.json)

- 28.56 分钟 · 受理 research：Record the final research state at the execution-window boundary: three confirmed implementation obligations and one paused, explicitly…。[完整交接](submissions/19b4c460168e4648a4a7614fcb2dd7aa/accepted.json)

- 30.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/146d09d7994e47cbae0ea19d2bfa4c75/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<a id="candidate-78d696f7669e4f7b9063d9743a4d70c3"></a>

暂停调查：Can a stale or delayed TimeoutNow request cause a follower to campaign and perturb or displace a newly established leader because the request carries no term and timeoutNow unconditionally enters Candidate state?
[候选原文与历史](state.json)
保存的语义未知：Whether a real delayed transport schedule can deliver a stale TimeoutNow after a new leader is established.；Whether the resulting follower campaign only perturbs the new leader or can displace it.；Whether the recipient's campaign term and candidateFromLeadershipTransfer observation are sufficient to distinguish disruption from ordinary election timeout behavior.
恢复条件：Resume when a controlled transport can hold a TimeoutNow from an old leader and release it after a new leader is established.；Retain the recipient follower's state transition, campaign term, and the new leader's authority observation before treating any disruption as a confirmed defect.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 4 项；当前 Unit 3 项、义务 3 项、固定检查制品 3 项。正式执行尝试 3 次；已保存评估的义务 3 项，其中有实际比较 3 项。已确认违反 3 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、62 次 Agent 调用、37 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.12 | 0.00 |
| Agent 调用 | 80 | 18 | 62 |
| 控制器目标执行 | 40 | 3 | 37 |

受控目标执行进程耗时（正式检查＋探索）：已记录 41.31 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 42.77 秒。

目标执行组成：正式检查 3 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v60`；展示版本 `audit-products-v60`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/146d09d7994e47cbae0ea19d2bfa4c75/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`4.304511104000085`（配置值不表示触发了超时）。
[调用记录](logs/146d09d7994e47cbae0ea19d2bfa4c75/check.json)；[stdout](logs/146d09d7994e47cbae0ea19d2bfa4c75/stdout.log)；[stderr](logs/146d09d7994e47cbae0ea19d2bfa4c75/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

