# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**；实际持续 **17.68 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. When a leader completes queued forwarded ReadIndex requests after quorum confirmation, each response and resulting ReadyToRead…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [forwarded_read_context_obligation](#claim-forwarded_read_context_obligation) |
| Can a RequestVoteResp whose sender is absent from the current voting membership reach the candidate vote tally through the normal… | 源码解释（研究者处置，未经性质执行） | Dispose of the specific apparent missing sender-membership guard in handleVoteResp by following the actual network consumer. Do not extrapolate to accumulated votes… | [受理解释](submissions/a13adc4117df4113a7a180f273052025/accepted.json) |

<a id="claim-forwarded_read_context_obligation"></a>

### 1. When a leader completes queued forwarded ReadIndex requests after quorum confirmation, each response and resulting ReadyToRead…（原文摘录）

**已确认违反**。要求原文：When a leader completes queued forwarded ReadIndex requests after quorum confirmation, each response and resulting ReadyToRead must retain the SystemCtx of the corresponding admitted request at its originating follower, including earlier requests completed by a later heartbeat context.

决定性范围：ReadIndex request identity across leader-side quorum batching and follower-side ReadyToRead delivery.
Stable term and voting membership during the requests.；Distinct nonzero SystemCtx values and known follower origins.；The leader has committed an entry in its current term.。

[完整要求、假设与排除范围](state.json)

制品 v3；对应性意见：no_issue_found。
[固定测试](direct-checks/5ab07ba90a524b3d84aeeacbcbfe0120/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/5ab07ba90a524b3d84aeeacbcbfe0120/plan.json)；[原始观察](logs/6e663440d82d463f8ed904152fd7db44/stdout.log)；[assessment](direct-checks/5ab07ba90a524b3d84aeeacbcbfe0120/6e663440d82d463f8ed904152fd7db44-assessment.json)；[对应性复核](submissions/8ecf249dfd2a403988227a66e057fc2d/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 14.61 秒；执行进程耗时 13.53 秒；[实际命令、工具版本与输入记录](logs/6e663440d82d463f8ed904152fd7db44/check.json)
执行边界：Synchronous peer driver with TestLogDB storage, actual Launch/tick/read/Handle/GetUpdate/Commit calls, and two lost heartbeat sends.；No target logic changes.；In-memory storage and synchronous transport substitute for disk and networking; no crash or persistence failure is claimed.；Contexts are supplied directly to Peer.ReadIndex; NodeHost client workers are not instantiated.；Application of non-configuration entries is represented by sequential applied-index notification; no application value claim.
固定比较 `ready_context_low_preserved`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | forwarded_batch | forwarded_batch |
| origin | 2 | 3 |
| event | ready_result | ready_result |
| ctx_low | 202 | 202 |
| admission.ctx_low | 101 | 202 |
| prefix.scenario | forwarded_batch | forwarded_batch |
| prefix.origin | 2 | 3 |
| prefix.leader_ready | true | true |
| prefix.follower_leader | 1 | 1 |
| prefix.follower_applied | 4 | 4 |
| admission.scenario | forwarded_batch | forwarded_batch |
| admission.leader | 1 | 1 |
| admission.origin | 2 | 3 |
| ctx | 202/30 | 202/30 |
| ctx_high | 30 | 30 |
| index | 4 | 4 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

固定比较 `ready_context_high_preserved`：有限检查未见违反；已比较 2 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 |
| --- | --- | --- |
| scenario | forwarded_batch | forwarded_batch |
| origin | 2 | 3 |
| event | ready_result | ready_result |
| ctx_high | 30 | 30 |
| admission.ctx_high | 30 | 30 |
| prefix.scenario | forwarded_batch | forwarded_batch |
| prefix.origin | 2 | 3 |
| prefix.leader_ready | true | true |
| prefix.follower_leader | 1 | 1 |
| prefix.follower_applied | 4 | 4 |
| admission.scenario | forwarded_batch | forwarded_batch |
| admission.leader | 1 | 1 |
| admission.origin | 2 | 3 |
| ctx | 202/30 | 202/30 |
| ctx_low | 202 | 202 |
| index | 4 | 4 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：After follower 2 forwards context A and its initial heartbeats are lost, does a real quorum acknowledgment of follower 3 context B cause the leader to respond to follower 2 with B instead of A,…
[受理问题、条件与来源](submissions/d4971d58954540cd8e9ae2ef72e630a4/accepted.json)；[固定输入](submissions/d4971d58954540cd8e9ae2ef72e630a4/inputs/readindex_explore_test.go)
<a id="exploration-1af4aa07a48f4d08b60a72b95c415233"></a>
[探索执行 1](#exploration-1af4aa07a48f4d08b60a72b95c415233)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/1af4aa07a48f4d08b60a72b95c415233/check.json)；[实际输出](logs/1af4aa07a48f4d08b60a72b95c415233/stdout.log)；[诊断](logs/1af4aa07a48f4d08b60a72b95c415233/stderr.log)
固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 15.06 秒；执行进程耗时 13.92 秒；[实际命令、工具版本与输入记录](logs/1af4aa07a48f4d08b60a72b95c415233/check.json)
[执行输入文件清单](experiments/e6f83c62996143e387a3b10ec2581123/workspace-delta/manifest.json)
[执行后文件清单](experiments/e6f83c62996143e387a3b10ec2581123/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-a3002381d2c842fda78f5fc6dac05390)

<a id="exploration-feedback-a3002381d2c842fda78f5fc6dac05390"></a>
[交接 1](#exploration-feedback-a3002381d2c842fda78f5fc6dac05390) · 后续说明；关联：[探索执行 1](#exploration-1af4aa07a48f4d08b60a72b95c415233)
后续受理交接原文（摘录，不是各次执行的独立观察）：Retained exploration completed with exit 0. Prefix reached term 2, commit/applied index 4 at all nodes. Follower 2 context 101/30 was observed pending at leader 1, its two heartbeat sends were dropped, and follower 3 then requested 202/30. Real heartbeat…
[完整交接；精确引用不表示已解决或已正式化](submissions/a3002381d2c842fda78f5fc6dac05390/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
尚无受理地图。
尚未登记双主线概览；局部调查可以先行，现有结果不代表整体覆盖。
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.80 分钟 · 实际执行：Trace a concrete context-preservation suspicion at forwarded ReadIndex completion. The leader queues each original context but constructs…；探索执行正常结束。[执行记录](logs/1af4aa07a48f4d08b60a72b95c415233/check.json)

- 8.33 分钟 · 修订前 v1：目标进程执行成功；保存的机械比较：结果未确定；复核与修订见各自后续节点。[原固定输入](direct-checks/a3002381d2c842fda78f5fc6dac05390/plan.json)；[原执行记录](logs/e8bbf4cc81854e38ba62ef52c237419c/check.json)；[原保存评估](direct-checks/a3002381d2c842fda78f5fc6dac05390/e8bbf4cc81854e38ba62ef52c237419c-assessment.json)

- 9.85 分钟 · 受理 revise_check：Repair the observation/oracle association in the first direct check: prefix lacked origin although the property identity requires scenario…；v1 checker_correspondence: revision_needed。[完整交接](submissions/c35c44a8b95242108a8c95d2c000f266/accepted.json)

- 10.10 分钟 · 修订前 v2：目标进程执行成功；保存的机械比较：观察到违反；复核与修订见各自后续节点。[原固定输入](direct-checks/c35c44a8b95242108a8c95d2c000f266/plan.json)；[原执行记录](logs/b74acd29ff6545e8b658b079dc9a48c4/check.json)；[原保存评估](direct-checks/c35c44a8b95242108a8c95d2c000f266/b74acd29ff6545e8b658b079dc9a48c4-assessment.json)

- 12.86 分钟 · 受理 revise_check：The v2 retained witness is semantically complete, but issue 80f35be38a854348bc5e39599365f455 challenged observation and oracle; v2 only…；v2 checker_correspondence: no_issue_found。[完整交接](submissions/5ab07ba90a524b3d84aeeacbcbfe0120/accepted.json)

- 13.10 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/6e663440d82d463f8ed904152fd7db44/check.json)

- 14.56 分钟 · 受理 research：Complete source and execution correspondence for the successor context-preservation check and resolve only the repaired…；v3 checker_correspondence: no_issue_found。[完整交接](submissions/8ecf249dfd2a403988227a66e057fc2d/accepted.json)

- 16.91 分钟 · 受理 explained：Dispose of the specific apparent missing sender-membership guard in handleVoteResp by following the actual network consumer. Do not…。[完整交接](submissions/a13adc4117df4113a7a180f273052025/accepted.json)

- 17.67 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e1c51c67256d4a15a5f5c72d4fdf3b84/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 3 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 1 项。受理、执行与结论分别计数。

剩余 739.21 秒、73 次 Agent 调用、36 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1060.79 | 739.21 |
| Agent 调用 | 80 | 7 | 73 |
| 控制器目标执行 | 40 | 4 | 36 |

受控目标执行进程耗时（正式检查＋探索）：已记录 54.21 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 58.04 秒。

目标执行组成：正式检查 3 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v60`；展示版本 `audit-products-v60`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/e1c51c67256d4a15a5f5c72d4fdf3b84/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`784.9598468019994`（配置值不表示触发了超时）。
[调用记录](logs/e1c51c67256d4a15a5f5c72d4fdf3b84/check.json)；[stdout](logs/e1c51c67256d4a15a5f5c72d4fdf3b84/stdout.log)；[stderr](logs/e1c51c67256d4a15a5f5c72d4fdf3b84/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

