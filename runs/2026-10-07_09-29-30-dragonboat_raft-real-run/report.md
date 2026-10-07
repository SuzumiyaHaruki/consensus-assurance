# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**；实际持续 **19.36 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 远程读批量确认返回了后续请求的上下文 | 已确认违反 | 同一任期内，节点 2 的请求上下文为 1101:30；后续请求确认后，节点 2 却收到 2202:30，且原请求已从领导者待处理队列移除。测试正常结束，验证的是本地响应关联错误，未测量客户端超时或线性一致性后果。 | [O-read-response-identity](#claim-O-read-response-identity) |

<a id="claim-O-read-response-identity"></a>

### 1. 远程读批量确认返回了后续请求的上下文

**已确认违反**。要求原文：When the leader consumes and removes a pending remote ReadIndex request as part of a quorum-confirmed prefix, it must emit the corresponding ReadIndexResp to that request origin carrying that request SystemCtx unchanged. Releasing several requests together may raise their index but must not substitute another released request context.

决定性范围：Local read-barrier response correlation for distinct, concurrently pending remote requests in a stable leader term and fixed voting membership, after current-term commitment and valid quorum confirmation.
Non-Byzantine peers and genuine response messages from contextual heartbeats；Distinct nonzero request contexts remain associated with their originating requests；Caller honors Peer update persistence/Commit and local applied-index duties。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/ac18a66f79e348dd9c65c8b1e40c795e/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/ac18a66f79e348dd9c65c8b1e40c795e/plan.json)；[原始观察](logs/ff815776b2a84273941ca361e91f3c49/stdout.log)；[assessment](direct-checks/ac18a66f79e348dd9c65c8b1e40c795e/ff815776b2a84273941ca361e91f3c49-assessment.json)；[对应性复核](submissions/7e7ad2562354446f9d6030e14738ec62/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 13.24 秒；执行进程耗时 12.76 秒；[实际命令、工具版本与输入记录](logs/ff815776b2a84273941ca361e91f3c49/check.json)
执行边界：Three real Peers, test LogDB, bootstrap/election/persistence/application handoffs, then fixed selective heartbeat loss and FIFO delivery; inspect admitted statuses and resulting messages/readiness.；No target code changed. Memory storage is used without crashes; deterministic transport send-loss policy and abstract bootstrap/noop application replace outer layers.；All observations occur synchronously between calls; no concurrency, sleeps, termination or private protocol state injection.
固定比较 `check-read-identity`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | remote_prefix | remote_prefix |
| origin | 2 | 3 |
| released | true | true |
| response_signature | 2:2202:30 | 3:2202:30 |
| admission.expected_response | 2:1101:30 | 3:2202:30 |
| admission.pending | true | true |
| admission.current_term_committed | true | true |
| admission.overlap_count | 2 | 2 |
| admission.lost_earlier_heartbeats | 2 | 2 |
| event | result | result |
| ready_contexts | 2202:30 | 2202:30 |
| remaining_pending | 0 | 0 |
| remaining_queue | 0 | 0 |
| response_count | 1 | 1 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Node step owns raft under raftMu. Leader proposals acquire term/index and replicate; followers match predecessor and refuse committed-history conflicts. Eligible full-member/witness acknowledgments update match…
- 上下文／权威转换（原文导航摘录）：Election ticks on eligible full nodes trigger campaigns unless committed work remains unapplied. Candidate increments term and votes for self; vote grant compares log freshness and prior vote; responses are…
- 两条主线的连接（原文导航摘录）：Term/role reset discards votes, remote replication progress and pending leader read confirmations while retaining committed log history. Subsequent leaders reconstruct pending configuration status and establish…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.62 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.80 分钟 · 受理 obligation：Fix the local identity-preservation responsibility using existing end-to-end read-context and prefix-release test expectations; source…。[完整交接](submissions/822ca4d8a3c843ce90599180b9826ebc/accepted.json)

- 11.74 分钟 · 受理 check：Execute fixed legal overlap through public Peer inputs and genuine protocol outputs. The expected relation comes from admitted request…。[完整交接](submissions/ac18a66f79e348dd9c65c8b1e40c795e/accepted.json)

- 11.96 分钟 · 实际执行：远程读批量确认返回了后续请求的上下文；执行完成；比较见 assessment。[执行记录](logs/ff815776b2a84273941ca361e91f3c49/check.json)

- 14.31 分钟 · 受理 review：远程读批量确认返回了后续请求的上下文；v1 checker_correspondence: no_issue_found。[完整交接](submissions/7e7ad2562354446f9d6030e14738ec62/accepted.json)

- 18.79 分钟 · 受理 research：Retain the answered configuration-publication concern and source-only snapshot continuation ownership, while removing obsolete unknowns for…。[完整交接](submissions/7c60478988d945fbbefb0ebb39b51edc/accepted.json)

- 19.36 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/8fadbc8ecca34d0aa0d62606ec5f0b43/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Transport buffering/failure ordering, backend durability, snapshot abort and overlapping status details, and state-machine session deduplication remain open.
  尚无精确对应交接。

- B-client-read：End-to-end client symptom for remote prefix release awaits execution; local timeout is not an infinite-stall observation
  尚无精确对应交接。

- B-config：Configuration variants beyond the traced accepted-entry callback remain open; external applied-index publication follows callback completion.
  相关交接：[交接 1](submissions/7c60478988d945fbbefb0ebb39b51edc/accepted.json)

- B-storage：LogDB backend durability implementation and crash atomicity remain unread
  尚无精确对应交接。

- B-recovery：Snapshot transfer retries and abort scheduling details remain open
  尚无精确对应交接。

- B-apply：State machine session deduplication internals and all application variants remain unread
  相关交接：[交接 1](submissions/7c60478988d945fbbefb0ebb39b51edc/accepted.json)

- F-commit：Backend crash consistency not inspected
  尚无精确对应交接。

- surface:LogDB.SaveRaftState：Engine ordering read; backend atomicity/durability not yet traced.
  尚无精确对应交接。

- surface:StateMachine session handling：Proposal completion callback read; deduplication and replay semantics require further source work.
  尚无精确对应交接。

- surface:StateMachine.stream / Transport.processSnapshot：Status producers and retry consumers traced; preparation error/shutdown ownership and overlapping transfer status identity need deeper history work before alleging lost continuation.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 638.28 秒、33 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1161.72 | 638.28 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 12.76 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 13.24 秒。

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/8fadbc8ecca34d0aa0d62606ec5f0b43/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`671.9918951139998`（配置值不表示触发了超时）。
[调用记录](logs/8fadbc8ecca34d0aa0d62606ec5f0b43/check.json)；[stdout](logs/8fadbc8ecca34d0aa0d62606ec5f0b43/stdout.log)；[stderr](logs/8fadbc8ecca34d0aa0d62606ec5f0b43/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

