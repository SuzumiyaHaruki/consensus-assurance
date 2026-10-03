# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 0 项。已产生观察的正式结论 0 项：已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **21.07 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1136.09 秒、34 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1263.91 | 1136.09 |
| Agent 调用 | 40 | 6 | 34 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 0 次＋探索 2 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v45`；展示版本 `audit-products-v45`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/8aa631098e324c06a8d2101ce7421e84/check.json)；[stdout](logs/8aa631098e324c06a8d2101ce7421e84/stdout.log)；[stderr](logs/8aa631098e324c06a8d2101ce7421e84/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| <a id="claim-C_snapshot_predecessor"></a>After a valid snapshot has successfully installed and restored through the receiver previous log end, predecessor validation for… | 尚无正式判定 | 义务已受理，尚无固定检查记录 | [C_snapshot_predecessor](state.json)；[候选 1](#candidate-8012be5b808d46bfbb71c0c47cd30b64) |

条件探索：After successful installSnapshot at the same index as an existing last log but a different term, does the next same-leader AppendEntries naming the installed snapshot index/term succeed? Compare…
所选问题／策略（原文摘录）：A smaller snapshot-boundary experiment can distinguish stale cached term selection from successful resynchronization. This is conditional construction knowledge: receiver logs and snapshot metadata are explicitly seeded, not attributed to…
[受理问题、条件与来源](submissions/19f4b1fa6aec47489e743d6bc11cc591/accepted.json)；[固定输入](submissions/19f4b1fa6aec47489e743d6bc11cc591/inputs/snapshot_boundary_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/a42d3ee47c6b4e059143ba6a673e116d/check.json)；[实际输出](logs/a42d3ee47c6b4e059143ba6a673e116d/stdout.log)；[诊断](logs/a42d3ee47c6b4e059143ba6a673e116d/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/a42d3ee47c6b4e059143ba6a673e116d/check.json)
[执行文件清单](experiments/5f91b3efee094ad9a00040f611141465/workspace-delta/manifest.json)；[执行文件清单](experiments/5f91b3efee094ad9a00040f611141465/workspace-outcome/manifest.json)；[执行文件清单](experiments/5f91b3efee094ad9a00040f611141465/workspace/assurance_generated_test.go)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/5dd558f0106c406394415d365d8bc26e/accepted.json)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

条件探索：After an actually completed successful snapshot installation at index 5 term 2, does an append naming that boundary succeed when the retained last log at index 5 has term 1 versus term 2? This…
所选问题／策略（原文摘录）：Repair the failed exploration prerequisite: defer r.Shutdown().Error() evaluated Shutdown immediately. A deferred closure postpones shutdown until after observations; explicit restore-success checks prevent an unreached setup from being…
[受理问题、条件与来源](submissions/5dd558f0106c406394415d365d8bc26e/accepted.json)；[固定输入](submissions/5dd558f0106c406394415d365d8bc26e/inputs/snapshot_boundary_explore_v2_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/8f3ac3661a174dd782bc8d6f1ef5dacc/check.json)；[实际输出](logs/8f3ac3661a174dd782bc8d6f1ef5dacc/stdout.log)；[诊断](logs/8f3ac3661a174dd782bc8d6f1ef5dacc/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；[实际命令、工具版本与输入记录](logs/8f3ac3661a174dd782bc8d6f1ef5dacc/check.json)
[执行文件清单](experiments/2c2fcec0d6f0437886f5020b2b271763/workspace-delta/manifest.json)；[执行文件清单](experiments/2c2fcec0d6f0437886f5020b2b271763/workspace-outcome/manifest.json)；[执行文件清单](experiments/2c2fcec0d6f0437886f5020b2b271763/workspace/assurance_generated_test.go)
执行后精确引用交接：[受理解释；不是本次独立观察](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

后续受理解释（关联 2 次执行）：Repaired CheckRun 8f3ac3661a174dd782bc8d6f1ef5dacc completed successful install and actual restore in both cases. With old log index 5 term 1 and installed snapshot index 5 term 2, getLastEntry remained (5,1), append_success=false and last index stayed 5.…
[完整交接；精确引用不表示已解决或已正式化](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader stamps admitted commands with term/index and stores them. Local storage and successful peer append/snapshot replies report match indexes into a tenure-owned object. Latest voters supply majority support, gated by…
- 上下文／权威转换（原文导航摘录）：Contact timeout starts eligible voter campaigning, optionally via pre-vote. Durable term/vote records, membership and lexicographic log freshness govern voting; campaign-local channels aggregate granted votes. New…
- 两条主线的连接（原文导航摘录）：Log freshness protects the history carried into new authority; persistence and snapshot restoration retain history across restart. A new tenure does not reuse the old quorum tracker: old replies reference old objects,…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.44 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 12.08 分钟 · 受理 explore：A smaller snapshot-boundary experiment can distinguish stale cached term selection from successful resynchronization. This is conditional…。[完整交接](submissions/19f4b1fa6aec47489e743d6bc11cc591/accepted.json)

- 12.26 分钟 · 实际执行：A smaller snapshot-boundary experiment can distinguish stale cached term selection from successful resynchronization. This is conditional…；条件观察完成。[执行记录](logs/a42d3ee47c6b4e059143ba6a673e116d/check.json)

- 14.13 分钟 · 实际执行：Repair the failed exploration prerequisite: defer r.Shutdown().Error() evaluated Shutdown immediately. A deferred closure postpones…；条件观察完成。[执行记录](logs/8f3ac3661a174dd782bc8d6f1ef5dacc/check.json)

- 18.57 分钟 · 受理 obligation：Fix a sourced snapshot predecessor-consumption responsibility after a completed conditional exploration, keeping unexecuted whole-history…。[完整交接](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

- 21.06 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/8aa631098e324c06a8d2101ce7421e84/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／争议仍有待办：
- [unit-C_snapshot_predecessor](research.json)：[C_snapshot_predecessor](#claim-C_snapshot_predecessor)；具体进度与缺口见对应义务

<a id="candidate-8012be5b808d46bfbb71c0c47cd30b64"></a>

研究中问题：After successful valid InstallSnapshot covers the receiver last-log index, must an otherwise valid current-term AppendEntries with PrevLogEntry at that boundary validate against the installed snapshot term rather than an obsolete retained log term?
[候选原文与历史](state.json)
保存的语义未知：Formal execution still needs fixed artifacts and legal-history correspondence; exploratory seeded metadata does not execute majority formation.；Automatic sender retry and wider system endpoint are not established by the isolated receiver experiment.

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Follower commit-boundary question retains ordinary backtracking counterevidence; recovery histories remain distinct.；Installed snapshot boundary can conflict with equal-index cached log term;…
  尚无精确对应交接。

- B_election：Crash/error behavior between the separate vote-term and vote-candidate writes is not yet resolved.
  尚无精确对应交接。

- B_replicate：Can a legal history leave nextIndex before an already matching prefix with a divergent suffix when a later request advertises commitment beyond its bounded batch? Backtracking may exclude the simple…
  相关交接：[交接 1](submissions/19f4b1fa6aec47489e743d6bc11cc591/accepted.json)

- B_follower_append：Whether producer history always makes the local-last-index commitment bound safe when an incoming batch ends before a retained suffix.；DeleteRange success followed by StoreLogs failure leaves the…
  相关交接：[交接 1](submissions/19f4b1fa6aec47489e743d6bc11cc591/accepted.json)；[交接 2](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

- B_membership：Public AddVoter API promises staging until ready; ConfigurationChangeCommand documentation and configuration tests explicitly specify direct Voter creation. The proposal alone is not authoritative;…
  尚无精确对应交接。

- B_recovery：When a snapshot supersedes the cached last log at an equal index with a different term, can the sender repair subsequent rejection without another state change?；Administrative user restore and…
  相关交接：[交接 1](submissions/19f4b1fa6aec47489e743d6bc11cc591/accepted.json)；[交接 2](submissions/5dd558f0106c406394415d365d8bc26e/accepted.json)；[交接 3](submissions/0865eab1b0c14c7885e71701b21018e2/accepted.json)

- B_history：External durable backend behavior on partial errors is unspecified by these observations; InmemStore is explicitly test-only.
  尚无精确对应交接。

- F_follower_commit：Does the composed sender/retry/history mechanism exclude a divergent retained suffix below this selected bound?
  尚无精确对应交接。

- F_snapshot_boundary：Whether all consumers honor the installed boundary when physically retained old entries conflict.
  尚无精确对应交接。

- surface:Raft administrative restore/recovery：Caller-authorized history replacement and disaster recovery need separate contract analysis; ordinary snapshot transfer is mapped.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
