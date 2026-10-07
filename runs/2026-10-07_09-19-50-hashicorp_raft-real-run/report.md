# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **9.66 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Can nonvoter replication acknowledgments complete VerifyLeader successfully when the pending verification has confirmation from… | 研究中，尚无正式义务 | Ground whether the local verification quorum must consist of voters from interface semantics and implementation use, rather than assuming every successful call witnesses… | [候选 1](#candidate-402cdfaeb47d4f148d7d6ab0184b7a23) |

条件探索：With real elections in a fixed 3-voter/1-nonvoter cluster, does VerifyLeader return nil when every AppendEntries to voters has been dropped since startup but AppendEntries to the nonvoter reaches the…
[受理问题、条件与来源](submissions/86429de5354047bb80872024ebb14483/accepted.json)；[固定输入](submissions/86429de5354047bb80872024ebb14483/inputs/verify_explore_test.go)
<a id="exploration-774945b2e44a4d6b98064e7098478bf1"></a>
[探索执行 1](#exploration-774945b2e44a4d6b98064e7098478bf1)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/774945b2e44a4d6b98064e7098478bf1/check.json)；[实际输出](logs/774945b2e44a4d6b98064e7098478bf1/stdout.log)；[诊断](logs/774945b2e44a4d6b98064e7098478bf1/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 11.13 秒；执行进程耗时 10.93 秒；[实际命令、工具版本与输入记录](logs/774945b2e44a4d6b98064e7098478bf1/check.json)
[执行输入文件清单](experiments/8b1d969abf604e5fafe43feed20dac5e/workspace-delta/manifest.json)
[执行后文件清单](experiments/8b1d969abf604e5fafe43feed20dac5e/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader dispatch assigns term/index, persists logs and records local match. Replication success records peer match in the term-specific commitment object. The configured voter order statistic advances commitment only…
- 上下文／权威转换（原文导航摘录）：Follower timeout starts a voter campaign, normally via pre-vote before actual durable term/vote changes. Per-election channels confine late replies. Incoming vote and append requests qualify term and history;…
- 两条主线的连接（原文导航摘录）：Only voters in the current configuration contribute to formation. Reconfiguration is serialized behind committed membership and a current-term entry, then changes quorum eligibility while retaining surviving IDs…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.74 分钟 · 受理 research：Retain initial two-line implementation map and sourced discrepancies while continuing missing authority paths; no execution or correctness…。[完整交接](submissions/6e3c194a63434c27967042e081d21a43/accepted.json)

- 6.95 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 9.16 分钟 · 实际执行：Candidate 402cdfaeb47d4f148d7d6ab0184b7a23 has a sourced voter-threshold/all-peer-registration mismatch. Static message loss rules out…；探索执行正常结束。[执行记录](logs/774945b2e44a4d6b98064e7098478bf1/check.json)

- 9.66 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/398fbee3741e425db3faf674be9e3bed/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [402cdfaeb47d4f148d7d6ab0184b7a23](research.json)：[候选 1](#candidate-402cdfaeb47d4f148d7d6ab0184b7a23)

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-774945b2e44a4d6b98064e7098478bf1)

<a id="candidate-402cdfaeb47d4f148d7d6ab0184b7a23"></a>

研究中问题：Can nonvoter replication acknowledgments complete VerifyLeader successfully when the pending verification has confirmation from fewer than a quorum of configured voters?
[候选原文与历史](state.json)
保存的语义未知：Ground whether the local verification quorum must consist of voters from interface semantics and implementation use, rather than assuming every successful call witnesses a fresh election.；Construct a legal mixed-membership verification interval with isolated nonvoter support and no hidden eligible replies; compare completion without fabricating transport responses.；Distinguish local support eligibility failure from whole-cluster stale-read consequence and independent lease timing.

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Nonvoter eligibility in VerifyLeader confirmation versus separate voter-only lease check.；Concurrent higher-term heartbeat and main-loop term write ordering.；Transfer monitor flag lifetime across…
  尚无精确对应交接。

- B-replicate：Pipeline decoder reads Response without Error; investigate whether partially decoded error-bearing responses can carry actionable fields under the actual transport error contract.
  尚无精确对应交接。

- B-authority：Two-key persistVote partial failure or interrupted-write interpretation remains unresolved.
  相关交接：[交接 1](submissions/e9bf95312a4c4a92a77091785d218edb/accepted.json)

- B-history：Does the storage fault contract permit transient failed writes after successful deletion while the node continues participation?
  尚无精确对应交接。

- B-consume：Batch ApplyBatch contract says no gaps while filtering excludes barrier and no-op entries; intended index meaning needs investigation.
  尚无精确对应交接。

- B-recovery：Retained suffix compatibility for incoming snapshot and failure paths remain local open details.
  尚无精确对应交接。

- B-heartbeat-context：Individual atomic fields do not prove atomicity of compare/persist/update against a concurrent higher-term transition; legal interleaving remains a separate sourced question.
  尚无精确对应交接。

- F-verify-tally：Whether nonvoter notification can complete the public future without eligible voter quorum confirmation despite the separate lease check.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1220.38 秒、36 次 Agent 调用、7 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 579.62 | 1220.38 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 8 | 1 | 7 |
| 新 Unit | 4 | 0 | 4 |
| 语义复核 | 6 | 0 | 6 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 10.93 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 11.13 秒。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/398fbee3741e425db3faf674be9e3bed/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/398fbee3741e425db3faf674be9e3bed/check.json)；[stdout](logs/398fbee3741e425db3faf674be9e3bed/stdout.log)；[stderr](logs/398fbee3741e425db3faf674be9e3bed/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

