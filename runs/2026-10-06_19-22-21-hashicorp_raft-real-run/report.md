# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **11.24 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Can VerifyLeader consume successful notifications from nonvoters as sufficient authority support, and thereby return success when… | 研究中，尚无正式义务 | Does the API’s authority-check responsibility exclude success based solely on self plus nonvoters, and what exact local or cluster history grounds that implication?；Can… | [候选 1](#candidate-324bee1b720648a6af48200af143e19a) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：The elected leader stamps and persists commands, then reports its local match and notifies peer replicators. Sender-bounded AppendEntries and snapshot success report matching indexes to a tenure-local commitment object,…
- 上下文／权威转换（原文导航摘录）：Normal timeout candidacy requires local voter eligibility. Optional pre-vote precedes term persistence, self-vote and requests only to voters. Recipients enforce candidate membership, term, prior vote and last-log…
- 两条主线的连接（原文导航摘录）：Persistent vote/term and log freshness constrain subsequent authority acquisition; durable log entries survive tenure loss although their uncommitted futures fail. Each new leader resets volatile match evidence and…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.67 分钟 · 受理 research：Retain first-run source investigation and two sourced discriminators while completing the required two-core map.。[完整交接](submissions/62d14b6128e34d3594daf78bc66aab6c/accepted.json)

- 8.21 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 11.23 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/a99bf9eda0da4ea2b2a9f284792c886e/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [324bee1b720648a6af48200af143e19a](research.json)：[候选 1](#candidate-324bee1b720648a6af48200af143e19a)

<a id="candidate-324bee1b720648a6af48200af143e19a"></a>

研究中问题：Can VerifyLeader consume successful notifications from nonvoters as sufficient authority support, and thereby return success when the local peer can no longer safely serve the API’s promised leadership check?
[候选原文与历史](state.json)
保存的语义未知：Does the API’s authority-check responsibility exclude success based solely on self plus nonvoters, and what exact local or cluster history grounds that implication?；Can an actual legal transport/election schedule retain old-leader belief long enough for nonvoter notifications to produce a completed success after authority is lost?；Which observation boundary cleanly distinguishes lack of admitted voter support from unrecorded earlier notifications?

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Verification eligibility and callback timing relative to election/lease expiry.；Legal sender history for follower commitment beyond the current validated request prefix.；Partial-store-error recovery…
  尚无精确对应交接。

- B-commit-consume：Whether sender nextIndex histories can expose follower propagation beyond a validated shared prefix when getLastIndex includes a divergent suffix.
  尚无精确对应交接。

- B-history：Fault semantics after partial storage writes and process restart require deeper store-specific work.
  尚无精确对应交接。

- B-resync：Old snapshot arrival overlapping established application needs separate history analysis.
  尚无精确对应交接。

- B-verify-start：Whether caller-visible authority checking requires voter-only responses; registration includes nonvoters.
  尚无精确对应交接。

- B-transport：Per-transport ordering beyond inspected network dispatch; injected transports are interfaces, not proof of legal arbitrary reordering.
  尚无精确对应交接。

- F-verify-support：A quorum-sized count can contain nonvoter notifications; whether source-authorized histories make its successful consumption unsafe remains to be checked.
  尚无精确对应交接。

- surface:Raft.appendEntries StoreLogs failure after DeleteRange：Explicit stale last-log metadata TODO after failed replacement; fault contract and recovery paths not yet established.
  尚无精确对应交接。

- surface:Raft.restoreUserSnapshot / RecoverCluster：Manual destructive history replacement differs from ordinary consensus recovery; inspect caller contract before treating it as a fault.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1725.83 秒、37 次 Agent 调用、8 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 674.17 | 1725.83 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 8 | 0 | 8 |
| 新 Unit | 4 | 0 | 4 |
| 语义复核 | 6 | 0 | 6 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 0.00 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 0.00 秒。

目标执行组成：正式检查 0 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v55`；展示版本 `audit-products-v55`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/a99bf9eda0da4ea2b2a9f284792c886e/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/a99bf9eda0da4ea2b2a9f284792c886e/check.json)；[stdout](logs/a99bf9eda0da4ea2b2a9f284792c886e/stdout.log)；[stderr](logs/a99bf9eda0da4ea2b2a9f284792c886e/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

