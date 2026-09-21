# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-21 Paxos 真实自主分析](2026-09-21_13-56-50-swiftpaxos_paxos-real-run/report.md)，框架版本为 `simplified-workflow-v9`，Codex 推理强度显式配置为 `medium`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用 | 19/20 |
| 累计执行时间 | 2114.21 秒 |
| 已接受义务与审计单元 | 各 1 项 |
| 已受理模型、模型搜索、校准、性质证据 | 均为 0 |
| 最终停止原因 | `Insufficient remaining agent calls to start a new candidate episode; unresolved work remains` |

本次选择恢复过程是否保持此前决定命令的有界义务。模型草稿使用 `GENERATE_FROM_OBSERVABLE_PROPERTIES`，缺少完整观测映射，受理时被拒绝；修复机制未能定位可执行的修复任务。原始草稿、未决条件和错误记录均保留，不能据此确认协议缺陷。`experiments: 1` 来自隔离构建能力探测，不是协议性质验证。

运行曾在 182437 字符的数据包超过 180000 上限时停止。删除重复的候选问题副本后，用户恢复同一运行；原有超限回执及先前结果保持在历史记录中。原始日志和状态中的本机绝对路径按原样保存。

2026-09-21 按用户要求，将 Git 追踪从两次 2026-09-20 的 HashiCorp Raft/Paxos 运行切换到本次运行，并提交和推送当前修改。旧目录继续保留本地，原先提交的归档可从 Git 历史取得；没有删除本地运行或改写旧失败。

排除临时锁、`.execution` 缓存、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照及实验输入、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
