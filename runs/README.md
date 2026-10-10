# 保留运行

当前 `runs/` 按开始时间追踪最近六次实验：五个实现各一次 Astra 实验，以及一次 DeepSeek HashiCorp 实验。`baseline/runs/` 原有五次实验的追踪保持不变。其余本地运行不因追踪切换而删除；旧归档可从 Git 历史查看。

各次使用独立会话。完整组使用方法 v60，各次预算均为 30 分钟、最多 80 次模型调用和 40 次目标执行。具体输入版本、执行条件与额度消耗以原始配置、状态及日志为准。

| 完整组实验 | 模型／推理档位 | 开始时间（2026-10-10） | 预算／实际时间 | 停止原因 |
| --- | --- | --- | --- | --- |
| [etcd](2026-10-10_13-27-45-etcd_raft-real-run/report.md) | `gpt-6-astra` / `low` | 13:27:45 | 30／3.37 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [HashiCorp](2026-10-10_13-31-08-hashicorp_raft-real-run/report.md) | `gpt-6-astra` / `low` | 13:31:08 | 30／3.70 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [Dragonboat](2026-10-10_13-34-50-dragonboat_raft-real-run/report.md) | `gpt-6-astra` / `low` | 13:34:50 | 30／17.68 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [HashiCorp](2026-10-10_13-44-26-hashicorp_raft-real-run/report.md) | `deepseek-flash` / `high` | 13:44:26 | 30／30.00 分钟 | 总预算耗尽时 Agent 调用超时；`resource_limit`，剩余时间为 0 |
| [OmniPaxos](2026-10-10_13-52-31-omnipaxos-real-run/report.md) | `gpt-6-astra` / `low` | 13:52:31 | 30／5.94 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [EPaxos](2026-10-10_13-58-28-swiftpaxos_epaxos-real-run/report.md) | `gpt-6-astra` / `low` | 13:58:28 | 30／3.69 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |

Dragonboat 记录 7 次模型调用、4 次目标执行；DeepSeek HashiCorp 记录 18 次模型调用、3 次目标执行。其余四次各记录 1 次模型调用。预算是上限，不表示完成了相应数量的检查。

以下 baseline 归档保留原记录；与本次完整组的版本、模型或预算不同，不构成同条件配对。

| 实验 | 模型／推理档位 | 开始时间（2026-10-09） | 预算／实际时间 | 停止原因 |
| --- | --- | --- | --- | --- |
| [HashiCorp baseline](../baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/index.md) | `gpt-6-astra` / `low` | 16:23:12 | 40／13.11 分钟 | `external_error`；模型服务返回网安风险拒绝，首回合未完成 |
| [etcd baseline](../baseline/runs/2026-10-09_19-51-11-etcd_raft-baseline/index.md) | `gpt-6-astra` / `low` | 19:51:11 | 40／10.28 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [Dragonboat baseline](../baseline/runs/2026-10-09_20-01-29-dragonboat_raft-baseline/index.md) | `gpt-6-astra` / `low` | 20:01:29 | 40／12.74 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [OmniPaxos baseline](../baseline/runs/2026-10-09_20-14-15-omnipaxos-baseline/index.md) | `gpt-6-astra` / `low` | 20:14:15 | 40／35.59 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [EPaxos baseline](../baseline/runs/2026-10-09_20-49-52-swiftpaxos_epaxos-baseline/index.md) | `gpt-6-astra` / `low` | 20:49:52 | 40／28.13 分钟 | `turn_timeout`；第二回合超时 |

HashiCorp baseline 保留 32 次工具调用记录、6 份测试文件及输出，包含 3 次隔离执行；[工作报告](../baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/work/report.md)是中断时草稿，尚未覆盖全部已执行调查。两侧的回合、工具和执行记录采用自身口径，不直接对等。

以上仅摘录原状态与报告，不重新评估。模型自报及完整组的确认状态均需结合适用条件、实际观察、反证及未决边界复核，不将局部结论扩展为完整集群结论。

原始报告、研究状态、固定制品、来源、评估和日志保持原样；历史归档不作为新自主实验的发现输入。

归档排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录、编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置。baseline 另排除 `.runtime`、`.codex`、`.agents`；已被原运行收尾清理的文件不凭报告补造。
