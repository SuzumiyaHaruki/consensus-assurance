# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **27.35 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 758.95 秒、36 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1641.05 | 758.95 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 4.78 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 794.99 秒。

目标执行组成：正式检查 1 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v53`；展示版本 `audit-products-v53`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/f3d3c89c85d549999a40ca066ed496fb/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/f3d3c89c85d549999a40ca066ed496fb/check.json)；[stdout](logs/f3d3c89c85d549999a40ca066ed496fb/stdout.log)；[stderr](logs/f3d3c89c85d549999a40ca066ed496fb/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 增量快照恢复丢失已决定的前缀 | 已确认违反 | 可信执行中，节点 3 原已决定 [11]，重连后收到增量 [22] 并确认恢复至索引 2，但公开读取仅返回快照 [22]，应有内容为 [11,22]。固定驱动使用真实协议消息及合法断连重连流程；该结论限于已执行的内存存储、单配置恢复场景。 | [C-delta-prefix](#claim-C-delta-prefix) |

<a id="claim-C-delta-prefix"></a>

### 1. 增量快照恢复丢失已决定的前缀

**已确认违反**。要求原文：When successful Delta synchronization represents a decided prefix as a snapshot, the snapshot must preserve the complete content of that decided prefix under the application Snapshot semantics, including entries already decided locally before recovery.

决定性范围：Successful snapshot-enabled SequencePaxos recovery in a single configuration using correctly implemented create/merge and Storage operations.
Non-Byzantine replicas and unmodified messages.；Snapshot::create represents its supplied ordered entries and merge incorporates subsequent delta entries.；Connected transport preserves per-link FIFO; a disconnected link may lose messages and reconnection is reported.；Storage operations succeed.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/651e2a8158024264b07b857caa9c202c/omnipaxos/tests/assurance_generated.rs)；[条件与检查器](direct-checks/651e2a8158024264b07b857caa9c202c/plan.json)；[原始观察](logs/4fcecc7255ae497e877cff1da4db063b/stdout.log)；[assessment](direct-checks/651e2a8158024264b07b857caa9c202c/4fcecc7255ae497e877cff1da4db063b-assessment.json)；[对应性复核](submissions/8e76d3d8b7c1490d8cdde1a9a9ce09fc/accepted.json)

固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 794.99 秒；执行进程耗时 4.78 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/4fcecc7255ae497e877cff1da4db063b/check.json)
执行边界：Three public OmniPaxos instances, genuine FIFO transport messages, one temporary node partition and reconnect notification. Record prerequisites, Delta dispatch, Accepted completion and synchronous decided reads.；No target code changes. A deterministic caller-owned transport models the documented external network boundary. Snapshot is a content-preserving vector with concatenate merge.
固定比较 `P-prefix-content`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case | delta_missing_entry |
| receiver | 3 |
| sync_id | 1 |
| completed | true |
| actual_content | [22] |
| sync.expected_content | [11,22] |
| prefix.expected_content | [11,22] |
| prefix.leader_decided | 2 |
| prefix.receiver_decided | 1 |
| prefix.receiver_accepted | 1 |
| accepted | 2 |
| compacted | 2 |
| decided | 2 |
| event | sync_result |
| read | Some([Snapshotted(SnapshottedEntry { trimmed_idx: 2, snapshot: Prefix([22]), _p: PhantomData<assurance_generated::Item> })]) |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：Caller append buffers during Prepare or forwards to promised leader. Prepare quorum selects highest accepted round/length history; leader syncs it, preserves maximum reported decision boundary, appends pending work when…
- 上下文／权威转换（原文导航摘录）：BLE heartbeat rounds assess connectivity/happiness and propose ballots; manual attempt increments a ballot directly. SequencePaxos requires higher ballot before leader preparation and resets leader support. Higher…
- 两条主线的连接（原文导航摘录）：Authority acquisition reads prior accepted history before creating new support: Promise metadata and optional log synchronization carry old accepted rounds and decisions into prepare quorum selection. AcceptSync…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.96 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 8.60 分钟 · 受理 check：Fix a check for the accepted snapshot Candidate using real public API history, full-content observations and sourced preservation semantics.。[完整交接](submissions/651e2a8158024264b07b857caa9c202c/accepted.json)

- 21.85 分钟 · 实际执行：增量快照恢复丢失已决定的前缀；执行完成；比较见 assessment。[执行记录](logs/4fcecc7255ae497e877cff1da4db063b/check.json)

- 24.11 分钟 · 受理 review：增量快照恢复丢失已决定的前缀。[完整交接](submissions/8e76d3d8b7c1490d8cdde1a9a9ce09fc/accepted.json)

- 27.34 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/f3d3c89c85d549999a40ca066ed496fb/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Delta snapshot base alignment is the first sourced discrepancy.；Configuration isolation and pending StopSign forwarding need deeper transition analysis.；Persistent backend failure behavior, async…
  尚无精确对应交接。

- B-election：BLE reply vector does not deduplicate by peer; transport duplication applicability remains unread.
  尚无精确对应交接。

- B-promise：Configuration isolation at transport/instance replacement boundaries remains unverified; ballot ordering omits config_id although equality includes it.
  尚无精确对应交接。

- B-accept：Lost/reset promise does not clear accepted_indexes; whether retained historical support is ever consumed outside its valid history remains a source question.
  尚无精确对应交接。

- B-sync：Delta merge uses the new cached decided boundary while sender delta starts at the old receiver boundary; legal histories and content consequence need investigation.
  相关交接：[交接 1](submissions/8e76d3d8b7c1490d8cdde1a9a9ce09fc/accepted.json)

- B-membership：Increasing successor configuration ID is documented but reconfigure validates only the successor config in isolation.；Runtime ownership of old messages during instance replacement is unread.
  尚无精确对应交接。

- B-compaction：Sparse node IDs and minimum-all-accepted trim accounting need separate reading.
  尚无精确对应交接。

- surface:OmniPaxos::handle_incoming configuration isolation：Core dispatch passes SequencePaxos messages without visible configuration filter. Need caller/runtime routing and legal transition history before attributing responsibility.
  尚无精确对应交接。

- surface:omnipaxos_runtime::spawn_actor：In-repository actor completion APIs and inbound processing are not yet traced; not externalized merely because transport is caller owned.
  尚无精确对应交接。

- surface:LeaderState::lost_promise / is_chosen：Accepted indexes remain when promise is lost; determine whether this is valid historical support or whether any legal continuation misuses it.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
