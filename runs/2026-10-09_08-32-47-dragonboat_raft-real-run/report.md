# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**；实际持续 **14.71 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. When a leader emits a ReadIndexResp for an originating remote request completed by readIndex confirmation, the response must…（原文摘录） | 检查未执行到比较 | 观察／关联尚不完整；执行 status=completed，exit=0：read-context：Event 30 {'scenario': 'coalesced_distinct_origins', 'origin': 2}: Ambiguous prerequisite…；[完整评估与原因](direct-checks/976474d08e59404987e1a2775bca3ed0/66730efdcb704bff91a0cf177ee505d2-assessment.json) | [read-reply-context-preservation](#claim-read-reply-context-preservation) |

<a id="claim-read-reply-context-preservation"></a>

### 1. When a leader emits a ReadIndexResp for an originating remote request completed by readIndex confirmation, the response must…（原文摘录）

**检查未执行到比较**。要求原文：When a leader emits a ReadIndexResp for an originating remote request completed by readIndex confirmation, the response must carry that request's original SystemCtx, including when confirmation completes multiple queued requests at once.

决定性范围：Request-identity preservation in the remote ReadIndex confirmation handoff.
CFT message loss is permitted; surviving messages follow their transport order.；Distinct context values identify pending read batches in the same stable leader term.；Each observed destination has one outstanding read in the fixed scenario, allowing independent origin-based attribution.。

[完整要求、假设与排除范围](state.json)

制品 v1；检查未执行到比较；对应性意见：尚未记录；场景比较完整：False；独立场景完整处置：False。
[固定测试](direct-checks/976474d08e59404987e1a2775bca3ed0/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/976474d08e59404987e1a2775bca3ed0/plan.json)；[原始观察](logs/66730efdcb704bff91a0cf177ee505d2/stdout.log)；[assessment](direct-checks/976474d08e59404987e1a2775bca3ed0/66730efdcb704bff91a0cf177ee505d2-assessment.json)

当前争议／阻塞：观察／关联尚不完整；执行 status=completed，exit=0：read-context：Event 30 {'scenario': 'coalesced_distinct_origins', 'origin': 2}: Ambiguous prerequisite…；[完整评估与阻塞](direct-checks/976474d08e59404987e1a2775bca3ed0/66730efdcb704bff91a0cf177ee505d2-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 13.72 秒；执行进程耗时 12.66 秒；[实际命令、工具版本与输入记录](logs/66730efdcb704bff91a0cf177ee505d2/check.json)
执行边界：Single-goroutine Peer Update/persistence/message scheduler; TestAssuranceForwardedReadContext.；Replaces actual networking and disk I/O with a deterministic FIFO message queue and the existing TestLogDB; executes unchanged Peer and raft code.；Observes private queue state only for admission prerequisites; reads output after synchronous ownership returns.；No production source, predicates or protocol state transitions are modified.
固定比较 `read-context`：结果未确定；已比较 0 项，完整见证 0 项，缺失 4 项。

观察缺口：Event 30 {'scenario': 'coalesced_distinct_origins', 'origin': 2}: Ambiguous prerequisite association; missing setup.origin；Event 31 {'scenario': 'coalesced_distinct_origins', 'origin': 3}: Ambiguous prerequisite association; missing setup.origin；Event 25 {'scenario': 'coalesced_distinct_origins', 'origin': 2}: Operation admission history: Ambiguous prerequisite association; missing setup.origin；Event 26 {'scenario': 'coalesced_distinct_origins', 'origin': 3}: Operation admission history: Ambiguous prerequisite association; missing setup.origin

| 记录字段 | 观察 1（未完成） | 观察 2（未完成） | 观察 3（未完成） | 观察 4（未完成） |
| --- | --- | --- | --- | --- |
| scenario | coalesced_distinct_origins | coalesced_distinct_origins | coalesced_distinct_origins | coalesced_distinct_origins |
| origin | 2 | 3 | 2 | 3 |
| event | read_admitted | read_admitted | read_reply | read_reply |
| actual_context | 未记录 | 未记录 | 202:30 | 202:30 |
| admitted.expected_context | 未记录 | 未记录 | 未记录 | 未记录 |
| setup.scenario | 未记录 | 未记录 | 未记录 | 未记录 |
| setup.term | 未记录 | 未记录 | 未记录 | 未记录 |
| setup.all_applied | 未记录 | 未记录 | 未记录 | 未记录 |
| setup.queue_empty | 未记录 | 未记录 | 未记录 | 未记录 |
| admitted.scenario | 未记录 | 未记录 | 未记录 | 未记录 |
| admitted.term | 未记录 | 未记录 | 未记录 | 未记录 |
| admitted.pending | 未记录 | 未记录 | 未记录 | 未记录 |
| admitted.dropped_first_replies | 未记录 | 未记录 | 未记录 | 未记录 |
| dropped_first_replies | 2 | 2 | 未记录 | 未记录 |
| expected_context | 101:30 | 202:30 | 未记录 | 未记录 |
| pending | 2 | 2 | 未记录 | 未记录 |
| term | 2 | 2 | 2 | 2 |
| applied | 未记录 | 未记录 | 4 | 4 |
| pending_after | 未记录 | 未记录 | 0 | 0 |
| received_context | 未记录 | 未记录 | 202:30 | 202:30 |
| received_index | 未记录 | 未记录 | 4 | 4 |
| reply_index | 未记录 | 未记录 | 4 | 4 |

前提关联：观察 1 → 未记录；观察 2 → 未记录；观察 3 → unknown；观察 4 → unknown。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns term/index to proposals and counts voting remotes/witnesses match positions. A current-term quorum index advances commit; follower predecessor checks and bounded commit propagation protect the accepted…
- 上下文／权威转换（原文导航摘录）：Ticks initiate elections for eligible full members only after committed work is applied. Vote freshness and one-vote state constrain authority acquisition. Higher terms, quorum loss and self-removal change authority;…
- 两条主线的连接（原文导航摘录）：Authority transitions discard volatile support rather than the decided log prefix. A new leader reconstructs progress and pending configuration state and appends a current-term no-op before multi-voter read admission…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.19 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 13.38 分钟 · 受理 check：Submit the local identity duty with a fixed overlapping Peer history and exact response-context comparison.。[完整交接](submissions/976474d08e59404987e1a2775bca3ed0/accepted.json)

- 13.60 分钟 · 实际执行：检查未执行到比较；对应性意见：尚未记录；执行完成；比较见 assessment。[执行记录](logs/66730efdcb704bff91a0cf177ee505d2/check.json)

- 14.71 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/bae52af56659489d9dede4d331abe6b8/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-read-reply-context-preservation](research.json)：[read-reply-context-preservation](#claim-read-reply-context-preservation)；具体进度与缺口见对应义务

<a id="candidate-e0f6fd3b448d483ca9044eaa0191f64a"></a>

研究中问题：When one heartbeat confirmation completes a prefix containing multiple forwarded ReadIndex requests, does each emitted ReadIndexResp preserve the original completed request SystemCtx so the origin can correlate it?
[候选原文与历史](state.json)
保存的语义未知：The fixed clean-copy execution must establish the overlapping admission and record each actual response context; semantic correspondence remains pending.

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Forwarded coalesced-read context preservation remains a concrete suspicion, with no execution yet.；Detailed transport admission/order, storage backend durability, membership validation and recovery…
  尚无精确对应交接。

- b-read-confirm：Whether batching multiple forwarded reads loses earlier identity in a complete legal message history; local and single-status paths are counterevidence to a universal failure.
  尚无精确对应交接。

- b-read-client：No numeric successful-read deadline is inferred from the API timeout; a context-loss witness should target local correlation rather than assert unbounded liveness.
  尚无精确对应交接。

- b-membership：Detailed membership validation and ordered-change rejection contracts remain unread.
  尚无精确对应交接。

- b-history：Storage backend atomicity, full fast-apply ordering and crash windows remain outside the current source trace.
  尚无精确对应交接。

- b-recovery：Snapshot transport durability and asynchronous recovery failure paths remain to be traced.
  尚无精确对应交接。

- b-consumption：Session deduplication and all state-machine execution variants remain unread.
  尚无精确对应交接。

- f-confirmed-read：Whether the remote reply encoder preserves each returned status identity for coalesced requests.
  尚无精确对应交接。

- surface:raft.handleCandidateRequestVoteResp：The handler excludes observers but does not locally require membership for all other senders. Producer, transport admission and legal delayed replies need tracing before any eligibility allegation.
  尚无精确对应交接。

- surface:raft.handleLeaderHeartbeatResp：The common remote wrapper includes observers while normal read-confirmation heartbeats target voting members. Qualification depends on the producer and membership history, which is not yet traced for…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 917.39 秒、37 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 882.61 | 917.39 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 12.66 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 13.72 秒。

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/bae52af56659489d9dede4d331abe6b8/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/bae52af56659489d9dede4d331abe6b8/check.json)；[stdout](logs/bae52af56659489d9dede4d331abe6b8/stdout.log)；[stderr](logs/bae52af56659489d9dede4d331abe6b8/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

