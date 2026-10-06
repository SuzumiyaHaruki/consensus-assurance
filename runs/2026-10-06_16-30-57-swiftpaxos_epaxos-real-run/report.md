# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**。已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **11.64 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1701.58 秒、36 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 698.42 | 1701.58 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 9.04 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 9.50 秒。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v54`；展示版本 `audit-products-v54`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/22acc618ef4c4b238cc3596cdafa62a9/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/22acc618ef4c4b238cc3596cdafa62a9/check.json)；[stdout](logs/22acc618ef4c4b238cc3596cdafa62a9/stdout.log)；[stderr](logs/22acc618ef4c4b238cc3596cdafa62a9/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| <a id="claim-C-instance-command-agreement"></a>Within one fixed configuration and crash-stop history, any two completed COMMITTED decisions for the same origin-replica/instance… | 尚无正式判定 | 义务已受理，尚无固定检查记录 | [C-instance-command-agreement](state.json)；[候选 2](#candidate-d1ee4127a89a42868699f1ced125267c) |
| Does acknowledging an eligible Accept while retaining a preaccepted or NONE status lose the accepted-support classification that… | 暂停调查，尚无正式义务 | Does retaining the preaccepted status independently permit a conflicting continuation when the recoverer self-VBallot does not dominate?；The composed recovery path lost… | [候选 1](#candidate-67ded68bdd3b49d7ba28b333d9eb0caf) |

条件探索：After a coordinator receives two Accept acknowledgements in N=5 and stops before Commit delivery, what support do followers export, and what does recovery select when its local slot was absent? Does…
所选问题／策略（原文摘录）：Construct a real-wire slow-path prefix and inspect follower status exported to recovery. An empty recoverer also tests the independent self-vbal selection mechanism. Direct unseen-slot recovery entry remains conditional exploration, not a…
[受理问题、条件与来源](submissions/9a5071d0f65041a1a4789e8e34a55f9a/accepted.json)；[固定输入](submissions/9a5071d0f65041a1a4789e8e34a55f9a/inputs/explore_accept_recovery_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-67ded68bdd3b49d7ba28b333d9eb0caf)
<a id="exploration-f758d4c2c09d4578b2233e1139e0eb6e"></a>
[探索执行 1](#exploration-f758d4c2c09d4578b2233e1139e0eb6e)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/f758d4c2c09d4578b2233e1139e0eb6e/check.json)；[实际输出](logs/f758d4c2c09d4578b2233e1139e0eb6e/stdout.log)；[诊断](logs/f758d4c2c09d4578b2233e1139e0eb6e/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 9.50 秒；执行进程耗时 9.04 秒；[实际命令、工具版本与输入记录](logs/f758d4c2c09d4578b2233e1139e0eb6e/check.json)
[执行输入文件清单](experiments/8d43cece85ad4c1b84fb26683cdaf112/workspace-delta/manifest.json)
[执行后文件清单](experiments/8d43cece85ad4c1b84fb26683cdaf112/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-2f72e71bab504228a5d89563110c19bc)

<a id="exploration-feedback-2f72e71bab504228a5d89563110c19bc"></a>
[交接 1](#exploration-feedback-2f72e71bab504228a5d89563110c19bc) · 后续说明；关联：[探索执行 1](#exploration-f758d4c2c09d4578b2233e1139e0eb6e)
后续受理交接原文（摘录，不是各次执行的独立观察）：The exploration completed all 20 dispatches. Original coordinator 0 recorded instance 0.0 COMMITTED with PUT(key=10,value=01), sequence 1 and dependency on 1.0. Followers 1 and 2 acknowledged Accept but retained statuses PREACCEPTED and PREACCEPTED_EQ; both…
[完整交接；精确引用不表示已解决或已正式化](submissions/2f72e71bab504228a5d89563110c19bc/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A1: A client proposal is batched by its receiving replica into a local-row instance. Conflict indexes supply sequence/dependencies; thriftiness selects a preferred live peer subset. PreAccept replies are filtered by…
- 上下文／权威转换（原文导航摘录）：A2: Authority is per instance, not exclusive global proposal leadership. Initial ballots equal origin replica ID. Recovery resets bookkeeping while retaining client proposals/value context, selects a ballot, adds a self…
- 两条主线的连接（原文导航摘录）：A1/A2 connection: The record status and value ballot exported by Prepare determine whether earlier formation support constrains the new attempt as committed, accepted or merely preaccepted. Reset bookkeeping discards…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.81 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 7.45 分钟 · 受理 explore：Construct a real-wire slow-path prefix and inspect follower status exported to recovery. An empty recoverer also tests the independent…。[完整交接](submissions/9a5071d0f65041a1a4789e8e34a55f9a/accepted.json)

- 7.60 分钟 · 实际执行：Construct a real-wire slow-path prefix and inspect follower status exported to recovery. An empty recoverer also tests the independent…；探索执行正常结束。[执行记录](logs/f758d4c2c09d4578b2233e1139e0eb6e/check.json)

- 10.73 分钟 · 受理 obligation：Fork a distinct decision-agreement responsibility from the original status-classification premise, retaining the conditional exploration…。[完整交接](submissions/2f72e71bab504228a5d89563110c19bc/accepted.json)

- 11.64 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/22acc618ef4c4b238cc3596cdafa62a9/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项


已选检查／复核待办：
- [unit-C-instance-command-agreement](research.json)：[C-instance-command-agreement](#claim-C-instance-command-agreement)；具体进度与缺口见对应义务

<a id="candidate-67ded68bdd3b49d7ba28b333d9eb0caf"></a>

暂停调查：Does acknowledging an eligible Accept while retaining a preaccepted or NONE status lose the accepted-support classification that later Prepare and recovery continuation require?
[候选原文与历史](state.json)
保存的语义未知：Does retaining the preaccepted status independently permit a conflicting continuation when the recoverer self-VBallot does not dominate?；The composed recovery path lost the prior command in a conditional exploration; an admitted-history agreement check is selected in the child.
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-f758d4c2c09d4578b2233e1139e0eb6e)

<a id="candidate-d1ee4127a89a42868699f1ced125267c"></a>

研究中问题：Can recovery of a scanner-eligible missing instance commit a different command batch after another replica already committed that same instance, when the original decision is delayed and prior acknowledgements remain in the recovery quorum?
[候选原文与历史](state.json)
保存的语义未知：Fixed execution must establish the later-instance hole prefix and correlate both completed decisions for exactly the same instance.；Causal contribution of unchanged follower status versus the recoverer self-VBallot assignment remains separate from agreement.

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Follower Accept leaves Status unchanged; investigate preservation through Prepare.；Prepare selection overwrites equal-VBallot tuples in reply order; recoverer also rewrites self vbal before exporting…
  尚无精确对应交接。

- B-accept：Does preservation of an acknowledged Accept require an ACCEPTED status visible to subsequent Prepare and PreAccept processing?
  尚无精确对应交接。

- B-client：Caller retry policy and deduplication contract remain unread; handlePropose explicitly leaves client retries as TODO.
  尚无精确对应交接。

- F-record：Whether follower Accept acknowledgement preserves the support classification needed across recovery.
  尚无精确对应交接。

- surface:recordInstanceMetadata：bal and vbal overwrite the same bytes; durable initialization/replay contract is unresolved.
  尚无精确对应交接。

- surface:handleTryPreAccept：Branch selection duplicates subcase 3 condition for subcase 4; determine actual reachability before testing inner handlers.
  尚无精确对应交接。

- surface:updateAttributes：Batch loop breaks at the first newly enlarged per-row dependency; later commands may require a greater dependency. Compare with actual command conflict responsibility.
  尚无精确对应交接。

- surface:handlePreAccept：Missing command fill indexes LeaderId rather than origin Replica; legal recovery reachability remains unresolved.
  尚无精确对应交接。

- surface:nodeArray.Less：Tie-break uses local proposeTime for same replica and sequence; determine whether legal SCC histories can reach that tie.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
