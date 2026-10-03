# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。已产生观察的正式结论 1 项：已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、31 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.16 | 0.00 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 1 | 5 |

目标执行组成：正式检查 2 次＋探索 1 次，其中失败／未完成 1 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v44`；展示版本 `audit-products-v44`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`309.49316611799804`（配置值不表示触发了超时）。
[调用记录](logs/5123f1c2467d46f8b3a16710bdb921b9/check.json)；[stdout](logs/5123f1c2467d46f8b3a16710bdb921b9/stdout.log)；[stderr](logs/5123f1c2467d46f8b3a16710bdb921b9/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 并发转发读确认覆盖了较早请求的上下文 | 已确认违反 | 在三投票节点、任期稳定且当前任期已提交的执行中，节点 2 提交上下文 101:1001，却收到并导出节点 3 的 202:2002；顺序执行对照保持了各自上下文。该证据验证的是 Peer 层响应关联错误，未证明应用读取违反线性一致性或客户端永久停滞。 | [C-forwarded-context](#claim-C-forwarded-context) |

<a id="claim-C-forwarded-context"></a>

### 1. 并发转发读确认覆盖了较早请求的上下文

**已确认违反**。要求原文：Within a stable leader term and fixed full-voter membership, when qualified confirmation releases a queued forwarded ReadIndex status and the implementation routes its response to the originating follower, the readiness context exported at that follower must equal the context admitted for that status. Coalescing may raise the read index, but must not substitute another request context.

决定性范围：Per-status correlation through completed forwarded-read response routing in a crash-free three-full-voter cluster with current-term committed history and distinct request contexts.
Each originating follower has one outstanding operation in the checked history, allowing independent correlation by origin.；All actual protocol messages are delivered without mutation; the overlap delays earlier heartbeat probes until later-context confirmation has completed.；Peer caller persists each update before message delivery and applies bootstrap configuration/no-op entries in order.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/00449e31985c4101b33a07c5362356ee/assurance_generated_test.go)；[条件与检查器](direct-checks/00449e31985c4101b33a07c5362356ee/plan.json)；[原始观察](logs/c062d2922ab74798a0e7788936085d88/stdout.log)；[assessment](direct-checks/00449e31985c4101b33a07c5362356ee/c062d2922ab74798a0e7788936085d88-assessment.json)；[对应性复核](submissions/acc4d910e5b44b40904c85d91b8ba4b1/accepted.json)

执行边界：Root package dragonboat launcher runs the fixed internal/raft TestAssuranceForwardedReadContexts; the inner protocol check is unchanged.；No target implementation changes.；Deterministic in-process transport delivers messages, deferring earlier probes only in overlap.；Application adapter consumes only bootstrap membership entries and the election no-op; no user state-machine result is simulated.；Read-only private fields establish setup/admission and diagnostics; decisive observations use Peer.GetUpdate ReadyToReads.；Technical packaging repair only: root launcher invokes the Go toolchain on internal/raft; all inner inputs, events, identity fields, oracle and schedule are unchanged. Subprocess stdout/stderr are forwarded verbatim and nonzero exit fails the launcher.
固定比较 `CHK-forwarded-context`：观察到违反；已比较 4 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3（违反见证） | 观察 4 |
| --- | --- | --- | --- | --- |
| scenario | serial | serial | overlap | overlap |
| origin | 2 | 3 | 2 | 3 |
| event | read_result | read_result | read_result | read_result |
| ctx | 101:1001 | 202:2002 | 202:2002 | 202:2002 |
| admitted.ctx | 101:1001 | 202:2002 | 101:1001 | 202:2002 |
| applied | 4 | 4 | 4 | 4 |
| index | 4 | 4 | 4 | 4 |
| term | 2 | 2 | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。

该问题保留的失败执行：[原始失败](logs/957fd78098304be69986dc2a90daee5c/stdout.log)；[诊断](logs/957fd78098304be69986dc2a90daee5c/stderr.log)。旧失败不覆盖当前结果。

条件探索：With actual batched LogDB persistence and an uncached batch after reopening, does one non-notfound KV GetValue error during append-to-existing-batch propagate, or does SaveRaftState succeed while the…
所选问题／策略（原文摘录）：Source returns false for any GetValue error in getBatchFromDB and then getMergedFirstBatch returns only new entries. A real-store wrapper injects one explicit error at the KV interface; it does not alter target logic or persistent bytes.…
[受理问题、条件与来源](submissions/93df072560394f75a290b66431af69ca/accepted.json)；[固定输入](submissions/93df072560394f75a290b66431af69ca/inputs/batch_launcher_test.go)；[固定输入](submissions/93df072560394f75a290b66431af69ca/inputs/batch_read_error_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/6015c2ed7f9b493e8e1194edbbd96796/check.json)；[实际输出](logs/6015c2ed7f9b493e8e1194edbbd96796/stdout.log)；[诊断](logs/6015c2ed7f9b493e8e1194edbbd96796/stderr.log)
[执行文件清单](experiments/a8fe48a579e740a4ba0779ee3fdeec2a/workspace-delta/manifest.json)；[执行文件清单](experiments/a8fe48a579e740a4ba0779ee3fdeec2a/workspace-outcome/manifest.json)
实际观察已保存，尚待解释；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Peer routes proposals to leader. Leader assigns term/index, appends, and sends predecessor-qualified replication; followers match predecessor and protect committed history. Acknowledgements update per-peer matches;…
- 上下文／权威转换（原文导航摘录）：Election timers initiate campaign only for eligible full voters without committed-but-unapplied work. New term resets transient votes/progress/read confirmations; vote granting checks log freshness and prior vote, and…
- 两条主线的连接（原文导航摘录）：Terms qualify newly counted support, but established committed history survives authority reset and constrains future logs and votes. Membership becomes active through RSM application; campaign defers when applied state…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 9.77 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 19.18 分钟 · 实际执行：并发转发读确认覆盖了较早请求的上下文；执行完成；比较见 assessment。[执行记录](logs/c062d2922ab74798a0e7788936085d88/check.json)

- 22.98 分钟 · 受理 review：并发转发读确认覆盖了较早请求的上下文。[完整交接](submissions/acc4d910e5b44b40904c85d91b8ba4b1/accepted.json)

- 27.65 分钟 · 受理 research：Integrate the accepted scoped read-routing answer at the next map handoff, retain independent limits, and save fresh source work on…。[完整交接](submissions/df6e8d8d295c416aaca35e4d07023e89/accepted.json)

- 31.20 分钟 · 受理 research：Retain contract investigation and distinguish unsupported result-buffer mutation from explicitly protected proposal input reuse; do not…。[完整交接](submissions/6df5a9143aca436fb52926cdad3e20b2/accepted.json)

- 34.50 分钟 · 受理 explore：Source returns false for any GetValue error in getBatchFromDB and then getMergedFirstBatch returns only new entries. A real-store wrapper…。[完整交接](submissions/93df072560394f75a290b66431af69ca/accepted.json)

- 34.82 分钟 · 实际执行：Source returns false for any GetValue error in getBatchFromDB and then getMergedFirstBatch returns only new entries. A real-store wrapper…；条件观察完成。[执行记录](logs/6015c2ed7f9b493e8e1194edbbd96796/check.json)

- 39.99 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/5123f1c2467d46f8b3a16710bdb921b9/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Forwarded queue-prefix release routes each response using the confirming heartbeat context, while local readiness uses per-status context; application/client endpoint consequences and other authority…
  尚无精确对应交接。

- B-persist：Specific LogDB implementations and crash fault injection paths are not yet audited.
  相关交接：[交接 1](submissions/93df072560394f75a290b66431af69ca/accepted.json)

- B-recovery：Detailed disk-state-machine recovery and snapshot transport interleavings remain open.
  相关交接：[交接 1](submissions/df6e8d8d295c416aaca35e4d07023e89/accepted.json)；[交接 2](submissions/93df072560394f75a290b66431af69ca/accepted.json)

- B-apply：Result.Data ownership across session cache, application return and client result exposure is not explicit in the inspected interface comments.；Disk/concurrent state-machine completion and session…
  相关交接：[交接 1](submissions/df6e8d8d295c416aaca35e4d07023e89/accepted.json)；[交接 2](submissions/6df5a9143aca436fb52926cdad3e20b2/accepted.json)

- surface:RequestResult.GetResult / Session.addResponse：Session history stores sm.Result by value and client result delivery copies that value without cloning Data. Does the caller or state-machine contract permit later byte-slice mutation, or is…
  相关交接：[交接 1](submissions/6df5a9143aca436fb52926cdad3e20b2/accepted.json)

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[direct_check](logs/957fd78098304be69986dc2a90daee5c/stdout.log)；[stderr](logs/957fd78098304be69986dc2a90daee5c/stderr.log)；[执行记录](logs/957fd78098304be69986dc2a90daee5c/check.json)
