# 保留运行

当前 `runs/` 按开始时间追踪最近六次实验：五个实现各一次 Astra 实验，以及一次 DeepSeek HashiCorp 实验。`baseline/runs/` 原有五次实验的追踪保持不变。其余本地运行不因追踪切换而删除；旧归档可从 Git 历史查看。

各次使用独立会话。完整组使用方法 v61，代码基线为 `dc4acbe6394948f9bfbea2183a840e808dc7d77e`，各次预算均为 30 分钟、最多 80 次模型调用和 40 次目标执行。具体输入版本、执行条件与额度消耗以原始配置、状态及日志为准。

| 完整组实验 | 模型／推理档位 | 开始时间（2026-10-10） | 预算／实际时间 | 停止原因 |
| --- | --- | --- | --- | --- |
| [etcd](2026-10-10_15-52-43-etcd_raft-real-run/report.md) | `gpt-6-astra` / `low` | 15:52:43 | 30／4.25 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [HashiCorp](2026-10-10_15-56-58-hashicorp_raft-real-run/report.md) | `gpt-6-astra` / `low` | 15:56:58 | 30／4.61 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [Dragonboat](2026-10-10_16-01-36-dragonboat_raft-real-run/report.md) | `gpt-6-astra` / `low` | 16:01:36 | 30／5.83 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [OmniPaxos](2026-10-10_16-07-26-omnipaxos-real-run/report.md) | `gpt-6-astra` / `low` | 16:07:26 | 30／2.23 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |
| [HashiCorp](2026-10-10_16-09-15-hashicorp_raft-real-run/report.md) | `deepseek-flash` / `high` | 16:09:15 | 30／30.00 分钟 | 总预算耗尽时 Agent 调用超时；`resource_limit`，剩余时间为 0 |
| [EPaxos](2026-10-10_16-09-40-swiftpaxos_epaxos-real-run/report.md) | `gpt-6-astra` / `low` | 16:09:40 | 30／9.72 分钟 | 模型服务返回网安风险拒绝；`tool_gap` |

DeepSeek HashiCorp 记录 26 次模型调用、7 次目标执行（1 次正式检查、6 次探索）；EPaxos 记录 3 次模型调用、2 次目标执行（1 次正式检查、1 次探索）。其余四次各记录 1 次模型调用、0 次控制器目标执行。预算是上限，不表示完成了相应数量的检查。

交接时需保留以下结论边界：

- DeepSeek HashiCorp 原报告登记 1 项已确认的有界义务违反：配置日志写入失败后，仍发布了未持久化的新配置。该记录不自动证明集群共识失效；`GetConfiguration` 返回索引的问题已受理义务，但尚无固定检查。
- EPaxos 原报告记录 `PrepareReply` 生产值经编码、解码后未保留 accepted-value ballot 的观察；对应性复核未完成，仍为待调查线索，不能提升为已确认缺陷。
- 其余四次在首回合被服务中断，无已受理候选或正式性质判定。五次 Astra 拦截均保留原始日志，不从拒绝信息推断具体触发文本。

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
