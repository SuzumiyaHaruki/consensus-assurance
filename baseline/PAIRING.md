# DeepSeek／HashiCorp 配对条件

本页说明中性配置与证据边界，不是调度器、评分器或运行授权。两份草案 [baseline](configs/hashicorp.deepseek-pair.baseline.yaml)／[完整组](configs/hashicorp.deepseek-pair.full.yaml) 默认关闭授权，正式重复实验前由用户确定条件。

| 条件 | 草案与实际边界 |
|---|---|
| 目标 | 相同干净 HashiCorp Raft 提交、模块和范围；记录各自捕获版本，旧试运行不能替代新配对 |
| 模型 | `deepseek-flash`、`high`、Responses、同一 provider；服务端具体修订未知 |
| 目录 | 同一 `configs/providers/deepseek-flash.models.json` 原字节，包括模板、上下文及 `supports_search_tool=true` |
| 共同功能 | 显式 `common_settings()` 与 `--ignore-user-config`；关闭子 Agent、自动 skills/plugins/memory/hooks、shell snapshot；保留普通 shell、原生压缩与目录声明的工具发现 |
| 重试 | 自定义 provider 请求／流重试 4／5，流空闲 300000 ms，关闭无限重连；无外层免费重试 |
| 配对开关 | 完整组显式 `codex_profile: single_agent`；默认 `null` 保持原方法路径，无 baseline 探针 |
| 调查方法 | 完整组保留双主线、研究问题、部分产品、固定执行、复核及知识回流；普通组使用原 `task.md` 和自由笔记 |
| 工具面 | baseline 的唯一 MCP 为必需的 `isolated_exec`；完整组沿用既有固定执行器，无此 MCP |
| 预算 | 两份草案均 3600 秒、单回合 900 秒、120 回合、动作 600 秒；完整组另有研究配额，须记录实际耗尽项 |
| 时间口径 | 两侧均从源码捕获前计时；准备、构建、工具、模型等待计入，不在截止后追加付费总结 |
| 工具链 | 本机所选 Go 1.25.8、Codex 0.155.0-alpha.16；正式实验固定相同 PATH，不能与旧 Go 1.23.5 运行混称同条件 |
| 依赖／构建 | 共享只读源码依赖，各 run 独立构建；run 内缓存复用和固定检查次数有差异。完整组 Rust 编译种子与普通组 Cargo 依赖复用不等价 |
| 工具环境 | baseline `inherit=none`，完整组 Agent `inherit=core` 加凭据排除，固定执行器 `clean_environment()`；不声称环境变量集合完全一致 |
| 源码／材料 | 源码与保留日志只读、工作／草稿可写；凭据不可读。完整组有方法和校验器权限，普通组不读取这些材料 |

## 环境与证据

| 路径 | 普通命令、管道、线程 | 同次调用内 TCP | 宿主 TCP |
|---|---|---|---|
| baseline 普通 shell | 可用 | 拒绝 | 拒绝 |
| 完整组 Agent 普通 shell | 可用 | 拒绝 | 拒绝 |
| baseline `isolated_exec` | 可用 | 独立网络内可用 | 拒绝 |
| 完整组固定执行器 | 可用 | 独立网络内可用 | 拒绝 |

两种执行器的文件视图不同，分别保留。`isolated_exec` 由 `/usr/bin/env -i` 启动可信 Python `-I -S`，只加载选定源码和包路径；不加载工作副本、site hooks 或个人配置。工具仅提供执行输出，不评定缺陷。多进程通信放在一次调用内，结束时清理后代进程；父进程用 pidfd 监控，避免创建线程退出误杀服务。

服务可用、实际模型请求暴露工具、真实模型选择并使用工具是三种证据。`check-env` 只检验标准 STDIO 清单及固定 TCP；不会创建额外 app-server 会话。实际 exec/resume、必需服务失败、长命令和请求结果回传由 [现有环境测试](tests/test_environment.py) 的本地 Responses fixture 验证。它使用真实 CLI 和目录，只将 endpoint、凭据换成合成值，不能证明线上认证、TLS、服务协商或模型推理。

本机原始 `2026-10-09_08-04-05-hashicorp_raft-smoke` 已人工核对并补存到 [精简归档](acceptance/2026-10-09-source-review/raw/smoke/run.json)：真实 DeepSeek 在同一 session 两次调用 MCP，首次 TCP 收发成功但预期断言失败，次轮只修预期后通过并解释原因。这是合成兼容性证据，不是共识缺陷或自主发现证据。本轮未重跑模型。

`single_agent` 的展开设置与原 `CODEX_HOME` 保存在既有 adapter 输入记录里；后续从该记录构造显式参数，不解析历史 CLI 语法或自动迁移 home。模型／provider／档位／目录等真实配置变化仍由现有 run 配置检查拒绝。旧记录可以离线阅读，不兼容的运行应新开。已生成的宿主 skills 必须显式禁用；空 home 不足以证明提示隔离。

当前所选 catalog 保持 `supports_search_tool=true`：真实请求通过客户端 `tool_search` 发现 `mcp__baseline_local.isolated_exec`。不再维护仅为诊断而翻转目录开关的测试变体。旧验收已从工作树清理，原始失败、版本与限制仍可从 [Git 归档](https://github.com/SuzumiyaHaruki/consensus-assurance/tree/29dd0aab5e38a5381ac69fbe61db3ffaa8230548/baseline/acceptance) 查看；未归档的本地初始化失败仅保留其[原始回执](acceptance/2026-10-09-source-review/raw/bootstrap-failure/check.json)及 stdout/stderr。当前核对与真实 TCP 证据保留在 [修改与验证报告](acceptance/2026-10-09-source-review/README.md)。

## 正式配对与离线复核

每次独立运行新建输出目录、研究状态和 session。完整组使用新建、位于 `/tmp` 以外的私有 `CODEX_HOME`，正常续接保持该目录；Codex helper 在 `/tmp` 下的限制已由历史实际环境暴露。运行器不继承旧审计或合成练习的答案。

baseline 输出到 `baseline/runs/`，完整组输出到根目录 `runs/`。两组可以在不同终端同时运行，各自拥有工作区、session 和 Codex home，仅共享只读目标与依赖。相同机器上的并行运行会竞争 CPU、内存和磁盘，也可能共同占用 API 额度；以时间为预算的正式配对宜顺序或交错运行，并记录顺序。

正式重复实验前记录：实现提交及 dirty 状态、目标提交、CLI／模型／目录／工具版本、缓存起点、机器负载、预设预算、重复次数与运行顺序、两侧授权和人工中断／复验政策。中断、失败、拒绝及零结果都保留，不能补跑替换后只报告成功样本。

人工对两组采用同一外部复核，记录原始主张、适用要求、合法前史、实际执行、反证、未决前提及去重关系。完整组 `confirmed` 与模型自报都只是材料，不是最终研究裁决；缺失前提的部分交付仍保留。共识相关缺陷是主要研究结果，一般鲁棒性问题可另述；不能仅凭 panic、代码位置数或“局部错误”判定类别或独立数量。

历史 40 分钟 baseline 报告有三个可复现的畸形输入 panic 案例：F1 的内存传输／运行节点用例实际终止进程；F2/F3 的 dispatch 测试捕获了 panic。F1/F3 涉及 `DecodeConfiguration`，该函数文档允许解码错误时 panic，问题在调用者的畸形字段处理责任。该次交付没有证明正常生产者、合法 CFT 执行前史或实际 TCP 部署可达性，因此不能写成三个已建立的独立共识正确性缺陷。按责任及修复关系去重，也不能只因共享函数而直接合并。

历史 [40 分钟 baseline](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/29dd0aab5e38a5381ac69fbe61db3ffaa8230548/baseline/runs/2026-10-09_08-06-10-hashicorp_raft-baseline/index.md) 与早期 120 分钟完整组的预算、Go 版本和网络条件不同，不能据此推断方法优劣。

当前追踪 2026-10-09 的 [baseline](runs/2026-10-09_16-23-12-hashicorp_raft-baseline/index.md) 和[完整组](../runs/2026-10-09_14-01-36-hashicorp_raft-real-run/report.md)。baseline 使用 Astra low、40 分钟预算，约 13 分 7 秒时因服务端网安风险拒绝中断；完整组使用 DeepSeek high、一小时预算，记录最后一次 Agent 调用超时、`run_stop.reason=resource_limit` 且剩余时间为 0。它们不构成同模型配对。此前的一小时 [DeepSeek baseline](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/25f48e19/baseline/runs/2026-10-09_14-01-25-hashicorp_raft-baseline/index.md) 保留在 Git 历史中；原始停止状态、失败与未决事项保持原样。
