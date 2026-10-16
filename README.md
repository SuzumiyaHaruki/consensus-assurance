# consensus-assurance

使用 Codex 寻找并验证 CFT 实现中的正确性缺口。以共识形成／推进和上下文／权限切换为阅读主线，整体理解与局部调查相互修正。可以先提出有来源的问题并直接检查，Behavior／Fact 条目按需共享和修订；结论仍受适用责任、合法前史、实际观测和独立判据约束。测试数量和地图完整度不是目标。

## 快速入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export PATH="$HOME/.local/bin:$PATH"
.venv/bin/consensus-assurance doctor --config configs/ca/deepseek.yaml
.venv/bin/consensus-assurance inspect \
  --config configs/ca/deepseek.yaml --repo /实际路径/hashicorp-raft
```

真实运行需要现有认证、材料发送及隔离执行授权；具体运行命令、工具路径和开发测试见环境文档。工具不会自动下载目标或提高预算。

真实 Codex 路径现在使用持久会话：Agent 在获准的源码快照内自行搜索，并在独立草稿目录写直接测试及辅助文件；控制器校验完整提交后，从固定制品和干净副本正式执行。未受理草稿连同全部错误交回同一调查修订。运行前会实际探测文件权限；不能证明源码只读、草稿可写且其他文件不可读时，不发送模型任务。目标仓库与历史运行始终不作为 Agent 可写工作区。

`budget.agent_turn_timeout` 限制单次Codex 调查，`budget.action_timeout` 限制正式工具动作，`budget.total_seconds` 限制整次运行；`agent_calls` 与 `experiments` 分别计数。旧的材料分片、packet、指针修复和阶段调度已退出生产树；源码阅读和上下文管理交给 Codex。`allow_agent_materials: false` 会在发送源码前停止Codex 调查；正式目标执行还要求 `allow_experiments: true` 和 `execution_isolation: bwrap`。离线替身使用相同提交入口；它不验证真实 Codex 的自主构造效果。

问题的局部暂停保留未决工作并继续 Codex 会话；开放运行持续推进到控制器时间／调用边界或真实中断；没有下一项完整检查不能结束整轮。用户预先指定的有限定向任务处置完毕后可结束。`research.json` 给出当前问题、实际结果位置、必要缺口、知识修订及剩余能力。只保留总时间、模型调用和目标执行等实际资源限制；增加总时长不会自动增加调用或执行次数。

新运行支持源码调查、条件探索和真实实现的直接检查／受控调度；执行后端支持 Go、Rust/Cargo、Java/Maven 和 Python。直接测试不等价于模型空间穷举。当前方法版本和加载路径以[权威清单](src/consensus_assurance/resources/task-skills.json)为准。旧运行及原始报告保持只读；恢复旧方法必须使用其原 Git 版本。含已退役产品配额的本地配置需从当前模板重新生成。

## 目标配置

`configs/targets/` 只描述七个目标的执行后端、模块、分析范围和测试路径；不绑定模型、预算、本机路径或授权。`configs/ca/` 与 `configs/baseline/` 分别保存两种入口的公共运行配置，均默认关闭授权。`configs/providers/` 保存模型目录；本机运行配置保存在忽略的 `configs/local/ca/` 和 `configs/local/baseline/`。

两个入口通过 `target_config` 引用同一目标；命令行 `--target-config configs/targets/zookeeper.yaml` 可选择另一目标。YAML 引用相对于所在文件解析，命令行路径相对于当前目录解析。CA 的目标文件提供默认值，运行配置中的显式 `target` 字段覆盖对应默认值；模型、预算与授权只取运行配置。保存到每次运行中的配置已经展开，不依赖目标模板后续是否移动。

baseline 保持仓库级入口 `python -m baseline`，CA 提供可安装的 `consensus-assurance` 命令。两者共享工具和配置读取，不合并研究流程。使用 `pip install -e '.[test,baseline]'` 安装开发依赖；所有测试位于 `tests/`，`pytest -m 'not real'` 选择普通离线测试，`real` 标记的外部工具检查按环境单独运行。

历史 `runs/`、`baseline/runs/` 和开发用 `AGENTS.md` 保留在本地但不进入发布文件；旧 `baseline/acceptance/` 产物已清理，可从已有 Git 历史查阅。

## 文档与记录

- [审计方法](docs/审计方法.md)：选择性理解、因果调查、证据与方法来源。
- [运行工作流](docs/运行工作流.md)：继续、暂停、知识回流及代码入口。
- [环境要求](docs/环境要求.md)：安装、运行、目标接入、隔离与测试。
- [历史运行索引](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/7458957eccbac5b2f4a9178b6a4ca3108bb67231/runs/README.md)：此前提交保留的实验档案。

v62 将语义责任收敛到调查、固定实验和解释；共享知识保留明确版本引用。旧图协调及重复裁决存储已退出。新实验使用英文研究记录和报告，直接展示当前问题、解释及证据限制，不生成另一份中文摘要。
