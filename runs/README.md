# 保留运行

当前 Git 仅追踪以下三次实验及本索引。此前追踪的 10 月 3 日 13:18 etcd/raft 和 13:58 HashiCorp Raft 实验保留在本地和 Git 历史中；其他本地运行也不删除。

三次均使用 `audit-products-v44`、`gpt-6-astra` / `low`，各配置 2400 秒、40 次 Agent 调用和 16 次控制器目标执行。三份状态记录的 Codex 会话 ID 不同，各自从空研究状态开始。etcd/raft 与 HashiCorp Raft 使用 Go 1.26.7，Dragonboat 使用 Go 1.23.5。

| 实验 | 实际时间 | Agent 调用 | 控制器执行／语义复核 | 停止依据 |
| --- | ---: | ---: | --- | --- |
| [16:08 etcd/raft](2026-10-03_16-08-46-etcd_raft-real-run/report.md) | 2400.11 秒 | 15 | 3 次探索、3 次正式检查／3 次复核 | 总时间预算到达 |
| [16:48 HashiCorp Raft](2026-10-03_16-48-46-hashicorp_raft-real-run/report.md) | 704.42 秒 | 3 | 无目标执行或复核 | 服务端安全拒绝，尚余 1695.58 秒 |
| [17:00 Dragonboat](2026-10-03_17-00-31-dragonboat_raft-real-run/report.md) | 2400.16 秒 | 9 | 1 次探索、2 次正式检查／1 次复核 | 总时间预算到达 |

- etcd/raft 源码为 `91180476b404beeb5326194e3fcdfa1758d4f222`。保存 3 个 Candidate、3 个 Unit 和 3 个固定检查；报告记录 3 项固定义务范围内的确认违反，具体适用条件、证据和边界见原始报告。
- HashiCorp Raft 源码为 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`。保存 1 个 Candidate，尚未形成 Unit 或正式检查；安全拒绝前的调查不能作为已验证缺陷。
- Dragonboat 源码为稳定版 v3.3.8，提交 `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`。保存 1 个 Candidate、1 个 Unit 和 1 个固定检查；报告记录 1 项固定义务范围内的确认违反，包含一次修订及未完成的后续工作，不代表整个实现审计完成。

本次推送同时包含源码解释与续写责任指导修改 `de150d4`、报告减量修改 `0cbae9b` 及 Dragonboat 目标配置。原始报告、研究状态、固定制品、来源、评估和日志保持原样；未完成回合不受理，历史归档不作为新自主实验的发现输入。

归档保留源码快照、研究地图、草稿、受理输入、执行差异、版本、评估及原始日志；排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录、编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置。
