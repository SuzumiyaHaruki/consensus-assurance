# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **10.33 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1780.31 秒、37 次 Agent 调用、7 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 619.69 | 1780.31 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 8 | 1 | 7 |
| 新 Unit | 4 | 0 | 4 |
| 语义复核 | 6 | 0 | 6 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 16.81 秒。

目标动作总耗时（含已记录的准备与复制）：未记录有效总量；1 项未完整记录，合计不完整。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v49`；展示版本 `audit-products-v49`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/ae393dc9fe764af5ad1d6f94f31cf466/check.json)；[stdout](logs/ae393dc9fe764af5ad1d6f94f31cf466/stdout.log)；[stderr](logs/ae393dc9fe764af5ad1d6f94f31cf466/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Can successful VerifyLeader completion be established by nonvoter replication acknowledgments when the current leader lacks… | 研究中，尚无正式义务 | Clarify the exact applicable authority guarantee of VerifyLeader and whether independently grounded eligibility suffices for a scoped obligation.；Construct legal… | [候选 1](#candidate-dcba9912fc5d48c5ab9c0af853f5666a) |

条件探索：For candidate dcba9912fc5d48c5ab9c0af853f5666a, does an old leader in a partition with a nonvoter complete VerifyLeader successfully after the other two voters elect a successor and complete a…
所选问题／策略（原文摘录）：The public VerifyLeader stale-read contract motivates a stronger same-history discriminator than tally arithmetic alone. Actual nodes supply all votes, appends and FSM completions. A wrapper drops cross-partition RPCs/responses and selects…
[受理问题、条件与来源](submissions/bb0a7c13888042d48936c175aa1ef53f/accepted.json)；[固定输入](submissions/bb0a7c13888042d48936c175aa1ef53f/inputs/verify_explore_test.go)
<a id="exploration-829c80b8a97546fbb2659f38331cd892"></a>
[探索执行 1](#exploration-829c80b8a97546fbb2659f38331cd892)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/829c80b8a97546fbb2659f38331cd892/check.json)；[实际输出](logs/829c80b8a97546fbb2659f38331cd892/stdout.log)；[诊断](logs/829c80b8a97546fbb2659f38331cd892/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 16.81 秒；[实际命令、工具版本与输入记录](logs/829c80b8a97546fbb2659f38331cd892/check.json)
[执行文件清单](experiments/0c9515ab0d6f43e1868a72f0be0254af/workspace-delta/manifest.json)；[执行文件清单](experiments/0c9515ab0d6f43e1868a72f0be0254af/workspace-outcome/manifest.json)；[执行文件清单](experiments/0c9515ab0d6f43e1868a72f0be0254af/workspace/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Leader admits commands, assigns current term/index and persists before local match. Peer workers replicate ordered prefixes, backtrack conflicts, fall back to snapshots and report successful stored prefixes. A…
- 上下文／权威转换（原文导航摘录）：Follower contact timeout allows configured voters to campaign. Optional pre-vote precedes durable term increment and one request per voter. Receivers constrain votes using known leader, membership, term, durable vote…
- 两条主线的连接（原文导航摘录）：Election log freshness and stored votes constrain who acquires authority over prior history. Each leader creates a new commitment object; late replication workers retain their old object and cannot directly populate the…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.34 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.68 分钟 · 受理 explore：The public VerifyLeader stale-read contract motivates a stronger same-history discriminator than tally arithmetic alone. Actual nodes…。[完整交接](submissions/bb0a7c13888042d48936c175aa1ef53f/accepted.json)

- 9.97 分钟 · 实际执行：The public VerifyLeader stale-read contract motivates a stronger same-history discriminator than tally arithmetic alone. Actual nodes…；探索执行正常结束。[执行记录](logs/829c80b8a97546fbb2659f38331cd892/check.json)

- 10.32 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/ae393dc9fe764af5ad1d6f94f31cf466/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
另有 1 次探索保存了执行记录，尚无精确对应的后续受理解释；这不是新增正式欠账。[待解释探索](logs/829c80b8a97546fbb2659f38331cd892/check.json)
- [dcba9912fc5d48c5ab9c0af853f5666a](research.json)：[候选 1](#candidate-dcba9912fc5d48c5ab9c0af853f5666a)

<a id="candidate-dcba9912fc5d48c5ab9c0af853f5666a"></a>

研究中问题：Can successful VerifyLeader completion be established by nonvoter replication acknowledgments when the current leader lacks responses from a voter quorum, and what authority responsibility applies to that result?
[候选原文与历史](state.json)
保存的语义未知：Clarify the exact applicable authority guarantee of VerifyLeader and whether independently grounded eligibility suffices for a scoped obligation.；Construct legal membership/leadership history and controlled transport schedule that observes which peers supply positive replies while preserving lease and negative-response paths.

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Verification eligibility and legal failure history are the selected discriminator.；Same-term snapshot age, concurrent heartbeat authority updates and partial vote persistence remain sourced…
  尚无精确对应交接。

- B_election：Failure between the two independent stable-store writes in persistVote has not been characterized.
  尚无精确对应交接。

- B_append_receive：Concurrent heartbeat term updates relative to blocking main-thread handlers need a composed ordering analysis.；After truncation followed by StoreLogs failure the source explicitly notes stale lastLog…
  尚无精确对应交接。

- B_recovery：Same-term delayed snapshot installation versus a newer applied prefix is not yet characterized.
  尚无精确对应交接。

- B_verify_ack：Does registering nonvoter workers allow successful verification without voter-quorum authority in a legal completed history?
  尚无精确对应交接。

- F_vote_record：Failure/crash between the two key writes remains an unresolved fault-contract and history question.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
