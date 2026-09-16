# consensus-assurance

**Domain-assisted、implementation-grounded：领域引导、实现为据的共识目标—义务驱动局部审计。** 目标决定审计意义，义务决定检查重点，代码决定模型行为，证据限定结论范围。

系统从仓库材料自主识别候选目标、义务与代码关系，交替执行覆盖探索、语义复核和有限局部检查。实现包括英文 agent 技能、受控代码实验、TLA+/TLC 搜索、轨迹校准、F1—F4 反馈及恢复。候选图不是整体正确性证明，也没有已知的全系统覆盖率分母。

当前保留的真实运行见 [实验报告](runs/2026-09-16_13-58-11-hashicorp_raft-real-run/report.md)。框架回归、受控模型和历史回复播放不替代真实自主验收；目前真实目标的自主建模验证闭环仍未验收通过。

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
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.round9.yaml
```

实际发送材料及隔离执行须有用户授权，命令与配置说明见 [HashiCorp 实验使用](docs/Hashicorp实验准备.md)。默认自主发现目标，`--goal` 仅为可选定向问题；`protocol: none` 不注入固定 Raft 性质清单。

```bash
.venv/bin/consensus-assurance run --config /实际路径/target.yaml
.venv/bin/consensus-assurance plan --config /实际路径/target.yaml
.venv/bin/consensus-assurance resume --run /实际路径/运行目录
.venv/bin/consensus-assurance report --run /实际路径/运行目录
```

`--repo` 优先于配置；均未提供才从实际桌面位置发现目标。配置相对路径以配置目录为基准。`plan` 会读取材料并调用已配置后端形成计划，不是无成本静态预览；只估算请用 `estimate`。

恢复不重置已消耗的调用和总时长。`--action-timeout 600` 只调整后续单动作上限，不能解决总预算耗尽、上下文过大或语义受阻。输入或控制器版本变化时使用新的运行或明确离线阶段，不能改写旧失败。

退出码 0 表示工作流正常结束，不表示协议正确；报告分别记录执行状态、产物接受、模型检查、校准与证据层级。

## 运行制品与回归数据

`runs/` 默认忽略，仅通过 `.gitignore` 的明确单目录例外归档用户指定实验。当前索引见 [runs/README.md](runs/README.md)。凭据、虚拟环境、临时锁和执行缓存不提交。删除旧归档不改写 Git 历史；回归所需的最小录制摘录保存在 `tests/fixtures/recorded_repair/`，不作为默认 discovery 输入。

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

运行时英文技能在 `src/consensus_assurance/resources/skills/`，短任务指令在 `resources/prompts/`，唯一加载清单是 `resources/task-skills.json`。控制器实际加载所选参考并记录 receipt，不假定 agent 会自行打开 Markdown 链接。

项目仓库：[SuzumiyaHaruki/consensus-assurance](https://github.com/SuzumiyaHaruki/consensus-assurance)。
