# 普通 Codex 审计基线

`codex_plain` 使用原生 Codex 自主阅读、编辑、测试、记录和修订，外层只负责源码捕获、权限、预算、精确 session 续接和留存。[task.md](task.md) 是普通任务与中性续接说明；不注入完整组的方法、历史答案、开发任务书或评价规则。完整组的研究产品、固定检查、复核和知识回流仍由主系统负责。

## 使用

需要支持 `pidfd` 的 Linux、Bubblewrap、支持命名权限的 Codex CLI 和目标工具链。依赖在审计前安装，运行中不联网补齐：

```bash
.venv/bin/python -m pip install -r baseline/requirements.txt
export PATH="$HOME/.local/bin:$PATH"
.venv/bin/python -m baseline check-env --config /absolute/path/to/local-config.yaml
.venv/bin/python -m baseline run --config /absolute/path/to/local-config.yaml
```

[DeepSeek](configs/deepseek.example.yaml)、[OpenAI](configs/openai.example.yaml)、[自定义服务](configs/custom-provider.example.yaml) 和 [HashiCorp 配对草案](PAIRING.md) 默认关闭授权。填写 `repo_path`、实际模型和连接；相对路径以 YAML 所在目录为准。`run` 要求 `allow_agent_materials`、`allow_experiments` 同时为 `true`，凭据只放环境变量。目标必须是干净 Git 提交，输出与源仓库分离；不会替用户清理工作树。

`check-env` 是独立的本地检查：捕获源码、验证权限、提示隔离、功能设置、工具版本、离线依赖，以及标准 MCP STDIO 工具清单和固定 TCP 收发。它不调用模型、不执行目标测试、不创建 app-server 会话，也不使用真实认证。Go 依赖检查为 `go list -m all`，Rust 为离线 `cargo metadata`。`environment_checked` 只证明这些本地项目通过。

普通 `run` 每次验证新运行的权限、捕获实际目录和工具版本，完成必要的 skills 初始化后直接进入审计。它不执行合成修复、不读取兼容性证书、不强制模型调用 MCP，也不重复执行 `check-env` 的服务和提示诊断。`tool_evidence` 分别记录服务探测、模型请求工具面和真实模型使用的证据范围；未检查的项目不会标成已验证。

独立的小样本兼容性练习使用现有测试入口，固定本地 Responses 回复，经过真实生产 `exec`／指定 session 的 `exec resume` 参数，保留请求、结果和命令记录；不消耗线上模型预算：

```bash
BASELINE_ACCEPTANCE_DIR="$HOME/.cache/consensus-assurance/local-compat-$(date +%Y%m%d-%H%M%S)" \
.venv/bin/python -m pytest -q baseline/tests/test_environment.py \
  -k 'request_tools or pairing_uses'
```

原 `smoke` 子命令和自动评分已退出。已有真实模型的双回合 TCP 失败／修复证据见 [本次核对](acceptance/2026-10-09-source-review/README.md)。环境变化后才需要有针对性的复验；脚本回复通过不能代替真实服务或模型推理证据。

## 配置与隔离

配置拒绝未知字段、重复 YAML 键和无效预算。目标配置只读取中性执行后端、模块、范围和路径，不继承研究问题、旧结论或完整组预算。模型写入的 `.codex`、`.agents` 会阻止后续回合启动。

自定义 provider 使用 Responses 和只含所选模型的 catalog，原字节保存到 `inputs/models.json`，推理档位必须匹配。原生 OpenAI 使用本机 `debug models --bundled` 目录；API 认证使用显式环境变量，ChatGPT 登录只读取已有文件认证。不会自动登录、切换模型或降档。

共同设置来自 `common_settings()`：关闭子 Agent、shell snapshot、自动 skills/plugins/MCP/memory/hooks，保留普通 shell、目录声明的工具发现和原生压缩。自定义 provider 保持请求／流重试 4／5、流空闲 300000 ms；原生 provider 使用记录版本的内置默认值。两个入口均以显式参数配置并使用 `--ignore-user-config`。

完整组只有显式选择 `codex_profile: single_agent` 才启用共同设置，记录在既有 `agent-inputs/runtime-settings.json`。初始回合和恢复读取同一记录；模型、provider、推理档位、catalog、CLI 及 profile 的实际配置变化仍在模型调用前拒绝。恢复须使用原 `CODEX_HOME`，旧记录不自动迁移。`codex_profile: null` 不创建配对记录或运行 baseline 探针。

当前 CLI 会在首次提示初始化时安装内置 skills；空私有 home 和 `skip_host_skill_discovery` 不足以阻止注入。因此保留一次离线初始化，再显式设置 `skills.config`。详细提示／features 诊断属于环境检查，日常回合不解析任意 CLI 参数或扫描历史 argv。

普通组使用私有 Codex home、空工作区 Git 边界和严格文件权限：源码／日志只读，工作区可写；框架方法、旧实验、控制文件和凭据不可读。权限探针验证实际正反控制及环境、procfs 凭据隔离，失败便停止。

baseline 的唯一 MCP 是 `baseline_local.isolated_exec`，设置 `required=true`，参数只有普通 `argv`、工作副本内相对 `cwd` 和可选 `timeout_seconds`。普通 shell 禁止网络；该工具每次创建独立网络、PID、IPC 和文件视图，允许同次调用内的本地 TCP，不开放宿主网络或任意挂载。源码和依赖只读，输出由宿主服务保留；命令退出、取消、断开及父进程退出均清理后代进程。完整组继续使用自己原有的固定执行器。

可选 `go_mod_cache_dir` 只读作为 `GOMODCACHE`；`cargo_dependency_cache_dir` 仅只读提供 Cargo home 的 `registry/`、`git/`，不开放认证配置。没有共享依赖时使用空离线缓存。每 run 的构建和临时目录位于 `work/.runtime/`，构建耗时计入预算；不复制或全量扫描宿主缓存。完整组 Rust 编译种子与普通组依赖复用存在差异，成本须分别说明。

## 预算与记录

总时间从源码捕获前起算，包含准备、工具和模型等待；每回合取单回合限制与总剩余的较小值，正常完成且有预算时精确续接同一 session。工具串行执行，请求上限、动作上限、回合剩余和总剩余共同约束。单回合超时会结束整个 run，配置时长是上限；局部准备超时不冒充总预算耗尽。到时只保留已有材料，不追加总结。

每次启动创建新目录、新 session；baseline 没有跨进程 resume 入口。`run.json` 保存阶段时点、实际停止原因和回合索引；`index.md` 链接最近完成报告与原始输出。usage 保留逐事件值，不未经核对求和。

`inputs/implementation.json` 用 Git 提交和 runtime dirty 状态标识干净同仓代码，另保存修改文件及外部安装模块的安全字节。CLI 保留路径、版本和一次性摘要，catalog 保留原字节。`inputs/local-exec.json` 保存一份服务配置、工具说明和权限依据；不在每回合重建 schema 或扫描整个 Python 环境。MCP 会延后加载代码，因此仍在启动回合前核对执行服务及其存储模块的字节；不另建部署锁定系统。

```text
runs/<run-id>/
  run.json, index.md
  inputs/                        # 配置、任务、目录、身份及本地检查
  source/                        # 只读 Git 快照
  work/                          # 最终工作文件，可能含未完成修改
  executions/<id>/               # argv、回合／请求 ID、期限、状态、原始 stdout/stderr
  turns/0001/
    request.txt, stdout.jsonl, stderr.log, final.txt, result.json
    changes/files/, changes/manifest.json
```

报告也在工作区变更中保留，`last_completed_report` 指向实际保留的版本；报告未变时复用该路径，后续超时修改不覆盖它。不再复制 `turns/N/report.md`；历史归档及旧链接不改写。回合末文件不冒充每条命令开始时的快照，模型自行 tee 的内容不冒充宿主原始输出。

结束后归档只读，排除凭据、虚拟环境、缓存、临时锁及权限覆盖。当前追踪 [HashiCorp baseline](runs/2026-10-09_12-07-16-hashicorp_raft-baseline/index.md)：预设一小时，实际运行约 35 分 44 秒，在第七回合启动前因工作副本配置目录检查停止；保留已完成的六回合及原始失败。历史运行可从 Git 历史查看，能力证据保留在 `acceptance/`；它们不进入新审计的上下文。
