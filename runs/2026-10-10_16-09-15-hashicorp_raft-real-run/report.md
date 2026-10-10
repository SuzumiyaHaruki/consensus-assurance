# 共识审计研究报告

## 运行概览

审计目标 **hashicorp_raft**；实际持续 **30.00 分钟**；结束类型：**控制器记录的资源边界**。
已确认违反命题 1 项；检查／复核待办 1 项。确认项数按义务命题计，不等于独立根因数。
[当前未决事项](#pending-work)；[完整停止依据与研究状态](state.json)。

## 主要结果

| 问题 | 当前判断 | 观察／未完成原因（原文摘录） | 证据入口 |
| --- | --- | --- | --- |
| 1. For a leader handling a membership change, the resulting configuration must not be installed as configurations.latest, and must…（原文摘录） | 已确认违反 | 机械比较：观察到违反；对应性意见：no_issue_found | [claim-config-publish-requires-durable-append](#claim-claim-config-publish-requires-durable-append) |
| <a id="claim-claim-getconfiguration-reports-config-index"></a>Raft.GetConfiguration must report the index of the configuration it returns, so that a caller can use that index as the prevIndex… | 尚无正式判定 | 义务已受理，尚无固定检查记录 | [claim-getconfiguration-reports-config-index](state.json)；[候选 1](#candidate-70dc8f86c666457abd3005cc666d5931) |

<a id="claim-claim-config-publish-requires-durable-append"></a>

### 1. For a leader handling a membership change, the resulting configuration must not be installed as configurations.latest, and must…（原文摘录）

**已确认违反**。要求原文：For a leader handling a membership change, the resulting configuration must not be installed as configurations.latest, and must not change the quorum derived from latest (commitment.setConfiguration match indexes, quorumSize, leader-lease and election voter sets), unless the corresponding configuration entry has been durably appended to the Raft log.

决定性范围：A leader that is processing a configurationChangeFuture and whose LogStore.StoreLogs returns an error for that entry.
A LogStore.StoreLogs error is an admitted input: dispatchLogs itself handles it by responding the error and setting state to Follower, so a transient store error is a handled, not fatal, condition.；The configuration entry index is assigned by dispatchLogs before StoreLogs is attempted.。

[完整要求、假设与排除范围](state.json)

制品 v1；对应性意见：no_issue_found。
[固定测试](direct-checks/5a22a6babe80452da22d6b9195b4634f/assurance_generated_test.go)；[条件与检查器](direct-checks/5a22a6babe80452da22d6b9195b4634f/plan.json)；[原始观察](logs/452a068dbfa1488ea15bc730a0f1e7bd/stdout.log)；[assessment](direct-checks/5a22a6babe80452da22d6b9195b4634f/452a068dbfa1488ea15bc730a0f1e7bd-assessment.json)；[对应性复核](submissions/4c25ca6279ca4285a42c9286256f3a32/accepted.json)

<details><summary>固定输入、执行与观察字段</summary>

固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.08 秒；执行进程耗时 13.56 秒；[实际命令、工具版本与输入记录](logs/452a068dbfa1488ea15bc730a0f1e7bd/check.json)
执行边界：In-package Go test (assurance_generated_test.go) that bootstraps one voter with an InmemStore whose StoreLogs can be failed on demand, waits for leadership, emits the leader-established and change-attempt prerequisites, performs AddVoter with a single injected StoreLogs failure, then emits assurance_config_published carrying whether the published configuration's assigned log index is present in the store.；One transient LogStore.StoreLogs failure is injected at the real LogStore boundary; no target source is modified；The harness is an added _test.go file in the captured package; observation is emitted as CA_EVENT JSON
固定比较 `checker-config-publish-durable`：观察到违反；已比较 1 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1（违反见证） |
| --- | --- |
| node | 8c135d44-acbc-3f85-05d8-898fcc79bb7d |
| published_ahead_of_durable | true |
| entry_durable | false |
| durable_last_index | 3 |
| event | assurance_config_published |
| published_voters | 2 |

前提关联：观察 1 → matched。首尾预览不参与比较，也不证明相等；日志链接附执行 ID、从 0 计的解析事件序号和字段路径，供复现定位，并非物理行号或自动跳转；不解码字符串。


</details>

条件探索：When a membership change's durable log write fails, does the leader still publish the new configuration into the live configuration it uses for quorum and election decisions, and can the node still…
[受理问题、条件与来源](submissions/19c98425e4d9482cadcf9bfa3e4f7a85/accepted.json)；[固定输入](submissions/19c98425e4d9482cadcf9bfa3e4f7a85/inputs/probe_config_publish_test.go)
<a id="exploration-c58e1c29dc684539981d40d9c4d50d32"></a>
[探索执行 1](#exploration-c58e1c29dc684539981d40d9c4d50d32)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/c58e1c29dc684539981d40d9c4d50d32/check.json)；[实际输出](logs/c58e1c29dc684539981d40d9c4d50d32/stdout.log)；[诊断](logs/c58e1c29dc684539981d40d9c4d50d32/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.74 秒；执行进程耗时 13.26 秒；[实际命令、工具版本与输入记录](logs/c58e1c29dc684539981d40d9c4d50d32/check.json)
[执行输入文件清单](experiments/3460d1e90f274affa6a45f7b137bb28f/workspace-delta/manifest.json)
[执行后文件清单](experiments/3460d1e90f274affa6a45f7b137bb28f/workspace-outcome/manifest.json)
探索执行记录已保存，尚无精确引用该执行的后续受理交接；输出不自动生成正式义务或审批待办。

条件探索：For the accepted claim claim-config-publish-requires-durable-append: is the published-vs-durable configuration divergence reachable without any LogStore error, and does only a restart repair the…
[受理问题、条件与来源](submissions/30772cda6d41434cbdec3fc134685d74/accepted.json)；[固定输入](submissions/30772cda6d41434cbdec3fc134685d74/inputs/probe_config_publish_test.go)
<a id="exploration-cb2a8bf5289046f9a58098b950a38762"></a>
[探索执行 2](#exploration-cb2a8bf5289046f9a58098b950a38762)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/cb2a8bf5289046f9a58098b950a38762/check.json)；[实际输出](logs/cb2a8bf5289046f9a58098b950a38762/stdout.log)；[诊断](logs/cb2a8bf5289046f9a58098b950a38762/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 13.44 秒；执行进程耗时 12.92 秒；[实际命令、工具版本与输入记录](logs/cb2a8bf5289046f9a58098b950a38762/check.json)
[执行输入文件清单](experiments/26bc936570f6428189d7361e50cf071e/workspace-delta/manifest.json)
[执行后文件清单](experiments/26bc936570f6428189d7361e50cf071e/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 1](#exploration-feedback-8a48ec28a24240de8d70659f37c5732a)

条件探索：For the remaining candidate discriminator: does a follower-side LogStore.StoreLogs failure reach the same published-versus-durable configuration divergence as the leader-side path, and what do other…
[受理问题、条件与来源](submissions/20b166fffa95479c8ac9b2f8403ff0e7/accepted.json)；[固定输入](submissions/20b166fffa95479c8ac9b2f8403ff0e7/inputs/probe_config_publish_test.go)
<a id="exploration-6c1f4fbd37ad49e79cd922b03259d1fe"></a>
[探索执行 3](#exploration-6c1f4fbd37ad49e79cd922b03259d1fe)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/6c1f4fbd37ad49e79cd922b03259d1fe/check.json)；[实际输出](logs/6c1f4fbd37ad49e79cd922b03259d1fe/stdout.log)；[诊断](logs/6c1f4fbd37ad49e79cd922b03259d1fe/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.20 秒；执行进程耗时 13.77 秒；[实际命令、工具版本与输入记录](logs/6c1f4fbd37ad49e79cd922b03259d1fe/check.json)
[执行输入文件清单](experiments/e522cb45ca344311b5e06aef712a9c1f/workspace-delta/manifest.json)
[执行后文件清单](experiments/e522cb45ca344311b5e06aef712a9c1f/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 2](#exploration-feedback-3d679f68abb6461bb6a2651533ca5995)

条件探索：For the last open discriminator of candidate 0a6d446a083a42cf91e99726f577eaea: does a LogStore.StoreLogs failure that occurs after appendEntries has already deleted a conflicting log suffix leave the…
[受理问题、条件与来源](submissions/e4239ee8f2e5442db3dbf8f7ce993276/accepted.json)；[固定输入](submissions/e4239ee8f2e5442db3dbf8f7ce993276/inputs/probe_config_publish_test.go)
<a id="exploration-b1b1d3fba8164059b25bbefb147d3fdb"></a>
[探索执行 4](#exploration-b1b1d3fba8164059b25bbefb147d3fdb)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/b1b1d3fba8164059b25bbefb147d3fdb/check.json)；[实际输出](logs/b1b1d3fba8164059b25bbefb147d3fdb/stdout.log)；[诊断](logs/b1b1d3fba8164059b25bbefb147d3fdb/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 14.44 秒；执行进程耗时 14.03 秒；[实际命令、工具版本与输入记录](logs/b1b1d3fba8164059b25bbefb147d3fdb/check.json)
[执行输入文件清单](experiments/fe2af22675c54ff780511516d753d683/workspace-delta/manifest.json)
[执行后文件清单](experiments/fe2af22675c54ff780511516d753d683/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 3](#exploration-feedback-87694961bf0c473693b0107b4e85d201)

条件探索：Can the truncation-then-failed-write history that leaves the cached and reported last-log index above durable content be produced by real producers, that is by a second leader elected in a higher…
[受理问题、条件与来源](submissions/6dda33bc425048a2850edce8446cead9/accepted.json)；[固定输入](submissions/6dda33bc425048a2850edce8446cead9/inputs/probe_config_publish_test.go)
<a id="exploration-9751d8de6e634624998aa5475f25d523"></a>
[探索执行 5](#exploration-9751d8de6e634624998aa5475f25d523)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/9751d8de6e634624998aa5475f25d523/check.json)；[实际输出](logs/9751d8de6e634624998aa5475f25d523/stdout.log)；[诊断](logs/9751d8de6e634624998aa5475f25d523/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 15.94 秒；执行进程耗时 15.45 秒；[实际命令、工具版本与输入记录](logs/9751d8de6e634624998aa5475f25d523/check.json)
[执行输入文件清单](experiments/4aa704be60a04ab181c107d25d4f53cc/workspace-delta/manifest.json)
[执行后文件清单](experiments/4aa704be60a04ab181c107d25d4f53cc/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 4](#exploration-feedback-d4a5c389880c46a6969de7bf09b791de)

条件探索：Does the public Raft.GetConfiguration future report the index of the latest configuration, or does it always report zero while the node itself tracks a nonzero configuration index after a committed…
[受理问题、条件与来源](submissions/bc5daf3c7f9a4842b4f3a6e9986777dc/accepted.json)；[固定输入](submissions/bc5daf3c7f9a4842b4f3a6e9986777dc/inputs/probe_config_publish_test.go)；[固定输入](submissions/bc5daf3c7f9a4842b4f3a6e9986777dc/inputs/probe_config_index_test.go)
<a id="exploration-86b51caa6a8141a9802f09aa24ea13af"></a>
[探索执行 6](#exploration-86b51caa6a8141a9802f09aa24ea13af)：探索执行正常结束；前提是否达到及观察含义见原始输出与后续受理解释；没有正式性质判定。[执行记录](logs/86b51caa6a8141a9802f09aa24ea13af/check.json)；[实际输出](logs/86b51caa6a8141a9802f09aa24ea13af/stdout.log)；[诊断](logs/86b51caa6a8141a9802f09aa24ea13af/stderr.log)
固定执行包 `.`；主文件 `assurance_generated_test.go`；目标动作总耗时 16.82 秒；执行进程耗时 16.22 秒；[实际命令、工具版本与输入记录](logs/86b51caa6a8141a9802f09aa24ea13af/check.json)
[执行输入文件清单](experiments/60276f9c735f494dbc9a2c20b7bad4bf/workspace-delta/manifest.json)
[执行后文件清单](experiments/60276f9c735f494dbc9a2c20b7bad4bf/workspace-outcome/manifest.json)
后续受理交接原文导航：[交接 5](#exploration-feedback-fdd1ed1b0d4f4731b237662af573f63c)

<a id="exploration-feedback-8a48ec28a24240de8d70659f37c5732a"></a>
[交接 1](#exploration-feedback-8a48ec28a24240de8d70659f37c5732a) · 后续说明；关联：[探索执行 2](#exploration-cb2a8bf5289046f9a58098b950a38762)
后续受理交接原文（摘录，不是各次执行的独立观察）：Two recorded unknowns are answered by executed evidence, not by argument. First, the exact recovery path: exploration check cb2a8bf5289046f9a58098b950a38762 recorded restart_after_failed_durable_write, where a node whose published configuration listed the…
[完整交接；精确引用不表示已解决或已正式化](submissions/8a48ec28a24240de8d70659f37c5732a/accepted.json)

<a id="exploration-feedback-3d679f68abb6461bb6a2651533ca5995"></a>
[交接 2](#exploration-feedback-3d679f68abb6461bb6a2651533ca5995) · 后续说明；关联：[探索执行 3](#exploration-6c1f4fbd37ad49e79cd922b03259d1fe)
后续受理交接原文（摘录，不是各次执行的独立观察）：The follower half of the discriminator is settled by executed evidence. Exploration check 6c1f4fbd37ad49e79cd922b03259d1fe built a two-node in-process cluster with both addresses as voters and their InmemTransports connected, then failed every StoreLogs call…
[完整交接；精确引用不表示已解决或已正式化](submissions/3d679f68abb6461bb6a2651533ca5995/accepted.json)

<a id="exploration-feedback-87694961bf0c473693b0107b4e85d201"></a>
[交接 3](#exploration-feedback-87694961bf0c473693b0107b4e85d201) · 后续说明；关联：[探索执行 4](#exploration-b1b1d3fba8164059b25bbefb147d3fdb)
后续受理交接原文（摘录，不是各次执行的独立观察）：The last discriminator is answered conditionally by executed evidence. Exploration check b1b1d3fba8164059b25bbefb147d3fdb drove a bootstrapped voter through real calls so its log held indices 1 to 4, then delivered one AppendEntries for a different leader in…
[完整交接；精确引用不表示已解决或已正式化](submissions/87694961bf0c473693b0107b4e85d201/accepted.json)

<a id="exploration-feedback-d4a5c389880c46a6969de7bf09b791de"></a>
[交接 4](#exploration-feedback-d4a5c389880c46a6969de7bf09b791de) · 后续说明；关联：[探索执行 5](#exploration-9751d8de6e634624998aa5475f25d523)
后续受理交接原文（摘录，不是各次执行的独立观察）：The remaining discriminator is answered by executed evidence produced through real code paths. Exploration check 9751d8de6e634624998aa5475f25d523 bootstrapped three voters with fully connected transports, elected a leader, isolated that leader from the other…
[完整交接；精确引用不表示已解决或已正式化](submissions/d4a5c389880c46a6969de7bf09b791de/accepted.json)

<a id="exploration-feedback-fdd1ed1b0d4f4731b237662af573f63c"></a>
[交接 5](#exploration-feedback-fdd1ed1b0d4f4731b237662af573f63c) · 后续说明；关联：[探索执行 6](#exploration-86b51caa6a8141a9802f09aa24ea13af)
后续受理交接原文（摘录，不是各次执行的独立观察）：No in-tree caller relies on GetConfiguration().Index() as the prevIndex guard, and the only in-tree consumer of that index value is Stats. The membership-change APIs take prevIndex as a caller-supplied parameter (api.go:946-1005) and the deprecated…
[完整交接；精确引用不表示已解决或已正式化](submissions/fdd1ed1b0d4f4731b237662af573f63c/accepted.json)

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
尚无受理地图。
尚未登记双主线概览；局部调查可以先行，现有结果不代表整体覆盖。
累计分钟从本轮创建起计，含暂停间隔；详细墙钟与耗时见执行记录。

- 6.46 分钟 · 实际执行：Sourced suspicion: appendConfigurationEntry (raft.go:1203-1241) calls dispatchLogs first, then unconditionally executes…；探索执行正常结束。[执行记录](logs/c58e1c29dc684539981d40d9c4d50d32/check.json)

- 10.65 分钟 · 受理 obligation：Sourced contract violation in the membership/authority transition path. configurations.latest is documented as the latest configuration in…。[完整交接](submissions/fdd6f486a20d42328f017893a1918973/accepted.json)

- 12.67 分钟 · 实际执行：This exploration reduces the two recorded gaps for candidate 0a6d446a083a42cf91e99726f577eaea. Gap 2 (recovery path), closed by a new…；探索执行正常结束。[执行记录](logs/cb2a8bf5289046f9a58098b950a38762/check.json)

- 15.76 分钟 · 实际执行：机械比较：观察到违反；对应性意见：no_issue_found；执行完成；比较见 assessment。[执行记录](logs/452a068dbfa1488ea15bc730a0f1e7bd/check.json)

- 16.85 分钟 · 受理 research：Review of direct check artifact 3b256fe6f42b4154b75d4d2ec02e27bf (check 452a068dbfa1488ea15bc730a0f1e7bd, outcome violated) for…；v1 checker_correspondence: no_issue_found、v1 applicability: no_issue_found。[完整交接](submissions/4c25ca6279ca4285a42c9286256f3a32/accepted.json)

- 17.73 分钟 · 受理 research：Sourced feedback on candidate 0a6d446a083a42cf91e99726f577eaea, which now carries a confirmed implementation violation through direct check…。[完整交接](submissions/8a48ec28a24240de8d70659f37c5732a/accepted.json)

- 19.40 分钟 · 实际执行：This exploration tests the follower half of the narrowed discriminator on candidate 0a6d446a083a42cf91e99726f577eaea and leaves the…；探索执行正常结束。[执行记录](logs/6c1f4fbd37ad49e79cd922b03259d1fe/check.json)

- 20.21 分钟 · 受理 research：Sourced feedback on candidate 0a6d446a083a42cf91e99726f577eaea recording what exploration check 6c1f4fbd37ad49e79cd922b03259d1fe settled…。[完整交接](submissions/3d679f68abb6461bb6a2651533ca5995/accepted.json)

- 21.66 分钟 · 实际执行：Conditional probe of the last open timing. Method: one bootstrapped voter is driven through real calls (leader election, then two Apply…；探索执行正常结束。[执行记录](logs/b1b1d3fba8164059b25bbefb147d3fdb/check.json)

- 22.19 分钟 · 受理 research：Final sourced feedback on candidate 0a6d446a083a42cf91e99726f577eaea recording the executed answer to its last open discriminator from…。[完整交接](submissions/87694961bf0c473693b0107b4e85d201/accepted.json)

- 23.23 分钟 · 受理 continue：Keeping candidate 0a6d446a083a42cf91e99726f577eaea active at the end of the available run time, with its remaining discriminator retained…。[完整交接](submissions/6540303ae7784155884d524404262559/accepted.json)

- 24.43 分钟 · 实际执行：This exploration closes the last open discriminator of candidate 0a6d446a083a42cf91e99726f577eaea using only real producers and controlled…；探索执行正常结束。[执行记录](logs/9751d8de6e634624998aa5475f25d523/check.json)

- 25.10 分钟 · 受理 research：Final sourced feedback on candidate 0a6d446a083a42cf91e99726f577eaea, recording that its last listed discriminator is now answered by real…。[完整交接](submissions/d4a5c389880c46a6969de7bf09b791de/accepted.json)

- 26.38 分钟 · 实际执行：A separate sourced observation found while auditing the configuration/authority path. Source: Raft.GetConfiguration builds the future as…；探索执行正常结束。[执行记录](logs/86b51caa6a8141a9802f09aa24ea13af/check.json)

- 27.09 分钟 · 受理 obligation：New sourced local contract violation found while auditing the configuration/authority path, registered as an obligation with physical…。[完整交接](submissions/93f90806eb8442549e8bac8a643b1dba/accepted.json)

- 27.72 分钟 · 受理 research：Sourced answer to the single recorded unknown of candidate 70dc8f86c666457abd3005cc666d5931, which was created from the retained…。[完整交接](submissions/fdd1ed1b0d4f4731b237662af573f63c/accepted.json)

- 28.17 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/ae4b144f97e643259f8ddb04000a70ed/accepted.json)

- 28.47 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/bb815607f2f44377b6e6709702e0f429/accepted.json)

- 28.73 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/a6ccef7db8434785950313dce32b66d6/accepted.json)

- 28.99 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/6cab6417058a4206b6a74ae97f5896ea/accepted.json)

- 29.29 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/fd69efd8a5a240419264c55bdace647f/accepted.json)

- 29.63 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/adbef3249e664a1cbc93b15f5868d79c/accepted.json)

- 29.78 分钟 · 受理 continue：State-preserving handoff at the end of the available run time; no new experiment is started because the remaining interval cannot fit a…。[完整交接](submissions/e26ef776e42f4cc99b61c801cfbd3d53/accepted.json)

- 30.00 分钟 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/ad08b225021a409f9dc12c69646a76ef/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

<a id="pending-work"></a>

## 当前未决事项


已选检查／复核待办：
- [unit-claim-getconfiguration-reports-config-index](research.json)：[claim-getconfiguration-reports-config-index](#claim-claim-getconfiguration-reports-config-index)；具体进度与缺口见对应义务

1 次探索尚无精确引用该执行的后续受理交接；前提与观察是否达到仍需核对：[探索执行 1](#exploration-c58e1c29dc684539981d40d9c4d50d32)

<a id="candidate-70dc8f86c666457abd3005cc666d5931"></a>

研究中问题：Does Raft.GetConfiguration report the index of the latest configuration, and what do callers lose if it always reports zero?
[候选原文与历史](state.json)

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。

<details><summary>预算、执行成本与运行元数据</summary>

已受理 Candidate 2 项；当前 Unit 2 项、义务 2 项、固定检查制品 1 项。正式执行尝试 1 次；已保存评估的义务 1 项，其中有实际比较 1 项。已确认违反 1 项、有限检查未见违反 0 项、待调查线索 0 项；另有已获源码解释的 Candidate 0 项。受理、执行与结论分别计数。

剩余 0.00 秒、54 次 Agent 调用、33 次控制器目标执行。资源余量不表示获准恢复或重试。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 1800.0 | 1800.14 | 0.00 |
| Agent 调用 | 80 | 26 | 54 |
| 控制器目标执行 | 40 | 7 | 33 |

受控目标执行进程耗时（正式检查＋探索）：已记录 99.21 秒。

目标动作总耗时（含已记录的准备与复制）：已记录 102.66 秒。

目标执行组成：正式检查 1 次＋探索 6 次，其中执行工具失败／未完成 0 次（不统计研究前提未达）；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；实际方法 `audit-products-v61`；展示版本 `audit-products-v61`；模式 real/autonomous；执行后端 `go_module`／run 默认包 `.`；Agent `codex`／配置 provider `deepseek`／请求模型 `deepseek-flash`／推理档位 `high`。重新渲染不代表重新审计。
服务端模型／版本：未记录；[非敏感连接输入（含 endpoint）](config.json)；[固定目录来源与摘要](agent-inputs/catalog.json)；[最近调用的 CLI、session 与 usage（缺失项仍未知）](logs/ad08b225021a409f9dc12c69646a76ef/check.json)。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

<details><summary>中断调用详情</summary>

中断调用 `agent_turn`：status=`timeout`；配置上限 timeout_limit=`total_seconds`；timeout_seconds=`12.988862057998631`（配置值不表示触发了超时）。
[调用记录](logs/ad08b225021a409f9dc12c69646a76ef/check.json)；[stdout](logs/ad08b225021a409f9dc12c69646a76ef/stdout.log)；[stderr](logs/ad08b225021a409f9dc12c69646a76ef/stderr.log)
总运行预算到达，控制器停止最后一次调用；已受理结果保留。
可靠完成回执：已记录完成事件；产物另行校验。

</details>

</details>

