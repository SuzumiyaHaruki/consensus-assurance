# 共识审计研究报告

## 运行概览

审计目标 **swiftpaxos_epaxos**；实际持续 **9.72 分钟**；结束类型：**控制器记录的服务／权限／工具中断**。
已确认违反命题 0 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. For a PrepareReply emitted by handlePrepare, successful in-memory transport encoding and decoding into a fresh PrepareReply must…（原文摘录） | 待调查线索 | 机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与原因](direct-checks/aadcf7f6d6294d2da76451388323b110/bd39742c939a458f979918f2cea3eb61-assessment.json) | [prepare_reply_value_ballot_preservation](#claim-prepare_reply_value_ballot_preservation) |

<a id="claim-prepare_reply_value_ballot_preservation"></a>

### 1. For a PrepareReply emitted by handlePrepare, successful in-memory transport encoding and decoding into a fresh PrepareReply must…（原文摘录）

**待调查线索**。要求原文：For a PrepareReply emitted by handlePrepare, successful in-memory transport encoding and decoding into a fresh PrepareReply must preserve the producer accepted-value ballot for the same acceptor and instance.

决定性范围：Local PrepareReply producer and lossless byte-transport contract, including nonzero accepted-value ballots.
The receiver decodes the complete byte stream emitted by SendMsg into a fresh PrepareReply, as the normal receive loop does.；The observed producer instance is not concurrently modified during handlePrepare and byte decoding.。

[完整要求、假设与排除范围](state.json)

制品 v1；机械比较：观察到违反；对应性意见：尚未记录；场景比较完整：True；独立场景完整处置：False。
[固定测试](direct-checks/aadcf7f6d6294d2da76451388323b110/epaxos/assurance_generated_test.go)；[条件与检查器](direct-checks/aadcf7f6d6294d2da76451388323b110/plan.json)；[原始观察](logs/bd39742c939a458f979918f2cea3eb61/stdout.log)；[assessment](direct-checks/aadcf7f6d6294d2da76451388323b110/bd39742c939a458f979918f2cea3eb61-assessment.json)

当前争议／阻塞：机械比较：观察到违反；对应性意见：尚未记录；待当前版本复核；[完整评估与阻塞](direct-checks/aadcf7f6d6294d2da76451388323b110/bd39742c939a458f979918f2cea3eb61-assessment.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.60 秒；执行进程耗时 7.28 秒；[实际命令、工具版本与输入记录](logs/bd39742c939a458f979918f2cea3eb61/check.json)
执行边界：Three bounded empty replicas; propose at owner 1, deliver its real PreAccept to acceptor 2, initiate recovery at replica 0, deliver its real Prepare to acceptor 2, decode the actual SendMsg reply.；Replace constructor startup and TCP sockets with constructor-equivalent empty protocol containers and separate per-link byte buffers.；Call private handlers synchronously; no event loop, timer, execution worker or crash is modeled.；Reduce instance arrays to four entries; only instance 1.0 is touched. No produced instance field or message is edited.；Hold the PreAcceptReply and unused Prepare bytes without delivering them.
固定比较 `value_ballot_transport`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| acceptor | 2 |
| replica | 1 |
| instance | 0 |
| event | prepare_reply_transport |
| decoded_vballot | 0 |
| admitted.vballot | 1 |
| admitted.status | 2 |
| decoded_status | 2 |
| identity_preserved | true |
| other_fields_preserved | true |
| preaccept_ballot | 1 |
| prepare_ballot | 3 |
| producer_status | 2 |
| producer_vballot_after_prepare | 1 |
| producer_vballot_before_prepare | 1 |
| value_ballot_preserved | false |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：Does an actual PrepareReply produced after a nonzero initial-ballot PreAccept preserve its accepted-value ballot through SendMsg and the receiver codec?
[受理问题、条件与来源](submissions/0513a22c775f405fb4611d71985005ed/accepted.json)；[固定输入](submissions/0513a22c775f405fb4611d71985005ed/inputs/probe_test.go)
<a id="exploration-dd87c8fbf4ce4592bdedad0e709cc053"></a>
[探索执行 1](#exploration-dd87c8fbf4ce4592bdedad0e709cc053)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/dd87c8fbf4ce4592bdedad0e709cc053/check.json)；[实际输出](logs/dd87c8fbf4ce4592bdedad0e709cc053/stdout.log)；[诊断](logs/dd87c8fbf4ce4592bdedad0e709cc053/stderr.log)
固定执行包 `./epaxos`；主文件 `epaxos/assurance_generated_test.go`；目标动作总耗时 7.93 秒；执行进程耗时 7.57 秒；[实际命令、工具版本与输入记录](logs/dd87c8fbf4ce4592bdedad0e709cc053/check.json)
[执行输入文件清单](experiments/d2d77ecffb254515823afa305a26e740/workspace-delta/manifest.json)
[执行后文件清单](experiments/d2d77ecffb254515823afa305a26e740/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-aadcf7f6d6294d2da76451388323b110)

<a id="exploration-feedback-aadcf7f6d6294d2da76451388323b110"></a>
[交接 1](#exploration-feedback-aadcf7f6d6294d2da76451388323b110) · 后续说明；关联：[探索执行 1](#exploration-dd87c8fbf4ce4592bdedad0e709cc053)
后续受理交接原文（摘录，不是各次执行的独立观察）：CheckRun dd87c8fbf4ce4592bdedad0e709cc053, its only emitted CA_EVENT, measured producer value ballot 1 both before and after Prepare ballot 3 and decoded value ballot 0. Identity and other payload fields were preserved. The fixed harness at…
[完整交接；精确引用不表示已解决或已正式化](submissions/aadcf7f6d6294d2da76451388323b110/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
尚无受理地图。
尚未登记双主线概览；局部调查可以先行，现有结果不代表整体覆盖。
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 3.31 分钟 · 实际执行：Source shows handlePrepare exports inst.vbal and handlePrepareReply selects values by VBallot, but PrepareReply Marshal/Unmarshal omit that…；探索执行正常结束。[执行记录](logs/dd87c8fbf4ce4592bdedad0e709cc053/check.json)

- 7.02 分钟 · 受理 check：Retained exploration CheckRun dd87c8fbf4ce4592bdedad0e709cc053 completed with producer VBallot 1, decoded VBallot 0, and preserved…。[完整交接](submissions/aadcf7f6d6294d2da76451388323b110/accepted.json)

- 7.14 分钟 · 实际执行：机械比较：观察到违反；对应性意见：尚未记录；执行完成；比较见 assessment。[执行记录](logs/bd39742c939a458f979918f2cea3eb61/check.json)

- 9.72 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/0bc3c15f4052445c80dbbd48ec17969f/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-prepare_reply_value_ballot_preservation](research.json)：[prepare_reply_value_ballot_preservation](#claim-prepare_reply_value_ballot_preservation)；具体进度与缺口见对应义务

<a id="candidate-3a16f87433b3420e97d71b2081dffbd9"></a>

研究中问题：Does PrepareReply transport preserve the accepted-value ballot exported by handlePrepare for a normally preaccepted instance?
[候选原文与历史](state.json)
保存的语义未知：Whether this independently causes a reachable divergent decision or applied result; self-reply ballot relabeling must be separated.

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 1 项；当前 Unit 1 项、义务 1 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 0 项、有限检查未见违反 0 项、待调查线索 1 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 1216.61 秒、77 次 Agent 调用、38 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 583.39 | 1216.61 |
| Agent 调用 | 80 | 3 | 77 |
| 控制器目标执行 | 40 | 2 | 38 |

受控目标执行进程耗时（正式检查＋探索）：已记录 14.85 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 15.52 秒。

目标执行组成：正式检查 1 次＋探索 1 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `35c69365f1c7737a08e237bfbaf828ee68897080`；实际方法 `audit-products-v61`；展示版本 `audit-products-v61`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `./epaxos`；Agent `codex`／配置 provider `Codex 默认`／请求模型 `gpt-6-astra`／推理档位 `low`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/0bc3c15f4052445c80dbbd48ec17969f/check.json)。

停止依据（记录摘录）：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work…；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`error`；配置上限 timeout_limit=`agent_turn_timeout`；timeout_seconds=`900.0`（配置值不表示触发了超时）。
[调用记录](logs/0bc3c15f4052445c80dbbd48ec17969f/check.json)；[stdout](logs/0bc3c15f4052445c80dbbd48ec17969f/stdout.log)；[stderr](logs/0bc3c15f4052445c80dbbd48ec17969f/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
调用诊断（不据此授权重试）：This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via…

</details>

</details>

