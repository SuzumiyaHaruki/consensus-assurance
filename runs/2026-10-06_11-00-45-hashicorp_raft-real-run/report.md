# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**。已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 2 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数；确认项数按义务命题计，不等于独立根因数。

实际持续 **20.58 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 1165.20 秒、32 次 Agent 调用、5 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1234.80 | 1165.20 |
| Agent 调用 | 40 | 8 | 32 |
| 控制器目标执行 | 8 | 3 | 5 |
| 新 Unit | 4 | 1 | 3 |
| 语义复核 | 6 | 2 | 4 |
| 修订 | 4 | 1 | 3 |

受控目标执行进程耗时（正式检查＋探索）：已记录 37.34 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 38.78 秒。

目标执行组成：正式检查 2 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v53`；展示版本 `audit-products-v53`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/e336c8b437284b1da04f745b473df73a/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/e336c8b437284b1da04f745b473df73a/check.json)；[stdout](logs/e336c8b437284b1da04f745b473df73a/stdout.log)；[stderr](logs/e336c8b437284b1da04f745b473df73a/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 非投票节点响应被计入领导权验证门槛 | 已确认违反 | 单节点 bootstrap 修复后的固定执行中，VerifyLeader 仍返回成功；合格投票支持为 1，所需门槛为 2，唯一正响应来自非投票节点。该结果支持局部投票资格计数缺陷；未测得第二个领导者或陈旧读取。 | [C-verify-eligible](#claim-C-verify-eligible) |

<a id="claim-C-verify-eligible"></a>

### 1. 非投票节点响应被计入领导权验证门槛

**已确认违反**。要求原文：In a fixed valid configuration, a leader verification that completes successfully by reaching its voter-derived quorum threshold must have support from a majority of configured voters (including the local voter); positive confirmations from configured nonvoters must not substitute for missing voter support.

决定性范围：Membership eligibility of the quorum-confirmation procedure backing VerifyLeader, within one elected leader tenure and fixed membership.
Correct real RPC handlers and reliable in-memory storage；Network may fail requests to selected voters while nonvoter is reachable；Finite scheduling may delay follower election timers; leader lease remains enabled。

[完整要求、假设与排除范围](state.json)

制品 v2；对应性意见：no_issue_found。
[固定测试](direct-checks/07ccd38b81c94aaaa9e8a6ca1926871c/assurance_generated_test.go)；[条件与检查器](direct-checks/07ccd38b81c94aaaa9e8a6ca1926871c/plan.json)；[原始观察](logs/7799a8fae1504918a40da305dff580be/stdout.log)；[assessment](direct-checks/07ccd38b81c94aaaa9e8a6ca1926871c/7799a8fae1504918a40da305dff580be-assessment.json)；[对应性复核](submissions/eeab3468911b46018f8840b07641d25f/accepted.json)

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 12.91 秒；执行进程耗时 12.38 秒；[实际命令、工具版本与输入记录](logs/7799a8fae1504918a40da305dff580be/check.json)
执行边界：Single voter bootstrap with the full three-voter/one-nonvoter configuration; three other NewRaft instances start with checked empty stores. The actual election and remaining verification driver are unchanged.；skipStartup and manual follower RPC pumps select a bounded schedule with follower election timers delayed；Transport wrapper returns errors to selected voter appends and declares pipelining unsupported; it delegates other operations unchanged；No edits to target implementation; mutex-protected counters instrument only transport responses
固定比较 `CHK-verify`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| operation | verify-1 |
| completed | true |
| success | true |
| eligible_voter_quorum | false |
| prepared.operation | verify-1 |
| prepared.policy | only_nonvoter_append_replies |
| prepared.state | Leader |
| prepared.voters | 3 |
| prepared.nonvoters | 1 |
| prepared.replication_started | false |
| admitted.operation | verify-1 |
| admitted.policy | only_nonvoter_append_replies |
| blocked_calls.b | 2 |
| eligible_voter_support | 1 |
| error |  |
| event | result |
| positive_append_responses.n | 1 |
| quorum | 2 |
| state | Leader |
| term | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：After a real three-voter election, can the public VerifyLeader future succeed when all subsequent AppendEntries to the other voters fail and only a nonvoter returns success? The constructor skips…
所选问题／策略（原文摘录）：Candidate 88e182240e5f44df859d5d7eb39d835e has an eligibility discriminator. Use a bounded real-handler election and public verification with no prior replication replies; retain this as construction exploration rather than property…
[受理问题、条件与来源](submissions/4d619f70dd204c62ac85ec714b5afff9/accepted.json)；[固定输入](submissions/4d619f70dd204c62ac85ec714b5afff9/inputs/verify_explore_test.go)
<a id="exploration-e0d835087411436692c37634f67da4b2"></a>
[探索执行 1](#exploration-e0d835087411436692c37634f67da4b2)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/e0d835087411436692c37634f67da4b2/check.json)；[实际输出](logs/e0d835087411436692c37634f67da4b2/stdout.log)；[诊断](logs/e0d835087411436692c37634f67da4b2/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.32 秒；执行进程耗时 12.78 秒；[实际命令、工具版本与输入记录](logs/e0d835087411436692c37634f67da4b2/check.json)
[执行输入文件清单](experiments/51b5d37c154e4d328165d9b8f4e52dcc/workspace-delta/manifest.json)
[执行后文件清单](experiments/51b5d37c154e4d328165d9b8f4e52dcc/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-aa0a66a272eb4347918f655825ece907)

<a id="exploration-feedback-aa0a66a272eb4347918f655825ece907"></a>
[交接 1](#exploration-feedback-aa0a66a272eb4347918f655825ece907) · 后续说明；关联：[探索执行 1](#exploration-e0d835087411436692c37634f67da4b2)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration e0d835087411436692c37634f67da4b2 completed: prepared leader term 2, 3 voters/1 nonvoter, no replication before blocked-voter policy; result success=true with positive_append_responses={n:1}, no positive voter responses and state Leader term 2.…
[完整交接；精确引用不表示已解决或已正式化](submissions/aa0a66a272eb4347918f655825ece907/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Leader persists assigned term/index entries then records its match. Per-peer workers accept successful append/snapshot responses into a tenure-specific voter tracker; newer terms signal loss of authority. Majority index…
- 上下文／权威转换（原文导航摘录）：Heartbeat expiry permits configured voters to campaign. Pre-vote does not advance term; actual election persists term and self-vote, asks each other latest voter once and tallies a per-campaign channel. Vote handlers…
- 两条主线的连接（原文导航摘录）：Voting log freshness links future authority to retained history; new tenure commitment starts empty and requires a current-term entry before inherited prefix can commit. Old replication workers retain old tracker and…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 7.22 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 9.68 分钟 · 实际执行：Candidate 88e182240e5f44df859d5d7eb39d835e has an eligibility discriminator. Use a bounded real-handler election and public verification…；探索执行正常结束。[执行记录](logs/e0d835087411436692c37634f67da4b2/check.json)

- 15.23 分钟 · 受理 review：非投票节点响应触发验证成功，初始化前提仍待修复。[完整交接](submissions/218da99ffd21494c97924f0432290859/accepted.json)

- 16.44 分钟 · 受理 revise_check：Repair only the challenged bootstrap initialization: one participating voter bootstraps, all other constructor stores are checked empty.…。[完整交接](submissions/07ccd38b81c94aaaa9e8a6ca1926871c/accepted.json)

- 16.66 分钟 · 实际执行：非投票节点响应被计入领导权验证门槛；执行完成；比较见 assessment。[执行记录](logs/7799a8fae1504918a40da305dff580be/check.json)

- 18.31 分钟 · 受理 review：非投票节点响应被计入领导权验证门槛。[完整交接](submissions/eeab3468911b46018f8840b07641d25f/accepted.json)

- 20.58 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/e336c8b437284b1da04f745b473df73a/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：VerifyLeader nonvoter callback eligibility is the principal selected discriminator.；Transient failed append after successful truncation: recovery before restart/snapshot remains unresolved; existing…
  尚无精确对应交接。

- B-commit：Durable support after follower truncation followed by failed StoreLogs remains to be investigated.
  尚无精确对应交接。

- B-leader：Detailed transfer cancellation and membership-overlap variants remain open.
  尚无精确对应交接。

- B-replication：Pipeline error/response contract correspondence with concrete transport implementations remains unread.
  尚无精确对应交接。

- B-append：Whether normal leader retries can repair deleted suffix after one StoreLogs failure, before snapshot or restart; compare legal input history and storage test expectations.
  尚无精确对应交接。

- B-vote：Split persistence of vote term and candidate requires separate failure-history investigation.
  尚无精确对应交接。

- B-snapshot：Stale same-term snapshot and snapshot/log boundary variants remain open.
  尚无精确对应交接。

- B-verify-register：No registration filter for nonvoters is visible, unlike lease counting.
  相关交接：[交接 1](submissions/eeab3468911b46018f8840b07641d25f/accepted.json)

- B-verify-confirm：Can reachable nonvoters supply the missing confirmations while other voters supply none?
  相关交接：[交接 1](submissions/eeab3468911b46018f8840b07641d25f/accepted.json)

- surface:Raft.persistVote partial storage failure：Vote term and candidate persist separately; investigate prior candidate plus failed candidate write before alleging duplicate-vote failure.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
