# 保留运行

当前选定归档：[2026-09-20_09-51-08-hashicorp_raft-real-run](2026-09-20_09-51-08-hashicorp_raft-real-run/report.md)，运行 ID `9fc3915a5ac74a6893622943285db8c0`；目标提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；控制器版本 `selected-question-v5`。原始资源 manifest 仍标 v4，保留该追溯信息不一致，不改写归档。

本次记录 29 个材料片段、83966 / 120000 唯一字符、20 / 20 次 agent 调用、5 / 6 次定向新源码读取、1527.81 / 2400 秒。6 个候选中 3 个 explained、2 个 blocked、1 个 active/analyze；0 个受理主张、0 个审计单元、0 个直接检查、0 个模型、0 次 TLC 性质搜索、0 条性质证据。一次 experiments 用量来自能力探测，不是候选验证。

停止原因是 `Budget exhausted: agent_calls`。AuditSpec v1 → v3、Behavior 9 → 13、Fact 7 → 8；两次深度描述反馈已受理。三个 Surface 扩展包均超过 180000 字符上限，未发送后端；commitment 候选的描述反馈被 target_profile 字段范围限制拒绝，后续诊断又缺失对象与来源。已有保护解释仍是限定范围的源码分析，不是实现正确性证据。本次归档提交不修复这些新发现的问题，不扩大预算。

2026-09-20 按用户明确要求，将 Git 追踪归档从 2026-09-18 15:00:06 切换到本次运行；旧归档保留本地，已提交版本保留于 Git 历史。其他运行和诊断目录不纳入 Git。本次切换不授权删除本地证据。

选定运行保留原始回复、来源快照、状态、日志及原始停止原因；临时锁、.execution 缓存和可重建的 experiments 工作副本不纳入 Git。归档不作为 runtime discovery 答案，测试仅在隔离副本读取。

本次提交包含此前完成的 v5 渐进式 AuditSpec 与深度知识回流重构及本次归档，不改写运行结论。
