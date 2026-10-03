# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。本轮有 0 项已产生观察的正式问题：已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项、探索执行 0 次。正式义务共 1 项，执行次数不等于问题数。

实际持续 **19.41 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1235.10 秒、35 次 Agent 调用、16 次控制器目标执行。源码调查能力：仍有预算。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1164.90 | 1235.10 |
| Agent 调用 | 40 | 5 | 35 |
| 控制器目标执行 | 16 | 0 | 16 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 0 次＋探索 0 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v42`；展示版本 `audit-products-v42`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`。
[调用记录](logs/5d086c8518e24784939d9ba7cb47cf30/check.json)；[stdout](logs/5d086c8518e24784939d9ba7cb47cf30/stdout.log)；[stderr](logs/5d086c8518e24784939d9ba7cb47cf30/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

尚无正式性质判定；已保存的整体理解与条件探索见下文，不能据此断言目标没有问题。

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader admits proposals, assigns term/index and emits append requests. Followers match predecessors, protect committed prefixes and defer append support until persistence. Leader tracks qualified replies and selects the…
- 上下文／权威转换（原文导航摘录）：Campaigns require promotable membership and scan committed entries after applied for pending configurations. Real campaigns persist votes, aggregate eligible votes and elect an up-to-date leader; pre-vote preserves the…
- 两条主线的连接（原文导航摘录）：Election log freshness and persistent term/vote constrain who may form future decisions; current-term commit and active voter quorums constrain advancement by that leader. Configurations take effect via ApplyConfChange,…

- 01:59:00 +0000（距创建墙钟 596.4 秒，含暂停间隔）；Agent 回合墙钟 379.17 秒 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 02:01:39 +0000（距创建墙钟 755.5 秒，含暂停间隔）；Agent 回合墙钟 158.96 秒 · 认识／制品更新：For the early-Advance Candidate, nextEnts in raft_test.go persists unstable entries, runs delayed messages and advances raftLog.applied but does not apply configuration entries. The campaign test…。[完整交接](submissions/f5155f7b4c874617bf9ad48729356f30/accepted.json)

- 02:07:07 +0000（距创建墙钟 1083.2 秒，含暂停间隔）；Agent 回合墙钟 327.68 秒 · 认识／制品更新：Fix the safe-read responsibility for a supported learner demotion and construct a correlated endpoint next; source observations are not yet a violation.。[完整交接](submissions/621b6faa1e4442d2a73d83d3586e2ba9/accepted.json)

- 02:08:28 +0000（距创建墙钟 1164.3 秒，含暂停间隔）；Agent 回合墙钟 80.92 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/5d086c8518e24784939d9ba7cb47cf30/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-claim-safe-read-after-demotion](research.json)：

候选：When Node.Advance is used before application finishes, can raftLog.applied cause campaign admission to skip a committed configuration entry whose ApplyConfChange is still pending, and what caller obligation or alternative mechanism prevents stale-membership authority?
保存的语义未知：Resolve whether the general Node.Advance overlap permission includes a committed configuration still awaiting ApplyConfChange; RawNode completion wording and the membership callback duty point toward stricter ordering.；The existing campaign test uses nextEnts, which advances applied without ApplyConfChange and thus does not settle actual configuration completion or legal delayed callback history.
恢复条件：A captured applicable contract or caller path establishes that configuration-bearing Ready batches may be advanced before ApplyConfChange, or explicitly excludes this overlap.
[候选原文与历史](state.json)

候选：Can a leader demoted to learner with StepDownOnRemoval=false incorrectly authorize a ReadOnlySafe read via the singleton-voter shortcut, after the surviving voter has completed later writes?
保存的语义未知：Can a complete API-driven demotion history retain the old leader without an unrelated message stepping it down before read admission?；Can bounded delivery advance the learner strictly past the returned index while leaving writes completed before read admission unapplied, producing an actual stale register read?
恢复条件：
[候选原文与历史](state.json)

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Applicability of early Advance before committed membership application and its effect on campaign eligibility.；Contract conflict on synchronous same-batch send/persist overlap.；Pending reads retained…
  尚无精确对应交接；保留地图原问，不推断解决或新增欠账。

- b-authority：Does permitted early Node.Advance allow the election configuration scan to omit configuration work still awaiting ApplyConfChange?
  已有精确引用的研究交接，登记项未自动消除：[f5155f7b4c874617bf9ad48729356f30](submissions/f5155f7b4c874617bf9ad48729356f30/accepted.json)

- b-persistence：README/doc.go permit same-batch send/persist overlap while Ready requires entries before messages; which usage contract governs that overlap remains disputed.
  尚无精确对应交接；保留地图原问，不推断解决或新增欠账。

- b-application：Whether early Advance excludes configuration-containing batches is not stated in the read Node contract; stricter RawNode wording and tests must be reconciled.
  已有精确引用的研究交接，登记项未自动消除：[f5155f7b4c874617bf9ad48729356f30](submissions/f5155f7b4c874617bf9ad48729356f30/accepted.json)

- b-reads：Can configuration-driven first current-term commitment occur under any legal early-Advance history, leaving precommit requests queued without a later advancement? No bounded completion obligation is…
  已有精确引用的研究交接，登记项未自动消除：[f5155f7b4c874617bf9ad48729356f30](submissions/f5155f7b4c874617bf9ad48729356f30/accepted.json)

- f-applied：Does the caller contract permit advancing the cursor past committed membership entries before ApplyConfChange, and if so what protects elections during the interval?
  尚无精确对应交接；保留地图原问，不推断解决或新增欠账。

- surface:Ready synchronous message persistence ordering：README and doc.go overlap permission conflicts with stronger Ready ordering. Preserve conflicting contracts before any executable allegation.
  尚无精确对应交接；保留地图原问，不推断解决或新增欠账。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
