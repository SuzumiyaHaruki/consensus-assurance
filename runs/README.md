# 保留运行

当前 `runs/` 按开始时间追踪最近六次实验：五个实现各一次 Astra low，以及一次 DeepSeek high HashiCorp。其余本地目录保留，旧归档可从 Git 历史查看；`baseline/runs/` 原有五次实验继续追踪。

本组六次使用方法 `audit-products-v62`，代码基线为 `2fe3fbcc6dc51ac4a95a7b339fa52371c0090b53`，各自使用独立会话。预算均为 30 分钟、最多 80 次模型调用及 40 次控制器目标执行；具体输入、工具版本、构建条件和实际用量以各自配置、状态与回执为准。

| 完整组实验 | 模型／推理档位 | 开始时间（2026-10-11） | 预算／实际时间 | 模型调用／目标执行 | 停止原因 |
| --- | --- | --- | --- | --- | --- |
| [HashiCorp](2026-10-11_12-49-23-hashicorp_raft-real-run/report.md) | `deepseek-flash` / `high` | 12:49:23 | 30／30.14 分钟 | 14／4 | 总预算耗尽，最后 Agent 回合超时；`resource_limit` |
| [etcd](2026-10-11_12-51-03-etcd_raft-real-run/report.md) | `gpt-6-astra` / `low` | 12:51:03 | 30／5.57 分钟 | 2／1 | 模型服务返回网安风险拒绝；`tool_gap` |
| [HashiCorp](2026-10-11_12-56-38-hashicorp_raft-real-run/report.md) | `gpt-6-astra` / `low` | 12:56:38 | 30／2.98 分钟 | 1／0 | 模型服务返回网安风险拒绝；`tool_gap` |
| [Dragonboat](2026-10-11_12-59-37-dragonboat_raft-real-run/report.md) | `gpt-6-astra` / `low` | 12:59:37 | 30／11.66 分钟 | 2／1 | 模型服务返回网安风险拒绝；`tool_gap` |
| [OmniPaxos](2026-10-11_13-11-17-omnipaxos-real-run/report.md) | `gpt-6-astra` / `low` | 13:11:17 | 30／4.08 分钟 | 1／0 | 模型服务返回网安风险拒绝；`tool_gap` |
| [EPaxos](2026-10-11_13-15-22-swiftpaxos_epaxos-real-run/report.md) | `gpt-6-astra` / `low` | 13:15:22 | 30／12.14 分钟 | 3／2 | 模型服务返回网安风险拒绝；`tool_gap` |

调用和执行次数是控制器记录，不等于发现数量，也不包括所有 Agent 回合内工具操作。DeepSeek 的最后回合在总预算到期被终止，收尾后记录 30.14 分钟；这不是另开了后续调查额度。五次 Astra 均被模型服务中断，原始错误保留，不从拒绝文字推断具体触发内容。

## 本次交接边界

以下仅摘录保存的状态与报告，不重新运行或重写历史评估：

- **DeepSeek HashiCorp**：14 次模型调用、4 次目标执行，调查安装快照后旧日志／缓存的 last-log 状态是否阻碍追随者追赶。轨迹包含实际三节点前史、控制场景、单调与非单调存储分支，并保留了一次清理超时失败及其后继修复。后继解释标为 `violated`，但原报告各实验均为“未确认违反”，保留的 `counterevidence` 等边界不能在交接时略去。观测是有限时间内的进展异常，不等于已证明永久停滞或安全性违反；网络传输、磁盘存储与重启后果未验证。
- **etcd Astra**：1 次条件探索，问题涉及空 ReadIndex context 与调用者的重试责任；未固定要求和比较，也无受理的执行解释，不能作为正式缺陷结论。
- **Dragonboat Astra**：1 次执行观察到批量确认读请求时的 SystemCtx 对应异常，机械比较为 `violated`；服务中断前没有受理的归属解释，仍未确认。
- **EPaxos Astra**：2 次目标执行，分别调查 PrepareReply 的 VBallot 编解码，以及 handleAccept 后的阶段状态。两次机械比较均为 `violated`；第一项已有局部序列化解释但仍保留反证／范围边界，原报告未确认；第二项没有执行解释。均不能扩展为已验证的分布式决议分歧或客户端后果。
- **HashiCorp Astra、OmniPaxos Astra**：各 1 次模型调用，0 次控制器目标执行，首回合服务中断，无已受理问题或正式结论。

待后续复核时，应分别查看固定实验依据、原始事件、解释中的反证及必要缺口；不要将模型的 `violated` 意见、进程成功或机械比较直接合并为缺陷有效性判定。局部 API／序列化结果和协议层后果保持各自范围。原有失败、前驱制品、供给假设和未决问题完整保留。

以下 baseline 归档保留原记录；与本次完整组的版本、模型或预算不同，不构成同条件配对。

| 实验 | 模型／推理档位 | 开始时间（2026-10-09） | 预算／实际时间 | 停止原因 |
| --- | --- | --- | --- | --- |
| [HashiCorp baseline](../baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/index.md) | `gpt-6-astra` / `low` | 16:23:12 | 40／13.11 分钟 | `external_error`；模型服务返回网安风险拒绝，首回合未完成 |
| [etcd baseline](../baseline/runs/2026-10-09_19-51-11-etcd_raft-baseline/index.md) | `gpt-6-astra` / `low` | 19:51:11 | 40／10.28 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [Dragonboat baseline](../baseline/runs/2026-10-09_20-01-29-dragonboat_raft-baseline/index.md) | `gpt-6-astra` / `low` | 20:01:29 | 40／12.74 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [OmniPaxos baseline](../baseline/runs/2026-10-09_20-14-15-omnipaxos-baseline/index.md) | `gpt-6-astra` / `low` | 20:14:15 | 40／35.59 分钟 | `external_error`；模型服务返回网安风险拒绝 |
| [EPaxos baseline](../baseline/runs/2026-10-09_20-49-52-swiftpaxos_epaxos-baseline/index.md) | `gpt-6-astra` / `low` | 20:49:52 | 40／28.13 分钟 | `turn_timeout`；第二回合超时 |

HashiCorp baseline 保留 32 次工具调用记录、6 份测试文件及输出，包含 3 次隔离执行；[工作报告](../baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/work/report.md)是中断时草稿，尚未覆盖全部已执行调查。两侧的回合、工具和执行记录采用自身口径，不直接对等。

以上完整组与 baseline 的方法、日期、模型或预算不同，不构成同条件配对。两侧成本与工具记录按各自口径读取。历史归档不作为新自主实验的发现输入。

归档保存原报告、研究状态、固定制品、捕获来源、执行差异和原始日志；排除凭据、虚拟环境、临时锁、`.execution`、编译缓存、可重建的 `experiments/**/workspace` 及本地权限覆盖配置。baseline 另排除 `.runtime`、`.codex`、`.agents`；运行期间已经清理的文件不补造。
