# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。已产生观察的正式结论 0 项：已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **11.74 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1695.58 秒、37 次 Agent 调用、16 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 704.42 | 1695.58 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 16 | 0 | 16 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 0 次＋探索 0 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v44`；展示版本 `audit-products-v44`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/51ff7bd13bfa41399b22da8b1a14ebfa/check.json)；[stdout](logs/51ff7bd13bfa41399b22da8b1a14ebfa/stdout.log)；[stderr](logs/51ff7bd13bfa41399b22da8b1a14ebfa/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Can VerifyLeader complete successfully from self plus nonvoter acknowledgements after the caller has lost voter-majority… | 研究中，尚无正式义务 | Can an actual legal partition/election schedule complete verification on nonvoter support after another leader exists, while excluding delayed voter replies?；Does the… | [候选 1](#candidate-31dc6bcdc42e48f99ea560a299c17e51) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Leader dispatch assigns term/index and persists locally, then self-matches and wakes per-peer replication. Replicators backtrack on mismatch, send bounded log batches or snapshots, and report successful progress into…
- 上下文／权威转换（原文导航摘录）：Follower contact timeout starts campaigns only with local voter eligibility; optional pre-vote precedes persisted term/vote advancement. Vote handling checks membership, known leader, term, prior vote and last-log…
- 两条主线的连接（原文导航摘录）：Log freshness and durable votes constrain authority acquisition. New tenure match accounting starts afresh, but retained log history may advance only when a current-term entry gains majority support. Latest…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 2.96 分钟 · 受理 research：Preserve initial two-core-path source investigation and two concrete follower-history questions before completing the core map. No…。[完整交接](submissions/b28c24d4169d427d8610850567724708/accepted.json)

- 8.85 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 11.74 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/51ff7bd13bfa41399b22da8b1a14ebfa/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [31dc6bcdc42e48f99ea560a299c17e51](research.json)：[候选 1](#candidate-31dc6bcdc42e48f99ea560a299c17e51)

<a id="candidate-31dc6bcdc42e48f99ea560a299c17e51"></a>

研究中问题：Can VerifyLeader complete successfully from self plus nonvoter acknowledgements after the caller has lost voter-majority authority, before the independent lease check steps it down?
[候选原文与历史](state.json)
保存的语义未知：Can an actual legal partition/election schedule complete verification on nonvoter support after another leader exists, while excluding delayed voter replies?；Does the public VerifyLeader contract require fresh voter-majority confirmation under these conditions, and how should the client observation be bounded?

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Bounded follower append commit boundary and divergent history；Post-truncation storage-error cache validity and backend fault assumptions；Nonvoter support and concurrent configuration changes in…
  尚无精确对应交接。

- campaign：Failure semantics between the two vote persistence writes remain unexamined.
  尚无精确对应交接。

- replicate-support：Legal history in which bounded AppendEntries ends before a divergent follower suffix remains to be traced.
  尚无精确对应交接。

- follower-append：Does bounded replication establish matching history through every index used by the follower commit bound?；After successful truncation and failed StoreLogs, cached last-log metadata is not refreshed;…
  相关交接：[交接 1](submissions/b28c24d4169d427d8610850567724708/accepted.json)

- membership：Detailed address-change and remove/re-add overlap semantics remain unread.
  尚无精确对应交接。

- verification：Can a reachable Nonvoter success complete VerifyLeader while the old leader has lost voter-majority contact and another leader exists, before lease step-down?；Configuration changes concurrent with a…
  尚无精确对应交接。

- fsm-consumption：Batching interface no-gap wording versus filtered internal log types has not been investigated.
  尚无精确对应交接。

- snapshot-recovery：Handling of delayed snapshots relative to newer applied entries needs separate source/history investigation.
  尚无精确对应交接。

- history-reconstruction：Concrete persistence backend error atomicity and restart fault contracts are not yet mapped.
  尚无精确对应交接。

- client-entry：Application-specific deterministic FSM correctness remains caller responsibility.
  尚无精确对应交接。

- commit-bound：Follower local-last-index bound may exceed entries matched by one bounded request.
  尚无精确对应交接。

- verify-tally-fact：Whether nonvoter support can make public verification falsely succeed after authority loss under a legal partition.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
