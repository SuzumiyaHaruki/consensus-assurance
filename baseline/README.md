# 普通 Codex 审计基线

`codex_plain` 使用原生 Codex 自主阅读、编辑、测试、记录和复查。外层负责固定输入、核对权限、预算、同一 session 续接和文件留存，不提供完整组的研究产品、结果 schema、发现配额或语义受理。普通任务及中性续接保留在 [task.md](task.md)，本轮没有修改。README、配对表、框架源码和历史答案不提供给普通组模型。

本轮从 `2dd96315` 增量修改。三个主体文件仍为 `__main__.py`、`codex.py`、`runner.py`。复用主系统的中性配置、Go 离线环境、存储与诊断，以及共同 Codex 设置；没有复制主 Agent/Engine。主系统只增加可选 `codex_profile: single_agent` 的显式参数与本地配置探针，并给现有正式执行隔离增加 PID namespace，不更改 `audit-products-v58` 的调查、判断或预算规则。

## 使用

需要 Linux、Bubblewrap、支持命名权限及本地提示检查的 Codex CLI，以及目标工具链。在仓库根目录使用已有环境：

```bash
.venv/bin/python -m baseline check-env --config /absolute/path/to/local-config.yaml
.venv/bin/python -m baseline smoke --config /absolute/path/to/local-config.yaml --allow-paid
.venv/bin/python -m baseline run --config /absolute/path/to/local-config.yaml
.venv/bin/python -m pytest baseline/tests -q -o cache_dir=baseline/.pytest_cache
```

[DeepSeek](configs/deepseek.example.yaml)、[OpenAI](configs/openai.example.yaml)、[自定义服务](configs/custom-provider.example.yaml) 示例默认关闭授权，需要填写 `repo_path`；相对路径以配置文件所在目录为准。新 [DeepSeek＋HashiCorp 配对草案](PAIRING.md) 也默认关闭授权，尚不能作为完整网络范围的正式配对。目标必须是干净 Git 提交，`runs_dir` 与源仓库分离；运行器不会替用户清理工作树。

`check-env` 保存快照，检查实际 CLI、权限、自动提示、沙箱内工具版本和离线依赖；Go 使用 `go list -m all`，Rust 使用离线 `cargo metadata`。它不发送目标给模型、不执行目标测试、不使用真实认证；API 凭据只记录是否存在。`environment_checked` 表示本地检查完成，不表示模型服务或 TCP 能力可用。

`run` 要求 `allow_agent_materials`、`allow_experiments` 都为 `true`；`smoke` 还要求 `--allow-paid`。合成冒烟最多两回合、300 秒，验证工具失败修复、文件交接与上下文连续性。不会自动登录、联网补依赖、换 provider 或追加免费总结。本次实施没有执行付费冒烟或新共识审计。

目录使用本地时间，例如 `2026-10-08_13-11-14-hashicorp_raft-baseline`，环境检查以 `-check-env` 结尾，同秒重名追加序号。启动时打印源码捕获、环境检查和模型调用阶段，`run.json.phase_times` 保存时点与累计耗时；进入模型调用时为 `stop: running`、`phase: model_audit`。服务端是否接收请求仍以原始调用输出为据。没有跨进程 resume 入口，再次运行会创建新目录和新 session。

## 连接、共同设置与依赖

配置拒绝未知字段、重复 YAML 键和无效预算。目标配置只读取中性 `execution_backend` 与 `target` 的模块、范围和路径，不继承问题、旧结论、主系统预算或检查命名。模型自写的 `.codex`、`.agents` 不会在后续回合被加载。

自定义 provider 复用 `CodexProvider` 和 Responses 接口，必须提供仅包含所选模型的真实 catalog；原字节保存到 `inputs/models.json`。模型、推理档位与目录匹配，不静默降档。原生 OpenAI 的目录来自本机 `debug models --bundled`；`auth_mode: api_key` 使用 `api_key_env`，`auth_mode: codex_login` 仅使用已有文件形式的 ChatGPT 登录，不自动登录或复制宿主配置。API key 只进入客户端，工具环境不继承它。

两组共同策略由 `src/consensus_assurance/adapters/agents/backend.py::common_settings()` 提供。普通组直接使用，完整组显式选择 `codex_profile: single_agent` 后使用；未选择时保留原有配置行为。共同策略关闭子 Agent、shell snapshot、自动 skills/plugins/MCP/memory/hooks，保留普通 shell 与原生压缩。自定义 provider 固定请求／流重试为 4／5、流空闲 300000 ms，关闭无限连接重试；原生 provider 的保留设置不覆盖。用实际 `features list` 和本地 `debug prompt-input` 检查生效结果；缺工具或探针失败不算通过。完整组的方法和结构化回执仍保留。

可选 `go_mod_cache_dir` 只读作为 `GOMODCACHE`；Go 离线变量直接复用 `GoModuleBackend.environment()`。可选 `cargo_dependency_cache_dir` 表示普通 Cargo home，只读连接其中的 `registry/` 和 `git/`；宿主认证和全局配置不开放。旧 `cargo_seed_cache_dir` 在新 baseline 配置中明确报迁移错误；历史 JSON 不回写，主系统的编译种子字段不改名。仅有编译 seed 而没有依赖树的目录会报类型不匹配。

不全量扫描、逐文件哈希或复制宿主依赖缓存。没有配置目录时使用空离线缓存；缺依赖直接报错，不联网补齐。构建与临时目录位于每 run 私有 `work/.runtime/`，冷构建成本计入预算。源码依赖缓存不等于编译种子，Rust 成本可比性仍须另行核对。

## 权限、身份与留存

普通组使用私有 Codex home、显式参数和空白工作区 Git 边界。工具根目录默认不可读，只开放捕获源码、当前工作区、本次日志、普通任务和必要工具及只读依赖。源码与宿主日志不可写，工作区可写；方法、历史 run、实现身份文件和凭据不可读。实际探针包含正向控制、拒绝控制、环境及 procfs 凭据检查，不以启动成功代替权限证据。

**本机 Codex 工具仍拒绝 TCP socket；主系统固定执行器能够在隔离网络内通信。** 两者不等价。三条路径的真实程序、文件、网络与终止结果，以及具体 TCP 阻塞与最小后续方案，统一放在 [PAIRING.md](PAIRING.md)。没有通过 `network.enabled=true`、全权限或开放宿主网络来消除差异。

模型调用前写入 `inputs/implementation.json`，由 `run.json` 引用：框架 Git 提交、相关执行输入 dirty 状态、四个 baseline 入口／任务文件、实际导入的中性模块路径与版本依据、Codex 可执行路径／版本／一次性摘要，以及配置、任务和 catalog 引用。服务端实际模型修订保持 `unknown`。只检查这些执行输入，不扫描 runs、目标历史、依赖缓存或整个 Python 环境。

Git HEAD 不能标识 dirty 文件或另一个安装位置的模块，CLI 版本字符串也不能区分同版本构建，因此这里只为有限执行字节记录摘要，不增加审批门槛。开发运行允许 dirty，并仅保存相关执行输入的安全字节，不打包无关未提交文件。结束时保存 `inputs/implementation-end.json`，重新检查入口字节及 CLI 文件元数据；启动身份不覆盖，期间变更会标为条件未固定。身份文件不进入模型提示。

总时间由单调时钟执行，源码、身份记录、环境准备、工具、等待模型都计入。每轮上限为单回合限制与总剩余时间的较小值；有预算时精确续接原 session。超时、取消、拒绝、配额和 session 变化保留分类；到时只做留存。回合数、内部工具调用与主系统正式检查数是不同计量，不互换。

```text
runs/<run-id>/
  run.json                       # 配置、环境、身份引用、阶段时点、停止原因和回合索引
  inputs/                        # 固定任务、catalog、源码清单、身份和本地探针
  source/                        # 只读 Git 快照，无历史
  work/                          # 最终工作文件，可能含未完成轮的修改
  turns/0001/
    request.txt
    stdout.jsonl
    stderr.log
    final.txt
    result.json
    report.md                    # 该回合实际存在的安全报告副本
    changes/files/
    changes/manifest.json
  index.md                       # 最近完成报告和原始记录入口
```

按回合保存工作文件差异，回合末版本不冒充每条命令执行前的版本。模型自行 tee 的日志是可写材料，不冒充宿主原始输出。原始 CLI 字节仅做精确凭据脱敏；usage 保持逐事件记录，未核实累计语义时不求和。结束后归档只读，排除 `.runtime`、`.execution`、虚拟环境、缓存、凭据、临时锁和权限覆盖；清理当前临时区不会删除共享依赖。

当前 Git 仍仅跟踪 [2026-10-08_13-11-14-hashicorp_raft-baseline](runs/2026-10-08_13-11-14-hashicorp_raft-baseline/index.md) 这一份历史运行。该目录和报告未修改，26 个完成回合及第 27 回合超时都保留。新无模型验收的选定依据位于 `acceptance/2026-10-08/`；其他本机运行继续忽略。

## 接入事实与验收

| 服务 | 已有证据 | 尚未验证 |
|---|---|---|
| DeepSeek | [真实运行索引](runs/2026-10-08_13-11-14-hashicorp_raft-baseline/index.md)、[第一回合](runs/2026-10-08_13-11-14-hashicorp_raft-baseline/turns/0001/result.json)、[续接回合](runs/2026-10-08_13-11-14-hashicorp_raft-baseline/turns/0002/result.json) 展示普通文本、多回合同 session、工具读写和执行 | 专用 smoke 命令未执行；本次完整组结构化回执和正式配对未执行；TCP 差异仍在 |
| 原生 OpenAI | 本地 catalog、命令构造与 API-key 隔离检查 | 真实模型调用、登录刷新和两组配对 |
| 其他 provider | 通用 Responses 配置入口 | 不因 DeepSeek 成功推断已适配，不自动进行付费接入 |

复用已有能力证据，不为补一个 smoke 名称重新付费。当前最终测试命令、环境、通过／失败／跳过、原始输出和已知缺口见 [验收记录](acceptance/2026-10-08/summary.json)。测试通过不等于 TCP 配对成立，也不证明任何共识实现正确。

共同条件表、历史 40／120 分钟试运行的定位及空白离线裁决表统一见 [PAIRING.md](PAIRING.md)，不另外建设调度或评价平台。
