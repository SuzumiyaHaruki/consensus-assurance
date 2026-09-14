# consensus-assurance

**Domain-assisted、implementation-grounded：领域引导、实现为据的共识义务驱动局部审计。** 只有一条领域引导流程，不增加盲测或解盲模式。方法是：**目标决定审计意义，义务决定检查重点，代码决定模型行为。**

最小实现包含材料读取、候选 G—O—C 关系生成、关系驱动选择、运行时模型/检查器/实验生成、真实轨迹的 TLC 可达性校准、有限模型搜索、F1—F4 修订与检查点恢复。关系图用于组织审计，不自动证明整个实现正确。

第一轮完成过本地框架和固定目标回归，历史结果见 [第一轮验收](docs/本次验收.md)。第二轮增量只执行本地框架、mock、受控样例和 TLC，不启动 Hashicorp 真实自主链，不发送其材料。详见 [第二轮修改与验收](docs/第二轮修改与验收.md)。**真实自主发现质量仍未验收；本地回归不能替代它。**

## 安装

需要 Python 3.10+。`requirements.txt` 安装运行依赖及本项目，`requirements-dev.txt` 额外安装测试和构建工具。系统工具及本次实测版本见 [环境要求](docs/环境要求.md)。从项目目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/consensus-assurance --help
```

模型检查还需要 Java 和官方 [TLC 工具](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4)。本次工具位于 `.tools/tla2tools.jar`，不提交到 Git。使用环境变量或配置提供路径：

```bash
export TLC_JAR="$PWD/.tools/tla2tools.jar"
.venv/bin/consensus-assurance doctor
```

Hashicorp Raft 实验需要 Go 及目标依赖的本地模块缓存；默认关闭模块下载（`GOPROXY=off`）。依赖缺失会如实报告。默认需要 Linux bubblewrap：只允许实验工作副本写入，并隐藏用户主目录及其他运行日志；当前不隔离网络命名空间。`execution_isolation: workspace` 是显式的较弱工作副本模式，不是安全沙箱。框架不自动降级。

## 本地回归：无需发送仓库材料

```bash
.venv/bin/consensus-assurance run --config examples/toy_protocol/config.yaml
TLC_JAR="$TLC_JAR" .venv/bin/python -m pytest -q
.venv/bin/python scripts/local_regression.py \
  --repo "$HOME/Desktop/hashicorp-raft" --tlc-jar "$TLC_JAR"
```

第一条用显式 mock 夹具执行非 Raft 计数器、轨迹校准和 F3 扩展。第三条是**预设的本地开发回归**：调用真实投票代码、采集写入与响应、验证有限轨迹和预置模型，不执行自主发现、不调用 agent。

缺少 `TLC_JAR` 或 Java 时，依赖真实 TLC 的 pytest 用例明确跳过；这不算工具验收通过。

可以只做本地能力探测并生成准确的自主分析受阻报告：

```bash
.venv/bin/consensus-assurance run --config configs/targets/local_only.yaml
```

此配置设置 `allow_agent_materials: false`，框架在创建 agent 请求前停止材料发送；Codex 版本和帮助探测只执行本地命令。

## 自主分析入口

以下入口已经实现，但其真实自主效果本次未验收。调用真实 Codex 会把选择的材料交给用户现有认证所连接的后端，需具备相应授权。本次开发不运行以下命令：

```bash
consensus-assurance run --repo "/实际路径/hashicorp-raft"
consensus-assurance plan --repo "/实际路径/hashicorp-raft"
consensus-assurance inspect --repo "/实际路径/hashicorp-raft"
consensus-assurance resume --run "/实际路径/runs/<run-id>"
consensus-assurance report --run "/实际路径/runs/<run-id>"
```

恢复时若单动作超时，可使用 `consensus-assurance resume --run "/实际路径/runs/<run-id>" --action-timeout 600` 调整后续动作上限。总时长、调用次数及已消耗预算不重置，实际超时仍受剩余总时长限制。变更写入检查点和事件记录；`config.json` 保留初始配置，当前配置以 `state.json` 为准。已完成阅读可复用，失败的 agent 请求会重新调用后端，不是接续被终止的模型会话。延长超时不能保证后端返回成功。

默认 `protocol: none`，不因 adapter 是 Hashicorp 就加入 Raft 标准性质清单；跨协议 inquiry 仍提供领域视角。显式选择 `protocol: raft` 只添加带出处的参考材料，复用同一流程，不代表其性质已适用。

`plan` 完成材料读取和关系计划后停止，不执行模型。默认不要求目标；`--goal` 仅用于可选定向问题。`--repo` 优先于配置，其后才按真实桌面配置发现目标。配置中的相对路径以配置文件目录为基准，CLI 相对路径以当前目录为基准。不会下载替代仓库。

配置示例：[hashicorp_raft.example.yaml](configs/targets/hashicorp_raft.example.yaml)。后端、协议提示、目标路径、实验权限与预算独立配置。mock 必须显式指定 `agent_backend: mock` 和响应夹具文件，没有隐藏默认答案。

报告顶部展示材料阅读、关系图接受、模型、校准和证据进度。执行表分别列出执行记录状态、产物或后续处理、性质判定边界；版本探测不显示为性质未知，agent 回复完成也不表示关系图已被接受。原始工具输出和校验诊断保留链接。

退出码 0 表示本次计划或工作流正常结束，**不是正确性结论**；2 表示配置、工具、预算或其他条件导致停止。结论以报告中的执行、模型、校准及发现状态为准。

## 运行制品

每次运行使用独立目录，`runs/` 不进版本控制：

新运行目录使用本地时间、实现、模式和命令命名，例如 `2026-09-14_16-00-00-hashicorp_raft-real-run`；同秒重名追加序号。内部对象 ID 仍保持唯一标识。旧运行目录继续支持恢复，不迁移含绝对路径的历史制品。现存运行用途见本地 [运行索引](runs/README.md)。

```text
config.json / snapshot.json       配置、执行输入与可读文件清单
source/                          脱敏筛选后的实际工作区副本
catalogue.json / materials.json   可发现材料与实际读过的片段
agent/                           英文请求、schema、原始结构化响应
graph.json / plan.json           候选关系、选择依据与审计单元
models/v*/                       独立行为、检查器、配置、观测与实验版本
experiments/                     每次实验的独立副本
calibrations/                    原始事件、投影、TLC 轨迹约束模型
logs/                            实际命令 stdout/stderr 与执行记录
actions/                         执行前任务与实际结果，支持继续原动作
history/ / events.jsonl           历史检查点与追加事件
state.json / report.md            当前记录与中文报告
```

模型结果只支持已检查模型范围。校准只说明有限真实观测可被模型解释。生成的测试断言或 agent 的 `confirmed` 声称不会自动升级为实现违反。事件监测器只支持明确可观测字段的有限安全断言；还必须关联实际输入、校准、同一操作的前提、合法性及适用性。部分观测能解释一条坏模型路径不构成实际违反。义务违反不自动升级为目标违反。

恢复保留活动单元、模型、反例与待执行动作。F1/F2 只使相关解释或语义版本的结果需重验；F3 的旧结果仍属于旧范围；F4 不使原模型搜索失效。输入无法安全关联则要求新建运行，不把历史复用伪装成新执行。

## 文档与扩展

- [第二轮修改与验收](docs/第二轮修改与验收.md)
- [后续 Hashicorp 实验准备（尚未执行）](docs/Hashicorp实验准备.md)
- [框架与八步工作流](docs/架构.md)
- [扩展实现、agent 和验证工具](docs/扩展.md)
- [限制与证据语义](docs/限制.md)
- [本次验收记录](docs/本次验收.md)

项目仓库：[SuzumiyaHaruki/consensus-assurance](https://github.com/SuzumiyaHaruki/consensus-assurance)。本地运行制品、目标仓库副本、虚拟环境和 TLC 二进制不提交到 Git。
