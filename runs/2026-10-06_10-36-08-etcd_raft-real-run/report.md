# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **24.60 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 924.26 秒、32 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1475.74 | 924.26 |
| Agent 调用 | 40 | 8 | 32 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 31.73 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 33.58 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v53`；展示版本 `audit-products-v53`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/ede243bdea7149b1bc16b1c777c40b51/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/ede243bdea7149b1bc16b1c777c40b51/check.json)；[stdout](logs/ede243bdea7149b1bc16b1c777c40b51/stdout.log)；[stderr](logs/ede243bdea7149b1bc16b1c777c40b51/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移失败后，自动退出联合配置的续行丢失 | 已确认违反 | 正式执行中，隐式联合配置在转移期间应用；转移于第 10 个 tick 结束，但第 10 与第 20 个 tick 的协议、存储与队列状态完全相同，AutoLeave 仍为 true。两个跟随者均响应了全部心跳；结合已核对的执行路径，该闭合循环表明自动退出依赖新的应用事件，不能仅靠正常驱动恢复。此结论不声称数值超时违约或已观测到客户端停机。 | [C-auto-exit-continuation](#claim-C-auto-exit-continuation) |
| Can the documented early-Advance optimization let configuration/election guards treat a configuration entry as applied while its… | 研究中，尚无正式义务 | Does early Advance explicitly exclude configuration entries or require another ordering constraint not yet read?；Can a finite allowed schedule reach stale-configuration… | [候选 1](#candidate-52e90932b4a042f6ae29ad8ef0a0bd34) |

<a id="claim-C-auto-exit-continuation"></a>

### 1. 领导权转移失败后，自动退出联合配置的续行丢失

**已确认违反**。要求原文：After a committed implicit joint configuration has been applied, Raft owns the continuation that proposes and completes exit when it is safe. A temporary leadership-transfer proposal obstruction must not leave a still-authoritative leader in a repeatable non-exiting execution after the transfer is aborted, while a quorum for both configurations is responsive and the caller continues the required tick, message, persistence and application work. No unrelated client proposal or manual leave-joint request is required to restart this automatic continuation.

决定性范围：Library-owned automatic exit for ConfChangeTransitionJointImplicit, with a stable leader following unsuccessful transfer and a responsive joint quorum.
Non-Byzantine participants; genuine implementation-generated network messages may be lost；Caller serializes RawNode, persists before emitting messages, applies ordered committed work and supplies ticks；Quorum remains responsive and no later leadership change or unrelated client proposal is required in the suffix；Implicit joint change has committed and applied; leader transfer obstruction has ended。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/51effd2b43aa4dceb563212f1dbcd184/assurance_generated_test.go)；[条件与检查器](direct-checks/51effd2b43aa4dceb563212f1dbcd184/plan.json)；[原始观察](logs/1f6dcf3ed0e64684805c07f201f458ba/stdout.log)；[assessment](direct-checks/51effd2b43aa4dceb563212f1dbcd184/1f6dcf3ed0e64684805c07f201f458ba-assessment.json)；[对应性复核](submissions/dda8f07350ad4770bddf08a8da318d2e/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 15.57 秒；执行进程耗时 14.76 秒；[实际命令、工具版本与输入记录](logs/1f6dcf3ed0e64684805c07f201f458ba/check.json)
执行边界：Single-threaded RawNode harness using actual emitted messages and MemoryStorage; direct read-only reflection captures all RawNode/raft/log/tracker fields and MemoryStorage data at drained boundaries. No target implementation is replaced.；No target code edits or behavior instrumentation. Controlled FIFO network may drop TimeoutNow only.；One public TransferLeader call is interleaved after committed configuration delivery and before ApplyConfChange/Advance.；Reflection records unexported state without invoking methods; excludes logger/traceLogger, duplicate Storage interface, MemoryStorage mutex and call statistics. MemoryStorage contents are captured separately. Function code identities are recorded; bound raft owner is the same node throughout.；Nil versus empty maps/slices and slice capacities are preserved; map entries are canonicalized by key. Pointer allocation addresses are omitted because the suffix does not branch on them.；Clock, driver diagnostic counters and recorded output are not fed back to protocol. The fixed schedule phase, transport policy, injected flag, operation identity and queue are captured.
固定比较 `P-no-pending-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| op_id | implicit-remove-3 |
| node | 1 |
| change_index | 3 |
| policy | drop_timeout_now |
| cycle_repeats | true |
| auto_leave | true |
| admitted.term | 2 |
| admitted.policy | drop_timeout_now |
| admitted.auto_leave | true |
| admitted.target | 2 |
| admitted.role | StateLeader |
| start.term | 2 |
| start.target | 0 |
| start.role | StateLeader |
| start.queue_count | 0 |
| start.local_messages | 0 |
| start.has_ready | false |
| start.ticks | 10 |
| start.timeout_drops | 1 |
| applied | 3 |
| applying | 3 |
| committed | 3 |
| event | cycle_result |
| has_ready | false |
| heartbeat_acks_2 | 10 |
| heartbeat_acks_3 | 10 |
| last | 3 |
| local_messages | 0 |
| outgoing_count | 3 |
| queue_count | 0 |
| role | StateLeader |
| state | str，7357 字符；首尾预览：{"change_index":3,"injected":true,"nodes":{"1":{"a…ll},"Index":1,"Term":1}}}},"transfer_policy":true}；[1f6dcf3ed0e64684805c07f201f458ba / event[6] / state](logs/1f6dcf3ed0e64684805c07f201f458ba/stdout.log) |
| target | 0 |
| term | 2 |
| ticks | 20 |
| timeout_drops | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For Candidate 0dc282d915a3474d896f2389a9478efe, can a three-voter RawNode execution commit and apply an implicit joint removal while transfer to voter 2 is blocked by dropped TimeoutNow, then drain…
所选问题／策略（原文摘录）：Construct only: no assertion of deadline violation or permanent stalling. Public RawNode operations and real messages create the prefix; per-node persistence/application and Advance are serialized. Snapshot initialization follows the…
[受理问题、条件与来源](submissions/1809733229a849048bea49e513c937bb/accepted.json)；[固定输入](submissions/1809733229a849048bea49e513c937bb/inputs/auto_exit_explore_test.go)
<a id="exploration-10be8c2524184bcaabc1ee8a94736885"></a>
[探索执行 1](#exploration-10be8c2524184bcaabc1ee8a94736885)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/10be8c2524184bcaabc1ee8a94736885/check.json)；[实际输出](logs/10be8c2524184bcaabc1ee8a94736885/stdout.log)；[诊断](logs/10be8c2524184bcaabc1ee8a94736885/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 18.01 秒；执行进程耗时 16.97 秒；[实际命令、工具版本与输入记录](logs/10be8c2524184bcaabc1ee8a94736885/check.json)
[执行输入文件清单](experiments/978d9cc731204469b4b22540a459b67e/workspace-delta/manifest.json)
[执行后文件清单](experiments/978d9cc731204469b4b22540a459b67e/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-24685def36cc467d92c8baa0eb0bdaaf)

<a id="exploration-feedback-24685def36cc467d92c8baa0eb0bdaaf"></a>
[交接 1](#exploration-feedback-24685def36cc467d92c8baa0eb0bdaaf) · 后续说明；关联：[探索执行 1](#exploration-10be8c2524184bcaabc1ee8a94736885)
后续受理交接原文（摘录，不是各次执行的独立观察）：The exploration completed a public RawNode history with implicit removal committed/applied at index 3 during transfer. The transfer case dropped one genuine TimeoutNow; by tick 10 transfer was cleared, while ticks 10/20/30/40 retained AutoLeave and…
[完整交接；精确引用不表示已解决或已正式化](submissions/24685def36cc467d92c8baa0eb0bdaaf/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：Leader assigns term/index, replicates entries, consumes persistence-qualified acknowledgments into Match, and commits a current-term quorum index. Followers match predecessor, repair uncommitted suffix, and learn…
- 上下文／权威转换（原文导航摘录）：Pre-vote can precede real term increment; log freshness and voting restrictions qualify grants, current voter aggregation determines election. Higher terms normally force follower, with lease/pre-vote exceptions. Reset…
- 两条主线的连接（原文导航摘录）：Support is interpreted under applied voter configuration and current leader term. New leader resets remote progress and appends an empty current-term entry before old history can advance through a new current-term…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.69 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 9.09 分钟 · 实际执行：Construct only: no assertion of deadline violation or permanent stalling. Public RawNode operations and real messages create the prefix;…；探索执行正常结束。[执行记录](logs/10be8c2524184bcaabc1ee8a94736885/check.json)

- 11.23 分钟 · 受理 obligation：Fix the library-owned continuation responsibility independently of finite observations; construct an exact-cycle witness next.。[完整交接](submissions/24685def36cc467d92c8baa0eb0bdaaf/accepted.json)

- 16.33 分钟 · 受理 check：Submit a fixed closed-cycle comparison against the accepted continuation obligation. New formal events use explicit admission and…。[完整交接](submissions/51effd2b43aa4dceb563212f1dbcd184/accepted.json)

- 16.58 分钟 · 实际执行：领导权转移失败后，自动退出联合配置的续行丢失；执行完成；比较见 assessment。[执行记录](logs/1f6dcf3ed0e64684805c07f201f458ba/check.json)

- 19.45 分钟 · 受理 review：领导权转移失败后，自动退出联合配置的续行丢失。[完整交接](submissions/dda8f07350ad4770bddf08a8da318d2e/accepted.json)

- 22.51 分钟 · 受理 continue：Select a distinct safety-relevant application-notification premise while retaining the confirmed continuation result and the explicit…。[完整交接](submissions/4b73c103425c4bd4948c722e4b7e9edb/accepted.json)

- 24.58 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/ede243bdea7149b1bc16b1c777c40b51/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [52e90932b4a042f6ae29ad8ef0a0bd34](research.json)：[候选 1](#candidate-52e90932b4a042f6ae29ad8ef0a0bd34)

<a id="candidate-52e90932b4a042f6ae29ad8ef0a0bd34"></a>

研究中问题：Can the documented early-Advance optimization let configuration/election guards treat a configuration entry as applied while its ApplyConfChange call is still pending, permitting decisions under stale voter eligibility?
[候选原文与历史](state.json)
保存的语义未知：Does early Advance explicitly exclude configuration entries or require another ordering constraint not yet read?；Can a finite allowed schedule reach stale-configuration admission or conflicting committed entries without omitting caller work or fabricating votes?

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：ReadIndex loss/retry contract limits any inference from configuration-driven release asymmetry；Pending read messages retained across reset；Early Advance notification versus actual configuration…
  尚无精确对应交接。

- B-authority：pendingReadIndexMessages is not cleared by reset; lifetime and later consumption need analysis
  相关交接：[交接 1](submissions/4b73c103425c4bd4948c722e4b7e9edb/accepted.json)

- B-config：Configuration-driven commit omits pending-read release. The API permits request loss and caller retries; no automatic per-request completion duty is yet grounded.
  尚无精确对应交接。

- B-application：Does the documented early-Advance optimization include configuration entries, and what prevents raftLog.applied from satisfying configuration/election guards while ApplyConfChange is outstanding?
  相关交接：[交接 1](submissions/4b73c103425c4bd4948c722e4b7e9edb/accepted.json)

- F-applied-notification：Precise caller duty for configuration application relative to optimized Advance.
  尚无精确对应交接。

- surface:raft.switchToConfig pending reads：ReadIndex may lose requests without notice and caller must retry. Missing release on configuration-driven commit remains an implementation asymmetry but is not by itself an established liveness…
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
