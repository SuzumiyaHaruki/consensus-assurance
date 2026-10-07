# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 领导权转移失败后自动退出联合配置缺少重试触发 | 已确认违反 | 实际检查中，转移超时后节点仍停留在索引 5 的联合配置；随后 10 个 tick 完成 40 条心跳消息和 30 个 Ready 批次，完整行为状态再次相同，自动退出未获触发。另行提交普通提案后才推进至索引 7 并退出联合配置；该结果限于已核对的稳定领导者与空闲调度，不主张安全性破坏或固定时间期限。 | [C-auto-leave-continuation](#claim-C-auto-leave-continuation) |

<a id="claim-C-auto-leave-continuation"></a>

### 1. 领导权转移失败后自动退出联合配置缺少重试触发

**已确认违反**。要求原文：After a committed implicit-joint configuration has been applied and acknowledged, a retained eligible leader must preserve automatic continuation to propose leaving joint consensus when a temporary leadership-transfer blocker clears. With stable authority, available joint quorum, fair ticks, delivery and completed Ready processing, it must not enter an indefinitely repeatable idle state with AutoLeave still pending solely because no unrelated client proposal arrives.

决定性范围：Implementation-owned automatic joint-exit continuation after failed leadership transfer; normal serialized RawNode Ready/Advance operation with no crashes or storage failure.
Committed entering configuration is genuinely applied before Advance.；The same eligible leader retains authority and both constituent quorums remain available.；A bounded loss of transfer-trigger traffic is allowed; all subsequent traffic is delivered and all required Ready work completes.；No further client proposal, manual leave, forced election, restart or configuration cancellation is owed by the caller solely to implement implicit automatic exit.。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：领导权转移失败后自动退出联合配置缺少重试触发；实际检查中，转移超时后节点仍停留在索引 5 的联合配置；随后 10 个 tick 完成 40 条心跳消息和 30 个 Ready 批次，完整行为状态再次相同，自动退出未获触发。另行提交普通提案后才推进至索引 7 并退出联合配置；该结果限于已核对的稳定领导者与空闲调度，不主张安全性破坏或固定时间期限。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/563626623cf144f5a145827eb45c0351/assurance_generated_test.go)；[条件与检查器](direct-checks/563626623cf144f5a145827eb45c0351/plan.json)；[原始观察](logs/e30e751a96ef45c8b43640539253ffe4/stdout.log)；[assessment](direct-checks/563626623cf144f5a145827eb45c0351/e30e751a96ef45c8b43640539253ffe4-assessment.json)；[对应性复核](submissions/fa101f4c2390469ab505fd65502b8e7f/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 16.25 秒；执行进程耗时 14.86 秒；[实际命令、工具版本与输入记录](logs/e30e751a96ef45c8b43640539253ffe4/check.json)
执行边界：Serialized three-node RawNode driver with actual Ready persistence/application and actual peer traffic; read-only recursive state observer and explicit post-result rescue.；No target code or protocol state mutations outside public API and required Storage writes.；Adds only read-only observation and a bounded transport loss policy for TimeoutNow.
固定比较 `CK-no-idle-cycle`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation_id | remove-node3-implicit-1 |
| event | cycle_result |
| forbidden_idle_cycle | true |
| admitted.scenario | failed_transfer_idle |
| admitted.triggered | true |
| admitted.transferee | 2 |
| admitted.dropped_timeout_now | 1 |
| admitted.role | StateLeader |
| admitted.drained | true |
| admitted.all_applied_config | true |
| admitted.config.auto_leave | true |
| apply_delta | 0 |
| config_index | 5 |
| drained | true |
| joint_pending | true |
| message_delta | 40 |
| only_heartbeats | true |
| ready_delta | 30 |
| roles_stable | true |
| same_state | true |
| scenario | failed_transfer_idle |
| snapshot | str，8842 字符；首尾预览：{"nodes":[{"type":"*raft.RawNode","value":{"asyncS…e,"schedule_phase":0,"triggered":true},"queue":[]}；[e30e751a96ef45c8b43640539253ffe4 / event[5] / snapshot](logs/e30e751a96ef45c8b43640539253ffe4/stdout.log) |
| tick | 30 |
| transferee | 0 |
| unchanged_tail | true |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：For candidate c1ba7e9ff9034a728850b297376ecbb8, does a real three-node RawNode history retain AutoLeave joint state after the last application acknowledgment overlaps a bounded failed transfer,…
[受理问题、条件与来源](submissions/6d4aab0eee924d288f53b734a9af2cc3/accepted.json)；[固定输入](submissions/6d4aab0eee924d288f53b734a9af2cc3/inputs/transfer_explore_test.go)
<a id="exploration-c9ed902712d346bb8321e3b863234579"></a>
[探索执行 1](#exploration-c9ed902712d346bb8321e3b863234579)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/c9ed902712d346bb8321e3b863234579/check.json)；[实际输出](logs/c9ed902712d346bb8321e3b863234579/stdout.log)；[诊断](logs/c9ed902712d346bb8321e3b863234579/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 17.35 秒；执行进程耗时 15.95 秒；[实际命令、工具版本与输入记录](logs/c9ed902712d346bb8321e3b863234579/check.json)
[执行输入文件清单](experiments/174e3ffec8f841bdbd02def9adf11315/workspace-delta/manifest.json)
[执行后文件清单](experiments/174e3ffec8f841bdbd02def9adf11315/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-563626623cf144f5a145827eb45c0351)

<a id="exploration-feedback-563626623cf144f5a145827eb45c0351"></a>
[交接 1](#exploration-feedback-563626623cf144f5a145827eb45c0351) · 后续说明；关联：[探索执行 1](#exploration-c9ed902712d346bb8321e3b863234579)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration c9ed902712d346bb8321e3b863234579 completed with exit 0. The entering config at index 5 was applied/acknowledged with node 1 leader in term 2 and transferee 2. Exactly one TimeoutNow was dropped. At tick 10 transferee cleared; through ticks 20 and…
[完整交接；精确引用不表示已解决或已正式化](submissions/563626623cf144f5a145827eb45c0351/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns term/index to proposals, emits log appends and defers its self-ack until persistence. Followers check predecessor identity, preserve committed entries, append the uncommitted suffix and return…
- 上下文／权威转换（原文导航摘录）：Election starts only from a promotable instance with no committed unapplied configuration. PreVote probes without raising term; real campaign increments term and counts persisted self/peer votes using current voter sets…
- 两条主线的连接（原文导航摘录）：A2 qualifies whose A1 support can be consumed: term dispatch and reset prevent a new leader from aggregating old-term replication replies, and the current-term entry requirement ties retained older log history to fresh…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 11.20 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 14.55 分钟 · 实际执行：Construct the selected legal overlap before fixing a progress oracle. Bootstrap all real nodes, persist every Ready, apply committed…；探索执行正常结束。[执行记录](logs/c9ed902712d346bb8321e3b863234579/check.json)

- 21.39 分钟 · 受理 check：The actual exploration reached the discriminator. Submit a fresh fixed check for a repeatable idle-cycle witness rather than converting its…。[完整交接](submissions/563626623cf144f5a145827eb45c0351/accepted.json)

- 21.66 分钟 · 实际执行：领导权转移失败后自动退出联合配置缺少重试触发；执行完成；比较见 assessment。[执行记录](logs/e30e751a96ef45c8b43640539253ffe4/check.json)

- 26.42 分钟 · 受理 review：领导权转移失败后自动退出联合配置缺少重试触发；v1 checker_correspondence: no_issue_found。[完整交接](submissions/fa101f4c2390469ab505fd65502b8e7f/accepted.json)

- 28.71 分钟 · 受理 research：Update the initial map at the natural handoff after an accepted reviewed finding, and retain substantive source-only progress on a…。[完整交接](submissions/3f3973e30d3344f09f0da8468201a2e1/accepted.json)

- 29.99 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e1db8dfb7be644d7ad4489a019813413/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<details><summary>地图登记与研究交接</summary>

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Whether configuration-triggered commitment can be the first current-term commit with pending reads, despite campaign restrictions.；Early-Advance configuration ordering, detailed membership/removal…
  尚无精确对应交接。

- B-application：The Node interface permits Advance while commands are still applying, whereas RawNode.Advance describes completed application. Whether early Advance may precede ApplyConfChange, rather than only the…
  相关交接：[交接 1](submissions/fa101f4c2390469ab505fd65502b8e7f/accepted.json)；[交接 2](submissions/3f3973e30d3344f09f0da8468201a2e1/accepted.json)

- surface:Node.Advance before finishing application / ApplyConfChange：Node.Advance permits overlap with ongoing application and Node.run handles advancec independently from confc. RawNode.Advance nevertheless records applied progress; hup then scans only beyond that…
  尚无精确对应交接。

- surface:rafttest.InteractionEnv storage/transport drivers：InteractionEnv wraps RawNode nodes, messages and test handlers. Detailed storage/transport handlers remain unread; no helper legality or scheduling guarantees are assumed.
  尚无精确对应交接。

- surface:Production network/disk/business application：Library boundary explicitly delegates IO and application; only sourced caller contracts, not a deployment implementation, are available.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、34 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.14 | 0.00 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 30.81 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 33.60 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/e1db8dfb7be644d7ad4489a019813413/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`76.61319153200748`（配置值不表示触发了超时）。
[调用记录](logs/e1db8dfb7be644d7ad4489a019813413/check.json)；[stdout](logs/e1db8dfb7be644d7ad4489a019813413/stdout.log)；[stderr](logs/e1db8dfb7be644d7ad4489a019813413/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

