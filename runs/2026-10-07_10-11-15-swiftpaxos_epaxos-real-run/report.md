# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **6.18 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Can recovery initiation promote its own stale or empty value report above an already committed remote report, causing recovery to… | 研究中，尚无正式义务 | Can a legal prefix leave initiator stale/empty while recovery quorum contains a committed report?；Will actual messages and selector preserve the remote decision despite… | [候选 1](#candidate-bfd4b4a4056c40faa569717328cf6a6d) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Client admission batches commands into a new own-row instance. Local conflicts generate sequence/dependencies; PreAccept recipients qualify them against their history and return current context. Leader merges…
- 上下文／权威转换（原文导航摘录）：Authority is per instance. Initial ballot is row owner ID. Recovery preserves proposals, resets bookkeeping and chooses a ballot congruent to the recovering replica, with higher-ballot adjustment conditional on…
- 两条主线的连接（原文导航摘录）：The same local command/status/value-ballot record is both formed by proposal/accept/commit and consumed by later authority acquisition. Recovery is meant to carry eligible prior support into new formation: accepted…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.30 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 6.18 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/94269689541c4974ab43994cd1711a50/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [bfd4b4a4056c40faa569717328cf6a6d](research.json)：[候选 1](#candidate-bfd4b4a4056c40faa569717328cf6a6d)

<a id="candidate-bfd4b4a4056c40faa569717328cf6a6d"></a>

研究中问题：Can recovery initiation promote its own stale or empty value report above an already committed remote report, causing recovery to select a different command for the same instance?
[候选原文与历史](state.json)
保存的语义未知：Can a legal prefix leave initiator stale/empty while recovery quorum contains a committed report?；Will actual messages and selector preserve the remote decision despite promoted self vbal?；What precisely sourced preservation responsibility and observation endpoint should a formal check encode?

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Legal recovery history discriminating self-report promotion from prior committed support remains to construct.；Independent quorum, Accept status, optional persistence and SCAN leads remain sourced…
  尚无精确对应交接。

- B-preaccept：Missing-command branch indexes LeaderId rather than Replica; relevance when recovery owner differs remains open.
  尚无精确对应交接。

- B-form：FastQuorumSize returns F+(F+1)/2 while callers subtract self; quorum intersection needs separate investigation.；AcceptReply greater-ballot handling is unreachable after inequality return.
  尚无精确对应交接。

- B-accept：Does missing ACCEPTED status allow recovery or delayed PreAccept to reinterpret support already counted for a decision?
  尚无精确对应交接。

- B-commit：Older Commit rejection after a promise needs preservation analysis through recovery.
  尚无精确对应交接。

- B-authority：Self value-ballot promotion differs from remote Prepare reporting; can an empty or stale initiator mask established remote support?；Repeated makeBallot may reuse a ballot; role loss has no explicit…
  尚无精确对应交接。

- B-select：Highest value ballot is considered before committed status; self promotion may suppress committed report.；Cases 3 and 4 have identical guards, making TryPreAccept branch unreachable from this…
  尚无精确对应交接。

- B-recover-trigger：Recovery detection does not establish a wall-clock completion deadline.
  尚无精确对应交接。

- B-execute：Protocol and execution goroutines share instance fields; coherent sampling needs explicit ownership in tests.；Local proposeTime tie-break and SCAN conflict integration need separate review.
  尚无精确对应交接。

- B-membership：No dynamic membership protocol was found in read paths; configuration mismatch validation not yet traced.
  尚无精确对应交接。

- B-persist：Captured constructor leaves StableStore nil and no replay reader found; crash-restart applicability is not established.
  尚无精确对应交接。

- B-transport：No transport duplication mechanism observed; tests must not invent duplicate delivery.
  尚无精确对应交接。

- B-client：Retry handling is TODO in handlePropose; full client retry policy remains unread.
  尚无精确对应交接。

- F-value：Whether selected reports preserve a previously established decision under an actual legal recovery prefix.
  尚无精确对应交接。

- F-decision：Global agreement across local decision records is not yet checked.
  尚无精确对应交接。

- surface:Replica.handleAccept：Missing status transition before positive ballot reply; preserve as independent support-retention lead.
  尚无精确对应交接。

- surface:Replica.FastQuorumSize：Formula and subtraction of self may undercount intended fast support; no safety history tested.
  尚无精确对应交接。

- surface:Replica.handleTryPreAccept：Selector branch appears unreachable; remaining handler variants not mapped.
  尚无精确对应交接。

- surface:Replica.recordInstanceMetadata：Overwrites ballot slot; enabled persistence and replay contract unresolved.
  尚无精确对应交接。

- surface:Replica.updateAttributes：Uses exact key conflict lookup whereas state.Conflict defines range conflicts for SCAN.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1429.16 秒、38 次 Agent 调用、16 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 370.84 | 1429.16 |
| Agent 调用 | 40 | 2 | 38 |
| 控制器目标执行 | 16 | 0 | 16 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 0.00 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 0.00 秒。

目标执行组成：正式检查 0 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/94269689541c4974ab43994cd1711a50/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/94269689541c4974ab43994cd1711a50/check.json)；[stdout](logs/94269689541c4974ab43994cd1711a50/stdout.log)；[stderr](logs/94269689541c4974ab43994cd1711a50/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

