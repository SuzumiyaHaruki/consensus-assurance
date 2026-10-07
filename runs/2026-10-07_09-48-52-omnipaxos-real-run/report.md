# 共识审计研究报告

## 运行概览

审计目标 **omnipaxos**；实际持续 **22.37 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. During legal leader/follower synchronization with a delta snapshot, does reconstructing the local base after updating decided_idx…（原文摘录） | 待调查线索 | 机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与原因](direct-checks/91a09b7e9d0b48e68f12ca23dac2de80/7967ebdf8bf64e6f9a669fd5c8b1ccaf-assessment.json) | [C-snapshot-preservation](#claim-C-snapshot-preservation) |

<a id="claim-C-snapshot-preservation"></a>

### 1. During legal leader/follower synchronization with a delta snapshot, does reconstructing the local base after updating decided_idx…（原文摘录）

**待调查线索**。要求原文：When a replica successfully installs a delta snapshot through valid synchronization of a decided log prefix, its snapshot and remaining decided entries must preserve the application state represented by that selected prefix, including prior decided keys not overwritten by the delta.

决定性范围：Content preservation of decided key-value state across successful follower delta synchronization.
Snapshot create folds key assignments and merge applies later assignments.；Storage conforms to its interface and calls are serialized.；Messages originate in the implementation and are delivered to intended configured replicas; temporary network disconnection is followed by reconnected notification.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/91a09b7e9d0b48e68f12ca23dac2de80/omnipaxos/tests/assurance_generated.rs)；[条件与检查器](direct-checks/91a09b7e9d0b48e68f12ca23dac2de80/plan.json)；[原始观察](logs/7967ebdf8bf64e6f9a669fd5c8b1ccaf/stdout.log)；[assessment](direct-checks/91a09b7e9d0b48e68f12ca23dac2de80/7967ebdf8bf64e6f9a669fd5c8b1ccaf-assessment.json)

当前争议／阻塞：机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与阻塞](direct-checks/91a09b7e9d0b48e68f12ca23dac2de80/7967ebdf8bf64e6f9a669fd5c8b1ccaf-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 10.69 秒；执行进程耗时 4.14 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/7967ebdf8bf64e6f9a669fd5c8b1ccaf/check.json)
执行边界：Three public OmniPaxos nodes with documented KV snapshot and MemoryStorage, FIFO generated-message pump and partition/reconnect schedule.；
固定比较 `snapshot_content`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| case_id | delta_reconnect |
| receiver | 3 |
| leader | 1 |
| config | 1 |
| round | 1 |
| session | 2 |
| completed | true |
| actual_state | {"tail":22} |
| admit.expected_state | {"base":11,"tail":22} |
| admit.case_id | delta_reconnect |
| admit.delta | true |
| admit.old_decided | 1 |
| admit.old_accepted | 1 |
| admit.old_state | {"base":11} |
| admit.leader_decided | 2 |
| admit.incoming_decided | 2 |
| admit.sync_idx | 2 |
| accepted | 2 |
| compacted | 2 |
| decided | 2 |
| event | sync_result |
| read | Some([Snapshotted(SnapshottedEntry { trimmed_idx: 2, snapshot: State({"tail": 22}), _p: PhantomData<assurance_generated::Value> })]) |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：For Candidate e6c8eebdd54b4ff8beb09b621803e32d, does a lagging follower reconnect generate a Delta from decided index 1 to 2, and what key-value state does its decided read return after handling that…
[受理问题、条件与来源](submissions/f4156783ec2b43958fa8a5ad2135827c/accepted.json)；[固定输入](submissions/f4156783ec2b43958fa8a5ad2135827c/inputs/delta_explore.rs)
显式引用的问题（不表示已解决）：[候选 1](#candidate-e6c8eebdd54b4ff8beb09b621803e32d)
<a id="exploration-f63fdbb7f34a4c76ba00402d9a313229"></a>
[探索执行 1](#exploration-f63fdbb7f34a4c76ba00402d9a313229)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/f63fdbb7f34a4c76ba00402d9a313229/check.json)；[实际输出](logs/f63fdbb7f34a4c76ba00402d9a313229/stdout.log)；[诊断](logs/f63fdbb7f34a4c76ba00402d9a313229/stderr.log)
固定执行包 `./omnipaxos`；主文件 `omnipaxos/tests/assurance_generated.rs`；目标动作总耗时 755.90 秒；执行进程耗时 9.07 秒；[构建依据](build-inputs/targets/omnipaxos/assurance_generated/basis.json)；已观察到测试启动；正常退出，性质比较另核；[实际命令、工具版本与输入记录](logs/f63fdbb7f34a4c76ba00402d9a313229/check.json)
[执行输入文件清单](experiments/45ee4ebf7f474e1b88077321d6239ada/workspace-delta/manifest.json)
[执行后文件清单](experiments/45ee4ebf7f474e1b88077321d6239ada/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-91a09b7e9d0b48e68f12ca23dac2de80)

<a id="exploration-feedback-91a09b7e9d0b48e68f12ca23dac2de80"></a>
[交接 1](#exploration-feedback-91a09b7e9d0b48e68f12ca23dac2de80) · 后续说明；关联：[探索执行 1](#exploration-f63fdbb7f34a4c76ba00402d9a313229)
后续受理交接原文（摘录，不是各次执行的独立观察）：Exploration completed with exit 0. All nodes first decided base=11 at index 1. With node 3 disconnected, nodes 1 and 2 decided tail=22 at index 2. Reconnect generated Delta({tail:22}) using follower decided base 1. Follower 3 then reported…
[完整交接；精确引用不表示已解决或已正式化](submissions/91a09b7e9d0b48e68f12ca23dac2de80/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A proposal is buffered, forwarded, or appended by the role/phase owner. Leader prepare collects distinct per-pid promises for the configured read quorum, selects highest accepted round then length and maximum decided…
- 上下文／权威转换（原文导航摘录）：BLE heartbeat rounds and manual attempts propose ballots, but SequencePaxos requires a ballot above its promise and former leader state. The new leader resets aggregation and persists its promise; a follower accepts…
- 两条主线的连接（原文导航摘录）：Authority acquisition does not discard prior accepted or decided history: promises carry accepted round/length and decision boundary; preparation selects history before accepting new proposals. AcceptSync transfers a…
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 4.22 分钟 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 18.12 分钟 · 实际执行：Resolve the legal-history and content discriminator with three fresh nodes, public API leadership/proposals, FIFO delivery and a…；探索执行正常结束。[执行记录](logs/f63fdbb7f34a4c76ba00402d9a313229/check.json)

- 20.47 分钟 · 受理 check：Fix the responsibility, genuine history and exact-content predicate for fresh trusted execution.。[完整交接](submissions/91a09b7e9d0b48e68f12ca23dac2de80/accepted.json)

- 20.66 分钟 · 实际执行：During legal leader/follower synchronization with a delta snapshot, does reconstructing the local base after updating decided_idx…（原文摘录）；执行完成；比较见 assessment。[执行记录](logs/7967ebdf8bf64e6f9a669fd5c8b1ccaf/check.json)

- 22.36 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/4937c52b33a645bb9300eca665a3b24c/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-C-snapshot-preservation](research.json)：[C-snapshot-preservation](#claim-C-snapshot-preservation)；具体进度与缺口见对应义务

<a id="candidate-e6c8eebdd54b4ff8beb09b621803e32d"></a>

研究中问题：During legal leader/follower synchronization with a delta snapshot, does reconstructing the local base after updating decided_idx preserve exactly the selected decided prefix, or can it duplicate, omit, or include superseded entries?
[候选原文与历史](state.json)
显式关联探索（不计为另一个发现）：[探索执行 1](#exploration-f63fdbb7f34a4c76ba00402d9a313229)

<details><summary>地图登记与研究交接</summary>

以下是地图 v1 的登记原文摘录，不等于当前检查欠账。精确引用仅表示相关；是否已回答及回填须核对条件和版本。[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

- core_overview：Delta snapshot base under advancing decided index in sync_log.；Cross-configuration message routing and membership identifier validation premises.；Buffered StopSign forwarding when its owner becomes a…
  尚无精确对应交接。

- B-sync：Delta creation uses incoming decided index after cache update: does local reconstruction still match the earlier prefix from which the delta was produced?
  相关交接：[交接 1](submissions/91a09b7e9d0b48e68f12ca23dac2de80/accepted.json)

- B-membership：Configuration nodes uniqueness/nonzero validation and cross-configuration message dispatch premises need further investigation
  尚无精确对应交接。

- F-snapshot：Whether sync delta merge uses the actual delta base before publishing its new bound.
  相关交接：[交接 1](submissions/91a09b7e9d0b48e68f12ca23dac2de80/accepted.json)

- surface:omnipaxos_runtime::spawn_actor / OmniPaxosHandle：In-repository async invocation and completion ownership requires source trace; not externalized by caller-driven transport.
  尚无精确对应交接。

- surface:OmniPaxos::handle_incoming configuration isolation：Sequence messages dispatch directly whereas heartbeat replies check config_id; legal cross-instance transport routing contract remains to be established.
  尚无精确对应交接。

- surface:SequencePaxos::forward_stopsign：Can buffer before leader known; follower sync visibly forwards ordinary proposals only. Need trace caller progress obligations and all consumers.
  尚无精确对应交接。

</details>

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 458.06 秒、36 次 Agent 调用、14 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1341.94 | 458.06 |
| Agent 调用 | 40 | 4 | 36 |
| 控制器目标执行 | 16 | 2 | 14 |
| 新 Unit | 6 | 1 | 5 |
| 语义复核 | 10 | 0 | 10 |
| 修订 | 6 | 0 | 6 |

受控目标执行进程耗时（正式检查＋探索）：已记录 13.21 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 766.59 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`；实际方法 `audit-products-v56`；展示版本 `audit-products-v56`；模式 real/autonomous；执行后端 `cargo`／run 默认包 `omnipaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/4937c52b33a645bb9300eca665a3b24c/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`559.6471636839997`（配置值不表示触发了超时）。
[调用记录](logs/4937c52b33a645bb9300eca665a3b24c/check.json)；[stdout](logs/4937c52b33a645bb9300eca665a3b24c/stdout.log)；[stderr](logs/4937c52b33a645bb9300eca665a3b24c/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

