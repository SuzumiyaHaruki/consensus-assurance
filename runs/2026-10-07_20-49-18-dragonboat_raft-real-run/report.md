# 共识审计研究报告

## 运行概览

审计目标 **dragonboat_raft**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 1 项；检查／复核待办 0 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 批量确认读取时，较早请求被回填为较晚请求的上下文 | 已确认违反 | 节点 2 的请求上下文为 101/1001，但后续确认释放两个请求时，其回复与可读通知均携带节点 3 的 202/2002；节点 3 的回复正确。该执行支持稳定成员、同一任期下的请求关联缺陷，未测量客户端超时或更广泛的一致性后果。 | [C-read-context-preservation](#claim-C-read-context-preservation) |
| Which progress responsibility applies when a full leader and a metadata-only witness commit an entry, the other full voter lacks… | 暂停调查，尚无正式义务 | Acquire a witness-specific availability/fault contract that resolves whether the explored surviving pair is owed continued formation, or an in-scope implementation… | [候选 1](#candidate-ca01097d4d9d47e1b705538d3b35e049) |

<a id="claim-C-read-context-preservation"></a>

### 1. 批量确认读取时，较早请求被回填为较晚请求的上下文

**已确认违反**。要求原文：For each admitted remote ReadIndex request released by a same-term leader quorum confirmation, publication of its read index must retain that request's original SystemCtx and recipient identity, including when a later context confirms a queued prefix.

决定性范围：Remote read-result identity at quorum prefix release in stable membership and authority; does not require eventual global progress.
Non-Byzantine participants and authentic generated protocol messages；Distinct nonzero read contexts and legal message loss; no fabricated acknowledgments；Leader has committed an entry in its term before admitting queued reads。

[完整要求、假设与排除范围](state.json)

本场景复核摘录：批量确认读取时，较早请求被回填为较晚请求的上下文；节点 2 的请求上下文为 101/1001，但后续确认释放两个请求时，其回复与可读通知均携带节点 3 的 202/2002；节点 3 的回复正确。该执行支持稳定成员、同一任期下的请求关联缺陷，未测量客户端超时或更广泛的一致性后果。

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/e87e6d87e0d049f791b6fafe7b96c687/internal/raft/assurance_generated_test.go)；[条件与检查器](direct-checks/e87e6d87e0d049f791b6fafe7b96c687/plan.json)；[原始观察](logs/26ad6abcd0bc44fb845a278c177d2f63/stdout.log)；[assessment](direct-checks/e87e6d87e0d049f791b6fafe7b96c687/26ad6abcd0bc44fb845a278c177d2f63-assessment.json)；[对应性复核](submissions/fc193376f721429187246bf45363d96a/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 15.02 秒；执行进程耗时 13.78 秒；[实际命令、工具版本与输入记录](logs/26ad6abcd0bc44fb845a278c177d2f63/check.json)
执行边界：Deterministic single-threaded Peer driver using real Launch, Tick, Handle, ReadIndex, GetUpdate and Commit; existing TestLogDB stores updates.；No target changes. Substitute synchronous storage and message delivery with declared loss; apply bootstrap configuration and no-op entries only.
固定比较 `check-read-context`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） | 观察 2 |
| --- | --- | --- |
| run | remote-prefix-loss | remote-prefix-loss |
| operation | read-on-2 | read-on-3 |
| request_node | 2 | 3 |
| completed | true | true |
| reply_contexts | 202/2002 | 202/2002 |
| release.expected_context | 101/1001 | 202/2002 |
| release.policy | drop-first-heartbeats | drop-first-heartbeats |
| release.prefix_size | 2 | 2 |
| release.current_term_committed | true | true |
| applied | 4 | 4 |
| event | result | result |
| policy | drop-first-heartbeats | drop-first-heartbeats |
| ready_contexts | 202/2002 | 202/2002 |
| ready_count | 1 | 1 |
| reply_count | 1 | 1 |
| term | 2 | 2 |

前提关联：观察 1 → matched；观察 2 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：After a full leader commits using witness metadata while another full voter lags, what happens to the remaining full voter election attempts when the leader becomes unreachable and the full…
[受理问题、条件与来源](submissions/8a18f0ee96e6421994f8ad58891db3ea/accepted.json)；[固定输入](submissions/8a18f0ee96e6421994f8ad58891db3ea/inputs/witness_explore_test.go)
<a id="exploration-b9ef5b7f02d846a69d49a1aafc6ab7b7"></a>
[探索执行 1](#exploration-b9ef5b7f02d846a69d49a1aafc6ab7b7)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/b9ef5b7f02d846a69d49a1aafc6ab7b7/check.json)；[实际输出](logs/b9ef5b7f02d846a69d49a1aafc6ab7b7/stdout.log)；[诊断](logs/b9ef5b7f02d846a69d49a1aafc6ab7b7/stderr.log)
固定执行包 `./internal/raft`；主文件 `internal/raft/assurance_generated_test.go`；目标动作总耗时 14.10 秒；执行进程耗时 13.09 秒；[实际命令、工具版本与输入记录](logs/b9ef5b7f02d846a69d49a1aafc6ab7b7/check.json)
[执行输入文件清单](experiments/efdf5133b7824c5bb62bb89d7c6ef2c3/workspace-delta/manifest.json)
[执行后文件清单](experiments/efdf5133b7824c5bb62bb89d7c6ef2c3/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-9bd0a0385d044364b273d41a50bbb91f)

<a id="exploration-feedback-9bd0a0385d044364b273d41a50bbb91f"></a>
[交接 1](#exploration-feedback-9bd0a0385d044364b273d41a50bbb91f) · 后续说明；关联：[探索执行 1](#exploration-b9ef5b7f02d846a69d49a1aafc6ab7b7)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration b9ef5b7f02d846a69d49a1aafc6ab7b7 exited zero. Its retained input launches two full voters, elects leader 1, commits/applies AddWitness(3), and checks membership and catch-up on all participants. It then drops leader-to-full-voter-2 messages for a…
[完整交接；精确引用不表示已解决或已正式化](submissions/9bd0a0385d044364b273d41a50bbb91f/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)。
- 共识形成与推进（原文导航摘录）：The leader indexes proposals and aggregates per-voter/witness match acknowledgments into current-term commitment; followers validate the preceding term and protect the committed prefix. Commit propagates via replication…
- 上下文／权威转换（原文导航摘录）：Election ticks campaign only for eligible nodes with no committed-but-unapplied entries. Available votes and up-to-date logs qualify support; known-peer response filtering and term dispatch precede aggregation. Higher…
- 两条主线的连接（原文导航摘录）：Support is owned by the current term and installed membership. Authority transitions clear volatile votes/read support/progress, while persisted term/vote and protected committed history constrain future elections and…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.84 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 12.80 分钟 · 实际执行：批量确认读取时，较早请求被回填为较晚请求的上下文；执行完成；比较见 assessment。[执行记录](logs/26ad6abcd0bc44fb845a278c177d2f63/check.json)

- 16.17 分钟 · 受理 review：批量确认读取时，较早请求被回填为较晚请求的上下文；v1 checker_correspondence: no_issue_found。[完整交接](submissions/fc193376f721429187246bf45363d96a/accepted.json)

- 24.98 分钟 · 受理 explore：Investigate the concrete witness metadata/eligibility premise under a real membership-add history; availability applicability remains…。[完整交接](submissions/8a18f0ee96e6421994f8ad58891db3ea/accepted.json)

- 25.21 分钟 · 实际执行：Investigate the concrete witness metadata/eligibility premise under a real membership-add history; availability applicability remains…；探索执行正常结束。[执行记录](logs/b9ef5b7f02d846a69d49a1aafc6ab7b7/check.json)

- 27.71 分钟 · 受理 continue：Register the sourced witness availability premise without presuming an obligation or reclassifying exploratory observations as evidence.。[完整交接](submissions/9bd0a0385d044364b273d41a50bbb91f/accepted.json)

- 29.42 分钟 · 受理 pause：Locally pause the witness progress question on unresolved normative applicability; preserve measured behavior and safety counterevidence…。[完整交接](submissions/793afd586c2e4ddeb39ced41bb51fefd/accepted.json)

- 29.99 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/8e37ce6c0b5d4b478faefcc83e1fb01d/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

<a id="candidate-ca01097d4d9d47e1b705538d3b35e049"></a>

暂停调查：Which progress responsibility applies when a full leader and a metadata-only witness commit an entry, the other full voter lacks that entry, and the leader becomes unreachable: is majority availability owed to the connected full-voter/witness pair or restricted by an explicit witness fault contract?
[候选原文与历史](state.json)
保存的语义未知：Whether generic quorum availability language applies to a full-voter/witness survivor pair in the explored asymmetric-history configuration; inspected witness text is experimental and does not explicitly settle that applicability.；Whether an authorized witness-specific deployment contract requires an additional up-to-date full replica before relying on failure tolerance.
恢复条件：Acquire a witness-specific availability/fault contract that resolves whether the explored surviving pair is owed continued formation, or an in-scope implementation mechanism that changes that applicability premise.

<details><summary>地图登记与研究交接</summary>

以下是地图 v3 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v3：概览、Behavior／Fact 与来源](audit-spec/v3.json)

- core_overview：Remote read prefix publication uses the confirming context for earlier remote statuses; the scoped execution/attribution is retained with its Candidate.；Read confirmations across membership…
  尚无精确对应交接。

- B-authority：Read-support interaction with live membership change beyond stable-membership case；Whether the generic majority-availability statement applies after commitment by a full leader and witness while the…
  相关交接：[交接 1](submissions/9bd0a0385d044364b273d41a50bbb91f/accepted.json)

- B-membership：All overlapping read/configuration transition variants remain unexamined
  尚无精确对应交接。

- B-persist：Storage backend failure atomicity and crash windows not deeply audited
  尚无精确对应交接。

- B-recovery：Snapshot transport failures and on-disk recovery variants remain open
  尚无精确对应交接。

- B-apply：Application-specific result buffer ownership and on-disk durability variants remain open.
  相关交接：[交接 1](submissions/f3293e1d224145219ce7c390e045cc27/accepted.json)

- B-session-dedup：Ownership/immutability of Result.Data retained in history versus returned to callers is not explicit in the inspected Result contract.
  尚无精确对应交接。

- B-session-checkpoint：Result.Data aliasing contract remains separate from successful serialization order.
  尚无精确对应交接。

- surface:Transport.send：Loss is sourced; detailed reconnection ordering and snapshot transfer remain open.
  尚无精确对应交接。

- surface:statemachine.Result.Data：Session.addResponse retains a Result whose Data is a slice; inspected interface describes creation/return but not reuse or caller mutation ownership. Need inspect return and snapshot consumers before…
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、31 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.19 | 0.00 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 26.87 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 29.12 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`；实际方法 `audit-products-v58`；展示版本 `audit-products-v58`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/8e37ce6c0b5d4b478faefcc83e1fb01d/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`33.660963252004876`（配置值不表示触发了超时）。
[调用记录](logs/8e37ce6c0b5d4b478faefcc83e1fb01d/check.json)；[stdout](logs/8e37ce6c0b5d4b478faefcc83e1fb01d/stdout.log)；[stderr](logs/8e37ce6c0b5d4b478faefcc83e1fb01d/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：未记录；未完成草稿不受理。

</details>

</details>

