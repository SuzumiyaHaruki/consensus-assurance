# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**；实际持续 **16.68 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| After an implicit joint configuration is committed and applied by a leader, can rejection of its automatic exit proposal during… | 研究中，尚无正式义务 | Construct a legal prefix with the joint entry committed before transfer, and its final application completion during transfer, without fabricating acknowledgements or… | [候选 1](#candidate-bb06765563e7461e80257e50a4cd3dc1) |

条件探索：Can a legal synchronous RawNode history consume the automatic-exit application trigger during a failed transfer and reach an equal full protocol/storage state across a fair post-abort tick period…
[受理问题、条件与来源](submissions/582d4a087b774d4d9705236e14411172/accepted.json)；[固定输入](submissions/582d4a087b774d4d9705236e14411172/inputs/transfer_explore_test.go)
<a id="exploration-9f7d4a88b7a7413cbb76781185504064"></a>
[探索执行 1](#exploration-9f7d4a88b7a7413cbb76781185504064)：已进入测试，执行失败；性质归因另核；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/9f7d4a88b7a7413cbb76781185504064/check.json)；[实际输出](logs/9f7d4a88b7a7413cbb76781185504064/stdout.log)；[诊断](logs/9f7d4a88b7a7413cbb76781185504064/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 18.33 秒；执行进程耗时 17.05 秒；[实际命令、工具版本与输入记录](logs/9f7d4a88b7a7413cbb76781185504064/check.json)
[执行输入文件清单](experiments/7e7b75c7e1894fe1bf32641d5d67f3ee/workspace-delta/manifest.json)
[执行后文件清单](experiments/7e7b75c7e1894fe1bf32641d5d67f3ee/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A leader owns proposal sequencing in its term. Proposals become indexed unstable entries; follower prefix matching and durable acknowledgements qualify per-peer Match support. Configured majorities, including both…
- 上下文／权威转换（原文导航摘录）：Campaign admission depends on voter eligibility and applied committed configuration changes. Term/vote and log freshness qualify votes; configured quorums acquire leadership. Higher-term dispatch and quorum checks…
- 两条主线的连接（原文导航摘录）：The active configuration determines whose votes and Match positions form support. Configuration application can reinterpret existing progress and recompute commitment; election admission waits for committed…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.39 分钟 · 受理 research：Retain initial sourced core backbone and distinct continuation questions; supporting recovery and configuration paths remain to be read…。[完整交接](submissions/7443ab8f8b6a452abe1d7750001eb77b/accepted.json)

- 8.80 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 11.88 分钟 · 实际执行：Candidate bb06765563e7461e80257e50a4cd3dc1: three real bootstrapped RawNodes; actual messages only, storage before sends, committed…；已进入测试，执行失败；性质归因另核。[执行记录](logs/9f7d4a88b7a7413cbb76781185504064/check.json)

- 16.67 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/079be386e97d4d7d8893a4c0c4a6c038/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [bb06765563e7461e80257e50a4cd3dc1](research.json)：[候选 1](#candidate-bb06765563e7461e80257e50a4cd3dc1)

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-9f7d4a88b7a7413cbb76781185504064)

<a id="candidate-bb06765563e7461e80257e50a4cd3dc1"></a>

研究中问题：After an implicit joint configuration is committed and applied by a leader, can rejection of its automatic exit proposal during leadership transfer consume the last application trigger, leaving no implementation-owned retry when that transfer aborts and the same leader remains healthy?
[候选原文与历史](state.json)
保存的语义未知：Construct a legal prefix with the joint entry committed before transfer, and its final application completion during transfer, without fabricating acknowledgements or skipping caller duties.；Determine whether fair post-abort ticks, transport and Ready completion reach a closed recurring state with no exit proposal; a finite delay alone is not an eventual-progress violation.

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Retry ownership after automatic exit proposal rejection during transfer.；Pending-read release when switchToConfig first commits current-term history.；Lease-mode timing assumptions and removal-channel…
  尚无精确对应交接。

- B-apply：Does a failed transfer consume the final application trigger with no later retry despite an otherwise idle healthy quorum?
  尚无精确对应交接。

- B-read：Can configuration-triggered first-term commitment strand deferred reads without another increasing Match response?
  尚无精确对应交接。

- F-autojoint：Automatic-exit retry after a transfer abort with no remaining application completion.
  尚无精确对应交接。

- surface:ReadOnlyLeaseBased and lease clock assumptions：Safe read backbone inspected; lease-mode fault/timing contract needs deeper review.
  尚无精确对应交接。

- surface:node.run removal proposal-channel handling：Inspected loop contains uncertainty about proposal admission after removal and leader changes; no legal counterexample established.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 799.34 秒、36 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1000.66 | 799.34 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 17.05 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 18.33 秒。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/079be386e97d4d7d8893a4c0c4a6c038/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/079be386e97d4d7d8893a4c0c4a6c038/check.json)；[stdout](logs/079be386e97d4d7d8893a4c0c4a6c038/stdout.log)；[stderr](logs/079be386e97d4d7d8893a4c0c4a6c038/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

- 失败／未完成：[exploration](logs/9f7d4a88b7a7413cbb76781185504064/stdout.log)；[stderr](logs/9f7d4a88b7a7413cbb76781185504064/stderr.log)；[执行记录](logs/9f7d4a88b7a7413cbb76781185504064/check.json)
