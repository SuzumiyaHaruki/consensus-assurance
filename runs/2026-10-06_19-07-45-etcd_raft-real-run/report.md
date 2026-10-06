# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**；实际持续 **14.59 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| When application completion attempts to leave an implicit joint configuration during a leadership transfer, does the same leader… | 研究中，尚无正式义务 | Does ordinary heartbeat-only Ready/Advance processing after timeout invoke appliedTo when it has no committed entries?；Construct one legal prefix with the joint entry… | [候选 1](#candidate-b406ba950f364d4fa655df71ee01c72d) |

条件探索：For candidate b406ba950f364d4fa655df71ee01c72d, does applying the final implicit joint entry while transfer to node 2 is active leave AutoLeave pending after transfer timeout under delivered…
[受理问题、条件与来源](submissions/530d80599e5f469e82c34b237a10c051/accepted.json)；[固定输入](submissions/530d80599e5f469e82c34b237a10c051/inputs/transfer_explore_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-b406ba950f364d4fa655df71ee01c72d)
<a id="exploration-d47915a0d7364bf9b9e4b650140450ce"></a>
[探索执行 1](#exploration-d47915a0d7364bf9b9e4b650140450ce)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/d47915a0d7364bf9b9e4b650140450ce/check.json)；[实际输出](logs/d47915a0d7364bf9b9e4b650140450ce/stdout.log)；[诊断](logs/d47915a0d7364bf9b9e4b650140450ce/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 16.99 秒；执行进程耗时 15.60 秒；[实际命令、工具版本与输入记录](logs/d47915a0d7364bf9b9e4b650140450ce/check.json)
[执行输入文件清单](experiments/8153aa22a9c242dcbe305ad6762f7326/workspace-delta/manifest.json)
[执行后文件清单](experiments/8153aa22a9c242dcbe305ad6762f7326/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns index and term to accepted proposals and queues a self acknowledgement behind persistence. Followers verify the predecessor term, replace only an uncommitted conflicting suffix, and return append…
- 上下文／权威转换（原文导航摘录）：Tick or explicit campaign begins an election only for an eligible voter without pending snapshots or committed unapplied configuration changes. Vote choice is conditioned on local vote/leader state and candidate log…
- 两条主线的连接（原文导航摘录）：Applied voter membership supplies both election and replication quorum meaning. A new leader resets peer Match and conservatively postpones new configuration changes until its inherited log tail is applied; its empty…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.26 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 9.13 分钟 · 受理 explore：Resolve whether normal Ready/Advance and heartbeat continuation retries a rejected implicit joint exit using real RawNode peers and one…。[完整交接](submissions/530d80599e5f469e82c34b237a10c051/accepted.json)

- 9.40 分钟 · 实际执行：Resolve whether normal Ready/Advance and heartbeat continuation retries a rejected implicit joint exit using real RawNode peers and one…；探索执行正常结束。[执行记录](logs/d47915a0d7364bf9b9e4b650140450ce/check.json)

- 14.58 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e331a25023474d6da98d7aca93946954/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [b406ba950f364d4fa655df71ee01c72d](research.json)：[候选 1](#candidate-b406ba950f364d4fa655df71ee01c72d)

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-d47915a0d7364bf9b9e4b650140450ce)

<a id="candidate-b406ba950f364d4fa655df71ee01c72d"></a>

研究中问题：When application completion attempts to leave an implicit joint configuration during a leadership transfer, does the same leader retain an implementation-owned continuation after the transfer times out, or can the active AutoLeave configuration remain without an exit proposal unless unrelated client work arrives?
[候选原文与历史](state.json)
保存的语义未知：Does ordinary heartbeat-only Ready/Advance processing after timeout invoke appliedTo when it has no committed entries?；Construct one legal prefix with the joint entry fully committed and applied, transfer still active at its completion callback, and no guaranteed later application work.；Determine the precise automatic-exit duty and scheduling assumptions without inventing a numeric deadline.
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-d47915a0d7364bf9b9e4b650140450ce)

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Automatic exit continuation after a failed leadership transfer with no new client proposals.；AutoLeave representation in status copies.；Legal reachability of pending-read release differences at…
  尚无精确对应交接。

- B_context_reset：Determine whether retained pre-commit read requests can affect semantics after authority changes; no violation inferred from retention.
  尚无精确对应交接。

- B_application：Does caller-owned ordinary Ready processing guarantee another appliedTo callback after a transfer rejects the only automatic exit attempt?
  尚无精确对应交接。

- B_configuration：Reachability of a first-current-term commitment caused by switchToConfig while an earlier read is pending needs history analysis.
  尚无精确对应交接。

- F_config：Configuration export via Clone may omit AutoLeave without changing the active tracker.
  尚无精确对应交接。

- surface:tracker.Config.Clone -> getStatus：Clone copies voter/learner maps but omits AutoLeave; getStatus uses the clone. Active Changer EnterJoint explicitly sets AutoLeave and LeaveJoint clears it, so export loss must not be conflated with…
  尚无精确对应交接。

- surface:raft.switchToConfig -> maybeCommit：Configuration-driven commit does not release pending pre-first-commit reads; legal reachability must account for the campaign guard against unapplied committed configuration entries.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 0 项、义务 0 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1524.88 秒、37 次 Agent 调用、15 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 875.12 | 1524.88 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 15.60 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 16.99 秒。

目标执行组成：正式检查 0 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v55`；展示版本 `audit-products-v55`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/e331a25023474d6da98d7aca93946954/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/e331a25023474d6da98d7aca93946954/check.json)；[stdout](logs/e331a25023474d6da98d7aca93946954/stdout.log)；[stderr](logs/e331a25023474d6da98d7aca93946954/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

