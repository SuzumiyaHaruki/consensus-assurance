# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-23 09:10 HashiCorp 真实自主分析](2026-09-23_09-10-40-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。运行采用 A1/A2 重点、Codex Astra `low`、框架版本 `focused-continuation-v16`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 27/40 次；2424.70/4800 秒 |
| 实现规格与候选 | 7 类 Activity；4 个候选，其中 1 个范围化解释、2 个升级、1 个仍在调查 |
| 审计单元与直接检查 | 各 2 项；2 次实际直接检查均完成 |
| 局部模型与校准 | 均为 0 |
| 局部结果 | AppendEntries 前驱完整性在明确故障注入条件下确认；VerifyLeader 非投票者输入出现不符，但 checker 对应性争议使其不能确认 |
| 停止原因 | 新 derive 包 192947 字符，超出 180000 上限；未发送该包，仍余 13 次 Agent 调用 |

前驱检查没有证明生产存储适配器会发生相同故障，也没有证明两次请求形成合法分布式发送方历史。VerifyLeader 检查止于隔离的内部聚合边界，其双向等值 checker 需修正并重跑；公共 API、网络和客户端后果尚未观察。心跳 contact 与连接性 lease 的源码解释不属于执行 Evidence。原始回复、观测、限制、失败和本机绝对路径按运行产物保留。

2026-09-23 按用户要求，将 Git 追踪从 2026-09-22 21:19 HashiCorp 运行切换到本次运行，并与当前代码修改一同提交、推送到 `main`。此前追踪的运行保留本地，也可从 Git 历史取得；此切换不删除其他实验。

归档排除临时锁、`.execution` 缓存、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照及实验输入、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
