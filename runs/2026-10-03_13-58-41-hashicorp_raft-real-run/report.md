# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 3 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。已产生观察的正式结论 2 项：已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 1 项。受理、执行与结论分别计数。

实际持续 **35.48 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 270.96 秒、29 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2129.04 | 270.96 |
| Agent 调用 | 40 | 11 | 29 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 3 | 7 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 2 次＋探索 0 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v43`；展示版本 `audit-products-v43`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`303.46300178099773`（配置值不表示触发了超时）。
[调用记录](logs/13fdbcd5c0514f20961fda895794e1b7/check.json)；[stdout](logs/13fdbcd5c0514f20961fda895794e1b7/stdout.log)；[stderr](logs/13fdbcd5c0514f20961fda895794e1b7/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前结果 | 回答摘录 | 检查进度 | 定位 |
| --- | --- | --- | --- | --- |
| 1. 部分投票持久化失败导致陈旧候选者获票 | 已确认违反 | 候选者键写入失败后，接收方留下“新任期 4、旧候选者 A”的组合，并向日志落后的 A 返回同任期投票成功；无故障对照拒绝该请求。结果限定于明确的单键写入错误返回模型，未观察到陈旧节点当选或已提交数据丢失。 | 机械比较：观察到违反；对应性意见：no_issue_found；当前检查已完整处置 | [claim-vote-freshness-after-write-error](#claim-claim-vote-freshness-after-write-error) |
| 2. 非投票节点回执被计入领导权验证票数 | 已确认违反 | 固定检查中，仅非投票节点返回心跳成功，验证票数仍从 1 增至 2 并触发阈值通知；合法投票节点对照也正常达到阈值。该结果验证局部资格计数缺陷，未观察公开 Future 完成或客户端陈旧读取。 | 机械比较：观察到违反；对应性意见：no_issue_found；当前检查已完整处置 | [claim-verify-voter-support](#claim-claim-verify-voter-support) |
| Can normal limited-batch replication following a legal leader change make a follower dispatch a divergent old suffix beyond the… | 源码解释，未经性质执行 | Predecessor term checks reject unmatched history; first conflicting request entry truncates the suffix.；Dedicated heartbeat requests carry no commit bound.；New leaders… | — | [候选记录](state.json) |

<a id="claim-claim-vote-freshness-after-write-error"></a>

### 1. 部分投票持久化失败导致陈旧候选者获票

**已确认违反**。要求原文：A voter must not grant a log-stale candidate a vote in a term in which it has not previously granted that candidate a vote merely because a failed vote-persistence attempt left the new term paired with a previous term candidate. Such a request remains subject to the normal last-log-term/index eligibility rule.

决定性范围：RequestVote eligibility after one candidate-value StableStore write returns an error without changing that key, while prior successful term/key writes remain durable. Fixed configuration and accurate logs.
Individual successful StableStore calls retain their values; an injected failed Set leaves its key unchanged.；The receiver continues along the implementation error-return path without an externally imposed process restart.；A prior vote for the stale candidate occurred only in an earlier term; the new-term attempt for another candidate was denied.。

排除：Any particular production storage backend frequency of this error；An observed elected stale leader or lost committed command；Byzantine requests, corrupt storage, membership/address changes。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：候选者键写入失败后，接收方留下“新任期 4、旧候选者 A”的组合，并向日志落后的 A 返回同任期投票成功；无故障对照拒绝该请求。结果限定于明确的单键写入错误返回模型，未观察到陈旧节点当选或已提交数据丢失。

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：True。
[固定测试](direct-checks/6a8f533248094889885d1b15ee6fcc45/assurance_generated_test.go)；[条件与检查器](direct-checks/6a8f533248094889885d1b15ee6fcc45/plan.json)；[原始观察](logs/6d624169e9c44667a5e943dae1ba4d65/stdout.log)；[assessment](direct-checks/6a8f533248094889885d1b15ee6fcc45/6d624169e9c44667a5e943dae1ba4d65-assessment.json)；[对应性复核](submissions/43c3b687555e430882c6662bc6701d8f/accepted.json)

固定比较 `vote-freshness`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| operation | successful_write_control | failed_candidate_write |
| event | vote_result | vote_result |
| granted | false | true |
| prefix.pair_term | 4 | 4 |
| prefix.old_vote_term | 2 | 2 |
| prefix.old_candidate | a | a |
| admitted.request_term | 4 | 4 |
| admitted.candidate_stale | true | true |
| admitted.prior_same_term_grant | false | false |
| response_term | 4 | 4 |
| rpc_completed | true | true |
| stored_candidate | b | a |
| stored_vote_term | 4 | 4 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-claim-verify-voter-support"></a>

### 2. 非投票节点回执被计入领导权验证票数

**已确认违反**。要求原文：In a stable configuration, acknowledgements from Nonvoter participants must not count toward the voter quorum used to complete a leader verification successfully. A successful verification must be supported by enough eligible voters for that verification, including the local voter when applicable.

决定性范围：Eligibility of response support consumed by VerifyLeader in an established leader tenure and unchanged configuration. Distinguish eligible voter acknowledgement from successful communication with a nonvoter.
Non-Byzantine peers, intact current configuration and no concurrent configuration change.；The leader is an eligible voter; response observations refer to the same verification operation.。

排除：Global linearizable-read endpoint or election-safety violation；Bounded eventual completion in the absence of a voter quorum；Membership transition and storage faults。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：固定检查中，仅非投票节点返回心跳成功，验证票数仍从 1 增至 2 并触发阈值通知；合法投票节点对照也正常达到阈值。该结果验证局部资格计数缺陷，未观察公开 Future 完成或客户端陈旧读取。

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：True；独立场景完整处置：True。
[固定测试](direct-checks/fad8e3f892144294b9c0c41d3e953f2c/assurance_generated_test.go)；[条件与检查器](direct-checks/fad8e3f892144294b9c0c41d3e953f2c/plan.json)；[原始观察](logs/7f8208006dcd48b98fddb2bea55e61df/stdout.log)；[assessment](direct-checks/fad8e3f892144294b9c0c41d3e953f2c/7f8208006dcd48b98fddb2bea55e61df-assessment.json)；[对应性复核](submissions/49d212a89c4940688dc8ec1dd485c86f/accepted.json)

固定比较 `verify-eligibility`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| operation | voter-b | nonvoter |
| event | verify_observed | verify_observed |
| eligibility_respected | true | false |
| admitted.election_grants | 3 | 3 |
| admitted.configuration_voters | 3 | 3 |
| admitted.quorum | 2 | 2 |
| admitted.initial_votes | 1 | 1 |
| admitted.registered_workers | 3 | 3 |
| actual_peer | voter-b | nonvoter |
| eligible_votes | 2 | 1 |
| final_votes | 2 | 2 |
| response_term | 2 | 2 |
| rpc_error |  |  |
| rpc_success | true | true |
| same_future | true | true |
| threshold_notified | true | true |
| worker_finished | true | true |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：Leader stores indexed current-term logs and reports its own match; per-peer replication verifies successful responses and accounts last sent entries or installed snapshot. Current voter majority and tenure startIndex…
- 上下文／权威转换（原文导航摘录）：Follower timeouts and transfer trigger campaigns over latest voters. Pre-vote checks plausibility without persisting term; actual election increments durable term, persists votes and uses log freshness. Campaign replies…
- 两条主线的连接（原文导航摘录）：Support is eligible within the captured leader tenure and current voter set. Fresh tenure accounting and a current-term no-op prevent simply reusing old majority indexes; old workers retain old commitment/stepDown…

- 06:07:34 +0000（距创建墙钟 531.9 秒，含暂停间隔）；Agent 回合墙钟 339.01 秒 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 06:16:59 +0000（距创建墙钟 1097.4 秒，含暂停间隔）；目标工具耗时 14.62 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment；对象 0b43318d5be04e4c8baa57ddea29a7a6。[执行记录](logs/7f8208006dcd48b98fddb2bea55e61df/check.json)

- 06:19:37 +0000（距创建墙钟 1254.8 秒，含暂停间隔）；Agent 回合墙钟 157.07 秒 · 受理 review：非投票节点回执被计入领导权验证票数；对象 unit-claim-verify-voter-support。[完整交接](submissions/49d212a89c4940688dc8ec1dd485c86f/accepted.json)

- 06:20:59 +0000（距创建墙钟 1336.8 秒，含暂停间隔）；Agent 回合墙钟 81.89 秒 · 受理 review：Resolve the source-premise issue on the previously explained ordinary catch-up candidate.。[完整交接](submissions/74d4dd65f6234904a7335f10de939576/accepted.json)

- 06:24:57 +0000（距创建墙钟 1575.2 秒，含暂停间隔）；Agent 回合墙钟 238.21 秒 · 受理 obligation：Investigate vote eligibility after a single returned storage write error; independently retain the confirmed verification counting result…；对象 unit-claim-vote-freshness-after-write-error, bc11db21270a4b959845b42fde5778f0。[完整交接](submissions/cc6478329f1a405493d06fd61ae9e5d7/accepted.json)

- 06:30:59 +0000（距创建墙钟 1937.7 秒，含暂停间隔）；Agent 回合墙钟 361.66 秒 · 受理 check：Compare real stale RequestVote handling after successful versus failed candidate persistence, retaining generated request history, stored…；对象 unit-claim-vote-freshness-after-write-error。[完整交接](submissions/6a8f533248094889885d1b15ee6fcc45/accepted.json)

- 06:31:19 +0000（距创建墙钟 1956.9 秒，含暂停间隔）；目标工具耗时 18.83 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment；对象 729f8585190e4f29b0746cd4e4d6a657。[执行记录](logs/6d624169e9c44667a5e943dae1ba4d65/check.json)

- 06:33:38 +0000（距创建墙钟 2096.1 秒，含暂停间隔）；Agent 回合墙钟 138.71 秒 · 受理 review：部分投票持久化失败导致陈旧候选者获票；对象 unit-claim-vote-freshness-after-write-error。[完整交接](submissions/43c3b687555e430882c6662bc6701d8f/accepted.json)

- 06:34:10 +0000（距创建墙钟 2128.7 秒，含暂停间隔）；Agent 回合墙钟 32.42 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/13fdbcd5c0514f20961fda895794e1b7/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：Ordinary accurate-metadata catch-up is explained by end-first backtracking and conflict truncation; storage-error and snapshot-specific histories remain separate questions.；VerifyLeader tally counts…
  尚无精确对应交接。

- b-election：Can failure of the candidate write after successful vote-term persistence make an old candidate receive a new-term duplicate grant despite being log-stale?
  相关交接：[交接 4](#handoff-43c3b687555e430882c6662bc6701d8f)

- b-follower-append：What storage failure semantics apply after successful truncation but failed replacement?；Can snapshot-specific histories invalidate the normal catch-up prefix argument?
  相关交接：[交接 1](#handoff-b9ec9df4ce324637b696103c99f1dc64)

- f-commit-bound：Storage-error or snapshot-specific histories may invalidate the accurate normal-log metadata premise; their effect on the dispatch bound remains unresolved.
  相关交接：[交接 1](#handoff-b9ec9df4ce324637b696103c99f1dc64)

- f-persisted-vote-pair：Fault-injected legal history and exact grant consequence need validation.
  相关交接：[交接 4](#handoff-43c3b687555e430882c6662bc6701d8f)

- surface:Transport heartbeat callback：Reverse-check concrete transport heartbeat admission and concurrency against shared append handler assumptions.
  尚无精确对应交接。

<a id="handoff-b9ec9df4ce324637b696103c99f1dc64"></a>

交接 1：[完整原文](submissions/b9ec9df4ce324637b696103c99f1dc64/accepted.json)；精确引用 b-follower-append, b-replicate, f-commit-bound。
回答摘录：For ordinary append catch-up with accurate persisted-log metadata and a normal matching-prefix/divergent-suffix history, the sender does not first send an arbitrary early matching batch. A new tenure starts nextIndex at the leader end plus one. Rejection…
该交接当时的剩余问题（非当前欠账）：The separate cached lastLog/storage-error surface could invalidate accurate-metadata premises and remains open.；Snapshot installation, administrative restore and changed peer identity histories require independent investigation if they produce an early nextIndex with a retained divergent suffix.；VerifyLeader eligibility has a more direct discriminator: all replication workers receive futures but quorumSize counts only voters; inspect permissible heartbeat history and construct a bounded correlated check.

<a id="handoff-49d212a89c4940688dc8ec1dd485c86f"></a>

交接 2：[完整原文](submissions/49d212a89c4940688dc8ec1dd485c86f/accepted.json)；精确引用 b-verify, f-verification-tally。
回答摘录：The completed fixed check measured real nonvoter heartbeat support increasing the verification tally from one to two and notifying the same future at threshold, although only the local voter was eligible. The voter control counted two eligible votes. The…
该交接当时的剩余问题（非当前欠账）：Investigate independent snapshot, persistence and recovery surfaces; do not repeat equivalent tally variants merely to accumulate confirmation.；A full public API/partition endpoint is a separate consequence question if later evidence makes it worth constructing.

<a id="handoff-cc6478329f1a405493d06fd61ae9e5d7"></a>

交接 3：[完整原文](submissions/cc6478329f1a405493d06fd61ae9e5d7/accepted.json)；精确引用 b-verify, f-verification-tally。
回答摘录：Accepted assessment confirms the scoped verification eligibility violation after correspondence review: successful nonvoter callback raises tally to two with one eligible voter, whereas the voter control has two eligible votes. The map now records the local…
该交接当时的剩余问题（非当前欠账）：Independent partial vote-persistence/freshness question selected here.；Verification public API completion and stale-read consequences remain unmeasured and are not needed for the local eligibility result.

<a id="handoff-43c3b687555e430882c6662bc6701d8f"></a>

交接 4：[完整原文](submissions/43c3b687555e430882c6662bc6701d8f/accepted.json)；精确引用 b-election, f-persisted-vote-pair。
回答摘录：Under the declared returned-write-error model, actual same-history execution produced a mixed term/candidate record and a later stale candidate grant through duplicate handling. One failed candidate write leaves old A with term 4; actual A request at term 4…
该交接当时的剩余问题（非当前欠账）：Production backend fault realization, final stale-leader election and client history loss remain independent scope limits.；Other retained follower storage-error and snapshot-history surfaces remain available for source investigation.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
