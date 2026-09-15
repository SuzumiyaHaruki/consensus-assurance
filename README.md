# consensus-assurance

**Domain-assisted、implementation-grounded：领域引导、实现为据的共识义务驱动局部审计。** 只有一条领域引导流程，不增加盲测或解盲模式。方法是：**目标决定审计意义，义务决定检查重点，代码决定模型行为，证据限定结论范围。**

最小实现包含材料读取、候选 G—O—C 关系生成、关系驱动选择、运行时模型/检查器/实验生成、真实轨迹的 TLC 可达性校准、有限模型搜索、F1—F4 修订与检查点恢复。关系图用于组织审计，不自动证明整个实现正确。

当前状态：用户于 2026-09-15 20:06 启动的第八轮真实运行已接受 2 个目标、3 项义务和 2 个审计单元，实际调用 agent 16 次，两次建模回复均请求依赖材料，**没有有效 Bundle、落盘模型或 TLC 性质检查**。复核的引用校验与修复上下文不一致，反复请求已缓存材料耗用了补读次数；新增绑定的定位和用途修正也未完成。具体见 [第八轮真实实验问题说明](docs/第八轮真实实验问题说明.md)及经用户授权归档的 [原运行报告](runs/2026-09-15_20-06-49-hashicorp_raft-real-run/report.md)。17:07 的 [第七轮失败](docs/第七轮真实实验问题说明.md)和更早运行保持各自历史身份；本地回归与离线回放不替代真实自主验收，**真实自主审计闭环仍未验收通过**。

第八轮增量修复已加入建模前的受控范围接回、具体问题解除与范围限制分离、发送前上下文准入和增量复核。原始 17:07 运行保持失败历史身份；受控新增依赖链与原回复离线接回分别验收，不称为新的 HashiCorp 自主成功。当前改动与限制见 [第八轮范围接回与验收](docs/第八轮范围接回与验收.md)，候选内容建议见 [离线语义审查](docs/第八轮候选语义审查.md)。

当前流程增加了持续职责探索与语义复核：职责尚无 goal 时也能形成探索任务，局部检查通过后仍可复核问题是否过弱，关系和适用条件可在建模前后通过 F2 修订。它们与局部验证交替执行，不是多种运行模式。前一轮修复记录见 [第七轮复核与材料闭环](docs/第七轮复核与材料闭环.md)。第四至第七轮记录保留其历史身份。Goal 可以覆盖多个义务，模型仍按局部范围检查；概览没有已知完备分母，不计算全系统覆盖率，也不把复核意见当作证明。

[第一轮验收](docs/本次验收.md)、[第二轮验收](docs/第二轮修改与验收.md)、[第三轮审计修订](docs/第三轮审计修订与验收.md)及最终任务书是历史记录；其“尚未启动实验”等表述对应当时阶段。当前使用方式以本 README 和本轮说明为准。

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

第一条用显式 mock 夹具执行非 Raft 计数器、轨迹校准和 F3 扩展；该历史夹具显式把探索与复核预算设为 0，只测试局部链。默认产品流程与新增覆盖回归会执行探索和语义复核。第三条是**预设的本地开发回归**：调用真实投票代码、采集写入与响应、验证有限轨迹和预置模型，不执行自主发现、不调用 agent。

缺少 `TLC_JAR` 或 Java 时，依赖真实 TLC 的 pytest 用例明确跳过；这不算工具验收通过。

可以只做本地能力探测并生成准确的自主分析受阻报告：

```bash
.venv/bin/consensus-assurance run --config configs/targets/local_only.yaml
```

此配置设置 `allow_agent_materials: false`，框架在创建 agent 请求前停止材料发送；Codex 版本和帮助探测只执行本地命令。

## 自主分析入口

以下入口已经实现，最近一次真实尝试尚未完成自主审计闭环。调用真实 Codex 会把选择的材料交给用户现有认证所连接的后端，需具备相应授权。本次开发不运行以下命令：

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

每次运行使用独立目录，`runs/` 默认不进版本控制；用户明确指定的历史归档使用单目录例外，本次仅归档 `2026-09-15_20-06-49-hashicorp_raft-real-run`，排除临时锁和 `.execution` 缓存：

新运行目录使用本地时间、实现、模式和命令命名，例如 `2026-09-14_16-00-00-hashicorp_raft-real-run`；同秒重名追加序号。内部对象 ID 仍保持唯一标识。旧运行目录继续支持恢复，不迁移含绝对路径的历史制品。现存运行用途见本地 [运行索引](runs/README.md)。

```text
config.json / snapshot.json       配置、执行输入与可读文件清单
source/                          脱敏筛选后的实际工作区副本
catalogue.json / materials.json   可发现材料与实际读过的片段
agent/                           英文请求、schema、原始结构化响应
packets/                         实际任务材料、复核契约、输入长度 receipt
state.json 的 read_plans          原读取请求、逐项状态、唯一材料账本与未满足范围
graph.json / plan.json           候选关系、选择依据与审计单元
models/v*/                       独立行为、检查器、配置、观测与实验版本
experiments/                     每次实验的独立副本
calibrations/                    原始事件、投影、TLC 轨迹约束模型
logs/                            实际命令 stdout/stderr 与执行记录
actions/                         执行前任务与实际结果，支持继续原动作
graph-commits/                   语义变更的原子提交与幂等恢复记录
reachability/                    辅助触发检查及其真实 TLC 输出
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

项目仓库：[SuzumiyaHaruki/consensus-assurance](https://github.com/SuzumiyaHaruki/consensus-assurance)。除上述明确授权的运行归档及其中的源码快照外，本地运行制品、目标仓库副本、虚拟环境和 TLC 二进制不提交到 Git。

覆盖实验准备配置：[hashicorp_raft.coverage.yaml](configs/targets/hashicorp_raft.coverage.yaml)。权限默认关闭；本轮没有运行该配置。

## 第五轮检查后的受限实验准备

本轮只执行框架和受控样例测试，没有启动新的 HashiCorp 自主分析。配置 [hashicorp_raft.round5.yaml](configs/targets/hashicorp_raft.round5.yaml) 不预设 goal，材料发送与目标执行默认关闭，沿用 20 次 agent 调用上限。

先执行不调用后端、不读取代码内容的路径及预算估算：

```bash
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.round5.yaml
```

`estimate` 的调用数是计划下限，补读、修复、模型后复核及后果调查可能超出它；不会自动加预算。正式启动方式见 [实验准备](docs/Hashicorp实验准备.md)，先检查本轮代码，再决定材料发送和执行授权。

报告区分原始 checker 结果、当前版本执行进度、触发可达性、未解决复核意见和未完成校准。`holds` 保留其有限模型含义；触发不可达时不能称为有效交互覆盖。确认局部义务违反后会记录后果调查、补偿机制候选或暂缓理由，不自动提升成目标违反。

## 第六轮：候选修复与受限重试

新配置为 [hashicorp_raft.round6.yaml](configs/targets/hashicorp_raft.round6.yaml)，权限仍默认关闭，不预设提交、快照或选举目标。先运行只读路径/预算估算：

```bash
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.round6.yaml
```

图校验现在返回带对象、字段和材料的诊断；修复会话分别保存原候选、当前版本、patch、诊断与有限计数。代码声明锚点和行为范围分开，同一位置的 `associations` 可服务多项义务；单元 `code_uses` 声明直接或支撑用途，支撑不等于已检查。英文指导位于 `resources/prompts/graph_consistency.txt`。

修复总上限默认每任务 4 次，单问题重复失败默认 1 次，无进展/循环累计 2 次停止，仍受总 agent_calls 和时间限制。针对同一控制器版本的运行，可显式使用 `resume --run <目录> --repair-attempts 6` 调整总修复上限；不重置已用调用、单问题失败或循环计数，不自动增加总付费调用上限。

旧控制器运行不直接恢复为“原版本成功”。`scripts/offline_candidate.py` 可将用户明确选择的历史候选与显式 patch 播放到新目录，仅使用 mock 后端，不执行目标；它不是新自主分析。历史失败运行保持原样，具体命令、出处缺口和本轮结果见第六轮说明。

## 第七轮的材料与接口约定

复核请求明确携带每个对象的类型、版本、所需 aspect、问题及来源，统一来自 `workflow/review_contract.py`。接口补充保留原分析和争议，不自动转换成“未发现问题”。读取请求使用快照中的实际文件长度做整批预检；越界不会被静默截到 EOF。初读、探索、局部与修复补读共用可恢复的读取账本。

`material_chars`/`material_chunks` 限制唯一取得的源范围；`context_chars` 限制单次 prompt 字符数（schema 另计），都不是 token 或费用。默认为局部依赖保留 35% 材料能力，为广度保留 20%；它们是可配置的有限调度选择，不是最优比例。已消费总额度不自动增加，未满足请求保留延期原因。具体限制和下一次实验入口见本轮验收说明。

`reading_purpose: context` 只请求补充上下文；`dependency` 会对实际图 diff 分类，必要时生成有版本的 ScopeUpdate。新增背景代码不会把其所有关联义务自动加入待检查列表。审计问题、义务、故障假设或排除条件的改变仍须 F2；事件路径的具体化需要范围判断和后续对应复核。

探索/复核预算按实际后端准入计数，准备超限单独记录并有限分包，未运行子任务不算父任务完成。同一已准入任务的修复继续消耗总 agent_calls；局部 ScopeAssessment 也消耗 semantic_reviews。收到实际结果不意味着问题解决。独立 scope_limitations 与影响当前判断的 limitations 分开，按 IssueResolution 明确解决旧问题，未解决的依赖继续限制结论。
