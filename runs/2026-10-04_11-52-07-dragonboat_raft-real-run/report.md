# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。已产生观察的正式结论 1 项：已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **19.69 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1218.81 秒、34 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1181.19 | 1218.81 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v47`；展示版本 `audit-products-v47`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/7294880c2bcc4151b72cde3a29c839a0/check.json)；[stdout](logs/7294880c2bcc4151b72cde3a29c839a0/stdout.log)；[stderr](logs/7294880c2bcc4151b72cde3a29c839a0/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 合并读确认时，较早远端请求的上下文被替换 | 已确认违反 | 三节点同一任期内，较晚请求的心跳确认释放两个远端读请求；节点 2 原上下文为 201/2001，实际响应及 ReadyToRead 均携带节点 3 的 202/2002。单请求对照保持原上下文；此结果仅证明响应关联错误，不证明陈旧读取或无限停滞。 | [C-read-context](#claim-C-read-context) |

<a id="claim-C-read-context"></a>

### 1. 合并读确认时，较早远端请求的上下文被替换

**已确认违反**。要求原文：When the leader releases an admitted forwarded ReadIndex request after quorum confirmation, the ReadIndexResp sent to its requester must carry that released request's SystemCtx unchanged, so the requester can associate ReadyToRead with the same operation. Coalesced confirmation may raise the read index but must not replace an earlier request's context with another request's context.

决定性范围：Per-operation response correlation for released forwarded requests within a stable leader term and membership after a current-term entry is committed.
Distinct nonzero SystemCtx values identify independently admitted requests.；Requests and quorum acknowledgements originate from the actual Peer handlers in one controlled history.；Non-Byzantine members; a delayed earlier response may overlap later traffic; no crash or membership change during the selected history.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e03642c1801746c7b24a03fc1dc1d643/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/e03642c1801746c7b24a03fc1dc1d643/plan.json)；[原始观察](logs/88621c84c65e4fc48ac49425d0866bff/stdout.log)；[assessment](direct-checks/e03642c1801746c7b24a03fc1dc1d643/88621c84c65e4fc48ac49425d0866bff-assessment.json)；[对应性复核](submissions/f2d220d525ca42da8c03e381f3faef15/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/88621c84c65e4fc48ac49425d0866bff/check.json)
执行边界：TestAssuranceForwardedReadContexts uses Peer.Launch/Tick/ReadIndex/Handle/GetUpdate/Commit with existing TestLogDB and synchronous update processing.；Replace transport with a deterministic queue delivering actual generated messages.；Use existing volatile TestLogDB instead of production disk backend, with no crash/restart.；Synchronously consume committed bootstrap and noop entries; no application query or NodeHost endpoint is measured.；Read private state only to verify setup/admission and report pending-count diagnostics.
固定比较 `K-read-context`：观察到违反；已比较 3 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） | 观察 3 |
| --- | --- | --- | --- |
| scenario | single | overlap | overlap |
| requester | 2 | 2 | 3 |
| observed | true | true | true |
| context | 101/1001 | 202/2002 | 202/2002 |
| admit.expected_context | 101/1001 | 201/2001 | 202/2002 |
| admit.admitted | true | true | true |
| event | response | response | response |
| index | 4 | 4 | 4 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns indexes/term, replicates entries, consumes term-qualified member responses, and commits a quorum index only if its log term is current. Followers require predecessor agreement and never replace…
- 上下文／权威转换（原文导航摘录）：Ticks initiate elections for eligible regular members; log freshness and one-vote rules qualify support. Candidate votes are deduplicated; peer admission excludes unknown response senders and candidate handling excludes…
- 两条主线的连接（原文导航摘录）：New leaders retain prior log decisions but reset replication accounting, scan pending configuration work and append a current-term noop. Current-term commitment gates multi-node read confirmation.…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.95 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 12.28 分钟 · 受理 obligation：Fix the sourced per-operation correlation responsibility before executing a history. The oracle will use independent requester identity and…。[完整交接](submissions/632c06feaedc4e41aa1e17476b7ca2ee/accepted.json)

- 15.63 分钟 · 受理 check：Execute the fixed remote-prefix correlation discriminator with generated producer history, independent operation correlation, and a…。[完整交接](submissions/e03642c1801746c7b24a03fc1dc1d643/accepted.json)

- 15.88 分钟 · 实际执行：合并读确认时，较早远端请求的上下文被替换；执行完成；比较见 assessment。[执行记录](logs/88621c84c65e4fc48ac49425d0866bff/check.json)

- 18.30 分钟 · 受理 review：合并读确认时，较早远端请求的上下文被替换。[完整交接](submissions/f2d220d525ca42da8c03e381f3faef15/accepted.json)

- 19.68 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/7294880c2bcc4151b72cde3a29c839a0/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Remote read-prefix responses use triggering context rather than each released context; legal overlap and responsibility need a fixed investigation.；Storage backend crash behavior, snapshot transfer…
  尚无精确对应交接。

- B-read-confirm：Can remote prefix release lose per-request context in a complete legal overlapping history?
  相关交接：[交接 1](submissions/f2d220d525ca42da8c03e381f3faef15/accepted.json)

- B-membership：Detailed admission and ordering options for all reconfiguration histories remain open.
  尚无精确对应交接。

- B-persistence：Specific backend crash atomicity and on-disk state-machine durability remain unexamined.
  尚无精确对应交接。

- B-recovery：Snapshot transport failures, asynchronous cancellation and disk-specific recovery variants remain open.
  尚无精确对应交接。

- B-apply：Session deduplication, batch apply and disk state-machine variants not yet fully traced.
  尚无精确对应交接。

- surface:engine.SaveRaftState backend and snapshot transport：What concrete backend and transport failure contracts preserve recovered support?
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
