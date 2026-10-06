# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**；实际持续 **22.50 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 批量确认读取时，早期远端请求收到后一个请求的上下文 | 已确认违反 | 实测节点 2 的请求上下文为 (1001,101)，但领导者向它发送、且它接收的就绪结果均为后一个请求的 (2001,202)；两个请求都已从领导者待处理队列移除。该结果验证了稳定任期内前缀确认的远端请求身份丢失，不等同于已测得客户端超时或线性一致性破坏。 | [C-read-prefix-identity](#claim-C-read-prefix-identity) |
| Can an initialized node consume a snapshot-published lastApplied and campaign using its old Peer membership before the snapshot… | 研究中，尚无正式义务 | Does an actual allowed schedule reach election processing after snapshot-visible index publication but before membership restoration?；What minimal valid snapshot/log… | [候选 1](#candidate-fca709e34cb341ed91ba6cf309a4f445) |

<a id="claim-C-read-prefix-identity"></a>

### 1. 批量确认读取时，早期远端请求收到后一个请求的上下文

**已确认违反**。要求原文：When a stable-term multi-voter leader releases a confirmed ReadIndex prefix, every released remote request must be published to its original requester with its original complete SystemCtx, including earlier requests covered by a later confirmation. The confirming request context must not replace an earlier released request identity.

决定性范围：ReadIndex prefix release and remote result identity in a stable leader term and unchanged voting membership after a current-term entry has committed.
Crash-free execution with valid known peers and non-Byzantine messages produced by those peers；Distinct nonzero-low contexts for concurrently pending requests；Message loss is permitted; surviving messages retain their per-route order；Peer caller processes and persists updates before sending ordinary messages。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e14d4e7688b5402a93214d2d9d0b7de5/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/e14d4e7688b5402a93214d2d9d0b7de5/plan.json)；[原始观察](logs/c611aead474d4b8fa96906fb00bd1771/stdout.log)；[assessment](direct-checks/e14d4e7688b5402a93214d2d9d0b7de5/c611aead474d4b8fa96906fb00bd1771-assessment.json)；[对应性复核](submissions/d2973c7ab6594d2287c3fda91eef1f07/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 15.98 秒；执行进程耗时 14.59 秒；[实际命令、工具版本与输入记录](logs/c611aead474d4b8fa96906fb00bd1771/check.json)
执行边界：Single goroutine Peer network with real constructors and handlers, captured TestLogDB and deterministic loss of first-context heartbeats.；Replaces asynchronous engine/transport with a synchronous persist-before-send Peer driver and FIFO queue; protocol logic is unchanged.；Uses captured TestLogDB and applies only initialization config/no-op entries; excludes crash durability and user application execution.
固定比较 `K-read-prefix`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | remote_prefix | remote_prefix |
| requester | 2 | 3 |
| released | true | true |
| actual_contexts | [{"Low":2001,"High":202}] | [{"Low":2001,"High":202}] |
| admit.expected_contexts | [{"Low":1001,"High":101}] | [{"Low":2001,"High":202}] |
| admit.queued | true | true |
| admit.current_term_committed | true | true |
| admit.pending_count | 2 | 2 |
| admit.dropped_heartbeats | 2 | 2 |
| applied | 4 | 4 |
| event | publication | publication |
| leader_pending | 0 | 0 |
| queue_empty | true | true |
| response_count | 1 | 1 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Node batches proposals into Peer under raftMu. Leader stamps term/index, replicates to members and advances commitment from voting match order statistic only for its current term. Followers require preceding term match…
- 上下文／权威转换（原文导航摘录）：Per-cluster term, role and applied membership define authority. Timers launch elections for eligible full members only after committed work is applied; votes require fresh log and no conflicting vote. Candidate quorum…
- 两条主线的连接（原文导航摘录）：Term dispatch precedes response consumption. Reset clears old votes, replication progress and pending ReadIndex support while retaining established log/commit; leader must form current-term commitment before multi-voter…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.51 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.08 分钟 · 受理 obligation：Contract/test investigation grounds a local read-result identity obligation. Transport admission failure permits loss of initial…。[完整交接](submissions/9e29fa36d4a34291a0dc756a63c7c005/accepted.json)

- 12.46 分钟 · 受理 check：The obligation is grounded and the remaining discriminator is actual remote context publication after a legal prefix-confirmation history.…。[完整交接](submissions/e14d4e7688b5402a93214d2d9d0b7de5/accepted.json)

- 12.72 分钟 · 实际执行：批量确认读取时，早期远端请求收到后一个请求的上下文；执行完成；比较见 assessment。[执行记录](logs/c611aead474d4b8fa96906fb00bd1771/check.json)

- 15.23 分钟 · 受理 review：批量确认读取时，早期远端请求收到后一个请求的上下文；v1 checker_correspondence: no_issue_found。[完整交接](submissions/d2973c7ab6594d2287c3fda91eef1f07/accepted.json)

- 18.81 分钟 · 受理 continue：Reselect the concrete snapshot-publication authority premise after the read correlation finding is confirmed. Save the answered read…。[完整交接](submissions/717ad2698de9484b8a54ccb198dbe922/accepted.json)

- 22.50 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/5f009c9ffe364b7c8e5d864e37372650/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [fca709e34cb341ed91ba6cf309a4f445](research.json)：[候选 1](#candidate-fca709e34cb341ed91ba6cf309a4f445)

<a id="candidate-fca709e34cb341ed91ba6cf309a4f445"></a>

研究中问题：Can an initialized node consume a snapshot-published lastApplied and campaign using its old Peer membership before the snapshot RestoreRemotes callback installs the corresponding participants?
[候选原文与历史](state.json)
保存的语义未知：Does an actual allowed schedule reach election processing after snapshot-visible index publication but before membership restoration?；What minimal valid snapshot/log history demonstrates a changed electorate without bypassing snapshot acceptance or caller duties?

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Pending read confirmation eligibility across membership transitions；Concrete LogDB crash guarantees and snapshot transport；Snapshot applied-index publication versus Peer membership restoration and…
  尚无精确对应交接。

- B-replicate：Witness metadata replication and snapshot-flow variants remain only partly read
  尚无精确对应交接。

- B-authority：Quiescence timing variants and all removal-in-flight cases remain open
  相关交接：[交接 1](submissions/717ad2698de9484b8a54ccb198dbe922/accepted.json)

- B-read-admit：Single-voter remote-request variants have not been fully investigated
  尚无精确对应交接。

- B-read-confirm：Eligibility of already-recorded confirmations across membership changes is not established
  相关交接：[交接 1](submissions/9e29fa36d4a34291a0dc756a63c7c005/accepted.json)；[交接 2](submissions/d2973c7ab6594d2287c3fda91eef1f07/accepted.json)；[交接 3](submissions/717ad2698de9484b8a54ccb198dbe922/accepted.json)

- B-persist：Concrete LogDB crash atomicity and filesystem fault behavior remain unread
  尚无精确对应交接。

- B-apply：Application-provided durability and on-disk recovery variants need separate contract review
  相关交接：[交接 1](submissions/717ad2698de9484b8a54ccb198dbe922/accepted.json)

- B-members：Full membership validation conditions and overlap with pending read confirmations remain open
  尚无精确对应交接。

- B-recovery：Snapshot transport, file validation and on-disk initialization corner cases remain unmapped；Can an initialized node step/elect with snapshot-visible lastApplied but old Peer membership before…
  相关交接：[交接 1](submissions/717ad2698de9484b8a54ccb198dbe922/accepted.json)

- F-committed：Storage crash behavior below LogDB has not been reviewed
  尚无精确对应交接。

- F-read-pending：Whether membership changes invalidate retained confirmations
  相关交接：[交接 1](submissions/d2973c7ab6594d2287c3fda91eef1f07/accepted.json)

- F-visible-applied：Whether step scheduling can consume the snapshot-visible index while Peer membership is still stale
  尚无精确对应交接。

- surface:raft.handleLeaderHeartbeatResp / membership transitions：Read-support producer/eligibility across changes needs composed history, not fabricated observer replies.
  尚无精确对应交接。

- surface:LogDB SaveRaftState / snapshot transport：Core call ordering read; backend atomicity and transferred-file validation not yet traced.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1049.80 秒、33 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1350.20 | 1049.80 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 14.59 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 15.98 秒。

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v55`；展示版本 `audit-products-v55`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/5f009c9ffe364b7c8e5d864e37372650/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/5f009c9ffe364b7c8e5d864e37372650/check.json)；[stdout](logs/5f009c9ffe364b7c8e5d864e37372650/stdout.log)；[stderr](logs/5f009c9ffe364b7c8e5d864e37372650/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

