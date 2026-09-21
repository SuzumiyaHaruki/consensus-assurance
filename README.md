# consensus-assurance

**领域引导、实现为据的 CFT 义务审计。** 从 Activity、Behavior、Fact 理解实现，推导 Obligation 和有界 AuditQuestion，由 Evidence 限定结论范围。

系统先从仓库材料恢复七类 Activity 及 Behavior/Fact 的不完整骨架，在有界 Surface 扩展与单个候选的深度分析之间交替，补读后解释关闭、保留证据不足或推导义务与代码关系，按当前问题优先取得关键材料、执行直接检查或局部模型，并保留有限覆盖探索和语义复核。实现包括英文 agent 技能、受控代码实验、TLA+/TLC 搜索、轨迹校准、F1—F4 反馈及恢复。候选图不是整体正确性证明，也没有已知的全系统覆盖率分母。

当前 Git 归档为 [2026-09-21 Paxos 自主分析](runs/2026-09-21_13-56-50-swiftpaxos_paxos-real-run/report.md)：使用 `medium`，形成 1 项义务和 1 个审计单元；模型草稿未受理，没有模型搜索、校准或性质证据。旧运行保留本地及已有 Git 历史，归档切换不删除原始证据。

当前实现将任务工作集与完整审计历史分开，并允许先保存有据的模型、后补 harness。语法检查、探索性搜索、真实轨迹校准与实现确认分别记录。当前方法见 [审计方法](docs/审计方法.md)，不代表已重新完成 HashiCorp 自主实验。

## 安装与工具

需要 Python 3.10+。运行依赖在 `requirements.txt`，测试和构建依赖在 `requirements-dev.txt`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/consensus-assurance --help
```

TLC 需要 Java 和官方 `tla2tools.jar`；系统工具不由 pip 安装：

```bash
export TLC_JAR="$PWD/.tools/tla2tools.jar"
.venv/bin/consensus-assurance doctor
```

HashiCorp Raft 实验还需要 Go、已准备的模块缓存和默认的 bubblewrap 隔离。缺少工具或依赖时如实受阻，不自动下载目标仓库或切换弱隔离。详情见 [环境要求](docs/环境要求.md)。

## 使用

无需发送目标材料的框架回归：

```bash
.venv/bin/consensus-assurance run --config examples/toy_protocol/config.yaml
TLC_JAR="$TLC_JAR" .venv/bin/python -m pytest -q
```

示例使用明确标记的 mock；真实 TLC 的执行也只能支持相应合成模型。缺少 Java/TLC 的测试会单独跳过，不算通过。

先检查目标和预算：

```bash
.venv/bin/consensus-assurance inspect --repo "$HOME/Desktop/hashicorp-raft"
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.yaml
```

实际发送材料及隔离执行须有用户授权，命令与配置说明见 [HashiCorp 实验使用](docs/Hashicorp实验准备.md)。默认自主发现目标，`--question` 仅为可选定向问题；`protocol: none` 不注入固定 Raft 性质清单。

```bash
.venv/bin/consensus-assurance run --config /实际路径/target.yaml
.venv/bin/consensus-assurance plan --config /实际路径/target.yaml
.venv/bin/consensus-assurance resume --run /实际路径/运行目录
.venv/bin/consensus-assurance report --run /实际路径/运行目录
```

`--repo` 优先于配置；均未提供时要求显式指定目标。配置相对路径以配置目录为基准。`plan` 会读取材料并调用已配置后端形成计划，不是无成本静态预览；只估算请用 `estimate`。

恢复使用运行自身保存的源码副本，保留已完成的 Agent/执行结果与已用预算；不保证内部任意语句中断后的透明恢复。`--action-timeout 600` 只调整后续单动作上限，不能解决总预算耗尽、上下文过大或语义受阻。输入被修改或控制器版本变化后需新运行；旧报告只读，失败原文不变。

退出码 0 表示工作流正常结束，不表示协议正确；报告分别记录执行状态、产物接受、模型检查、校准与证据层级。

## 运行制品与回归数据

`runs/` 默认忽略，仅通过 `.gitignore` 的明确单目录例外归档用户指定实验。当前索引见 [runs/README.md](runs/README.md)。凭据、虚拟环境、临时锁和执行缓存不提交。删除旧归档不改写 Git 历史；回归所需的最小合成资源保存在 `tests/fixtures/`，不作为默认 discovery 输入。

原始分析仓库只读，实验在单独副本中运行。清理活动运行前必须先确认已停止；默认不得擅自删除证据。

## 文档与运行时技能

- [架构与模块职责](docs/架构.md)
- [运行工作流、预算、修订与技能路由](docs/运行工作流.md)
- [环境要求](docs/环境要求.md)
- [HashiCorp 实验使用](docs/Hashicorp实验准备.md)
- [测试与打包](docs/测试.md)
- [扩展接入](docs/扩展.md)
- [能力限制与证据边界](docs/限制.md)
- [上游方法借鉴与许可](docs/上游方法借鉴.md)

运行时英文技能在 `src/consensus_assurance/resources/skills/`，短任务指令在 `resources/tasks/`，唯一加载清单是 `resources/task-skills.json`。控制器实际加载所选参考并记录 receipt，不假定 agent 会自行打开 Markdown 链接。

项目仓库：[SuzumiyaHaruki/consensus-assurance](https://github.com/SuzumiyaHaruki/consensus-assurance)。

控制器版本以 `resources/task-skills.json` 为唯一来源。候选按明确 ID 继续、暂停和恢复；读取没有次数硬配额，材料总量、上下文、Agent 调用、时间和执行预算仍有效。直接检查按整体审阅，实际观察与最终结论范围分别记录。详见 [当前工作流](docs/运行工作流.md)。

源码审计默认不需要执行后端；HashiCorp 与三个 SwiftPaxos 变体共用 go_module，目标差异写入 YAML。新增配置为 `configs/targets/swiftpaxos_{paxos,n2paxos,swift}.yaml`，均为 protocol:none，材料发送及目标执行默认关闭。实际环境准备、隔离构建与未决限制见 [环境要求](docs/环境要求.md)；最新 Paxos 自主分析结果见 [运行索引](runs/README.md)。
