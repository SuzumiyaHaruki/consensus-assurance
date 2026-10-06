# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 2 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **20.33 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1180.35 秒、34 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1219.65 | 1180.35 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 1 | 5 |

受控目标执行进程耗时（正式检查＋探索）：已记录 27.74 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 29.92 秒。

目标执行组成：正式检查 2 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v54`；展示版本 `audit-products-v54`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/04cf36e1800a4b4c9b39d2aca5d41781/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/04cf36e1800a4b4c9b39d2aca5d41781/check.json)；[stdout](logs/04cf36e1800a4b4c9b39d2aca5d41781/stdout.log)；[stderr](logs/04cf36e1800a4b4c9b39d2aca5d41781/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 合并读取确认时，远端响应覆盖了较早请求的上下文 | 已确认违反 | 在固定任期、三投票节点的执行中，节点 2 提交的上下文是 30/101，却收到 30/202；节点 3 的响应正确。后一个请求获得多数确认并释放队列前缀时，较早远端请求的身份未被保留。此结果限定于响应关联，不证明陈旧读取或无限等待。 | [C-read-response-context](#claim-C-read-response-context) |

<a id="claim-C-read-response-context"></a>

### 1. 合并读取确认时，远端响应覆盖了较早请求的上下文

**已确认违反**。要求原文：When a leader releases admitted remote ReadIndex requests upon quorum confirmation in a stable term and membership, each response to a released request origin must preserve that request full SystemCtx so its origin can associate readiness with the admitted operation, including requests released as a prefix by confirmation of a later context.

决定性范围：Per-peer ReadIndex response correlation for distinct remote origins with one pending request each; stable multi-voter term and membership, current-term committed entry, valid nonzero distinct contexts and generated quorum confirmation.
Crash-fault message loss may discard earlier heartbeats while later heartbeats and responses are delivered.；Peer caller persists exported entries/state before dependent outbound messages, applies committed configuration in order, and acknowledges updates.；Each origin has exactly one admitted request so origin independently identifies its expected response.。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/b9c1642e5df6406483e05cc39f6958d0/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/b9c1642e5df6406483e05cc39f6958d0/plan.json)；[原始观察](logs/341c374e13dd4cf494054d1a1d15c4ab/stdout.log)；[assessment](direct-checks/b9c1642e5df6406483e05cc39f6958d0/341c374e13dd4cf494054d1a1d15c4ab-assessment.json)；[对应性复核](submissions/c42fde6e935142ad8b4b415092b4a6b8/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 14.47 秒；执行进程耗时 13.53 秒；[实际命令、工具版本与输入记录](logs/341c374e13dd4cf494054d1a1d15c4ab/check.json)
执行边界：TestAssuranceRemoteReadContextPrefix uses captured Peer and TestLogDB with generated election and read traffic. One origin identifies one operation independently of the compared context. Preparation observations carry the independent origin identity for each admitted operation; the same actual prepared cluster supports both.；
固定比较 `CHK-read-context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | prefix_release | prefix_release |
| origin | 2 | 3 |
| event | read_response | read_response |
| context | 30/202 | 30/202 |
| admitted.context | 30/101 | 30/202 |
| setup.scenario | prefix_release | prefix_release |
| setup.term | 2 | 2 |
| setup.fault_policy | drop_first_context_heartbeats | drop_first_context_heartbeats |
| setup.voters | 3 | 3 |
| setup.queue_length | 0 | 0 |
| admitted.scenario | prefix_release | prefix_release |
| admitted.term | 2 | 2 |
| from | 1 | 1 |
| index | 4 | 4 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Peer.ProposeEntries enters leader handler, assigns current term and sequential index, updates self match, and broadcasts replication. Followers check previous term/index, reject mismatches, append a matching suffix and…
- 上下文／权威转换（原文导航摘录）：Ticks initiate campaigns only for eligible nonremoved full members and only after committed work is applied. Candidate increments term and self-votes; vote grants check saved vote and log freshness; known eligible…
- 两条主线的连接（原文导航摘录）：Authority reset prevents counting prior-term progress, while the surviving committed log constrains election freshness and future replication. Applied membership defines voting support; single pending configuration and…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.19 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.80 分钟 · 受理 check：The acquired prefix-release test expectation and exact-context consumer ground a local correlation obligation. A small Peer-level history…。[完整交接](submissions/1991554df7c041329a92b245dde28959/accepted.json)

- 10.05 分钟 · 修订前 v1：目标进程执行成功；保存的机械比较：结果未确定；复核与修订见各自后续节点。[原固定输入](direct-checks/1991554df7c041329a92b245dde28959/plan.json)；[原执行记录](logs/d2357d1e3a8940adb7c5b984d944f417/check.json)；[原保存评估](direct-checks/1991554df7c041329a92b245dde28959/d2357d1e3a8940adb7c5b984d944f417-assessment.json)

- 11.82 分钟 · 受理 review：读取确认的原始上下文不匹配，事件关联仍需修复；v1 checker_correspondence: revision_needed。[完整交接](submissions/0dc41629b69a42189cad6b273d1fdfb9/accepted.json)

- 13.66 分钟 · 受理 revise_check：Repair observation input for review issue 4c4940beea2340beaa2b15a42d634b8e: add origin to setup emissions only. Monitor encoding,…。[完整交接](submissions/b9c1642e5df6406483e05cc39f6958d0/accepted.json)

- 13.90 分钟 · 实际执行：合并读取确认时，远端响应覆盖了较早请求的上下文；执行完成；比较见 assessment。[执行记录](logs/341c374e13dd4cf494054d1a1d15c4ab/check.json)

- 15.91 分钟 · 受理 review：合并读取确认时，远端响应覆盖了较早请求的上下文；v2 checker_correspondence: no_issue_found。[完整交接](submissions/c42fde6e935142ad8b4b415092b4a6b8/accepted.json)

- 20.31 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/04cf36e1800a4b4c9b39d2aca5d41781/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Remote ReadIndex response context differs from local release when one confirmation releases a prefix.；Snapshot storage/transport and asynchronous recovery variants need deeper reading.；Membership…
  尚无精确对应交接。

- B-authority：Interaction of membership callbacks and queued prior replies across membership transitions remains to be investigated
  尚无精确对应交接。

- B-membership：Detailed membership acceptance constraints in members.handleConfigChange are unread
  尚无精确对应交接。

- B-history：Storage implementation crash atomicity and transport ordering require deeper source investigation
  尚无精确对应交接。

- B-recovery：Snapshot file validation and exact asynchronous recovery admission are not yet traced
  尚无精确对应交接。

- B-application：All session retry and on-disk/concurrent state-machine variants remain unread
  尚无精确对应交接。

- B-read-confirm：Does the remote branch preserve correlation for earlier requests released by confirmation of a later context?
  相关交接：[交接 1](submissions/c42fde6e935142ad8b4b415092b4a6b8/accepted.json)

- B-read-consume：Effects of miscorrelated remote readiness need a legal multi-request history and execution witness
  尚无精确对应交接。

- F-readpending：Remote release may emit confirming context instead of saved context
  相关交接：[交接 1](submissions/c42fde6e935142ad8b4b415092b4a6b8/accepted.json)

- surface:members.handleConfigChange：RSM caller acquired; detailed acceptance and ordered-change guards unread.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
