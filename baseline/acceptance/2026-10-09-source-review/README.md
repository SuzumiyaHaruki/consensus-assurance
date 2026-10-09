# baseline 与可选配对支持精简：修改和验证

起点：`d52ad947163aaeff033c862e44683eb909f76b1b`。先完整应用用户补丁，再按任务书收缩职责；代码位于评审分支 `codex/baseline-simplification-20261009`。未修改 `baseline/task.md`、模型／档位／目录、方法资源、研究类型或正式配对配置，未运行付费模型或完整审计。

## 实现与保留例外

- `c6fcdf73`：保留非首位空字符串参数，仍拒绝空程序、错误类型和 NUL；准备阶段局部超时报原有运行错误，真正耗尽总时间才记 `total_deadline`。宿主超时优先于迟到的 native completion。
- `c398a8ee`：`single_agent` 只保存并复用既有 adapter 配置记录，实际 exec/resume 继续显式覆盖并使用 `--ignore-user-config`。删除通用 CLI 参数解释器、历史 argv 扫描、可信对象互相防篡改和旧 home 自动迁移。保留真实连接变化检查、原 home 续接及默认 `null` 路径。
- `08d43ff6`：普通审计删除固定 smoke、评分、预算覆盖和特殊停止分支；删除 app-server RPC 客户端。服务清单／固定 TCP 改由显式 `check-env` 经标准 STDIO 检查，普通运行不冒称已验证。小样本请求工具面与双回合练习复用现有测试入口。
- 干净代码以 Git 提交和 dirty 状态标识；修改／外部安装代码保留安全字节，不再维护固定模块清单及结束扫描。CLI 一次性身份和实际 catalog 原字节保留，MCP 描述仅记录一次。
- 报告直接引用 `changes/files/report.md`，未变则复用该版本；后续超时编辑单独留存，旧归档链接不改写。

两项必要例外继续保留：本机 CLI 在首次提示初始化时才安装内置 skills，空 home、`features list`、`debug models --bundled` 均不能提前完成抑制；因此保留一次离线初始化和显式 `skills.config`，详细提示解析仅在环境检查中运行。MCP 子进程稍后重新加载 `local_exec.py` 和存储模块，Git 启动记录本身不能约束后来读取的字节，因此保留两项启动前字节核对，不增加部署锁或新 gate。

`isolated_command` 的 **22 行（含分隔空行）原样迁移**到 baseline；完整组 `sandbox_command` 文件视图和进程隔离未合并。测试内仅保留通用 Go/Rust 样本构造，不搬迁被删除的 smoke 场景与评分器。

## 本机验证

工具：Python **3.10.12**、Codex **0.155.0-alpha.16**、Go **1.25.8**、Cargo/Rust **1.88.0**、Bubblewrap **0.6.1**。不是补丁作者的缺工具环境。

| 检查 | 本机结果 |
|---|---|
| 修改前 `pytest -q baseline/tests tests/unit/test_codex_agent.py` | **139 passed，218.72 秒** |
| 两项缺陷对应回归 | **20 passed，28 deselected** |
| 精简后单元回归 | **84 passed，6.11 秒** |
| 首轮真实环境 | **24 passed、3 failed，101.32 秒**；失败及处理见下文 |
| 有针对性的环境复测 | **4 passed，24 deselected，72.47 秒** |
| 相关完整验证命令（下方） | **165 passed，208.52 秒**，失败／跳过均为 0 |
| 最后收紧归档范围及 Python 3.10 超时转换后：`pytest -q baseline/tests/test_baseline.py tests/unit/test_codex_agent.py` | **85 passed，5.17 秒** |
| 干净代码 `08d43ff6` 的真实 HashiCorp `check-env` | **通过，4.05 秒，0 模型回合**；1 次固定 STDIO TCP 探针，Git dirty=false，未复制干净实现源码 |

各轮有重叠，不把数量相加。本次没有跑全仓测试。可复现的相关验证命令：

```bash
export PATH="$HOME/.local/bin:$PATH"
BASELINE_ACCEPTANCE_DIR="$HOME/.cache/consensus-assurance/pair-check-$(date +%Y%m%d-%H%M%S)" \
.venv/bin/python -m pytest -q baseline/tests tests/unit/test_codex_agent.py tests/unit/test_execution.py \
  tests/integration/test_audit_products.py::test_existing_unit_actual_technical_repair_review_progress \
  tests/integration/test_audit_products.py::test_accepted_check_recovers_without_remaining_model_call \
  tests/integration/test_audit_products.py::test_recovery_does_not_repeat_model_or_target_execution \
  tests/integration/test_audit_products.py::test_one_investigation_fixes_packages_for_checks_exploration_and_revision \
  tests/integration/test_audit_research.py::test_review_pause_and_reselection_continue_to_controller_boundary \
  tests/integration/test_audit_research.py::test_knowledge_growth_preserves_execution_and_supplies_the_next_check \
  tests/integration/test_audit_research.py::test_default_overview_precedes_focus_without_requiring_both_labels_per_question \
  tests/integration/test_direct_checks.py::test_unattributed_failures_and_exact_completed_witness
.venv/bin/python -m baseline check-env --config baseline/configs/hashicorp.deepseek-pair.baseline.yaml
```

原始本机日志在 `/home/nitro/.cache/consensus-assurance/baseline-simplification-2026-10-09/`，分别为 `before-tests.log`、`environment-first.log`、`environment-recheck.log`、`verification.log`、`final-unit.log` 和 `check-env.log`；环境执行与回环请求也保留在那里。正式 `check-env` 目录为 `baseline/runs/2026-10-09_11-15-57-hashicorp_raft-check-env/`。

首轮两个边界断言把空 namespace 内创建同名临时文件误当成宿主写入；改用读和 `r+` 打开已有文件的拒绝控制，未放宽任何挂载。第三个断言误把 catalog 模板的通用 skills 说明当成注入列表，改查实际请求 `input`；两组实际 exec/resume 均无宿主 skills／AGENTS／个人 developer 指令。最后发现 Python 3.10 的 `asyncio.TimeoutError` 不等同内建类型，显式转换后用真实异步等待超时验证分类及授权恢复。

保留覆盖：默认完整组无配对初始化；生产初始／续接参数及同一 session；实际模型／档位／目录；源码／日志只读和工作区可写；凭据隐藏；普通 shell 禁网；私有 TCP 与宿主连接成功／拒绝控制；12 秒真实 CLI 工具调用；必需 MCP 缺失在初始与续接入口均停止；超时、取消、EOF、父进程退出、服务终止及脱离 session 的后代清理；研究提交、固定执行、对应复核、恢复、知识增长和继续选题。

测试职责收敛：删除已退出的 profile 语法／可信对象变更／home 迁移矩阵和 smoke 评分测试；完整组编译、超时和方法契约仍由既有测试负责，不在 baseline 做交叉矩阵；仅保留一个按实际配置及 registry 装配的配对检查。第三方兼容性只测所选 catalog，不再翻转 `supports_search_tool`。历史诊断归档原样保留。

## 旧证据与行数

人工核对原 `2026-10-09_08-04-05-hashicorp_raft-smoke`：session 均为 `01a11df9-8155-7252-b0bc-119710e806dc`；第一轮 item `item_8` 对应执行 `8faf8de3aca1427995e6e6e9b5a79f1e`，收到 ping/pong 后断言失败，退出码 1；第二轮 `item_3` 对应 `7c15b9333e024ce9b5830b4ecf766908`，只把预期 wrong 改成 pong，退出码 0。MCP 返回与宿主回执逐项相同，原始输出和[第二轮解释](raw/smoke/turns/0002/final.txt)相符。所需 **30 文件、1118 行**复制到 [raw/smoke](raw/smoke/run.json)，原本机目录不改动。本次没有为代码迁移再调用模型，也没有把这些记录提供给自主审计。

按独立责任计量，相对 `d52ad947`：

| 范围（行数，不按字节） | 修改前 | 修改后 | 净变化 |
|---|---:|---:|---:|
| 全部运行 Python：`src/**/*.py` 与 `baseline/*.py` | 8707 | 8408 | **−299** |
| 全部测试 Python：`tests/**/*.py` 与 `baseline/tests/**/*.py` | 7760 | 7533 | **−227** |
| 两份 baseline 使用文档＋本报告 | 214 | 195 | -19 |
| 补存的旧原始证据（复制，非代码） | 0 | 1118 | +1118 |

运行 Python 增加 185、删除 484 行；其中上述 22 行只是所有权迁移。测试增加 262、删除 489 行。补丁随附的任务书副本和另一环境的验证文本不再新增，收敛为本报告；没有删除既有历史证据。

证据边界：本地 STDIO 成功、脚本化 Responses、旧真实模型使用分别报告。既有畸形输入 F1/F2/F3 不写成三个独立 CFT 缺陷，进程终止与捕获 panic 区分见 [配对说明](../../PAIRING.md)。完整组 `confirmed` 不等于外部研究裁决；本轮不新增分类器或评价字段，历史不同条件运行也不支持方法优越性的因果结论。
