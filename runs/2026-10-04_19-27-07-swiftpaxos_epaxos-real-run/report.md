# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**。已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **9.35 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1838.75 秒、37 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 561.25 | 1838.75 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 7.77 秒。

目标动作总耗时（含已记录的准备与复制）：未记录有效总量；1 项未完整记录，合计不完整。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v49`；展示版本 `audit-products-v49`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/ea9b2f3fe0bf4e67a99c63656d5eacb7/check.json)；[stdout](logs/ea9b2f3fe0bf4e67a99c63656d5eacb7/stdout.log)；[stderr](logs/ea9b2f3fe0bf4e67a99c63656d5eacb7/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| After a nonstale Accept is acknowledged, can recovery reliably distinguish and preserve its accepted tuple when handleAccept… | 研究中，尚无正式义务 | Which legal crash/delay history exposes the status distinction after a completed slow-path acknowledgement?；Does a sourced local acceptance/recovery responsibility… | [候选 1](#candidate-eee4de64737240419ebf2cd5af7bae73) |

条件探索：For candidate eee4de64737240419ebf2cd5af7bae73, does replica 1 restart phase1 and drop an acknowledged dependency after its Prepare quorum comprises itself and two previously empty replicas, while…
所选问题／策略（原文摘录）：Discriminate whether genuine slow-path Accept acknowledgements followed by recovery through a quorum intersecting at the acceptor preserve the committed tuple. All protocol messages come from target senders; retained Commit and…
[受理问题、条件与来源](submissions/cc07145c0add4e63871c8512424f98b4/accepted.json)；[固定输入](submissions/cc07145c0add4e63871c8512424f98b4/inputs/accept_recovery_explore_test.go)
<a id="exploration-f0aaf5b56d5f426eac5739df1c19765b"></a>
[探索执行 1](#exploration-f0aaf5b56d5f426eac5739df1c19765b)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/f0aaf5b56d5f426eac5739df1c19765b/check.json)；[实际输出](logs/f0aaf5b56d5f426eac5739df1c19765b/stdout.log)；[诊断](logs/f0aaf5b56d5f426eac5739df1c19765b/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 7.77 秒；[实际命令、工具版本与输入记录](logs/f0aaf5b56d5f426eac5739df1c19765b/check.json)
[执行文件清单](experiments/9a3f7f3397a04a8e87ba4df145c52a2b/workspace-delta/manifest.json)；[执行文件清单](experiments/9a3f7f3397a04a8e87ba4df145c52a2b/workspace-outcome/manifest.json)；[执行文件清单](experiments/9a3f7f3397a04a8e87ba4df145c52a2b/workspace/epaxos/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A client proposal allocates its origin row slot and establishes command/Seq/Deps at its owner. PreAccept receivers qualify ballot and merge local conflicts, reporting current value ballot and status. Matching replies…
- 上下文／权威转换（原文导航摘录）：Authority is per instance, not solely the master-selected leader. Initial ballot equals origin replica; recovery replaces leader bookkeeping and chooses a ballot based on proposer id and, when IsLeader, maxRecvBallot.…
- 两条主线的连接（原文导航摘录）：Formation writes the same tuple and status that Prepare exposes to new owners. bal qualifies old requests while vbal and Status determine how old support is interpreted during recovery. Acks can contribute to local…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.74 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.56 分钟 · 实际执行：Discriminate whether genuine slow-path Accept acknowledgements followed by recovery through a quorum intersecting at the acceptor preserve…；探索执行正常结束。[执行记录](logs/f0aaf5b56d5f426eac5739df1c19765b/check.json)

- 9.35 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/ea9b2f3fe0bf4e67a99c63656d5eacb7/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
另有 1 次探索保存了执行记录，尚无精确对应的后续受理解释；这不是新增正式欠账。[待解释探索](logs/f0aaf5b56d5f426eac5739df1c19765b/check.json)
- [eee4de64737240419ebf2cd5af7bae73](research.json)：[候选 1](#candidate-eee4de64737240419ebf2cd5af7bae73)

<a id="candidate-eee4de64737240419ebf2cd5af7bae73"></a>

研究中问题：After a nonstale Accept is acknowledged, can recovery reliably distinguish and preserve its accepted tuple when handleAccept leaves Status unchanged?
[候选原文与历史](state.json)
保存的语义未知：Which legal crash/delay history exposes the status distinction after a completed slow-path acknowledgement?；Does a sourced local acceptance/recovery responsibility suffice, or is a same-history divergence needed to establish the intended guarantee?

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Legal recovery histories for missing ACCEPTED status and changed local value ballot.；Quorum-size applicability across N; duplicate reply support assumptions.；SCAN conflict coverage, SCC tie-break…
  尚无精确对应交接。

- B-phase1：Does quorum sizing and attribute merging preserve required support across permitted N and recovery ownership?
  尚无精确对应交接。

- B-accept：What recovery guarantee is established by an acknowledgement whose stored Status remains preaccepted or NONE?；Higher-ballot AcceptReply retry block follows a != ballot return and appears unreachable.
  尚无精确对应交接。

- B-authority：Recovery initiation changes vbal unlike received Prepare; whether it can hide a higher-priority prior accepted value needs legal-history investigation.
  尚无精确对应交接。

- B-recover-select：Can a legal delayed-message/crash history make selection discard an acknowledged accepted tuple?
  尚无精确对应交接。

- B-execute：Tie-breaking by local proposeTime for same-row equal-Seq SCC members requires checking reachability.
  尚无精确对应交接。

- B-membership：Even-membership admissibility and intended fast-quorum sizing are not explicitly documented in read sources.
  尚无精确对应交接。

- B-persist：No captured restart decoder or initialized store found by StableStore search; durable-mode responsibility remains unresolved.
  尚无精确对应交接。

- B-client：Client retry handling is explicitly TODO in handlePropose; no exactly-once responsibility is presumed.
  尚无精确对应交接。

- F-record：Which acknowledged value information remains recoverable after an acceptor retains preaccepted status?
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
