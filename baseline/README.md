# 普通 Codex 审计基线

本目录提供 `codex_plain`：原生 Codex 自己阅读、编辑、测试、记录和复查；外层只固定输入、验证环境、管理预算、续接同一 session 并留存文件。没有主系统的研究产品、结果 schema、发现配额或语义受理。本目录 README、测试和框架源码不会提供给被测模型。

实施起点为 `3318fedfd89cd6e92bd9c227673100591dcc9d1d`（`audit-products-v58`）。全部新增代码位于 `baseline/`，没有更改主 CLI、`src/`、主方法或历史归档。初版实现与本地验收没有启动付费模型调用或真实共识审计；后续用户运行见下方归档说明，不据单次运行宣称方法增益或模型已经可以正式配对。

## 使用

在仓库根目录使用已有 Python 环境；无需修改生产打包或测试收集配置。此实现需要 Linux、Bubblewrap、支持命名权限表及本地提示检查的 Codex CLI，以及目标的 Go 或 Rust 工具链。示例都默认关闭授权，并且没有目标仓库路径或真实凭据。

```bash
python -m baseline check-env --config /abs/local-baseline.yaml
python -m baseline smoke --config /abs/local-baseline.yaml --allow-paid
python -m baseline run --config /abs/local-baseline.yaml
python -m pytest baseline/tests -o cache_dir=baseline/.pytest_cache
```

本机可使用 `.venv/bin/python` 替换 `python`。复制 [DeepSeek 示例](configs/deepseek.example.yaml)、[OpenAI 示例](configs/openai.example.yaml) 或[自定义服务示例](configs/custom-provider.example.yaml)，填写 `repo_path`；所有相对路径都相对于**该配置文件所在目录**。复制到其他位置时相应调整路径。仓库要求干净 Git 提交；运行器不会清理用户工作树。`runs_dir` 必须与目标仓库分离。

`check-env` 不使用真实凭据，也不连接付费模型。它保存目标快照，验证 CLI、实际权限、自动提示加载、工具链和离线依赖解析；Go 使用 `go list -m all`，Rust 使用离线 `cargo metadata`。它不会执行目标测试或将目标发送给模型。API 凭据是否存在仅记录布尔值；登录凭据留到获授权运行时检查。成功表示本地环境检查完成，不表示模型服务可用。

`run` 必须同时设置 `allow_agent_materials: true` 和 `allow_experiments: true`。这分别授权发送捕获材料和在隔离副本中执行模型选择的本地程序。缺失权限、路径、API 凭据、已有登录或有效模型目录时，在模型请求前停止。不会自动登录、下载工具链、在线安装依赖或切换服务。

`smoke` 还必须显式传入 `--allow-paid`，只测试选定 provider。它使用合成 Go 子包或 Rust crate，最多两回合、总计最多 300 秒；需要配置中的两项授权。第一回合读取带上下文 token 的 fixture、写笔记、构造失败测试并修正，第二回合精确续接、再次读写和执行。记录原生工具事件、失败后再次调用、第二回合执行及 token 交接；没有这些观察就不会返回成功。仍需人工核对真实参数、测试修改和失败输出读取；它不裁决共识缺陷。完整系统还须从原有入口单独通过结构化产品回执验收。

没有跨进程 `resume` 命令。运行器退出后保留本次结果；再次执行 `run` 会创建独立 run，不能替换或补足先前运行。

新目录使用本机本地时间与目标名称，例如 `2026-10-08_12-50-00-hashicorp_raft-baseline`，启动时立即向终端 stderr 打印路径。环境检查和合成冒烟分别以 `-check-env`、`-smoke` 结尾；同一秒重名时追加 `-2`、`-3` 等序号。JSON 时间记录仍使用 UTC。已有目录保持原路径，避免破坏进行中的进程和留存记录内的绝对路径。

启动时分别打印源码捕获、环境检查和模型调用阶段，`run.json` 的 `phase` 同步更新。`stop: environment_checked` 只表示本地检查结束；正式运行进入模型调用时显示“本地准备完成，开始调用模型”，并记录 `stop: running`、`phase: model_audit`。服务端是否接收请求仍需看原始调用输出。

当前 Git 仅跟踪 [2026-10-08_13-11-14-hashicorp_raft-baseline](runs/2026-10-08_13-11-14-hashicorp_raft-baseline/index.md) 这一份运行归档，其他运行和本地配置继续忽略。该 HashiCorp/DeepSeek 运行按 2400 秒总预算结束，留存 26 个完成回合和第 27 回合的超时记录；报告、原始输出和未完成回合均保留。模型报告尚未经共同外部标准裁决。

## 配置与连接

顶层配置只接受 `baseline_id`、`target_config`、`repo_path`、`agent_model`、`agent_reasoning_effort`、`codex_provider`、`auth_mode`、`api_key_env`、`runs_dir`、两项授权、两个可选离线依赖目录及 `budget`。未知字段、重复 YAML 键、隐式继承和无效预算均拒绝。没有任意 argv、headers 或每个服务独立的循环。

- `codex_provider` 直接复用主系统 `CodexProvider`，使用 Responses 路径。自定义模型必须提供真实且仅包含所选模型的 `model_catalog_path`。占位 endpoint/model 被拒绝；不得只改其他服务 catalog 的 slug。
- 原生 OpenAI 使用 `codex_provider: null`。`auth_mode: codex_login` 只使用已有、文件形式的 ChatGPT 登录，运行时将认证复制到私有临时 Codex home；退出时销毁该临时认证，不修改原认证文件。keyring 登录不在首版支持范围内。
- 原生 API-key 模式设置 `auth_mode: api_key`、`api_key_env: BASELINE_OPENAI_API_KEY`，配置只保存变量名。客户端按本机 CLI 的接口映射到 `CODEX_API_KEY`；工具进程不继承它。自定义服务使用 `codex_provider.env_key`。
- 推理档位按 catalog 核对，绝不静默降档。`null` 表示不传推理覆盖参数，只允许没有默认档位及支持档位的显式自定义 catalog；原生默认值无法证明参数省略时拒绝。线上是否真正省略该参数仍须在该模型接入验收中确认。
- 自定义 catalog 原字节复制到 `inputs/models.json`，保留工具形态、上下文、压缩和行为模板。原生 OpenAI 通过本机 `debug models --bundled` 捕获完整原生目录，再使用该副本；模型必须在该目录中。该步骤不刷新在线目录。
- 不替换 Codex 的原生上下文压缩器。自定义 provider 的原生请求/流重试分别固定为 4/5，流空闲上限 300000 毫秒；原生 OpenAI 的保留 ID 禁止覆盖，记录其 CLI 版本所带默认策略。两者关闭无限连接重试，外层重试为零。正式配对须使用同一 CLI 二进制和实际设置，不能把 CLI 升级视为相同条件。

目标配置只读取 `execution_backend` 和 `target` 中的 `variant`、`expected_module`、`execution_package`、`analysis_roots`。不继承其任务问题、focus、harness 命名、旧 findings 或主系统预算。Go 模块名和相对路径在本地核对；源码保留普通文档、源码与测试。

依赖访问沿用 `src/` 的方式：可选 `go_mod_cache_dir` 作为只读 `GOMODCACHE`，直接复用 `GoModuleBackend.environment()` 的离线设置；可选 `cargo_seed_cache_dir` 为普通 Cargo home，与 `CargoBackend` 一样仅将其 `registry/` 和 `git/` 只读连接到本次私有 Cargo home，不开放宿主认证和全局配置。这不是主系统 Cargo 编译 seed 格式。不全量扫描、计算逐文件摘要或复制共享依赖缓存，也不创建依赖文件清单；使用的路径和环境保存在配置及 `run.json`。缺少依赖时离线工具直接报错，不自动联网补齐。没有配置依赖目录时使用空离线缓存。构建缓存位于 `work/.runtime/`，每 run 独立冷启动；预先准备依赖的成本须单列。锁定文件如 `Cargo.lock`、`go.sum` 保留；临时依赖锁不归档。

## 权限与留存

客户端使用私有 Codex home、显式设置和空白工作区 Git 边界，忽略用户配置，禁用自动技能、插件、MCP、记忆、hooks 和子 Agent，保留管理员约束。用本机离线 `debug prompt-input` 检查最终提示、`features list` 检查生效功能；无法检查或发现额外说明即停止。CLI 内置技能需要逐项禁用，不能只依赖一个功能开关。模型自写的 `.codex`/`.agents` 目录不会在后续回合被接入。目标内 `AGENTS.md`、`SKILL.md` 等沿用捕获排除政策。

工具使用命名权限表：根目录默认不可读，仅开放固定源码、当前工作区、当次 run 的回合日志、普通任务和必要工具链。原始源码、宿主日志只读，只有 `work/` 可写。主方法、schema、README、历史结果、其他 session 和凭据不可读。实际探针包括正向读写、不可写/chmod 控制、canary 拒绝读取、环境变量及 procfs 凭据检查、程序/管道/线程和禁网测试；探针崩溃不是通过。

**本 profile 禁止工具外网与 loopback socket，允许本地管道和线程。** 主系统正式执行器使用 Bubblewrap 的独立网络 namespace，不能仅凭同样“禁网”就认定两者 socket 能力相等。需要 socket/loopback 的目标必须在两组实测相同能力；不相等时该范围暂不可比较。不得通过全权限、开放外网或宿主秘密来补齐。这里没有更改主系统权限。

run 总截止由单调时钟执行，准备、阅读、工具执行、笔记、等待模型均占预算。每回合上限取总剩余时间和 `agent_turn_timeout` 的较小值。普通最终回复后，只要预算仍有余量就精确续接原 session，以 [task.md](task.md) 的固定中性文本继续。没有汇总器、强制换题或发现配额。

`RUN_BLOCKED:`、明确最终拒绝、顶层错误、session 变化、无法辨识的完成事件都会停止；不会从目标工具输出中的 “denied” 等词推断服务拒绝。原生已完成事件也不覆盖顶层错误。无法确定的外部阻塞保留原文供检查，不猜测原因、不换 provider 或账号。单轮超时、总截止、取消和认证等错误分开记录。取消和期限会终止本轮进程组，包括仍存活的子进程；预算后只做留存，不再请求模型、运行测试或补报告。

```text
runs/<run-id>/
  run.json                 # 生效配置、环境、预算、真实 stop、回合索引
  inputs/                  # 单一任务、配置摘要、中性目标、catalog、源码清单、无模型探针
  source/                  # 只读 Git 提交快照；没有历史
  work/                    # 结束时的工作文件；未完成轮可能已改写它
  turns/0001/
    request.txt
    stdout.jsonl
    stderr.log
    final.txt
    result.json            # 精确 session、时间、原始 usage、完成/错误、工具事件数
    report.md              # 该回合结束时确有安全 report 文件才保存
    changes/files/         # 相对上一回合的新/改文件
    changes/manifest.json  # 删除、权限变化、排除项
  index.md                 # 状态与链接；不重写模型结论
```

完整 run 结束后设置文件系统只读权限。回合完成版报告与最后未完成版独立保存；没有报告写“未交付完成回合报告”，不会写“没有缺陷”。即使报告缺失仍保存最终文本，不再花一次模型调用补格式。宿主原始输出与模型自行写入或 tee 的日志分离；除精确凭据值脱敏外不改写 CLI 字节。

按回合保存文件差异。`.runtime/` 是预先声明的专用缓存/临时区，不应作为复现文件位置；归档排除它、虚拟环境、缓存、凭据、临时锁、权限覆盖、符号链接、硬链接和特殊文件，并保留排除记录。共享依赖缓存不复制进归档，清理本次临时区不会删除共享依赖。源捕获使用 Git blob 标识，不增加审批 hash。工作差异复用已有 `digest`，只用于识别模型修改的文件字节，不扫描共享依赖，也不作结论或受理门槛。

回合末快照**不是每条命令执行前的输入快照**。执行对应的准确版本仍须结合原始工具日志及离线复跑检查；工作副本上的修改、模型自述或通过的测试不自动证明原实现存在缺陷。原始 usage 按事件保留；未核实是累计还是增量时不求和，不由回合墙钟伪算 tokens/s。Agent 回合数、内部工具事件数与主系统正式目标执行数分别报告。

## 接入状态与本轮验收

2026-10-08 本机版本：Codex `0.155.0-alpha.16`、Go `1.25.8`、Cargo/Rust `1.88.0`。本地真实 Codex sandbox、提示隔离、Go 子包/Rust crate 失败与修复运行已验证；模拟事件只证明运行器的处理逻辑。OpenAI Docs 对原生 [JSONL、文本输出和 session 续接](https://learn.chatgpt.com/docs/non-interactive-mode) 以及[连接、环境、权限配置](https://learn.chatgpt.com/docs/config-file/config-reference) 的说明辅助了实现；生效行为仍以留存的本机探针为准。

初版验收为 **42 passed in 25.07s**。2026-10-08 简化依赖访问后，`.venv/bin/python -m pytest baseline/tests -q -o cache_dir=baseline/.pytest_cache` 为 **44 passed in 28.72s**，包含真实 Go/Cargo 工具、共享依赖不可写及宿主凭据不可读检查。同一 HashiCorp 配置的完整 CLI `check-env` 从旧实现的 834.09 秒降至 1.08 秒，本机记录在 `runs/2026-10-08_13-08-33-hashicorp_raft-check-env/`；隔离副本上另执行 `go test -run '^$' ./...`，编译通过，本机记录在 `runs/2026-10-08_13-08-57-hashicorp_raft-check-env/inputs/dependency-build/`。后者没有选中任何测试，不作为目标正确性证据。两次均无模型回合。上述验收未执行付费双回合、真实目标审计、真实登录刷新或完整组验收；用户后续实际运行单独归档。

初版交付规模：新增 12 个文件、1,376 个非空行，其中实现 Python 842 行、测试 Python 370 行，其余为任务、配置及说明；没有新增运行时依赖。统计不含被忽略的本地运行、缓存和验收临时文件。

| 服务 | 公开接入依据与目录 | 基线付费双回合 | 完整组冒烟 | 正式配对 |
|---|---|---|---|---|
| 原生 OpenAI | 官方原生 Codex；本机目录与 API-key 隔离已做无模型检查 | 未执行 | 本轮未执行 | 未成立 |
| DeepSeek | 复用仓库既有 Responses 配置及固定 catalog；本地连接参数/工具边界已检查 | 未执行 | 本轮未执行 | 未成立 |
| Kimi Code | 实施要求记载官方 Codex/Responses 接入；需核对该产品与 key 范围 | 未执行 | 未执行 | 未成立 |
| GLM | 官方所需路径及工具形态尚待核实，通用 SDK 兼容不算证据 | 未执行 | 未执行 | 未成立 |
| Grok | 实施要求记载 Responses/工具支持；仍需核对本项目 Codex 路径 | 未执行 | 未执行 | 未成立 |

初版实现及上述本地验收没有执行真实模型调用，故没有填写任何“服务已适配”结果；后续单次审计也不自动等于两组兼容验收通过。其余厂商没有复制 provider 类或伪造 catalog。安全拒绝按服务真实结果保留；不设置绕过或自动改写研究请求的路径。这里的公开依据只表明接入起点，不等于双回合兼容；基线普通文本可用但完整组回执不可用时，是兼容阻塞，不能计作方法胜负。

必要复用：`CodexProvider`/中性 `TargetConfig`、`GoModuleBackend.environment()`、`write_json`、可变材料 `digest`、源码敏感材料排除规则、顶层 `codex_diagnostic`/`classify_failure`。这些仅由宿主导入，工具不获得 `src/` 的读取权限。没有复制整个主 Agent/Engine。少量进程组、deadline、文本 JSONL 处理有意独立，避免 `ProcessRunner.agent_turn` 的研究说明及主 Agent 产品 schema。核心仍是 `__main__.py`、`runner.py`、`codex.py` 三个文件和两类测试。

## 共同离线评价口径

数量主指标是每个独立 run **原预算内交付、经共同外部标准裁决成立的不同缺陷数**。主系统 `confirmed` 和基线“发现了”都只是待审阅输入，不直接得分。实验允许无提升、局部提升或基线更好；不开发自动裁决、模型投票或评分平台。

质量分别记录适用要求、合法前史/输入、实际行为对命题的支持、复现材料可用性和责任类别。局部记录错误不因未展示最大集群后果而失效，也不能以无来源的更强要求判缺陷。协议安全/进展、历史与存储、接口完成、一般启动工程问题分列，不能事后只选完整组占优的类别。

去重按责任与修复关系处理：重跑不增加独立数量；同一修复关系的分支变体、局部缺口及后果保留命题映射，不简单相加。不同责任不能仅因同一个函数而合并。维护者确认和是否历史已知可以单列。裁决区分成立、被具体依据否定、证据不足；未完成不自动当误报。源码排除结论只在有参考结论的样本上评价，不声称测得开放仓库的全局漏报率。

成本记录每 run 墙钟、可核实费用/usage、首个有效交付时点及后续有效问题时点，人工裁决成本另列。独立复验可以执行已有 harness，不能补写关键前史、新测试或新假设，再追记为原预算内成果。尽量盲化模型与组别，以同一标准审全部确认提案，保留每次运行、重复发现及停止原因，报告均值、分布与效应。累计并集和同 run 共享前提的多个命题不是独立样本。

正式比较前在本机记录配对计划：模型/推理/认证/完整 catalog 与 CLI 配置、目标提交与范围、两组代码版本、相同预设墙钟及预算、工具/网络/依赖冷暖状态、重复次数、顺序及人工干预政策。两组必须采用同一源排除政策、相同 catalog 字节和共同工具条件；本基线不会替主系统暗中修兼容性。中性配置无法一致时，先列出最小主系统变更另行审阅，当前比较保持未成立。

交错或随机运行顺序，保留所有启动运行；外部拒绝和环境失败分列，不能删除不利记录、补跑替换或以拒绝次数证明语义增益。映射、复核等方法成本计入完整组相同预算；独立 check-env 和统一依赖准备成本单列。可先用 DeepSeek、两个目标、两组各三次做试点，但这不是本轮执行授权或最终样本量。之后只增加通过两组兼容验收的模型；正式泛化评价保留未参与方法调优的目标/模块，不据试点给基线更差提示。
