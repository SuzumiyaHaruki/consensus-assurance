# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。本轮有 0 项已产生观察的正式问题：已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有源码解释 0 项、探索执行 1 次。正式义务共 0 项，执行次数不等于问题数。

实际持续 **36.08 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 2634.92 秒、36 次 Agent 调用、15 次控制器目标执行。源码调查能力：仍有预算。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 4800.0 | 2165.08 | 2634.92 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 16 | 1 | 15 |
| 新 Unit | 6 | 0 | 6 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |
| 模型工具 | 6 | 0 | 未启用 |

目标执行组成：正式检查 0 次＋探索 1 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
模型检查：未使用 TLA+／TLC。新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v36`；展示版本 `audit-products-v36`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

## 主要结果

| 问题 | 当前结果 | 实际回答摘录 | 证据 |
| --- | --- | --- | --- |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：RawNode.Propose or serialized Node loop enters the role-specific state machine. A leader admits entries, assigns term/index and appends locally; a follower forwards only with leader knowledge and enabled forwarding,…
- 上下文／权威转换（原文导航摘录）：An election timeout or Campaign starts only for a locally eligible nonlearner without pending snapshot or unapplied committed configuration. Pre-vote leaves term/vote unchanged; real campaign increments term and queues…
- 两条主线的连接（原文导航摘录）：Authority reset clears tally, peer Match, and heartbeat read acknowledgments but preserves log and committed/application positions; old uncommitted entries can be replaced only above committed. Current-term entry…

- 05:42:05 +0000 · research：The inspected RawNode entry is explicitly thread-unsafe and sends Propose into raft.Step; a returned proposal call is not an observed commit or application. Followers forward only with a known leader and forwarding enabled; candidates reject proposals; leaders reject proposals during transfer or after losing their own Progress…（记录摘录；调查回执时间，不是目标执行耗时）。[完整交接](submissions/92b25a38705b47deb8c85bbeffd0dda0/accepted.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

**开放责任：Ready.Messages persistence ordering**

已知／缺口：Package guide allows same-batch entry writes concurrent with message sends; Ready.Messages states after stable append. Preserve conflict for entry-specific caller policy investigation.
Package guide allows same-batch entry writes concurrent with message sends; Ready.Messages states after stable append. Preserve conflict for entry-specific caller policy investigation.
下一步尚未记录；需补适用来源或具体判别。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)；

**开放责任：ReadIndex context retries**

已知／缺口：Version-qualified retry permission and context-keyed pending map need correspondence analysis before an oracle is selected.
Version-qualified retry permission and context-keyed pending map need correspondence analysis before an oracle is selected.
下一步尚未记录；需补适用来源或具体判别。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)；

**开放责任：MemoryStorage.Compact**

已知／缺口：Caller must restrict compaction to applied prefix; detailed backend retention/read interplay not mapped.
Caller must restrict compaction to applied prefix; detailed backend retention/read interplay not mapped.
下一步尚未记录；需补适用来源或具体判别。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)；

独立探索：With a real election/proposal/append prefix and unchanged follower HardState, does sending an actual synchronous follower Ready MsgAppResp before appending its same-batch entries cause leader Match…；[实际输出](logs/2343c66b8d6141379d7caf3e48fce461/stdout.log)；[诊断](logs/2343c66b8d6141379d7caf3e48fce461/stderr.log)。条件观察完成，不是正式性质结论。
历史处置摘录：未保存明确后续归属；不自动生成当前待办。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。模型结果与实现证据分开，脚本化 Agent 产品不证明自主发现。
