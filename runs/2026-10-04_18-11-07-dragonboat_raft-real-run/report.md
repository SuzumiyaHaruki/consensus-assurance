# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 2 项。正式执行尝试 2 次；已保存评估的义务 2 项，其中有实际比较 2 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **35.99 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 240.65 秒、32 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2159.35 | 240.65 |
| Agent 调用 | 40 | 8 | 32 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 28.77 秒。

目标动作总耗时（含已记录的准备与复制）：未记录有效总量；2 项未完整记录，合计不完整。

目标执行组成：正式检查 2 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v49`；展示版本 `audit-products-v49`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`353.74746204900293`（配置值不表示触发了超时）。
[调用记录](logs/8cc87645ebd14fd8bbf78de3945ea941/check.json)；[stdout](logs/8cc87645ebd14fd8bbf78de3945ea941/stdout.log)；[stderr](logs/8cc87645ebd14fd8bbf78de3945ea941/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 远端 ReadIndex 批量确认替换了较早请求的标识 | 已确认违反 | 三节点、固定任期与成员配置下，节点 2 的请求以 301:101 注册并获确认，但其收到的响应及 ReadyToRead 均为节点 3 的 302:202。检查验证的是 Peer 层操作标识传播错误；未执行客户端超时或应用层陈旧读。 | [C-read-context](#claim-C-read-context) |
| 2. When an unaligned batched-log append needs a previously persisted prefix after a cache miss, can a KV read error be treated as…（原文摘录） | 待调查线索 | 机械比较：观察到违反；对应性意见：尚未记录；原因摘录：Direct oracle correspondence is unreviewed；[完整评估与原因](direct-checks/daa3cdee65e44f2089392448006c6c93/838c7c95d62547dc9e2a81917a772eba-assessment.json) | [C-batch-prefix](#claim-C-batch-prefix) |

<a id="claim-C-read-context"></a>

### 1. 远端 ReadIndex 批量确认替换了较早请求的标识

**已确认违反**。要求原文：For a remotely initiated ReadIndex operation registered under a distinct SystemCtx and included in a successfully confirmed pending prefix, propagation of its readiness to the originating peer must preserve that operation's SystemCtx. A later context may supply confirmation for earlier requests, but must not substitute its identity for theirs.

决定性范围：ReadIndex request-to-readiness identity preservation across stable-term, fixed-membership leader prefix confirmation and remote response delivery.
Crash-free non-Byzantine peers and unmodified messages; asynchronous delivery may delay earlier heartbeat replies.；Distinct nonzero contexts, one outstanding operation per remote origin, current-term leader commitment, and successful prefix confirmation.；Consumer is Peer.GetUpdate ReadyToReads; no application read result is claimed.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/db287f8d6f7b436bbd5ecb7be6b29f15/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/db287f8d6f7b436bbd5ecb7be6b29f15/plan.json)；[原始观察](logs/b5f3cb2c346040a9b22ca064ee24a691/stdout.log)；[assessment](direct-checks/db287f8d6f7b436bbd5ecb7be6b29f15/b5f3cb2c346040a9b22ca064ee24a691-assessment.json)；[对应性复核](submissions/a7ee26f8807941869a9ff8c30bd9a139/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 13.96 秒；[实际命令、工具版本与输入记录](logs/b5f3cb2c346040a9b22ca064ee24a691/check.json)
执行边界：Crash-free Peer-level network using real Handle/ReadIndex/Tick/GetUpdate/Commit and existing in-memory TestLogDB. Only two fixed read contexts and delivery policy are injected.；No target code or protocol state mutation. Package-local reads observe live registration, term, commit, queue removal and status index.；Memory-backed TestLogDB substitutes durable storage under a no-crash scope; production transport and RSM scheduling replaced by synchronous update processing.；Bootstrap configuration entries are accepted through Peer.ApplyConfigChange; the harness verifies all are Initialize/AddNode. No later configuration change or application command occurs.；Only node 1 clock advances for election; no ticks during finite read-message schedule. All messages are genuine outputs and delivered unchanged, with earlier-context replies delayed then released.；Request contexts are fixed legal distinct nonzero values instead of node random generation; the contract treats them as opaque operation identifiers.
固定比较 `CK-read-context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | remote_prefix | remote_prefix |
| origin | 2 | 3 |
| event | read_ready | read_ready |
| context | 302:202 | 302:202 |
| admitted.context | 301:101 | 302:202 |
| admitted.term | 2 | 2 |
| confirmed.context | 301:101 | 302:202 |
| confirmed.term | 2 | 2 |
| applied | 4 | 4 |
| index | 4 | 4 |
| phase | reads | reads |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


<a id="claim-C-batch-prefix"></a>

### 2. When an unaligned batched-log append needs a previously persisted prefix after a cache miss, can a KV read error be treated as…（原文摘录）

**待调查线索**。要求原文：If saving a strictly appended log suffix reports success, previously successfully persisted entries preceding that suffix must remain intact unless explicitly removed by a snapshot or compaction operation. A failed lookup of their existing batch must not turn a successful append into implicit prefix deletion.

决定性范围：Batched LogDB shard storage preservation across an unaligned append after close/reopen with one reported non-not-found KV lookup error.
Earlier entries were successfully saved and verified after reopening the same backend.；Incoming entry 4 strictly follows existing entries 1 through 3 within one batch; there is no snapshot, truncation request, compaction or concurrent writer.；The single read fault returns an error before invoking the GetValue callback and does not change stored bytes; subsequent backend calls operate normally.；The implication is conditioned on saveRaftState returning nil; a returned error does not violate this success-conditioned property.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/daa3cdee65e44f2089392448006c6c93/internal/logdb/assurance_generated_test.go)；[条件与检查器](direct-checks/daa3cdee65e44f2089392448006c6c93/plan.json)；[原始观察](logs/838c7c95d62547dc9e2a81917a772eba/stdout.log)；[assessment](direct-checks/daa3cdee65e44f2089392448006c6c93/838c7c95d62547dc9e2a81917a772eba-assessment.json)

当前争议／阻塞：Direct oracle correspondence is unreviewed；[完整评估与阻塞](direct-checks/daa3cdee65e44f2089392448006c6c93/838c7c95d62547dc9e2a81917a772eba-assessment.json)

固定执行包 `./internal/logdb`；主文件 `internal/logdb/assurance_generated_test.go`；目标动作总耗时未完整记录；执行进程耗时 14.80 秒；[实际命令、工具版本与输入记录](logs/838c7c95d62547dc9e2a81917a772eba/check.json)
执行边界：Real shard save, batching and default backend in a temporary directory with a one-shot IKVStore read-error adapter. No target state or backend bytes are edited.；Direct db.saveRaftState entry bypasses ShardedDB partition routing and the Raft engine; one cluster/node and sequential calls make those scheduling duties explicit.；Factory wraps real default KV backend only to return one non-not-found error for the selected entry-batch lookup; actual filesystem fault production is substituted, not claimed.；A real close/reopen produces the cache miss. Observations decode actual stored bytes through GetValue and restoreBatchFields; they do not use the merge cache.；Single-thread contexts are reset before saving and destroyed before closing each database. The same database directory is reopened, resources are closed and temporary storage cleaned by testing.；No crash, concurrent write, snapshot or compaction is introduced. Entry commands and fixed indexes are ordinary pb.Update inputs.
固定比较 `CK-batch-prefix`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | cold-append-4 |
| cluster | 11 |
| node | 1 |
| event | append_observed |
| success | true |
| prefix | [] |
| admitted.prefix | [{"index":1,"term":1,"cmd":"one"},{"index":2,"term":1,"cmd":"two"},{"index":3,"term":1,"cmd":"three"}] |
| admitted.policy | one-read-error |
| admitted.cold_cache | true |
| faulted.policy | one-read-error |
| returned_error |  |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：Node/Peer proposals reach the leader, which appends current-term entries and sends predecessor-qualified replication. Followers reject mismatching prefixes or append matching entries, protect committed history and…
- 上下文／权威转换（原文导航摘录）：Election ticks on eligible full members trigger term increment and self-vote. Vote grants require vote eligibility and log freshness; known response admission and unique sender counting qualify election support.…
- 两条主线的连接（原文导航摘录）：Only support qualified by current term/role and current membership advances formation; remote progress is rebuilt on authority reset while committed log history constrains future leaders through freshness and prefix…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.00 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 13.39 分钟 · 实际执行：远端 ReadIndex 批量确认替换了较早请求的标识；执行完成；比较见 assessment。[执行记录](logs/b5f3cb2c346040a9b22ca064ee24a691/check.json)

- 15.92 分钟 · 受理 review：远端 ReadIndex 批量确认替换了较早请求的标识。[完整交接](submissions/a7ee26f8807941869a9ff8c30bd9a139/accepted.json)

- 20.64 分钟 · 受理 research：Incorporate the accepted scoped finding and investigation of composed membership/application protections; retain a precise result-buffer…。[完整交接](submissions/8c67f1f1b8f04030b7c320f25f45a4a2/accepted.json)

- 27.87 分钟 · 受理 continue：Select the sourced cold-cache error-handling discrepancy in persisted history rather than presume a contract for arbitrary result-buffer…。[完整交接](submissions/84f1a585f9104d09a1a20e57bd31b402/accepted.json)

- 33.81 分钟 · 受理 check：Exercise the accepted cold-cache discriminator using actual saved bytes and one reported read error; permit proper error propagation and…。[完整交接](submissions/daa3cdee65e44f2089392448006c6c93/accepted.json)

- 34.07 分钟 · 实际执行：When an unaligned batched-log append needs a previously persisted prefix after a cache miss, can a KV read error be treated as…（原文摘录）；执行完成；比较见 assessment。[执行记录](logs/838c7c95d62547dc9e2a81917a772eba/check.json)

- 35.97 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/8cc87645ebd14fd8bbf78de3945ea941/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-C-batch-prefix](research.json)：[C-batch-prefix](#claim-C-batch-prefix)；具体进度与缺口见对应义务

<a id="candidate-1ef7ca38c73f47a492bf1072229cef0a"></a>

研究中问题：When an unaligned batched-log append needs a previously persisted prefix after a cache miss, can a KV read error be treated as absence and cause a successful write to discard that prefix?
[候选原文与历史](state.json)

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：Remote confirmed-prefix response emission uses the triggering context for earlier remote requests; NodeHost client and application consequences remain outside the checked endpoint.；Pending…
  尚无精确对应交接。

- B-membership：Pending readIndex confirmation maps are not explicitly pruned on removal; the applicability of retained support requires accounting for read invocation, prior configuration commitment and subsequent…
  相关交接：[交接 1](submissions/8c67f1f1b8f04030b7c320f25f45a4a2/accepted.json)

- B-persistence：Specific logdb crash/atomicity behavior and FastApply variants remain untraced.
  尚无精确对应交接。

- B-apply：Ownership and mutation constraints for Result.Data shared between session history and client-visible results remain unclear.；On-disk state-machine session bypass and recovery variants need deeper…
  相关交接：[交接 1](submissions/8c67f1f1b8f04030b7c320f25f45a4a2/accepted.json)

- B-read-client：End-to-end timeout and retry consequences of response-context mismatch remain unexecuted.
  尚无精确对应交接。

- B-batch-merge：Does a reported KV read error during a cache-miss merge permit a successful append that overwrites a previously persisted prefix?
  尚无精确对应交接。

- surface:raft.handleNodeConfigChange/readIndex.confirm：Determine whether retained confirmations across legal configuration changes violate an applicable authority condition after accounting for configuration commitment timing and permitted earlier…
  尚无精确对应交接。

- surface:StateMachine.update -> Session.addResponse -> RequestResult.GetResult：Result.Data is a slice stored in session history and returned by value through completion; determine who owns its backing bytes and whether legal application/client reuse can change replay or…
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
