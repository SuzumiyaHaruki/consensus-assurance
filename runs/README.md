# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-27 13:22 HashiCorp 真实运行](2026-09-27_13-22-02-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。采用 `gpt-6-astra` / `low`、框架版本 `native-products-v24`、`hashicorp_raft` 执行后端；本次未限定 activity_focus，未启用 TLC。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 17/40 次；1500.12/1500 秒，耗尽 25 分钟总预算 |
| 研究地图与候选 | 2 个地图版本；1 个 escalated 候选，聚焦 A2 联系标记与租约消费 |
| 检查与复核 | 1 次探索执行、2 次正式直接检查、1 次受理的对应性复核 |
| 模型与校准 | 均为 0 |
| 当前结果 | 1 个 partial Unit；2 条 inconclusive Evidence、2 条 implementation_candidate Finding，均来自同一问题的两个制品版本；确认数为 0 |
| 停止 | 最后一次原生调用只剩 16.81 秒；明确记录 total_seconds / resource_limit，剩余调用 23 次 |

正式输出记录：在手工初始化的两投票者局部状态下，接收端不处理请求、不回复；实际内存流水线超时完成后，`pipelineDecode` 刷新联系时间，手工调用 `checkLeaderLease` 后仍为 Leader；普通复制超时对照不刷新联系时间，转为 Follower。修正配置并调用 `ValidateConfig` 后，第二次正式执行重现同一差异。完整选举前史、自动租约调度、并发保护和客户端后果仍未建立。

两版检查均为 `violated` 且比较完整，但旧配置复核问题尚未正式关闭，不能作为已确认缺陷。17 次调用中 9 次提交被拒，对应调用耗时约 806 秒。关闭问题还存在控制器规则冲突：配置修复保留 oracle，却被要求修改 oracle 才能关闭；本次只作只读分析和内存诊断，未更改运行状态。详见 [实验分析](../docs/实验分析-2026-09-27-13-22-HashiCorp.md)。

按用户要求，将 Git 追踪从 `2026-09-27_10-33-24-hashicorp_raft-real-run` 切换到本次运行。此前追踪的运行保留在本地，也可从 Git 历史取得；此切换不删除其他实验。

归档排除临时锁、`.execution` 缓存、原生草稿临时目录、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照、原生草稿、正式制品、实验输入差异、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
