# consensus-assurance

领域引导、实现为据的 CFT 审计框架。先理解源码中的责任、行为和事实，再选择有来源的问题，用有界检查和实际证据限定结论。

## 快速入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export PATH="$HOME/.local/bin:$PATH"
export TLC_JAR="/实际路径/tla2tools.jar"
.venv/bin/consensus-assurance doctor --config configs/targets/swiftpaxos_paxos.yaml
.venv/bin/consensus-assurance inspect \
  --config configs/targets/swiftpaxos_paxos.yaml --repo /实际路径/swiftpaxos
```

真实运行需要现有认证、材料发送及隔离执行授权；具体运行命令、工具路径和开发测试见环境文档。工具不会自动下载目标或提高预算。

真实 Codex 路径现在使用持久会话：Agent 在获准的源码快照内自行搜索，并在独立草稿目录写测试或 TLA+ 文件；控制器校验完整提交后，从固定制品和干净副本正式执行。未受理草稿连同全部错误交回同一调查修订。运行前会实际探测文件权限；不能证明源码只读、草稿可写且其他文件不可读时，不发送模型任务。目标仓库与历史运行始终不作为 Agent 可写工作区。

`budget.native_turn_timeout` 限制单次原生调查，`budget.action_timeout` 限制正式工具动作，`budget.total_seconds` 限制整次运行；`agent_calls`、`experiments` 和 `model_checks` 分别计数。旧的 `material_chars`、`context_chars`、分片与 breadth/depth 配额仅服务离线旧阶段，不能衡量原生会话读了多少源码。`allow_agent_materials: false` 会在发送源码前停止原生调查；正式目标执行还要求 `allow_experiments: true` 和 `execution_isolation: bwrap`。历史 mock 阶段用于离线回归，不验证原生 Codex 的自主构造效果。

## 目标配置

configs/targets 中包含 HashiCorp Raft 与 SwiftPaxos 的 Paxos、N²Paxos、Swift 配置；目标差异由 TargetConfig 声明，使用共同工具链后端。默认自主选题，--question 可指定定向问题。合成流程入口为 examples/toy_protocol/config.yaml，其结果不能冒充真实自主发现。

## 文档与记录

- [审计方法](docs/审计方法.md)：概念、分解路线、有限证据与方法来源。
- [运行工作流](docs/运行工作流.md)：继续、暂停、知识回流及代码入口。
- [环境要求](docs/环境要求.md)：安装、运行、目标接入、隔离与测试。
- [运行索引](runs/README.md)：用户指定归档及其实际结果。
