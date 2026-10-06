# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**；实际持续 **18.44 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 日志替换后原写入仍返回成功 | 待调查线索 | 固定执行中，值 101 的 append_notify 返回 Ok(1)，但该位置已由新任期决定为 202。消息来自真实三节点协议执行，原写入未到达多数派；现有 Superseded 分支未阻止此次错误成功。观测完成后的 actor 退出等待另行超时，未据此推断永久无法退出。；当前检查尚未完整处置；已观察到测试启动；执行失败或未完成；[完整评估与原因](direct-checks/069f50073c9d48479cf6e9f531f908cb/d6c6f213390745ee9884b2c7b71b96c1-assessment.json) | [C-notify-identity](#claim-C-notify-identity) |

<a id="claim-C-notify-identity"></a>

### 1. 日志替换后原写入仍返回成功

**待调查线索**。要求原文：For a pending append_notify operation in an uncompacted log, an Ok(k) completion must refer to the submitted entry at the assigned decided position. A later ballot deciding a different entry at that position must not certify the original operation as successful.

决定性范围：Async actor append_notify identity consumption across core authority transitions, one fixed three-member configuration, MemoryStorage, unbatched and uncompacted entries, no restarts or Byzantine behavior.
Caller routes authentic emitted messages to their intended nodes; finite partition loss is permitted and reconnection callbacks are supplied.；Actor runs on the provided AsyncRuntime contract with finite periodic real-time sleeps; caller services transport and reads decisions.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：no_issue_found；场景比较完整：False；独立场景完整处置：False。
[固定测试](direct-checks/069f50073c9d48479cf6e9f531f908cb/omnipaxos_runtime/tests/assurance_generated.rs)；[条件与检查器](direct-checks/069f50073c9d48479cf6e9f531f908cb/plan.json)；[原始观察](logs/d6c6f213390745ee9884b2c7b71b96c1/stdout.log)；[assessment](direct-checks/069f50073c9d48479cf6e9f531f908cb/d6c6f213390745ee9884b2c7b71b96c1-assessment.json)；[对应性复核](submissions/3c72459d96c24ab8a69254ea716c81ab/accepted.json)

当前争议／阻塞：当前检查尚未完整处置；已观察到测试启动；执行失败或未完成；[完整评估与阻塞](direct-checks/069f50073c9d48479cf6e9f531f908cb/d6c6f213390745ee9884b2c7b71b96c1-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 19.84 秒；执行进程耗时 17.30 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；执行失败或未完成；[实际命令、工具版本与输入记录](logs/d6c6f213390745ee9884b2c7b71b96c1/check.json)
执行边界：Public API integration test; raw core setup followed by one actor owner and two synchronous core peers. All protocol messages are emitted by target code. TRACE lines retain packet provenance and ordered routing; CA_EVENT lines retain admission and result.；No target behavior modifications. Test transport partitions node 1 and later heals; time configuration uses 10-second ticks and 1ms egress to allow legal incoming processing between notifier ticks.；Test AsyncRuntime delegates spawning and sleep to tokio; keeps actor join handle for observed shutdown. Core peers are synchronously driven and their clocks/transport serviced during result wait.
固定比较 `CHK-notify`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| scenario | replacement |
| operation | notify-A |
| completed | true |
| ok | true |
| actual_value | 202 |
| admission.requested_value | 101 |
| admission.admitted | true |
| admission.scenario | replacement |
| event | result |
| returned_index | 1 |
| error | none |
| decided_idx | 1 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：For Candidate 739a7fe5e829431788df0e6cbe41428f, can an actual three-node protocol history replace an isolated leader's unchosen append before its next actor notifier tick, and what does append_notify…
[受理问题、条件与来源](submissions/c684ba3e71344c4c9993cbea3e4dd2bf/accepted.json)；[固定输入](submissions/c684ba3e71344c4c9993cbea3e4dd2bf/inputs/explore_notify.rs)
显式引用的问题（不表示已解决）：[候选 1](#candidate-739a7fe5e829431788df0e6cbe41428f)
<a id="exploration-177a4b6271e445a7b4a10e593ed89837"></a>
[探索执行 1](#exploration-177a4b6271e445a7b4a10e593ed89837)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/177a4b6271e445a7b4a10e593ed89837/check.json)；[实际输出](logs/177a4b6271e445a7b4a10e593ed89837/stdout.log)；[诊断](logs/177a4b6271e445a7b4a10e593ed89837/stderr.log)
固定执行包 `./omnipaxos_runtime`；主文件 `omnipaxos_runtime/tests/assurance_generated.rs`；目标动作总耗时 40.94 秒；执行进程耗时 14.73 秒；[构建依据](build-inputs/targets/omnipaxos_runtime/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/177a4b6271e445a7b4a10e593ed89837/check.json)
[执行输入文件清单](experiments/39ffab5272ea45fc9e2c7efdf9ee7cf8/workspace-delta/manifest.json)
[执行后文件清单](experiments/39ffab5272ea45fc9e2c7efdf9ee7cf8/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-069f50073c9d48479cf6e9f531f908cb)

<a id="exploration-feedback-069f50073c9d48479cf6e9f531f908cb"></a>
[交接 1](#exploration-feedback-069f50073c9d48479cf6e9f531f908cb) · 后续说明；关联：[探索执行 1](#exploration-177a4b6271e445a7b4a10e593ed89837)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration compiled the public runtime harness and completed its genuine-message replacement history. Raw events show A=101 emitted only by isolated node 1, B=202 decided on nodes 2/3, ballot-2 AcceptSync delivering suffix [202] and decided index 1, origin…
[完整交接；精确引用不表示已解决或已正式化](submissions/069f50073c9d48479cf6e9f531f908cb/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Append is proposal admission: followers forward or buffer, leaders buffer in Prepare or append in Accept. A new leader gathers sender-indexed promises, selects the maximum accepted history and maximum reported decision…
- 上下文／权威转换（原文导航摘录）：BLE uses heartbeat rounds and configuration-tagged ballots to select leadership. SequencePaxos independently requires a ballot higher than its existing leader and promise. A local leader resets volatile quorum…
- 两条主线的连接（原文导航摘录）：Authority is insufficient without prepare support: prior accepted rounds and lengths determine the history installed in the new ballot, while prior decisions constrain the reported decision prefix. Buffered proposals…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.26 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 10.77 分钟 · 实际执行：Construct with public APIs and original emitted messages. Prepare initial leader synchronously; move it into actor, isolate its unbatched…；探索执行正常结束。[执行记录](logs/177a4b6271e445a7b4a10e593ed89837/check.json)

- 14.49 分钟 · 受理 check：Fix the sourced append-notification identity obligation and execute an independently fixed check after the informative exploration.。[完整交接](submissions/069f50073c9d48479cf6e9f531f908cb/accepted.json)

- 14.82 分钟 · 实际执行：日志替换后原写入仍返回成功；已进入测试，执行失败；性质归因另核。[执行记录](logs/d6c6f213390745ee9884b2c7b71b96c1/check.json)

- 17.76 分钟 · 受理 review：日志替换后原写入仍返回成功；v1 checker_correspondence: no_issue_found。[完整交接](submissions/3c72459d96c24ab8a69254ea716c81ab/accepted.json)

- 18.43 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/5070276b731e481f8b9b6416f8af1123/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-C-notify-identity](research.json)：[C-notify-identity](#claim-C-notify-identity)；具体进度与缺口见对应义务

<a id="candidate-739a7fe5e829431788df0e6cbe41428f"></a>

研究中问题：Can append_notify return Ok for an assigned slot whose entry was replaced and decided under a later ballot before the next notifier tick?
[候选原文与历史](state.json)
保存的语义未知：Correspondence now reviewed for the fixed local-origin identity witness; controller assessment remains authoritative. Independent shutdown timeout is outside this identity proposition.
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-177a4b6271e445a7b4a10e593ed89837)

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Sparse node IDs: accepted_indexes is sized by maximum PID, and minimum-all includes every slot; applicability of sparse IDs and trim semantics unresolved.；BLE counts reply vector entries, unlike…
  尚无精确对应交接。

- F-promise：PersistentStorage power-loss durability and failure rollback details remain untested; MemoryStorage has no process-crash durability.
  尚无精确对应交接。

- F-assignment：Whether success after ballot change can refer to a different decided entry under one legal message history.
  相关交接：[交接 1](submissions/069f50073c9d48479cf6e9f531f908cb/accepted.json)；[交接 2](submissions/3c72459d96c24ab8a69254ea716c81ab/accepted.json)

- surface:LeaderState::get_min_all_accepted_idx：Vector includes slots up to max PID; determine permitted membership identity shape and compaction contract.
  尚无精确对应交接。

- surface:BallotLeaderElection::handle_reply：Round/configuration filtering does not deduplicate replies; transport duplication legality and consequences need source investigation.
  尚无精确对应交接。

- surface:SequencePaxos::resend_message_timeout：Retry branches distinguish protocol messages; caller reconnect and delivery duties remain to establish.
  尚无精确对应交接。

- surface:ActorState::push_to_all_subs/push_to_sub：Cursor advances per returned LogEntry, while compacted prefix markers represent multiple indices; inspect snapshot subscription history and contract.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1293.56 秒、34 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1106.44 | 1293.56 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 32.03 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 60.78 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 1 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v55`；展示版本 `audit-products-v55`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/5070276b731e481f8b9b6416f8af1123/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/5070276b731e481f8b9b6416f8af1123/check.json)；[stdout](logs/5070276b731e481f8b9b6416f8af1123/stdout.log)；[stderr](logs/5070276b731e481f8b9b6416f8af1123/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

- 失败／未完成：[direct_check](logs/d6c6f213390745ee9884b2c7b71b96c1/stdout.log)；[stderr](logs/d6c6f213390745ee9884b2c7b71b96c1/stderr.log)；[执行记录](logs/d6c6f213390745ee9884b2c7b71b96c1/check.json)
