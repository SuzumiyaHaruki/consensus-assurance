# 共识义务驱动局部审计报告

运行标识：`590a37c240a74d4e852838a8f1ed59af`；模式：**真实工具运行**。

问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。

分析入口：`autonomous`。regression 表示预设开发回归，不能计为自主发现验收。


## 义务与有界审计结论
尚无已受理的有界审计问题或结论。

## 本次流程进度

工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。

| 阶段 | 已记录的进度 |
| --- | --- |
| 材料阅读 | 已完成首轮阅读；保存 17 个片段 |
| 义务与代码关系 | 尚未完成发现结果的工作流接受；当前图有 0 项主张、0 个审计单元 |
| 直接实现检查 | 已保存 0 个制品；完成 0 次执行；不等于整体性质成立 |
| 局部模型 | 已保存 0 个模型版本；保存不代表检查通过 |
| 轨迹校准 | 0 条校准记录；不等同于性质判定 |
| 模型搜索 | 0 次执行记录；逐项结果见下方，未执行不计通过 |
| 性质证据 | 0 条直接证据；范围与层级见证据记录 |

若 agent 回复完成而目标发现仍未被接受，不能把该回复视为已成立的关系图。历史记录未保存具体拒绝原因时，报告不补造原因。

## 分析输入与探索范围

仓库：`/home/nitro/Desktop/hashicorp-raft`
提交：`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；分支：`detached / unavailable`；脏工作区：`False`。
快照：`eb5d0abb45354e08a1f651024c3b7519`，纳入 88 个文件；读取 17 个材料片段，仍有未读范围的文件 88 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。
候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。

## 义务与选择依据

领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考：
- `configured_reference`：未提供协议参考清单
定向补读：Read material；关联 []；实际新增片段 ['README.md:1:80', 'docs/README.md:1:80', 'api.go:1:80', 'transport.go:1:80', 'raft.go:1:80', 'log.go:1:80', 'config.go:1:80', 'fsm.go:1:80']。
定向补读：The supplied excerpts establish public interfaces and broad obligations but omit the implementation ranges that determine actual behavior. These eight ranges cover the highest-priority responsibility coordinates: decision formation and progression, authority transitions, recovery and resynchronization, configuration changes, decision application, history lifecycle, and client-visible completion. Cached ranges are not repeated; each request is an exact contiguous interval and remains within the 160-line limit.；关联 ['README.md:1:80', 'docs/README.md:1:80', 'api.go:1:80', 'transport.go:1:80', 'raft.go:1:80', 'log.go:1:80', 'config.go:1:80', 'fsm.go:1:80']；实际新增片段 ['raft.go:135:340', 'raft.go:468:700', 'raft.go:1203:1390', 'raft.go:1440:1605', 'raft.go:1603:1814', 'replication.go:137:388', 'snapshot.go:72:278', 'configuration.go:129:310']。
定向补读：Resolve covered citation ranges without new source acquisition；关联 []；实际新增片段 []。

## 实现理解（支持信息）

| Activity | 适用性 | 义务 | 证据 | 未知 |
| --- | --- | --- | --- | --- |
| A1 | applicable | [] | [] | ['The supplied excerpts do not show commitment quorum calculation, commit notification, or all stale-response handling.', 'The supplied excerpts do not establish how persistence failures interact with already issued replication responses.'] |
| A2 | applicable | [] | [] | ['The supplied excerpts do not show the complete election tally and leader-transition persistence path.', 'The exact legal relationship between persisted term/vote state and state transitions requires additional source review.'] |
| A3 | applicable | [] | [] | ['Receiver-side snapshot validation, FSM restore, log replacement, and post-restore index reconstruction are not shown.', 'Startup recovery from LogStore, StableStore, and SnapshotStore is not shown.', 'Snapshot transfer completion does not by itself establish FSM restoration in the supplied evidence.'] |
| A4 | applicable | [] | [] | ['The supplied excerpts do not show all configuration request admission and commit completion paths.', 'The exact behavior of configuration state during snapshot restore and log suffix replacement needs review.', 'The protocol-version branch for LogConfiguration application is only partially shown.'] |
| A5 | applicable | [] | [] | ['The FSM worker, response correlation, and exact ordering between FSM completion and last-applied updates are not shown.', 'The supplied excerpt does not establish whether the last-applied update represents dispatch or completed FSM execution.', 'The complete restore interaction with application state is not shown.'] |
| A6 | applicable | [] | [] | ['Concrete LogStore, SnapshotStore, and sink durability/atomicity are not supplied.', 'Snapshot replacement, cleanup of failed snapshots, and startup reconstruction are not fully shown.', 'The exact ordering and failure recovery after snapshot close but before compaction require review.'] |
| A7 | applicable | [] | [] | ['The complete client API and future implementation are not included in the supplied excerpts.', 'Caller retry, identity, cancellation, and duplicate-operation semantics are not established.', 'The exact point at which ApplyFuture success is exposed relative to durable commit and FSM completion needs review.'] |
未解释责任：Raft.installSnapshot；The entry point is identified, but receiver-side snapshot installation and its fact lifecycle are not present in the supplied source.
未解释责任：Raft.NewRaft/startup recovery；Startup restoration from stable, log, and snapshot stores is required to complete recovery understanding but is not included in supplied ranges.

| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |
| --- | --- | --- | --- |
| `ed0568a0` | 扩展职责/交接覆盖 | pending/read | Resolve decisive understanding gaps； |

| 复核对象/版本 | 层面 | 判断 | 材料与推导 |
| --- | --- | --- | --- |
尚无已执行的语义复核；有来源的候选不因此变成已确认规范。

职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。

## 未受理草稿分析
尚未完成自主义务发现；未补入预置义务。

## 候选修复会话

原始候选、当前版本、修复 patch 与问题计数分开保存；调用完成不等于候选或语义已接受。
会话 `616cb046ca24441a8aa8cb371eee41d0`：repairing；候选版本 0；修复调用 0；原始候选 [original.json](repair-sessions/616cb046ca24441a8aa8cb371eee41d0/original.json)；当前候选 [candidate-0.json](repair-sessions/616cb046ca24441a8aa8cb371eee41d0/candidate-0.json)；问题 Audit unit references missing bindings or relations。
诊断及材料：[{'details': {}, 'code': 'unclassified_validation', 'category': 'semantic', 'task': 'derive', 'candidate_version': 0, 'object_ids': [], 'paths': [], 'material_ids': [], 'message': 'Audit unit references missing bindings or relations', 'allowed': ['stop']}]；重复失败：{}；显式范围/语义计划：无。

## 实验能力与执行

| 能力 | 状态 | 执行依据 |
| --- | --- | --- |
| package_tests | probe_confirmed | 361528b96017439ba3533672e62c05df：Package build and selected existing tests; not a full suite or scheduling probe |
| precise_schedule_replay | unavailable | 无执行确认：No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites |

默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。

| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |
| --- | --- | --- | --- | --- |
| Codex 版本检查：agent_probe `687dee27` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/687dee27056f42ab927095733e225ac8/stdout.log) / [stderr.log](logs/687dee27056f42ab927095733e225ac8/stderr.log) |
| Codex 参数检查：agent_capabilities `8a35a18f` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/8a35a18f767542d0b47f872d31a2caeb/stdout.log) / [stderr.log](logs/8a35a18f767542d0b47f872d31a2caeb/stderr.log) |
| Java 版本检查：java_probe `1d28ae23` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/1d28ae23347e4e878179c304977a8ce0/stdout.log) / [stderr.log](logs/1d28ae23347e4e878179c304977a8ce0/stderr.log) |
| 验证工具启动检查：verifier_probe `0a9268d2` | 正常完成 | 版本帮助已识别，工具可用；命令退出码 1 | 不适用：未检查性质 | [stdout.log](logs/0a9268d21f1f42e9a614918da5392ba2/stdout.log) / [stderr.log](logs/0a9268d21f1f42e9a614918da5392ba2/stderr.log) |
| 目标工具链版本检查：implementation_tool_probe `adb4302d` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/adb4302d14094107b8e7edbea512ddbd/stdout.log) / [stderr.log](logs/adb4302d14094107b8e7edbea512ddbd/stderr.log) |
| 现有测试与实验能力探测：capability_probe `361528b9` | 正常完成 | 所执行测试通过 | 仅限实际测试覆盖；不自动证明目标或确认违反 | [stdout.log](logs/361528b96017439ba3533672e62c05df/stdout.log) / [stderr.log](logs/361528b96017439ba3533672e62c05df/stderr.log) |
| Agent 分析或修复：agent `a5c5c064` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/a5c5c064867641eca38a7772bc8114e3/stdout.log) / [stderr.log](logs/a5c5c064867641eca38a7772bc8114e3/stderr.log) / [response.json](agent/cee1d760e3b349d5a5c78349c79f349c-read/response.json) |
| Agent 分析或修复：agent `3e4d0e1b` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/3e4d0e1becb748148261d0f7f8226a23/stdout.log) / [stderr.log](logs/3e4d0e1becb748148261d0f7f8226a23/stderr.log) / [response.json](agent/81ba3fa5e0a34e12b47444dd40ee8077-discover/response.json) |
| Agent 分析或修复：agent `fd43f491` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/fd43f4910d0848c5959150b8e7fd9890/stdout.log) / [stderr.log](logs/fd43f4910d0848c5959150b8e7fd9890/stderr.log) / [response.json](agent/d7190e0571ce4c01aff146695ab14845-derive/response.json) / [graph-validation-error.txt](agent/d7190e0571ce4c01aff146695ab14845-derive/graph-validation-error.txt) |

逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）：

## 模型、校准与证据范围

尚未生成并执行局部模型；没有模型层检查结论。

## 候选发现与 F1—F4

本次尚无记录的候选违反。这不代表实现没有缺陷。
本次没有实际应用的语义修订；工具错误不冒充 F1—F4。

## 未决事项与停止原因

停止原因（原文）：Cannot localize an authorized mechanical repair; explicit semantic plan required: Audit unit references missing bindings or relations
控制器格式：obligation-audit-v1；阶段：new_run。
恢复位置：探索/复核任务 `None`；单元 `None`，模型 `None`，反例 `None`，下一动作 `discover`。
- Cannot localize an authorized mechanical repair; explicit semantic plan required: Audit unit references missing bindings or relations
- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。
- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。

## 实际运行统计

累计执行时间：426.98 秒；预算计数：`{'experiments': 1, 'agent_calls': 3}`。
首个已保存模型前耗时：尚无模型；模型仍须通过实际工具检查。
审计单元 0；范围扩展 0；语义修订 0；校准 0。
完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。


## 材料、上下文与实际产物

字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。
唯一材料 76708/120000 字符；区间并集 15/40。广度当前可分配 1292、为深度保留 42000；深度可分配 43292、为广度保留 0。
建模类执行记录 0；受理且非空 Bundle 回复 0；落盘模型版本 0（仅模型阶段 0，完整组件 0）；实际性质搜索记录 0（触达与校准另列）。

| 阶段 | 新调用记录 | 已记录时长（秒） |
| --- | --- | --- |
| agent_probe | 1 | 0.02（1 条有起止时间） |
| agent_capabilities | 1 | 0.02（1 条有起止时间） |
| java_probe | 1 | 0.06（1 条有起止时间） |
| verifier_probe | 1 | 0.15（1 条有起止时间） |
| implementation_tool_probe | 1 | 0.01（1 条有起止时间） |
| capability_probe | 1 | 13.08（1 条有起止时间） |
| read | 1 | 52.23（1 条有起止时间） |
| discover | 1 | 254.83（1 条有起止时间） |
| derive | 1 | 103.88（1 条有起止时间） |
缓存复用/重附加记录 1 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。

| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |
| --- | --- | --- | --- | --- |
| read/bc81dbac | accepted | 119021/119021 | 1294 | 0/0 |
| discover/3891e452 | executed | 107211/107211 | 13645 | 0/0 |
| derive/3b6ac1b4 | executed | 169984/169984 | 19048 | 0/0 |
复核接口修复会话 0；实际 F2 语义修订 0。二者不互相替代。

## 范围接回、复核复用与里程碑

里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。
同语义复核复用记录 0；上下文准备失败 0；未发送包不消耗实际探索/复核轮数。
读取计划：当前 receipt 有新源 2、纯缓存 1；修复无进展次数 0。targeted_reads 按取得新源的逻辑计划计数，历史用量不重算；缓存发送仍消耗实际 agent 调用与时间。
技能加载 `bc81dbacae7e4c02a909d92621b3e56b`：版本 obligation-audit-v1，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/activity-classes.md', 'tasks/read.md']；仅以实际发送状态为准。
技能加载 `3891e452bf1e46688d44a751d821edab`：版本 obligation-audit-v1，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/discover.md']；仅以实际发送状态为准。
技能加载 `3b6ac1b4745b4526b2f9f316ea0c2253`：版本 obligation-audit-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
需接回且已取得新材料的计划 0；已接回 0；连接率 无可计算分母/历史未记录。这不是语义通过率或系统覆盖率。
实际发送包中源正文累计 178445 字符（跨调用重复发送会重复计入）；schema 累计 33987 字节。无真实 token/账单字段时不换算费用。