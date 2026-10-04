# 保留运行

当前 Git 仅追踪以下最近五次正式实验及本索引，分别对应 etcd/raft、HashiCorp Raft、Dragonboat、OmniPaxos 和 SwiftPaxos 中的修订版 EPaxos。之前的运行保留在本地，已提交版本仍可从 Git 历史查看。

五次实验均使用 `audit-products-v49`，各配置 2400 秒、`gpt-6-astra` / `low`。下表直接摘录保存的状态与报告；具体适用条件、检查过程、证据和未完成工作见各自原始报告。按各自固定义务和执行范围报告确认结果；其他性质、不同模式和更广后果分别研究。

| 实验 | 实际时间 | 报告中的正式结论 | 停止依据 |
| --- | ---: | --- | --- |
| [17:36 etcd/raft](2026-10-04_17-36-49-etcd_raft-real-run/report.md) | 1437.09 秒 | 1 项确认违反 | 服务端安全拒绝 |
| [18:00 HashiCorp Raft](2026-10-04_18-00-47-hashicorp_raft-real-run/report.md) | 619.69 秒 | 已受理 1 项 Candidate，尚无正式执行或确认结果 | 服务端安全拒绝 |
| [18:11 Dragonboat](2026-10-04_18-11-07-dragonboat_raft-real-run/report.md) | 2159.35 秒 | 1 项确认违反、1 项待调查线索 | 服务端安全拒绝 |
| [18:47 OmniPaxos](2026-10-04_18-47-07-omnipaxos-real-run/report.md) | 2400.34 秒 | 2 项确认违反；另 1 项检查构建超时，未执行到比较 | 总时间边界 |
| [19:27 EPaxos](2026-10-04_19-27-07-swiftpaxos_epaxos-real-run/report.md) | 561.25 秒 | 已受理 1 项 Candidate，尚无正式执行或确认结果 | 服务端安全拒绝 |

原始报告、研究状态、固定制品、来源、评估和日志保持原样；未完成回合不受理，历史归档不作为新自主实验的发现输入。

归档保留源码快照、固定构建依据与锁文件、研究地图、草稿、受理输入、执行差异、版本、评估及原始日志；排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录、编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置。
