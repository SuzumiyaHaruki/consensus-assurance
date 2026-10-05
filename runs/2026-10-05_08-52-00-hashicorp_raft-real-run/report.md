# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **8.89 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1866.35 秒、37 次 Agent 调用、8 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 533.65 | 1866.35 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 8 | 0 | 8 |
| 新 Unit | 4 | 1 | 3 |
| 语义复核 | 6 | 0 | 6 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 0.00 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 0.00 秒。

目标执行组成：正式检查 0 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v50`；展示版本 `audit-products-v50`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/79f7996315604349a1db198ac53dd18f/check.json)；[stdout](logs/79f7996315604349a1db198ac53dd18f/stdout.log)；[stderr](logs/79f7996315604349a1db198ac53dd18f/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| <a id="claim-claim-verify-authority"></a>VerifyLeader must not report successful leadership confirmation for a node whose authority has already been superseded by an… | 尚无正式判定 | 义务已受理，尚无固定检查记录 | [claim-verify-authority](state.json)；[候选 1](#candidate-5cce01d59279482eb5cd8c3faf4534af) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader assigns term/index, stores locally and replicates to all configured peers. Successful append or snapshot responses report match indices to the leader-term tracker. Only configured voters contribute to its…
- 上下文／权威转换（原文导航摘录）：Follower timeout can start a voter election. Optional pre-vote precedes durable term increment and persisted self vote. Requests are scoped to one election reply channel; recipient eligibility, freshness, leader and…
- 两条主线的连接（原文导航摘录）：Election log freshness preserves prior eligible history, while committing a new-term no-op establishes the new leader commitment boundary. Old election reply channels and old replication commitment objects remain…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.69 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.12 分钟 · 受理 obligation：Applicable public authority confirmation and voter-specific documentation ground a safety obligation; execute a real mixed-suffrage…。[完整交接](submissions/16c7f13d90d74c0e9000ca43a57f7740/accepted.json)

- 8.89 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/79f7996315604349a1db198ac53dd18f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项


已选检查／复核待办：
- [unit-claim-verify-authority](research.json)：[claim-verify-authority](#claim-claim-verify-authority)；具体进度与缺口见对应义务

<a id="candidate-5cce01d59279482eb5cd8c3faf4534af"></a>

研究中问题：Can VerifyLeader return success based on nonvoter acknowledgements when eligible voters have not confirmed this authority?
[候选原文与历史](state.json)
保存的语义未知：Can a partitioned former leader complete VerifyLeader from nonvoter support before its independent voter lease expires?；Can actual voter-majority election and completed newer write establish the false authority/stale state endpoint in that same history?

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Storage partial failures and crash recovery atomicity remain unresolved.；Verification nonvoter eligibility is a sourced discrepancy, not an established violation.；InmemTransport routes through…
  尚无精确对应交接。

- b-election：StableStore partial write/crash semantics for the separately persisted vote term and candidate remain unread.
  尚无精确对应交接。

- b-follower-append：Whether producer backtracking and transport ordering always prevent follower commitment beyond the prefix established by this request.；After successful suffix deletion followed by StoreLogs error,…
  尚无精确对应交接。

- b-recovery：Delayed same-term snapshots versus already applied state need further history analysis.
  尚无精确对应交接。

- b-verify：Whether nonvoter notification counting completes a public verification after a newer-term voter majority has acquired authority in the same legal partition history.
  相关交接：[交接 1](submissions/16c7f13d90d74c0e9000ca43a57f7740/accepted.json)

- surface:Raft.persistVote：What atomicity/recovery assumptions connect separately persisted vote term and candidate after an interrupted write?
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
