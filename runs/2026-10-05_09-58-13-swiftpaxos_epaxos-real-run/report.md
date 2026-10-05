# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**。已受理 Candidate 2 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

实际持续 **24.71 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
剩余 917.61 秒、31 次 Agent 调用、13 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 1482.39 | 917.61 |
| Agent 调用 | 40 | 9 | 31 |
| 控制器目标执行 | 16 | 3 | 13 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 1 | 9 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 17.21 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 17.64 秒。

目标执行组成：正式检查 1 次＋探索 2 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v50`；展示版本 `audit-products-v50`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/11ebd50b09df402fbab81f8a3c5b3c9c/check.json)；[stdout](logs/11ebd50b09df402fbab81f8a3c5b3c9c/stdout.log)；[stderr](logs/11ebd50b09df402fbab81f8a3c5b3c9c/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. 恢复回复的值选票在传输中丢失 | 已确认违反 | 固定检查中，接受者经真实 PreAccept 建立的值选票为 1；真实 Prepare 回复经序列化和解码后变为 0。同一回复的身份、当前选票、状态和命令数量一致。结论仅限字段保真责任，不证明集群共识安全被破坏。 | [C-prepare-value-ballot](#claim-C-prepare-value-ballot) |
| After a nonstale Accept is successfully acknowledged for a preaccepted instance, does the recipient retain and report that… | 研究中，尚无正式义务 | Construct a producer-generated slow-path Accept and show actual acknowledgment and later Prepare response on one history.；Determine whether retained vbal/attributes… | [候选 1](#candidate-034d70569cf0415abd1f6d31beae20f7) |

<a id="claim-C-prepare-value-ballot"></a>

### 1. 恢复回复的值选票在传输中丢失

**已确认违反**。要求原文：For a PrepareReply emitted by handlePrepare and successfully decoded through the implementation transport without corruption, the decoded VBallot must equal the stored value ballot reported by the producer for the same acceptor and instance.

决定性范围：Value-ballot preservation across the PrepareReply transport, for producer-established live instance state in fixed-membership volatile EPaxos.
Non-Byzantine producer and uncorrupted complete message bytes.；Producer is handlePrepare after an actual PreAccept-established state; observation is of the same reply and instance.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/90b0c970a398426d91118919c8b2284e/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/90b0c970a398426d91118919c8b2284e/plan.json)；[原始观察](logs/fd01442675f846f1a5adc7de29ea3b7d/stdout.log)；[assessment](direct-checks/90b0c970a398426d91118919c8b2284e/fd01442675f846f1a5adc7de29ea3b7d-assessment.json)；[对应性复核](submissions/1afab011be084b10bd77065b9b08865c/accepted.json)

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 5.76 秒；执行进程耗时 5.60 秒；[实际命令、工具版本与输入记录](logs/fd01442675f846f1a5adc7de29ea3b7d/check.json)
执行边界：Bounded synchronous handler harness with constructor-equivalent empty arrays and in-memory peer byte streams.；Manual constructor-equivalent state uses bounded rows and channels rather than allocating MAX_INSTANCE and starting run goroutines.；Buffered in-memory streams replace peer sockets; actual SendMsg and codecs execute unchanged. No bytes or protocol fields are edited.；Driver calls synchronous handlers, delivers one generated PreAccept and one generated Prepare, and leaves other generated messages pending.；Explicit startRecoveryForInstance substitutes for automatic scanner scheduling; no automatic continuation or deadline assertion.；No background goroutines, files or connections require cleanup; test terminates after decoding the reply.
固定比较 `CK-prepare-vballot`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| acceptor | 2 |
| replica | 1 |
| instance | 0 |
| event | decoded |
| vballot | 0 |
| producer.vballot | 1 |
| producer.command_count | 1 |
| producer.status | 2 |
| ballot | 3 |
| command_count | 1 |
| status | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


条件探索：For Candidate 479b78003ae14c8e9e80a639cf8a0066, does an actual initial-ballot PreAccept at row 1 establish nonzero vbal that handlePrepare reports but its wire reply loses, and what does the real…
所选问题／策略（原文摘录）：Real handlePropose produces PreAccept and real startRecoveryForInstance produces Prepare; requests and replies use actual codecs/SendMsg into captured streams. Constructor-equivalent bounded state replaces sockets, timers and goroutines.…
[受理问题、条件与来源](submissions/b8fc26d78f7540beb21c800ee098fe5b/accepted.json)；[固定输入](submissions/b8fc26d78f7540beb21c800ee098fe5b/inputs/explore_reply_test.go)
<a id="exploration-18fb7d1363fa40c1aa157f28b2038356"></a>
[探索执行 1](#exploration-18fb7d1363fa40c1aa157f28b2038356)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/18fb7d1363fa40c1aa157f28b2038356/check.json)；[实际输出](logs/18fb7d1363fa40c1aa157f28b2038356/stdout.log)；[诊断](logs/18fb7d1363fa40c1aa157f28b2038356/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 6.28 秒；执行进程耗时 6.14 秒；[实际命令、工具版本与输入记录](logs/18fb7d1363fa40c1aa157f28b2038356/check.json)
[执行文件清单](experiments/0c4d819bce6f45499871f6cb90ce1d6d/workspace-delta/manifest.json)；[执行文件清单](experiments/0c4d819bce6f45499871f6cb90ce1d6d/workspace-outcome/manifest.json)；[执行文件清单](experiments/0c4d819bce6f45499871f6cb90ce1d6d/workspace/epaxos/assurance_generated_test.go)
后续受理交接原文导航：[交接 1](#exploration-feedback-cb3b928ec4a04532ac72f58353efa2ad)

条件探索：For Candidate 034d70569cf0415abd1f6d31beae20f7, does a real slow-path Accept acknowledgment counted by its owner leave recipient Status preaccepted, and what status does its next Prepare report?
所选问题／策略（原文摘录）：Use five nodes/F=2 with real owner and recipient proposals creating differing PreAccept attributes; real reply aggregation emits Accept. Deliver one generated Accept, decode its real reply and let owner count it. Observe recipient state…
[受理问题、条件与来源](submissions/1847669aa6314419a7d53e011699aac6/accepted.json)；[固定输入](submissions/1847669aa6314419a7d53e011699aac6/inputs/explore_accept_test.go)
显式引用的问题（不表示已解决）：[候选 1](#candidate-034d70569cf0415abd1f6d31beae20f7)
<a id="exploration-563eae5f1d964500bd0c94f432fbf06a"></a>
[探索执行 2](#exploration-563eae5f1d964500bd0c94f432fbf06a)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/563eae5f1d964500bd0c94f432fbf06a/check.json)；[实际输出](logs/563eae5f1d964500bd0c94f432fbf06a/stdout.log)；[诊断](logs/563eae5f1d964500bd0c94f432fbf06a/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 5.60 秒；执行进程耗时 5.47 秒；[实际命令、工具版本与输入记录](logs/563eae5f1d964500bd0c94f432fbf06a/check.json)
[执行文件清单](experiments/94ee0a9e0f2e483282fa80d6e536238b/workspace-delta/manifest.json)；[执行文件清单](experiments/94ee0a9e0f2e483282fa80d6e536238b/workspace-outcome/manifest.json)；[执行文件清单](experiments/94ee0a9e0f2e483282fa80d6e536238b/workspace/epaxos/assurance_generated_test.go)
探索执行记录已保存，尚待解释；输出不自动生成正式义务或审批待办。

<a id="exploration-feedback-cb3b928ec4a04532ac72f58353efa2ad"></a>
[交接 1](#exploration-feedback-cb3b928ec4a04532ac72f58353efa2ad) · 后续说明；关联：[探索执行 1](#exploration-18fb7d1363fa40c1aa157f28b2038356)
后续受理交接原文（摘录，不是各次执行的独立观察）：Under the controlled three-node prefix, owner 1 produced a PUT PreAccept, acceptor 2 established PREACCEPTED_EQ at vbal 1, and recovery 0 produced Prepare ballot 3. The acceptor retained vbal 1 and reported one command, ballot 3/status 2; decoding the actual…
[完整交接；精确引用不表示已解决或已正式化](submissions/cb3b928ec4a04532ac72f58353efa2ad/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)。
- 共识形成与推进（原文导航摘录）：Client admission allocates an owner-row instance, computes dependencies and sequence from conflicts and preaccepts. Live preferred peers establish or retain local state and reply. Coordinator filters reply ballot/phase,…
- 上下文／权威转换（原文导航摘录）：Authority is per-instance: original row ballot equals owner ID. Recipients reject below joined bal; Prepare advances bal and reports vbal/history. Incomplete execution prefixes trigger recovery. Recovery replaces…
- 两条主线的连接（原文导航摘录）：Formation creates the stored support later reported by Prepare. Ballot transitions are therefore tied to both current promise and prior value context. Recovery consumer selects by VBallot, while remote serialization…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 8.03 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 10.96 分钟 · 实际执行：Real handlePropose produces PreAccept and real startRecoveryForInstance produces Prepare; requests and replies use actual codecs/SendMsg…；探索执行正常结束。[执行记录](logs/18fb7d1363fa40c1aa157f28b2038356/check.json)

- 13.45 分钟 · 受理 obligation：Ground a narrow transport obligation following producer-backed exploration; do not promote exploration to property Evidence or infer…。[完整交接](submissions/cb3b928ec4a04532ac72f58353efa2ad/accepted.json)

- 15.49 分钟 · 受理 check：Fix the measured producer-to-wire discriminator under the accepted narrow obligation; fresh execution and semantic correspondence are…。[完整交接](submissions/90b0c970a398426d91118919c8b2284e/accepted.json)

- 15.58 分钟 · 实际执行：恢复回复的值选票在传输中丢失；执行完成；比较见 assessment。[执行记录](logs/fd01442675f846f1a5adc7de29ea3b7d/check.json)

- 18.20 分钟 · 受理 review：恢复回复的值选票在传输中丢失。[完整交接](submissions/1afab011be084b10bd77065b9b08865c/accepted.json)

- 20.25 分钟 · 受理 continue：Select the independent accepted-phase retention relationship after the completed codec check. Existing guards and retained fields remain…。[完整交接](submissions/7216c8446f4b42e88e34ba1079bec666/accepted.json)

- 22.57 分钟 · 实际执行：Use five nodes/F=2 with real owner and recipient proposals creating differing PreAccept attributes; real reply aggregation emits Accept.…；探索执行正常结束。[执行记录](logs/563eae5f1d964500bd0c94f432fbf06a/check.json)

- 24.71 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/11ebd50b09df402fbab81f8a3c5b3c9c/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查／复核暂无待办；研究范围仍可开放。

正在调查的问题：
- [034d70569cf0415abd1f6d31beae20f7](research.json)：[候选 1](#candidate-034d70569cf0415abd1f6d31beae20f7)

1 次探索已有原始执行记录，尚待受理解释；前提与观察是否达到仍需核对：[探索执行 2](#exploration-563eae5f1d964500bd0c94f432fbf06a)

<a id="candidate-034d70569cf0415abd1f6d31beae20f7"></a>

研究中问题：After a nonstale Accept is successfully acknowledged for a preaccepted instance, does the recipient retain and report that accepted phase to a subsequent Prepare?
[候选原文与历史](state.json)
保存的语义未知：Construct a producer-generated slow-path Accept and show actual acknowledgment and later Prepare response on one history.；Determine whether retained vbal/attributes supply an alternative to the phase distinction consumed by recovery.
显式关联探索（不计为另一个发现）：[探索执行 2](#exploration-563eae5f1d964500bd0c94f432fbf06a)

### 地图登记与研究交接

以下是地图 v2 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v2：概览、Behavior／Fact 与来源](audit-spec/v2.json)

- core_overview：Reachable impact of PrepareReply VBallot omission and self-reply relabeling.；Accept acknowledgment versus unchanged recipient Status.；Quorum configuration boundaries, automatic progress and optional…
  尚无精确对应交接。

- B-formation：Does missing ACCEPTED assignment permit later preaccept/recovery to reinterpret support already acknowledged?；Quorum formulas and peer accounting require a separate responsibility check, especially…
  相关交接：[交接 1](submissions/7216c8446f4b42e88e34ba1079bec666/accepted.json)

- B-authority：Does the locally relabeled self reply overshadow eligible prior state?；makeBallot does not always strictly increase across retry; implications need legal histories.；TryPreAccept branch has duplicated…
  相关交接：[交接 1](submissions/7216c8446f4b42e88e34ba1079bec666/accepted.json)

- B-wire：Wider recovery decision consequences depend separately on prior history and local self-reply context.
  相关交接：[交接 1](submissions/cb3b928ec4a04532ac72f58353efa2ad/accepted.json)；[交接 2](submissions/1afab011be084b10bd77065b9b08865c/accepted.json)

- B-recovery-trigger：Progress under pending queues, repeated recovery and peer loss is not established by the nominal grace constant.
  尚无精确对应交接。

- B-config：No dynamic membership path read; configuration mismatch and even-size applicability remain open.
  尚无精确对应交接。

- B-consume：Same-row/sequence tie ordering and range-command conflict tracking remain unexamined responsibilities.
  尚无精确对应交接。

- B-persistence：Durable startup and crash-restart contract are not established; do not infer supported recovery from writers alone.
  尚无精确对应交接。

- B-client：Retry/deduplication and concurrent invocation contract require further caller investigation.
  尚无精确对应交接。

- F-state：Eligibility of acknowledged Accept state when Status remains preaccepted.
  相关交接：[交接 1](submissions/7216c8446f4b42e88e34ba1079bec666/accepted.json)

- F-prepare：Effect of wire omission versus independent self-reply relabeling in reachable recovery histories.
  相关交接：[交接 1](submissions/cb3b928ec4a04532ac72f58353efa2ad/accepted.json)

- surface:Replica.handlePrepareReply subCase 4：Identical subCase 3 and 4 predicates make TryPreAccept dispatch apparently unreachable; establish intended applicability before testing its deeper anomalies.
  尚无精确对应交接。

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
