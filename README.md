# consensus-assurance

使用 Codex 寻找并验证 CFT 实现中有适用依据的正确性缺口。Activity → Behavior → Fact → Candidate → Obligation → 检查／复核 → 理解回流服务缺陷调查；A1/A2 主导，五类支撑按依赖展开。整体理解、保护分析和负结果是手段，测试数量或跑满预算不是目标；没有发现配额，合法执行与独立证据标准保持不变。

## 快速入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export PATH="$HOME/.local/bin:$PATH"
.venv/bin/consensus-assurance doctor --config configs/targets/etcd_raft.yaml
.venv/bin/consensus-assurance inspect \
  --config configs/targets/etcd_raft.yaml --repo /实际路径/etcd-raft
```

真实运行需要现有认证、材料发送及隔离执行授权；具体运行命令、工具路径和开发测试见环境文档。工具不会自动下载目标或提高预算。

真实 Codex 路径现在使用持久会话：Agent 在获准的源码快照内自行搜索，并在独立草稿目录写直接测试及辅助文件；控制器校验完整提交后，从固定制品和干净副本正式执行。未受理草稿连同全部错误交回同一调查修订。运行前会实际探测文件权限；不能证明源码只读、草稿可写且其他文件不可读时，不发送模型任务。目标仓库与历史运行始终不作为 Agent 可写工作区。

`budget.agent_turn_timeout` 限制单次Codex 调查，`budget.action_timeout` 限制正式工具动作，`budget.total_seconds` 限制整次运行；`agent_calls` 与 `experiments` 分别计数。旧的材料分片、packet、指针修复和阶段调度已退出生产树；源码阅读和上下文管理交给 Codex。`allow_agent_materials: false` 会在发送源码前停止Codex 调查；正式目标执行还要求 `allow_experiments: true` 和 `execution_isolation: bwrap`。离线替身使用相同提交入口；它不验证真实 Codex 的自主构造效果。

Candidate／family／focus 的局部停止保留未决工作并继续Codex 会话；开放运行持续推进到控制器时间／调用边界或真实中断；没有下一项完整检查不能结束整轮。用户预先指定的有限定向任务处置完毕后可结束。`research.json` 给出已映射关系的未知、问题交接及剩余能力。增加总时长不会自动增加正式执行、Unit、复核或修订额度。

新运行支持源码调查、条件探索和真实实现的直接检查／受控调度；内置 TLA/TLC 产品、搜索及校准链已退出，不再要求 Java 或 JAR。直接测试不等价于模型空间穷举。旧运行及原始报告保持只读，旧模型配置会明确拒绝。

## 目标配置

configs/targets 保留 etcd Raft、HashiCorp Raft、Dragonboat、OmniPaxos、SwiftPaxos 中 EPaxos 的五份目标模板，以及一份 DeepSeek 接入示例。目标模板默认关闭材料发送和执行授权；本地 `*.run.yaml` 用于 GPT，`*.deepseek.run.yaml` 用于 DeepSeek，均不提交。目标差异由 TargetConfig 声明，使用共同工具链后端。默认自主选题，--question 可指定定向问题。examples/toy_protocol 是隔离回归源代码，不是默认选题答案。

## 文档与记录

- [审计方法](docs/审计方法.md)：概念、分解路线、有限证据与方法来源。
- [运行工作流](docs/运行工作流.md)：继续、暂停、知识回流及代码入口。
- [环境要求](docs/环境要求.md)：安装、运行、目标接入、隔离与测试。
- [运行索引](runs/README.md)：用户指定归档及其实际结果。
