# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **18.91 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1265.13 秒、34 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1134.87 | 1265.13 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 13.84 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 15.02 秒。

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v53`；展示版本 `audit-products-v53`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/0e300836134a47518ff519d67788ba32/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/0e300836134a47518ff519d67788ba32/check.json)；[stdout](logs/0e300836134a47518ff519d67788ba32/stdout.log)；[stderr](logs/0e300836134a47518ff519d67788ba32/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 合并确认错误复用后一个读请求上下文 | 已确认违反 | 三个投票成员、任期稳定且当前任期条目已提交时，后一个心跳确认释放了两个远端读请求。副本 2 的原上下文为 101/30，却收到 202/30；副本 3 的 202/30 正确，两个返回索引均为 4。该结果确认局部响应关联缺陷，不等同于已观测到错误读取值或客户端超时。 | [O-read-response-context](#claim-O-read-response-context) |

<a id="claim-O-read-response-context"></a>

### 1. 合并确认错误复用后一个读请求上下文

**已确认违反**。要求原文：When a current multi-voter leader releases a pending remote ReadIndex request after quorum confirmation and emits its ReadIndexResp to the requesting replica, the response must carry that released request’s SystemCtx unchanged, including when one confirmation releases several queued requests. The returned index may be advanced to the later confirmed safe index.

决定性范围：Local correlation of an actually released remote read request to its emitted ReadIndexResp in a stable leader term and membership.
Crash-fault operation with unmodified messages produced by configured peers.；Distinct nonzero SystemCtx values identify the pending requests; source identity and term are preserved through delivery.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/288e18585101441d84a4ad44e6903602/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/288e18585101441d84a4ad44e6903602/plan.json)；[原始观察](logs/ddfecbc913294fb1a5f2b793b003ea11/stdout.log)；[assessment](direct-checks/288e18585101441d84a4ad44e6903602/ddfecbc913294fb1a5f2b793b003ea11-assessment.json)；[对应性复核](submissions/df3585ba8a5d46758cda41c40f63818a/accepted.json)

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 15.02 秒；执行进程耗时 13.84 秒；[实际命令、工具版本与输入记录](logs/ddfecbc913294fb1a5f2b793b003ea11/check.json)
执行边界：Three bootstrapped Peers, synchronous update storage/application/commit driver, real tick/vote election and deterministic FIFO message delivery with a fixed first-heartbeat loss policy.；No target code changes. Captured TestLogDB provides in-memory storage for a no-crash history.；Network and application scheduling are implemented by the driver; responses are produced only by Peer.Handle.；Read-only internal sampling verifies pending records, membership, term and completed setup.
固定比较 `P-read-context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| scenario | overlapping_remote_reads | overlapping_remote_reads |
| cluster | 7 | 7 |
| origin | 2 | 3 |
| event | response | response |
| context | 202/30 | 202/30 |
| release.expected_context | 101/30 | 202/30 |
| release.removed | true | true |
| release.quorum | 2 | 2 |
| index | 4 | 4 |
| qualified | true | true |
| sender | 1 | 1 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：Leader assigns term/index to proposals, followers validate previous log term and protect committed history, and eligible member responses advance replication progress. Voter/witness quorum match plus current-term log…
- 上下文／权威转换（原文导航摘录）：Election establishes a new term and self vote; up-to-date eligible voting responses establish leadership. Term dispatch rejects stale messages and resets volatile support on authority changes. Peer filters unknown…
- 两条主线的连接（原文导航摘录）：Committed history survives role reset while vote tallies, replication match and pending read-index trackers do not. New leaders append a current-term entry before quorum-dependent reads can proceed. Campaigning waits…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.99 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 11.54 分钟 · 受理 check：The acquired producer/test and exact-context consumer establish a local identity duty. Submit one fixed clean-copy check with real…。[完整交接](submissions/288e18585101441d84a4ad44e6903602/accepted.json)

- 11.79 分钟 · 实际执行：合并确认错误复用后一个读请求上下文；执行完成；比较见 assessment。[执行记录](logs/ddfecbc913294fb1a5f2b793b003ea11/check.json)

- 14.18 分钟 · 受理 review：合并确认错误复用后一个读请求上下文。[完整交接](submissions/df3585ba8a5d46758cda41c40f63818a/accepted.json)

- 18.08 分钟 · 受理 research：Continue independent frontier investigation after the confirmed correlation result. Preserve producer-side eligibility protections and…。[完整交接](submissions/69ba5d289a1047568d88a7401a48f4f9/accepted.json)

- 18.90 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/0e300836134a47518ff519d67788ba32/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：Pending read support across nonlocal membership changes needs a legal configuration/read-interval history before any current-quorum mismatch can be interpreted as a defect.；KV-specific crash…
  尚无精确对应交接。

- B-persist：KV-specific synchronization and crash durability details remain open; ordinary reload mechanism is mapped in B-reload.
  尚无精确对应交接。

- B-snapshot：On-disk imported snapshot variants and interrupted filesystem installation are not yet followed.
  尚无精确对应交接。

- B-read：Pending read confirmations survive nonlocal membership changes while confirm uses the current quorum size. Is there a legal history in which retained support supplies no valid authority point within…
  相关交接：[交接 1](submissions/dd9ac5351b2f4cbdbc8b4b1052f7c038/accepted.json)；[交接 2](submissions/df3585ba8a5d46758cda41c40f63818a/accepted.json)；[交接 3](submissions/69ba5d289a1047568d88a7401a48f4f9/accepted.json)

- B-consume：Concurrent and on-disk application variants have only representative coverage.
  尚无精确对应交接。

- B-reload：KV-specific crash behavior and bootstrap variants remain open.
  尚无精确对应交接。

- B-readclient：End-to-end timeout/retry consequence of a miscorrelated response is not yet executed.
  尚无精确对应交接。

- surface:raft.readIndex.confirm across applyConfigChange：Current quorum size is consulted while per-request sender confirmations remain. Need an actual permissible configuration history and authority point within the read interval; past membership support…
  尚无精确对应交接。

- surface:messageHandler.HandleSnapshotStatus -> MessageQueue.AddDelayed -> raft.handleLeaderSnapshotStatus：Status delay occurs in the NodeHost queue, so absence of Hint forwarding by Peer.ReportSnapshotStatus is not missing delay. The generation/ordering relationship of an old status and a subsequent…
  尚无精确对应交接。

- surface:raft.makeMetadataEntries and witness election participation：Witnesses retain term/index metadata without command payload, but cannot campaign or be promoted into full members under mapped role guards. Metadata-only replication alone does not establish a…
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
