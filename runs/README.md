# 保留运行

`runs` 当前追踪下列 HashiCorp 和 etcd CA 实验。`baseline/runs` 继续保留原有实验。本次追加 etcd 归档，现有归档不变；此前退出追踪的历史归档可从 Git 历史查看。

| 实验 | 模型／档位 | 开始时间（2026-10-11） | 预算／实际时间 | 调用与执行 | 停止原因 |
| --- | --- | --- | --- | --- | --- |
| [HashiCorp CA](2026-10-11_19-38-40-hashicorp_raft-real-run/report.md) | `deepseek-flash` / `high` | 19:38:40 | 60／59.80 分钟 | 80 次模型调用、0 次控制器目标执行 | `resource_limit`，调用数耗尽，剩余约 12.1 秒 |
| [etcd CA](2026-10-11_20-38-28-etcd_raft-real-run/report.md) | `deepseek-flash` / `high` | 20:38:28 | 60／60.01 分钟 | 55 次模型调用、13 次控制器目标执行 | `resource_limit`，总时限到达，最后 Agent 回合被终止 |
| [baseline](../baseline/runs/2026-10-11_16-25-33-hashicorp_raft-baseline/index.md) | `deepseek-flash` / `high` | 16:25:33 | 60／60.01 分钟 | 39 个回合（38 完成、1 超时）、12 份隔离执行记录 | `total_deadline` |

两次 CA 方法均为 `audit-products-v64`，实现提交为 `7494dab1a67b1f426e9c05f45db9edffcb48de6f`。捕获的 HashiCorp 提交为 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，etcd 提交为 `91180476b404beeb5326194e3fcdfa1758d4f222`。CA 与保留的 baseline 不是同批启动的配对实验；各自实际输入、源码身份、工具、预算及会话以保留记录为准。

两次 CA 均配置 3600 秒总预算、80 次模型调用、900 秒单回合、600 秒单次动作及 40 次控制器目标执行上限。HashiCorp 保留 32 个问题、45 条归属解释和 49 条共享知识，没有固定实验或控制器目标执行回执；etcd 保留 11 个问题、14 条归属解释、27 条共享知识和 13 个固定实验。报告中的模型解释、机械比较及各自限制原样保存，模型自述不作为独立缺陷裁决。

本次只归档保存状态，没有重算或修改实验报告。问题、解释、反证及未决缺口保留；baseline 原归档不变。工具／执行次数采用各自记录口径，不等于发现数量，也不能据此直接判定方法优劣。

归档包含捕获源码、配置记录、固定实验、提交及执行差异、原始日志和报告；排除凭据、虚拟环境、临时锁、`.execution`、编译缓存、完整组可重建的 `experiments/**/workspace` 和本地权限覆盖配置。baseline 另排除 `.runtime`、`.codex`、`.agents`。历史实验产物不能成为新自主实验的输入。
