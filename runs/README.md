# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-28 12:40 HashiCorp 真实运行](2026-09-28_12-40-13-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`。采用 `gpt-6-astra` / `low`、框架版本 `native-products-v27`、通用 `go_module` 执行后端；无定向问题、fixture 或协议知识包，未启用 TLA+／TLC。

预算为 40 分钟、40 次 Agent 调用、8 次实验。实际使用 10 次 Agent 调用、约 23 分 25 秒，完成 1 次探索实验、1 次正式直接检查和 1 次语义复核。详细依据、假设和未解决问题见[报告](2026-09-28_12-40-13-hashicorp_raft-real-run/report.md)及[状态记录](2026-09-28_12-40-13-hashicorp_raft-real-run/state.json)。

VerifyLeader 检查通过隔离源码副本中的 Go 测试执行真实选举、应用和分区场景：新 leader 已在更高 term 当选并应用命令后，旧 leader 的 VerifyLeader 仍返回 nil。记录为限定范围内的实现语义违反，未建立旧应用读、冲突提交、通用活性或其他传输模式的后果。另一个问题根据源码解释了负向心跳回复对仍在接收通知的验证计数的保护；该解释不是新的执行证据。

本轮在继续调查日志存储失败路径时收到 Codex 的网安内容拒绝，见[原始错误](2026-09-28_12-40-13-hashicorp_raft-real-run/logs/10261a583c374c8c8e72deb40520e73b/stdout.log)。停止时仍剩约 16 分 35 秒和 30 次 Agent 调用；日志未提供具体命中的规则或文本，不能推断为本地超时或预算耗尽，也不能据此确定平台内部触发原因。

本次将 Git 追踪从 `2026-09-27_20-36-05-hashicorp_raft-real-run` 切换到上述运行，旧运行保留在本地及 Git 历史中。归档排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录与编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置；保留源快照、草稿、固定制品、版本记录、实验输入差异及原始日志。归档不作为新实验的发现输入。
