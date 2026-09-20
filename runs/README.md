# 保留运行

当前 Git 追踪以下两次真实自主分析（框架版本 `selected-question-v7`）：

| 归档 | 停止原因 | Agent 调用 | 定向补读 | 耗时 |
| --- | --- | --- | --- | --- |
| [HashiCorp Raft](2026-09-20_16-31-53-hashicorp_raft-real-run/report.md) | `Budget exhausted: agent_calls` | 20/20 | 6/6 | 1728.78 秒 |
| [经典 Paxos](2026-09-20_17-08-44-swiftpaxos_paxos-real-run/report.md) | `Budget exhausted: targeted_reads` | 15/20 | 6/6 | 1383.37 秒 |

HashiCorp 形成快照保留合同证据不足、LogCache 读取回填疑点的局部解释，以及尚未完成的恢复失败与快照坐标问题。Paxos 保留历史接受报告归属的具体疑点，并发现 Commit 广播与短消息解码的布局差异，尚未执行复现。

两次均有 0 个受理主张、0 个审计单元、0 个模型、0 条性质证据。每次的 `experiments: 1` 来自构建能力探测，不是协议性质验证。具体保护、反证和未决范围以各自原始记录为准。

2026-09-20 按用户要求，将 Git 追踪从 `2026-09-20_12-07-49-hashicorp_raft-real-run` 切换至上述两次运行，并发布当前修改。旧实验保留本地，已提交归档仍在 Git 历史；不删除本地证据，不改写原始回复、状态、日志和失败结论。

排除临时锁、.execution 缓存、可重建的 experiments 工作副本和本地权限配置。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；旧框架阶段不能直接用当前版本原地 resume。
