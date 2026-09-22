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

## 目标配置

configs/targets 中包含 HashiCorp Raft 与 SwiftPaxos 的 Paxos、N²Paxos、Swift 配置；目标差异由 TargetConfig 声明，使用共同工具链后端。默认自主选题，--question 可指定定向问题。合成流程入口为 examples/toy_protocol/config.yaml，其结果不能冒充真实自主发现。

## 文档与记录

- [审计方法](docs/审计方法.md)：概念、分解路线、有限证据与方法来源。
- [运行工作流](docs/运行工作流.md)：继续、暂停、知识回流及代码入口。
- [环境要求](docs/环境要求.md)：安装、运行、目标接入、隔离与测试。
- [运行索引](runs/README.md)：用户指定归档及其实际结果。
