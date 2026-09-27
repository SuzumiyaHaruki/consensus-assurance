# consensus-assurance

使用 Codex 原生 Agent 的 CFT 实现审计方法与证据工具。围绕两个核心正确性维度，沿五类实现支撑恢复实际行为与事实，以有来源的问题和合法执行见证限定结论。

## 快速入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export PATH="$HOME/.local/bin:$PATH"
.venv/bin/consensus-assurance doctor --config configs/targets/swiftpaxos_paxos.yaml
.venv/bin/consensus-assurance inspect \
  --config configs/targets/swiftpaxos_paxos.yaml --repo /实际路径/swiftpaxos
```

真实运行需要现有认证、材料发送及隔离执行授权；具体运行命令、工具路径和开发测试见环境文档。工具不会自动下载目标或提高预算。

真实 Codex 路径现在使用持久会话：Agent 在获准的源码快照内自行搜索，并在独立草稿目录写测试或 TLA+ 文件；控制器校验完整提交后，从固定制品和干净副本正式执行。未受理草稿连同全部错误交回同一调查修订。运行前会实际探测文件权限；不能证明源码只读、草稿可写且其他文件不可读时，不发送模型任务。目标仓库与历史运行始终不作为 Agent 可写工作区。

`budget.native_turn_timeout` 限制单次原生调查，`budget.action_timeout` 限制正式工具动作，`budget.total_seconds` 限制整次运行；`agent_calls`、`experiments` 和 `model_checks` 分别计数。旧的材料分片、packet、指针修复和阶段调度已退出生产树；源码阅读和上下文管理交给 Codex。`allow_agent_materials: false` 会在发送源码前停止原生调查；正式目标执行还要求 `allow_experiments: true` 和 `execution_isolation: bwrap`。离线替身使用相同提交入口；它不验证真实 Codex 的自主构造效果。

默认 `verifier_backend: none`，直接检查无需 Java/TLC。要探索关键历史，在新运行中显式选择 `--verifier-backend tlc --tlc-jar /实际路径/tla2tools.jar`；模型方法届时按需加载，轨迹不自动确认实现。

## 目标配置

configs/targets 中包含 HashiCorp Raft 与 SwiftPaxos 的 Paxos、N²Paxos、Swift 配置；目标差异由 TargetConfig 声明，使用共同工具链后端。默认自主选题，--question 可指定定向问题。examples/toy_protocol 是隔离回归源代码，不是默认选题答案。

## 文档与记录

- [审计方法](docs/审计方法.md)：概念、分解路线、有限证据与方法来源。
- [运行工作流](docs/运行工作流.md)：继续、暂停、知识回流及代码入口。
- [环境要求](docs/环境要求.md)：安装、运行、目标接入、隔离与测试。
- [本轮验证记录](docs/合法执行见证改造.md)：能力、验证层次与未验证事项。
- [运行索引](runs/README.md)：用户指定归档及其实际结果。
