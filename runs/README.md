# 保留运行

当前选定归档：[2026-09-20_12-07-49-hashicorp_raft-real-run](2026-09-20_12-07-49-hashicorp_raft-real-run/report.md)，运行 ID `04b04265fe6f4887bea3eb4e2bb8456d`；目标提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；控制器与资源版本均为 `selected-question-v6`。

本次记录 25 个材料片段、20 / 20 次 agent 调用、5 / 6 次定向新源码读取、1353.09 / 2400 秒。三个 Surface 完成导航及解释，prompt 为 26765–50212 字符。AuditSpec v1 → v5，Behavior 10 → 27，Fact 5 → 11；两项深度反馈中一项完成、一项尚未发送。任务完成不表示整个 Surface 已覆盖。

停止原因原文为 `Budget exhausted: agent_calls`。三个候选分别是 Snapshot 合同证据不足、选举 channel 隔离的局部解释、FSM/Future 局部解释后等待描述性回流。三次候选选择均出现来源引用字段错误，共消耗四次修复调用；最后的 spec_refine 仅准备 packet，未获调用额度。0 个受理主张、0 个审计单元、0 个模型、0 条性质证据；一次 experiments 消耗来自能力探测。

2026-09-20 按用户要求，将 Git 追踪从 `2026-09-20_09-51-08-hashicorp_raft-real-run` 切换至本次运行，并发布当前 v6 修改。旧实验保留本地，已提交的旧归档保留在 Git 历史；不删除本地证据，不改写原始回复、状态、日志和失败结论。

排除临时锁、.execution 缓存、可重建的 experiments 工作副本和本地权限配置。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；历史 v5 不能用 v6 原地 resume。
