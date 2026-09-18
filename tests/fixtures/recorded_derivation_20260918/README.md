# 历史推导回归摘录

摘自 `2026-09-18_10-29-33-hashicorp_raft-real-run`：保留原始 state、AuditSpec、derive 回复和来源快照，支持既有候选推导和历史版本拒绝恢复测试。不是新的实验，不表示原运行成功；完整原记录仍在 Git 历史。

仅供隔离副本中的离线回归，不进入 runtime discovery。state 中历史绝对路径保留原样，测试必须重定位后使用。
