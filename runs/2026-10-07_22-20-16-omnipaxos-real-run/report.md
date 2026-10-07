# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**；实际持续 **7.82 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| Does delta-snapshot synchronization preserve the receiver's previously decided prefix when the sender decided boundary is beyond… | 研究中，尚无正式义务 | Construct and verify an all-public-API legal history reaching Delta with sender decided index greater than receiver log length.；Measure recovered snapshot contents;… | [候选 1](#candidate-bda91e297914410a954599c3112fd6bc) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：The local leader flushes/batches proposals and sends AcceptDecide only after Prepare collected a read quorum and adopted maximum accepted-round/index history. Followers in the promised ballot and Accept phase append…
- 上下文／权威转换（原文导航摘录）：BLE heartbeat rounds select potential authority; try_become_leader is also public. SequencePaxos only acquires a strictly higher local ballot, persists its promise, clears leader support and requests promises. Receiving…
- 两条主线的连接（原文导航摘录）：Promises report accepted round/index and decided boundary. The new leader selects the highest accepted history, retains the maximum reported decided boundary and synchronizes before admitting new formation. AcceptSync…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.15 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 7.81 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/f50b1ae2c0a64dbf9e65d6c1e725b8a0/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [bda91e297914410a954599c3112fd6bc](research.json)：[候选 1](#candidate-bda91e297914410a954599c3112fd6bc)

<a id="candidate-bda91e297914410a954599c3112fd6bc"></a>

研究中问题：Does delta-snapshot synchronization preserve the receiver's previously decided prefix when the sender decided boundary is beyond the receiver's available log, given sync_log updates cached decided_idx before reconstructing the base?
[候选原文与历史](state.json)
保存的语义未知：Construct and verify an all-public-API legal history reaching Delta with sender decided index greater than receiver log length.；Measure recovered snapshot contents; neither a numeric boundary nor successful acknowledgment establishes content preservation.

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Delta snapshot base reconstruction after decided-boundary update；Cross-configuration routing and ballot ordering/equality boundary；Runtime append identity correlation across leader changes；Compaction…
  尚无精确对应交接。

- B-authority：Ballot ordering ignores config_id while equality includes it; cross-configuration routing boundary remains unexamined
  尚无精确对应交接。

- B-recovery：Delayed same-ballot synchronization across reconnect sessions has not been analyzed
  尚无精确对应交接。

- B-sync-install：Does reconstructing the delta base after updating decided_idx preserve the old decided prefix when new decided_idx exceeds the locally available log?
  尚无精确对应交接。

- B-membership：Duplicate/nonzero peer validation and inter-configuration message routing require further source investigation
  尚无精确对应交接。

- B-client：Runtime adds tracked append completion; assignment and reassignment semantics not yet mapped
  尚无精确对应交接。

- F-delta：Consumer must reconstruct the correct old base; current cached boundary is changed before reconstruction.
  尚无精确对应交接。

- surface:Ballot::cmp and OmniPaxos::handle_incoming：Ordering omits configuration id; routing responsibility needs investigation before attributing cross-configuration input.
  尚无精确对应交接。

- surface:OmniPaxos runtime append_notify / drain_notifiers：Runtime completes by assigned index before testing supersession; assignment producer and full legal history remain unread.
  尚无精确对应交接。

- surface:SequencePaxos::trim / LeaderState::get_min_all_accepted_idx：Accepted-index vector is sized by maximum pid rather than participant count; consequences for sparse ids require separate review.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1330.75 秒、38 次 Agent 调用、16 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 469.25 | 1330.75 |
| Agent 调用 | 40 | 2 | 38 |
| 控制器目标执行 | 16 | 0 | 16 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 0.00 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 0.00 秒。

目标执行组成：正式检查 0 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/f50b1ae2c0a64dbf9e65d6c1e725b8a0/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/f50b1ae2c0a64dbf9e65d6c1e725b8a0/check.json)；[stdout](logs/f50b1ae2c0a64dbf9e65d6c1e725b8a0/stdout.log)；[stderr](logs/f50b1ae2c0a64dbf9e65d6c1e725b8a0/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

