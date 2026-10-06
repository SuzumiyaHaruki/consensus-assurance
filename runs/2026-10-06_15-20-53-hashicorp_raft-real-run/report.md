# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 0 项。正式执行尝试 0 次；已保存评估的义务 0 项，其中有实际比较 0 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **11.97 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1681.99 秒、37 次 Agent 调用、8 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 718.01 | 1681.99 |
| Agent 调用 | 40 | 3 | 37 |
| 控制器目标执行 | 8 | 0 | 8 |
| 新 Unit | 4 | 1 | 3 |
| 语义复核 | 6 | 0 | 6 |
| 修订 | 4 | 0 | 4 |

受控目标执行进程耗时（正式检查＋探索）：已记录 0.00 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 0.00 秒。

目标执行组成：正式检查 0 次＋探索 0 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v54`；展示版本 `audit-products-v54`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/835d9e74c0024a0cb317f415a793c5cf/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/835d9e74c0024a0cb317f415a793c5cf/check.json)；[stdout](logs/835d9e74c0024a0cb317f415a793c5cf/stdout.log)；[stderr](logs/835d9e74c0024a0cb317f415a793c5cf/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| <a id="claim-C-verify-current-authority"></a>In a fixed cluster configuration, a VerifyLeader invocation on a former leader must not return success when, before that… | 尚无正式判定 | 义务已受理，尚无固定检查记录 | [C-verify-current-authority](state.json)；[候选 1](#candidate-59a161bafed9415daefcfa3b835fa20e) |

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns term/index and stores each entry before self match. Per-peer replicators send bounded batches with previous index/term and leader commit index; rejection backs nextIndex down, missing history sends a…
- 上下文／权威转换（原文导航摘录）：Contact loss permits a configured voter to pre-vote and then persist a new term and self vote. Candidate attempts own independent reply channels, solicit voters and tally a majority. Vote receivers enforce eligibility,…
- 两条主线的连接（原文导航摘录）：Prior persistent entries and snapshot state survive leadership changes and constrain elections through last index/term comparisons. Old volatile support is isolated in old per-attempt channels and old commitment…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 5.22 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 7.56 分钟 · 受理 obligation：Ground the authority-confirmation responsibility in the public VerifyLeader contract, using actual server-local configuration and routing…。[完整交接](submissions/60718311051949eca810839bafc10858/accepted.json)

- 11.96 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/835d9e74c0024a0cb317f415a793c5cf/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项


已选检查／复核待办：
- [unit-C-verify-current-authority](research.json)：[C-verify-current-authority](#claim-C-verify-current-authority)；具体进度与缺口见对应义务

<a id="candidate-59a161bafed9415daefcfa3b835fa20e"></a>

研究中问题：Can positive responses from nonvoter replication peers satisfy VerifyLeader while a voter quorum has not confirmed the current authority, and does the independently scheduled voter lease check prevent this result from being exposed?
[候选原文与历史](state.json)
保存的语义未知：A production execution must establish the stable mixed configuration, a higher-term leader and its committed command before verification admission, then observe the same VerifyLeader future result.；The controlled schedule must account for pre-partition in-flight replies before attributing false confirmation specifically to nonvoters.

### 地图登记与研究交接

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：VerifyLeader peer eligibility versus voter threshold and lease protection.；Follower commit bound and legal partial-prefix histories.；Fast-path heartbeat concurrency and transport ordering.；Storage…
  尚无精确对应交接。

- B-replication：Legal histories that might leave a divergent follower suffix beyond a successful bounded AppendEntries request remain to be analyzed.
  尚无精确对应交接。

- B-append-receiver：Heartbeat dispatch concurrency and transport classifier boundaries require separate examination.；Whether producer/backtracking history makes every retained suffix below LeaderCommitIndex eligible is…
  尚无精确对应交接。

- B-recovery：User-forced restore and manual RecoverCluster have distinct semantics not yet traced.
  尚无精确对应交接。

- B-verify-register：Why nonvoter replication peers are included in an authority confirmation whose threshold is voter-based.
  相关交接：[交接 1](submissions/60718311051949eca810839bafc10858/accepted.json)

- surface:appendEntries commit bound：The receiver bounds commit by local lastIndex rather than last entry in this request. Producer nextIndex initialization and backwards search may guarantee the unmatched suffix is removed on first…
  尚无精确对应交接。

- surface:appendEntries storage failure after truncation：Code notes stale lastLog after StoreLogs fails following DeleteRange. Fault contract, store failure semantics and future consumers need reading.
  尚无精确对应交接。

- surface:processHeartbeat transport fast path：Constructor permits concurrent fast path despite handler main-thread comment. Need concrete transport classifier and shared-state synchronization before alleging concurrent authority transition…
  尚无精确对应交接。

- surface:restoreUserSnapshot / RecoverCluster：Separate forced-history APIs identified through API and leader-loop dispatch; caller duties and full implementations not yet traced.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
