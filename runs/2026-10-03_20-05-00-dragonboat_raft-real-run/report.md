# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。已产生观察的正式结论 1 项：已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **20.32 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1180.88 秒、33 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1219.12 | 1180.88 |
| Agent 调用 | 40 | 7 | 33 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 1 | 5 |

目标执行组成：正式检查 2 次＋探索 0 次，其中失败／未完成 1 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v45`；展示版本 `audit-products-v45`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/43d64e393205405482d20920e7f31820/check.json)；[stdout](logs/43d64e393205405482d20920e7f31820/stdout.log)；[stderr](logs/43d64e393205405482d20920e7f31820/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 重叠转发读取的响应标识被替换 | 已确认违反 | 在固定任期和三投票成员下，后一个读取的心跳确认释放两个请求时，节点 2 请求的 901:201 被返回为节点 3 的 902:302。串行对照正常；已观察到 Peer 层标识不匹配，未证明应用读取过期或客户端无限等待。 | [claim-read-context](#claim-claim-read-context) |

<a id="claim-claim-read-context"></a>

### 1. 重叠转发读取的响应标识被替换

**已确认违反**。要求原文：For a forwarded ReadIndex operation that the current leader releases after quorum confirmation, delivery of its ReadyToRead result at the originating peer must retain that operation's SystemCtx. Confirmation of a later queued operation may advance the read index, but must not substitute that later operation's identity for an earlier released operation.

决定性范围：ReadIndex identity preservation through leader prefix confirmation and response delivery, within one stable term and unchanged three-voter membership. Distinct originating followers each have exactly one pending context; all messages are produced by the implementation.
Crash-free peers with serialized Peer API calls and compliant persistence/update acknowledgement.；Finite controlled network scheduling may delay earlier-context heartbeats while later-context heartbeats are delivered; no fabricated sender or confirmation.；No context reuse, role transition or membership change during the read interval.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/2910ead4a6714170a90f7ce00ffe86df/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/2910ead4a6714170a90f7ce00ffe86df/plan.json)；[原始观察](logs/eae47b2a7b964503b32c9881fc487819/stdout.log)；[assessment](direct-checks/2910ead4a6714170a90f7ce00ffe86df/eae47b2a7b964503b32c9881fc487819-assessment.json)；[对应性复核](submissions/200d139fc9d8438995770cbbb9bc85f0/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/eae47b2a7b964503b32c9881fc487819/check.json)
执行边界：TestAssuranceReadContext uses Peer.Launch/Tick/ReadIndex/Handle/GetUpdate/Commit and the captured TestLogDB helper. Each origin issues exactly one read in each scenario.；Use captured in-memory TestLogDB instead of engine LogDB and deterministic delivery queues instead of transport. No crashes or storage failures occur.；Driver persists State and EntriesToSave before any message delivery, applies bootstrap config/no-op entries, acknowledges Update and reports applied index.；Private state is read only for prefix/admission diagnostics; all protocol state changes use Peer methods.
固定比较 `read-context`：观察到违反；已比较 4 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3（违反见证） | 观察 4 |
| --- | --- | --- | --- | --- |
| scenario | serial_control | serial_control | overlap | overlap |
| origin | 2 | 3 | 2 | 3 |
| observed | true | true | true | true |
| context | 901:201 | 902:302 | 902:302 | 902:302 |
| admitted.context | 901:201 | 902:302 | 901:201 | 902:302 |
| applied | 4 | 4 | 4 | 4 |
| event | read_result | read_result | read_result | read_result |
| index | 4 | 4 | 4 | 4 |
| term | 2 | 2 | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

该问题保留的失败执行：[原始失败](logs/fb7425bce2514b47b93fc5af74b916af/stdout.log)；[诊断](logs/fb7425bce2514b47b93fc5af74b916af/stderr.log)。修订转折见时间线，旧失败不覆盖当前结果。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Leader proposals become indexed current-term entries; follower predecessor checks and durable-before-response dispatch produce replication support. Leader counts voters including witnesses, selects quorum match and…
- 上下文／权威转换（原文导航摘录）：Ticks on eligible nonleaders initiate election after applied history catches up. Candidate increments term, self-votes and wins a voter quorum; vote grant checks history and prior vote. Known response filtering precedes…
- 两条主线的连接（原文导航摘录）：Committed history survives authority change and constrains subsequent elections and append replacement. Transition reset removes prior vote counts, remote match support and pending read confirmations; new leader commits…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.25 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 10.74 分钟 · 受理 obligation：The captured SystemCtx/ReadyToRead interface grounds identity preservation independently of timeout or linearizability guarantees. Fix this…。[完整交接](submissions/76c246849bab4b66b504e6bbfcfb5ade/accepted.json)

- 13.98 分钟 · 受理 check：Execute the accepted identity-preservation obligation with real message producers and a legal overlapping schedule, plus a serial control.…。[完整交接](submissions/69fc81302308407ea35befd21add3092/accepted.json)

- 14.21 分钟 · 修订前 v1：已进入测试，panic 尚未归因；后续版本独立执行与复核。[原失败记录](logs/fb7425bce2514b47b93fc5af74b916af/check.json)

- 16.41 分钟 · 受理 revise_check：F4 initialization repair: trusted execution fb7425bce2514b47b93fc5af74b916af stopped at checkLaunchRequest before read admission because…。[完整交接](submissions/2910ead4a6714170a90f7ce00ffe86df/accepted.json)

- 16.63 分钟 · 实际执行：重叠转发读取的响应标识被替换；执行完成；比较见 assessment。[执行记录](logs/eae47b2a7b964503b32c9881fc487819/check.json)

- 19.67 分钟 · 受理 review：重叠转发读取的响应标识被替换。[完整交接](submissions/200d139fc9d8438995770cbbb9bc85f0/accepted.json)

- 20.31 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/43d64e393205405482d20920e7f31820/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Forwarded read response correlation when one confirmation releases several contexts.；Read confirmation eligibility across membership changes without term reset.；Backend atomicity, detailed snapshot…
  尚无精确对应交接。

- b-authority：Membership-transition effects on outstanding read confirmations beyond a term reset remain untraced.
  尚无精确对应交接。

- b-read-deliver：Can later-context confirmation substitute the wrong identity for an earlier forwarded read under a legal overlapping history?
  相关交接：[交接 1](submissions/200d139fc9d8438995770cbbb9bc85f0/accepted.json)

- b-persist：LogDB backend crash atomicity and transport faults have not been inspected.
  尚无精确对应交接。

- b-client-read：Timeout is an allowed request outcome; a correlation discrepancy alone does not establish a numeric progress guarantee.
  尚无精确对应交接。

- surface:LogDB.SaveRaftState：Backend crash atomicity is not established by engine call order.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[direct_check](logs/fb7425bce2514b47b93fc5af74b916af/stdout.log)；[stderr](logs/fb7425bce2514b47b93fc5af74b916af/stderr.log)；[执行记录](logs/fb7425bce2514b47b93fc5af74b916af/check.json)
