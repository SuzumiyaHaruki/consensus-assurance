# 配对准备与离线裁决

本轮从 `ffc4d1e2a9841719e2c480e7eea18ff447b1b753` 开始，主系统方法仍为 `audit-products-v58`。这里记录宿主侧条件，不进入普通组提示。两组可以采用不同的调查路线，不预设完整组获胜。本地服务、请求工具面和结果回传分别核对；真实模型使用工具仍待用户执行合成冒烟，不使用历史 shell 调用记录或本地脚本响应替代。

## 新配对草案

使用 [普通组配置](configs/hashicorp.deepseek-pair.baseline.yaml) 和 [完整组配置](configs/hashicorp.deepseek-pair.full.yaml)。两份配置默认关闭材料发送和实验授权，未启动任何新审计。完整组用 `codex_profile: single_agent` 显式传入共同设置；普通组直接复用同一 `common_settings()`。不能用 `CODEX_HOME/config.toml` 代替这些参数，因为真实入口使用 `--ignore-user-config`。

| 条件 | 状态 | 本次准备值／具体差异与依据 |
|---|---|---|
| 目标 | 已核对 | HashiCorp Raft；`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；相同干净仓库、模块、`.` 范围；实际可见文件核对见 [source-parity.json](acceptance/2026-10-08/source-parity.json) |
| 模型连接 | 已核对 | `deepseek-flash`、`high`、`https://api.deepseek.com`、Responses、`DEEPSEEK_API_KEY`；认证值不保存；只核对客户端配置，不推断服务端模型修订 |
| 模型目录 | 已核对 | 两组读取同一 `configs/providers/deepseek-flash.models.json` 原字节；行为模板、上下文和压缩设置一起保留；原生并发工具能力由该目录声明 |
| CLI 与实现 | 已核对 | 同一本机 Codex 可执行文件；路径、版本、一次性摘要、框架提交和实际导入位置见 [implementation.json](acceptance/2026-10-08-tcp/implementation.json)；正式运行须在冻结实现后重新记录各侧身份 |
| 基础功能 | 已核对 | 共同单 Agent；关闭 shell snapshot、自动 skills/plugins/MCP/memory/hooks；baseline 另显式注册唯一中性 MCP，完整组仍无此 MCP；保留普通 shell、原生压缩和目录声明的并发工具能力；两条 Agent 路径的完整 `features list` 实际相等，见 [能力记录](acceptance/2026-10-08-tcp/summary.json) |
| 重试与等待 | 已核对 | 自定义 provider 两组显式请求重试 4、流重试 5、流空闲 300000 ms，关闭无限连接重试；主系统既有研究动作回流保留在总预算中；原生 provider 的保留设置不覆盖 |
| 工具链 | 已核对 | 沙箱内 Go 1.25.8、Linux x86_64；Rust/Cargo 1.88.0 合成程序也已验证；正式 Go 配对使用相同 `/usr/local/go/bin` 和同一 CLI 路径，不能拿旧 Go 1.23.5 的结果配对 |
| 普通程序／管道／线程 | 已核对 | 四条路径均能执行合成 Go/Rust 测试，先失败再修复；真实管道与线程有成功控制；见能力记录中的原始输出 |
| 隔离内 TCP | 已核对 | 两个普通 shell 继续拒绝 socket；baseline MCP 和完整组固定执行器均完成同一次调用内多进程 listen/connect/send/recv，网络 namespace 与宿主不同 |
| 外部／宿主隔离 | 已核对 | 受控宿主 TCP 服务有成功控制，四路径均拒绝连接；支持 TCP 的路径无外部路由。新工具另有宿主路径型 Unix socket 成功／拒绝控制、文件允许列表、私有 procfs 及凭据／文件描述符检查，原始依据见能力记录 |
| 文件与凭据 | 已核对 | 普通组不可读方法、历史 run、实现身份或凭据；源码／日志／共享依赖只读，工作区可写。完整组保留其方法与校验器读取权限，属于有意差异；固定执行器隐藏原始材料，仅暴露工作副本与工具依赖 |
| 工具环境传递 | 具体差异 | baseline 使用 `inherit=none` 与显式工具 PATH；完整组 Agent 沿用 `inherit=core` 加凭据排除，固定执行器使用 `clean_environment()`。实际工具版本相同、凭据拒绝控制通过，但不宣称环境变量集合完全相同；原始环境记录随能力探针保存 |
| 终止 | 已核对 | 四路径超时／总期限／取消检查；新工具另验证单工具上限、MCP 取消、STDIO 断开、服务强杀及正常父进程退出，脱离原 session 的子进程停止心跳，原始输出保留 |
| Go 依赖与构建起点 | 已核对 | 同一只读 `~/go/pkg/mod`，不扫描、哈希或复制全缓存；各 run 独立干净构建目录，构建时间计入预算；依赖预备和独立环境验收成本另列 |
| run 内构建复用 | 具体差异 | 普通组工作区与完整组 Agent 草稿可各自复用本 run 的构建缓存；完整组固定检查按隔离 workspace 建立 Go 缓存。共同冷起点不代表后续构建次数或复用完全相同，该成本须随实际执行记录报告 |
| Rust 编译复用 | 具体差异 | 普通组只有只读源码依赖缓存；完整组另有编译种子机制。此次验证普通 Cargo 能力，不宣称两组 Rust 热构建成本相同 |
| 预算 | 已核对 | 新草案两组均 2400 秒、单 Agent 回合 900 秒、高层回合上限 120、普通执行／正式执行上限 600 秒；完整组额外配额在 YAML 中列明，不给普通组虚构相同对象；须报告实际哪个容量成为瓶颈 |
| 预算起算 | 已核对 | baseline 从创建 run 前起算并保存各准备阶段时点；主系统 `Engine.start()` 从源码捕获前起算，捕获耗时进入 `BudgetTracker`，环境探针、地图、构造和复核继续计时。两侧都不免费扣除准备或截止后追加总结 |
| 宿主资源与运行顺序 | 未知 | 正式执行前填写 CPU／内存及其他负载、重复次数、随机或交错顺序；不得并行抢占后再视为同条件；不补跑替换中断或零结果 |
| 线上变更与完整组回执 | 未知 | 本轮未调用模型；历史 DeepSeek 证明普通文本与工具能力，不证明本次完整组结构化回执成功，也不证明服务端别名对应固定模型修订 |

完整组读取双主线、Behavior/Fact、Candidate/Obligation、固定检查、复核和知识回流说明；普通组保留原 `task.md`、自由笔记与普通报告。输出 schema、正式命名、验证及回流工具是有意差异，不要求普通组生成 `CA_EVENT` 或 finding JSON。

## 隔离工具与四条实际路径

| 路径 | 普通程序／管道／线程 | TCP | 宿主 TCP |
|---|---|---|---|
| baseline 普通 shell | 成功 | 拒绝 | 拒绝 |
| 完整组 Agent 普通 shell | 成功 | 拒绝 | 拒绝 |
| baseline `isolated_exec` | 成功 | 隔离内多进程双向收发 | 拒绝 |
| 完整组固定执行器 | 成功 | 隔离内多进程双向收发 | 拒绝 |

baseline 在真实 `exec` 与精确 `exec resume` 使用的显式参数中配置 `mcp_servers.baseline_local`，唯一白名单工具为 `isolated_exec`，`required=true`。本机 app-server 实际发现的工具 schema、服务来源和原始结果随验收保存；真实 exec/resume 的必需服务失败测试在推理之前停止。后者使用本地创建并注入合成说明的空会话，不是模型生成历史。线上模型是否正确选择和调用工具仍待付费冒烟。

服务由 `/usr/bin/env -i` 清空环境，再以可信 Python 的 `-I -S` 加显式安装目录启动；不加载工作副本、PYTHONPATH、site hooks 或宿主个人配置。STDIO 仅传协议。MCP 使用固定 `mcp==1.26.0`，安装方法见 README；不手写 JSON-RPC，也不在运行时安装依赖。[官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 提供字段依据，实际可用性以保存的本机探针为准。

工具接受普通 argv，不生成 harness、协议前史或语义判断。例如模型可调用 `isolated_exec({"argv":["go","test","./sample"],"cwd":".","timeout_seconds":60})`。返回形如 `{"execution_id":"<实际ID>","status":"completed","exit_code":1,"timeout_seconds":60,"timeout_limit":"requested","stdout":{"preview":"<实际输出>","truncated":false,"path":"<run>/executions/<ID>/stdout.txt"}}`；这只是字段示例，不是验收结果。非零测试、启动错误、超时、取消和无完成回执的中断分别保留。

每次调用独立创建网络、PID、IPC 和文件视图，工具根只来自可信准备，模型路径不增加宿主挂载。工作副本可写，源码和依赖只读；宿主控制目录与记录不在测试视图中。输出经管道由服务写入宿主日志，测试不能 seek 或改写原始日志；普通 shell 可只读查看完整记录。模型自行 tee 的文件仍属于可写工作材料。

执行上限取请求值、600 秒配置上限、回合剩余和整轮剩余的最小值；串行排队也消耗预算。每回合更新可信期限，run 期限不重置。客户端等待上限为较大的回合／命令上限加 5 秒清理余量；测试本身仍受宿主硬期限约束。取消、断开或服务死亡不保留常驻集群，多个通信进程应放进一次调用。

共同配置仍来自 `common_settings()`，完整组的方法资源、固定执行和复核保留。主系统首次本地有效检查后保存 profile 名称和展开设置；后续和恢复先核对持久记录及历史 argv。同名功能或工具策略变化会在付费调用前要求新 run，不覆盖旧依据；未启用 profile 的历史路径不强制迁移。原生 provider 无 catalog 时也可独立创建记录。

## 正式执行前填写

| 项目 | 状态（已核对／具体差异／未知） | 值与原始依据 |
|---|---|---|
| 两侧实现提交、dirty 状态与安装来源 | 未知 | |
| 目标提交、范围和可见文件 | 未知 | |
| 实际 CLI／模型／目录／工具版本 | 未知 | |
| 本地通信能力与允许的比较范围 | 未知 | |
| 依赖准备、冷暖状态与机器负载 | 未知 | |
| 预设预算、重复次数和运行顺序 | 未知 | |
| 两侧材料发送／本地执行授权 | 未知 | |
| 人工干预、停止和复验政策 | 未知 | |

每次独立运行都创建新目录、空研究状态和新 session。完整组还应使用新建、位于 `/tmp` 以外的私有 `CODEX_HOME`；实际 CLI 拒绝在 `/tmp` 创建所需 helper。使用相同 PATH 固定 Go 和 Codex；原生会话数据不与旧实验共享。这里不提供已授权执行脚本，也不启动矩阵。

## 共同离线裁决表

| run／组别 | 原始主张与位置 | 涉及要求／范围 | 原执行与文件依据 | 裁决及具体理由 | 问题类别 | 去重关系 |
|---|---|---|---|---|---|---|
| | | | | | | |

两侧全部确认主张都接受同一外部标准；主系统 `confirmed` 和模型自报都只是输入。以每个独立 run 原预算内交付、裁决成立的不同缺陷数为数量指标，同时报告证据质量、原始成本、首个有效交付及未决事项。局部缺陷不要求展示最大系统后果；未完成不自动算误报。类别事先包含共识安全／进展、历史与存储、接口完成、一般工程、测试基础设施，先报告总量和分类，不能事后排除 helper 问题，也不能把它升级为共识安全缺陷。

同一问题重现不增加独立数量；同机制变体和后果保留关系。无法唯一归并时保留命题数及具体归并理由。每轮产出与累计并集分开；所有中断、拒绝、失败和零结果保留。尽量隐藏模型与组别，不能完全盲化之处如实记载。复验可运行已有材料，但不能补写关键前史后追记成原预算内成果。

## 历史试运行

当前 Git 跟踪最新的 [40 分钟 baseline 原始归档](runs/2026-10-08_19-48-15-hashicorp_raft-baseline/index.md)，此前归档保留在 Git 历史及本机；它不能与本机 `runs/2026-10-07_11-29-07-hashicorp_raft-real-run` 的 120 分钟 DeepSeek high 完整组运行配成同条件样本。前者使用 Go 1.25.8，后者记录 Go 1.23.5，网络与功能条件也不同。

用户提供的上轮离线复查意见是：EnsureSamePeers 的过期参考值有源码与执行依据；EnsureLeader 的实际失败需要区分即时断言职责与调用者等待前提，“不重试”不自动构成 helper 违约。本轮未追加模型或目标复验来改变这些结论。模型对上游版本的强调、报告内状态不一致和末尾重复总结原样保留；这些观察不进入后续普通组任务。

## 本次工具暴露与 profile 检查

固定 CLI 仍为 `0.155.0-alpha.16`，共同 catalog、行为模板、上下文预算和 `high` 推理档位均未修改。两组仍引用同一份 `configs/providers/deepseek-flash.models.json`，其中 `supports_search_tool=true`、`tool_mode=null`。本机真实请求先提供带有 `baseline_local` 来源说明的客户端 `tool_search`；经该入口发现后，`tool_search_output` 提供 `mcp__baseline_local` namespace 中的 `isolated_exec` 及参数 schema，随后调用和执行结果回传均成功，精确 `exec resume` 也已验证。因此，当前本机证据没有复现 [上游 #36382](https://github.com/openai/codex/issues/36382) 所述的“既无工具也无搜索入口”。该 issue 针对较早版本，不能据此断言历史 DeepSeek 未调用 MCP 的原因。

仅将 `supports_search_tool` 改为 `false` 的测试副本会直接暴露同一 namespace；候选值的 exec、resume、schema 和结果回传也已核对。既有目录已具有可用的发现路径，按本轮要求保留它，不将候选值写入生产 catalog。旧 run 的 `inputs/models.json` 保持原样；也没有通过改变普通审计提示来补偿工具选择。

| 证据层次 | 当前结论 | 边界与入口 |
|---|---|---|
| 服务与隔离执行 | 本地已验证 | 真实 MCP 协议、Go／Rust 双向 TCP、非零断言与修复结果；原安全和生命周期回归保留 |
| Codex 注册 | 本地已验证 | 现有 app-server 清单及固定 TCP 探针；不等于模型侧选择工具 |
| 请求工具面与结果回传 | 本地已验证 | 真实生产 `Codex.turn()` 装配的 exec 与精确 resume，请求中先确认工具搜索或直接定义，再发脚本化调用；执行结果与受保护记录匹配并进入后续请求 |
| 真实模型选择、调用和理解结果 | 本轮未运行 | 用户后续执行两回合 smoke；未调用 DeepSeek、GPT 或其他远端模型，不能从本地成功推断服务端接受请求或模型能力 |

请求捕获只使用合成项目、虚拟凭据和临时回环 HTTP fixture，不转发请求。保留 provider ID、Responses、目录字节、工具策略和配置装配路径；不可避免的差异为 endpoint 从 DeepSeek HTTPS 改为本地 HTTP、认证环境变量及值使用合成内容。请求和脚本返回保存在 [验收目录](acceptance/2026-10-08-tool-surface/summary.json)，不记录认证头；这些材料证明本机客户端连接链路，不证明真实服务的能力协商、TLS、认证、模型推理或线上可用性。原生 OpenAI 的目录、权限和认证隔离继续用原回归验证，没有套用 DeepSeek 候选配置。

主系统 profile 漏检已通过真实 `validate_profile()` 复现：正常历史 argv 追加 `mcp_servers.fixture.command` 曾被接受，测试没有启动该服务。现在按所拥有的配置路径边界检查 MCP、features、skills、memories、标量策略和共同重试设置；历史参数、准备命令、最终 exec／resume 及 Engine 预算前入口均检查。相同值重复和字典顺序变化可接受；冲突重复、未声明子键、父表替换及无法可靠解释的受保护引号路径报具体参数并停止。本机 `config/read` 验证了 CLI 的顺序覆盖、父表替换和严格模式对引号路径的拒绝；没有用排序或重复键 TOML 拼接替代真实语义。已有 provider 连接校验、默认 profile、旧回执复用与私有目录归一化继续保留。

本次 smoke 用一个固定的小型 TCP 测试贯穿两回合，替代“任何失败命令后再有成功命令”和“任一轮成功隔离执行”的弱判据。两轮都必须出现批准工具的已完成 MCP item，返回 execution ID 必须对应相同回合、argv、状态和结果；第一轮须实际到达 TCP 后触发指定断言，第二轮修正同一测试后通过。前后版本按回合留存，不冒充命令开始瞬间的快照；第二轮说明仍须人工阅读。普通自主审计不因零调用自动失效，也不携带合成约束。

最终相关回归、提交、净增减及原始记录统一见 [summary.json](acceptance/2026-10-08-tool-surface/summary.json)。运行步骤见 [README](README.md)，草案仍默认未授权，预算仍为 2400／900／600 秒及 120 回合。本轮本地完成不表示正式配对条件全部满足。

## 前次交付与验证（隔离 TCP）

主系统 profile 保持修复为 `ba8d17d8`，中性文件视图函数为 `995f0455`，直接调用核对和系统编译器链接补充为 `7ca3c2ac`；baseline 工具及接入为 `3583feb4`，最终测试修正为 `fd76f7f3`。`backend.py`／`engine.py` 核对 profile，`experiment.py::isolated_command()` 组装最小视图；默认未启用 profile 的行为及原 `sandbox_command()` 固定执行职责保持。baseline 新增一个 `local_exec.py`、固定协议依赖声明，并扩展现有配置、回合留存及两份测试。相对本轮起点，运行实现增加 400 行、删除 11 行，测试增加 297 行、删除 17 行。没有任务队列、服务管理 CLI、研究状态机或主系统语义对象。

最终非付费回归为 **190 passed in 231.99s**，失败和跳过均为 0，覆盖既有 baseline 与指定主系统回归及新增职责，不代表全仓测试。HashiCorp `check-env` 为 4.90 秒，0 模型回合，相关执行输入已提交且前后未变化；Go 为 1.25.8，Rust/Cargo 为 1.88.0，CLI 为 0.155.0-alpha.16。原始命令、结果、代码体积和实现身份见 [summary.json](acceptance/2026-10-08-tcp/summary.json)。此前 [154 项验收](acceptance/2026-10-08/summary.json) 保持原样，新结果不回写为旧实验能力。本轮不启动线上模型、目标审计或历史会话恢复；本地合成会话仅用于验证 CLI 配置及启动失败行为。
