# 共识义务驱动局部审计报告

运行标识：`cc4d0482b72a4410940cc41599c2ee6a`；模式：**真实工具运行**。

目标解释审计意义，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。

分析入口：`autonomous`。regression 表示预设开发回归，不能计为自主发现验收。


## 本次流程进度

工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。

| 阶段 | 已记录的进度 |
| --- | --- |
| 材料阅读 | 已完成首轮阅读；保存 19 个片段 |
| 目标、义务与代码关系 | 发现结果已被工作流接受；当前图有 3 项主张、2 个审计单元 |
| 直接实现检查 | 已保存 0 个制品；完成 0 次执行；不等于整体性质成立 |
| 局部模型 | 已保存 0 个模型版本；保存不代表检查通过 |
| 轨迹校准 | 0 条校准记录；不等同于性质判定 |
| 模型搜索 | 0 次执行记录；逐项结果见下方，未执行不计通过 |
| 性质证据 | 0 条直接证据；范围与层级见证据记录 |

若 agent 回复完成而目标发现仍未被接受，不能把该回复视为已成立的关系图。历史记录未保存具体拒绝原因时，报告不补造原因。

## 职责覆盖与语义复核

材料读取、职责认识、语义复核和局部性质检查分别记录。职责概览由当前材料逐步形成，不是完备全集；不计算全系统覆盖率。复核暂未发现问题不等于形式证明，多个 agent 回复一致也不等于独立证据。

| 职责候选 | 来源 | 关联目标/义务 | 尚未解释 |
| --- | --- | --- | --- |
| RESP1：FSM snapshot capture and persistence | fsm.go:16:285, snapshot.go:15:278 | G1, O1 | Does the snapshot capture represent the intended FSM index?；Does sink close publish durable, reopenable state? |
| 交接候选 RESP1 → RESP2 | ['snapshot.go:15:278'] | Persisted snapshot metadata and bytes are handed to compaction and later recovery. | {'assignments': [{'unit_id': 'U1', 'version': 1, 'execution_status': 'blocked', 'coverage_limitations': []}, {'unit_id': 'U1', 'version': 1, 'execution_status': 'blocked', 'coverage_limitations': []}], 'status': 'assigned_not_proven', 'reason_needs_review': True}；分配不等于完成覆盖 |
| RESP2：Log compaction and snapshot-based follower catch-up | snapshot.go:15:278, replication.go:137:387 | G1, O1 | Can compaction remove data before recovery has a usable alternative?；Does snapshot installation restore the required replication position? |
| 交接候选 RESP2 → RESP3 | ['replication.go:137:387'] | A retained snapshot is handed to the follower installation path. | {'assignments': [], 'status': 'unassigned', 'reason_needs_review': True}；分配不等于完成覆盖 |
| RESP3：FSM application and restore | fsm.go:16:285 | 尚未形成目标/义务 | How are restored indexes and application state reconstructed?；What concrete FSM and snapshot implementation guarantees apply? |

| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |
| --- | --- | --- | --- |
| `6fbe8081` | 扩展职责/交接覆盖 | blocked/read | The current workset does not represent client admission, commit progression, and completion correlation, which determine what state snapshot capture is expected to include.；Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt |
| `a00aff90` | 扩展职责/交接覆盖 | blocked/read | Concrete store behavior is required to decide whether the snapshot-compaction obligation applies as an executable check.；Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt |
| `b461a545` | 扩展职责/交接覆盖 | completed/done | Initial discovery requested additional material; existing units do not suppress it； |
| `a015af23` | 扩展职责/交接覆盖 | blocked/read | Deferred initial material remains unexplored；Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt |
| `f297eaae` | 扩展职责/交接覆盖 | blocked/read | Complete the thin activity map for snapshot recovery and determine whether the concrete failed-replacement suspicion affects a legal restart or follower catch-up path.；Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt |
| `89977fa5` | 语义复核 | blocked/analyze | Review new semantic inputs, dependency evidence or checker correspondence；Explicit semantic/scope plan requested: The schema diagnostic requires adding three fields, converting alternatives to a string, and removing the extra judgment and analysis fields. The permitted representation repair operation supports value replacement only and provides no authorized deletion or parent-object replacement path, so this item cannot be made schema-valid without a deletion-capable repair operation. |
| `40f0f5df` | 语义复核 | blocked/analyze | Review new semantic inputs, dependency evidence or checker correspondence；Structured response repair stopped after 3 attempts: Interface repair must retain prior negative analysis and limitations; only diagnosed metadata may change |
| `03584d7e` | 扩展职责/交接覆盖 | blocked/analyze | Select one bounded question from the responsibility backlog；Cannot localize an authorized mechanical repair; explicit semantic plan required: Coverage intent references unselected evidence or bindings |

| 复核对象/版本 | 层面 | 判断 | 材料与推导 |
| --- | --- | --- | --- |
尚无已执行的语义复核；有来源的候选不因此变成已确认规范。

职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。

## 分析输入与探索范围

仓库：`/home/nitro/Desktop/hashicorp-raft`
提交：`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；分支：`detached / unavailable`；脏工作区：`False`。
快照：`439aa24c182444c4b7216e747982d230`，纳入 88 个文件；读取 19 个材料片段，仍有未读范围的文件 81 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。
候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。

## 目标、义务与选择依据

领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考：
- `configured_reference`：未提供协议参考清单
定向补读：Read material；关联 []；实际新增片段 ['README.md:1:100', 'docs/README.md:1:100', '.github/CODEOWNERS:1:13', '.github/workflows/ci.yml:1:88', '.gitignore:1:26', 'bench/bench.go:1:100', 'docs/apply.md:1:100', 'fuzzy/apply_src.go:1:68']。
定向补读：The catalogue supports a broad implementation-grounded survey across decision progression, role and timeout control, durable history and recovery, membership, transport-facing replication, and decision-to-service effects. The selected ranges prioritize concrete producers, consumers, shared state, and cross-thread handoffs while separating implementation observations from documentation expectations. Existing initial materials describe the intended apply sequence and high-level roles, but do not establish the actual behavior of the core loops, persistence paths, membership transitions, or asynchronous response handling.；关联 ['docs/apply.md:1:100', 'docs/README.md:1:100', 'README.md:1:100']；实际新增片段 ['raft.go:135:360', 'raft.go:965:1205', 'raft.go:1976:2241', 'replication.go:137:387', 'fsm.go:16:285', 'snapshot.go:15:278']。
定向补读：Does the concrete configured SnapshotStore make a successfully closed snapshot durably openable, and does the restart or lagging-peer recovery path reconstruct the FSM state before compactLogsWithTrailing deletes the selected log range?；关联 ['U1']；实际新增片段 ['file_snapshot.go:1:551', 'inmem_snapshot.go:1:113', 'raft.go:1244:1602', 'raft.go:1603:1955']。
定向补读：The current workset does not represent client admission, commit progression, and completion correlation, which determine what state snapshot capture is expected to include.；关联 ['RESP3']；实际新增片段 []。
定向补读：Concrete store behavior is required to decide whether the snapshot-compaction obligation applies as an executable check.；关联 ['RESP1', 'RESP2']；实际新增片段 []。
定向补读：Concrete store behavior is required to decide whether the snapshot-compaction obligation applies as an executable check.；关联 ['RESP1', 'RESP2']；实际新增片段 ['log.go:1:192']。
定向补读：Initial discovery requested additional material; existing units do not suppress it；关联 []；实际新增片段 []。
定向补读：Initial discovery requested additional material; existing units do not suppress it；关联 []；实际新增片段 []。
定向补读：The diagnostic requires substantive decomposition review for O1, but the implementation materials needed to assess necessity, sufficiency, alternatives, and producer/consumer dependencies are omitted from the supplied context. The available documentation and retained candidate analysis identify the relevant gaps but cannot establish the missing judgment. No review item is added until the requested source ranges are acquired.；关联 ['O1']；实际新增片段 []。
定向补读：The requested unit review cannot be completed from the supplied materials. The required decomposition aspect depends on omitted source ranges, and the available in-memory store excerpt alone cannot establish the complete executable scope or applicability. No semantic judgment or approval is proposed until those ranges are acquired.；关联 ['U_snapshot_failed_replacement']；实际新增片段 []。
定向补读：Deferred initial material remains unexplored；关联 []；实际新增片段 []。
定向补读：Complete the thin activity map for snapshot recovery and determine whether the concrete failed-replacement suspicion affects a legal restart or follower catch-up path.；关联 ['RESP2', 'RESP3']；实际新增片段 []。
定向补读：Select one bounded question from the responsibility backlog；关联 ['RESP1']；实际新增片段 []。
- `G1`（goal，unassessed）：After a snapshot is durably persisted and log compaction completes, a restarted or lagging Raft peer must retain a recoverable representation of the committed FSM state and the history needed for continued replication.
  来源：README.md:1:100, docs/README.md:1:100, snapshot.go:15:278；待确认：Concrete store durability and recovery semantics are unread.。
  语义版本：1；行为材料 ['snapshot.go:15:278', 'replication.go:137:387']；职责依据 ['README.md:1:100', 'docs/README.md:1:100', 'fsm.go:16:285']；绑定 ['B1', 'B2', 'B3', 'B4']。
  推导：The implementation persists an FSM snapshot, records snapshot metadata, compacts logs, and later sends a snapshot to lagging peers. The documentation states that snapshots permit removal of logs used to reach the captured state and that committed entries may be applied to the FSM.；适用性：Applicable when snapshotting is enabled, a snapshot is successfully created and persisted, and compaction or lagging-peer recovery is exercised.；未决/冲突：['Whether concrete store implementations make persisted snapshot data and metadata durable together.', 'Whether recovery reconstructs all state required after the selected compaction point.']。
- `O1`（obligation，unassessed）：For every successful takeSnapshot path, log deletion must not remove the only recoverable history or snapshot representation needed to reconstruct the FSM state at or before the compacted index and to continue replication.
  来源：snapshot.go:15:278, replication.go:137:387；待确认：The source for concrete store Close, List ordering, Open durability, and DeleteRange behavior is missing.；The restart reconstruction path is missing.。
  语义版本：1；行为材料 ['snapshot.go:15:278', 'replication.go:137:387']；职责依据 ['README.md:1:100', 'docs/README.md:1:100', 'snapshot.go:15:278']；绑定 ['B1', 'B2', 'B3', 'B4']。
  推导：takeSnapshot calls FSMSnapshot.Persist, closes the sink, updates last-snapshot state, and then compacts through compactLogsWithTrailing. A lagging peer is later recovered through sendLatestSnapshot, which selects and opens a listed snapshot. These producer-consumer dependencies make recoverability across compaction an applicable candidate obligation.；适用性：Applicable only after successful snapshot persistence and close; not established for error paths or concrete stores whose contracts are unread.；未决/冲突：['Whether sink.Close durably publishes the snapshot before compaction.', 'Whether List returns a snapshot that Open can still recover after compaction.', 'Whether the FSM snapshot is semantically complete at snapReq.index.']。
- `O2`（obligation，unassessed）：When a new snapshot attempt fails before successful persistence, a previously usable snapshot must remain available if it is the only recoverable representation needed for restart or follower recovery.
  来源：snapshot.go:15:278, inmem_snapshot.go:1:113, fsm.go:16:285；待确认：Applicability of this obligation to all SnapshotStore implementations requires the concrete store-selection and recovery configuration.；The restart and follower-consumption paths have not been read.。
  语义版本：1；行为材料 ['inmem_snapshot.go:1:113', 'snapshot.go:15:278', 'fsm.go:16:285']；职责依据 []；绑定 ['B_inmem_create', 'B_inmem_cancel', 'B_take_snapshot']。
  推导：The goal requires a recoverable representation after snapshot/compaction operations. The in-memory implementation replaces the prior snapshot during Create, while the failure path calls Cancel, which is a no-op. This derives a candidate producer/consumer obligation for preserving the prior representation across failed replacement.；适用性：Applicable when InmemSnapshotStore is configured and a prior snapshot exists before a replacement snapshot fails.；未决/冲突：['Whether the surrounding recovery workflow can legally tolerate loss of the prior snapshot after a failed attempt.']。

审计单元 `U1` 引用关系 ['R1', 'R2', 'R3'] 和代码绑定 ['B1', 'B2', 'B4']。
选择依据（原文）：Follow pending boundary producers before consumers; otherwise use the agent's justified ordering

审计单元 `U_snapshot_failed_replacement` 引用关系 ['R_G1_O2'] 和代码绑定 ['B_take_snapshot', 'B_inmem_create', 'B_inmem_cancel']。
选择依据（原文）：Follow pending boundary producers before consumers; otherwise use the agent's justified ordering

单元 `U1`：blocked；This is the highest-ranked feasible unit because it connects an explicit system consequence to a complete visible orchestration path, while the unresolved store and recovery handoffs are concrete and discriminating.
范围：Snapshot persistence, compaction, and lagging-peer recovery for one configured store variant.；能否表达目标后果：True。

单元 `U_snapshot_failed_replacement`：blocked；The concrete implementation exposes a narrow, directly testable recovery hazard without assuming a universal consensus rule. The broader G1/O1 path still needs recovery and replication sources.
范围：Failed replacement snapshot behavior in InmemSnapshotStore, including prior snapshot availability after Persist error and Cancel.；能否表达目标后果：True。
审计问题：Does the concrete configured SnapshotStore make a successfully closed snapshot durably openable, and does the restart or lagging-peer recovery path reconstruct the FSM state before compactLogsWithTrailing deletes the selected log range?；意义：A failure could make committed state unrecoverable after compaction or prevent a lagging peer from rejoining, despite the documented snapshot-based bounded-log guarantee.；材料：['snapshot.go:15:278', 'replication.go:137:387', 'README.md:1:100', 'docs/README.md:1:100']。
建模前复核/探索性许可：{}。
有效交互覆盖限制（独立于原始 checker 结果）：['No executable trigger requirement covers point CP1', 'No executable trigger requirement covers point CP2', 'No executable trigger requirement covers point CP1', 'No executable trigger requirement covers point CP2', 'No executable trigger requirement covers point CP3']。
单元 `U1` 逐项执行进度：{}；尚待检查：['O1']。已检查仅指记录范围内的 checker，不代表义务整体成立。
审计问题：With an existing valid snapshot A, does a replacement snapshot B that is created by InmemSnapshotStore.Create and then fails during FSMSnapshot.Persist leave A openable and listed after the failure, or has A already been replaced by unusable B?；意义：Loss of the prior usable snapshot can remove the only recovery representation while log history may still be relied upon for restart or follower catch-up, directly threatening the recoverability goal.；材料：['snapshot.go:15:278', 'fsm.go:16:285', 'inmem_snapshot.go:1:113']。
建模前复核/探索性许可：{}。
有效交互覆盖限制（独立于原始 checker 结果）：['No executable trigger requirement covers point CP1', 'No executable trigger requirement covers point CP2', 'No executable trigger requirement covers point CP3', 'No executable trigger requirement covers point CP1', 'No executable trigger requirement covers point CP2', 'No executable trigger requirement covers point CP3']。
单元 `U_snapshot_failed_replacement` 逐项执行进度：{}；尚待检查：['O2']。已检查仅指记录范围内的 checker，不代表义务整体成立。

## 候选修复会话

原始候选、当前版本、修复 patch 与问题计数分开保存；调用完成不等于候选或语义已接受。
会话 `5f001ef74f304a69a6a7464f91cafb4d`：accepted；候选版本 1；修复调用 1；原始候选 [original.json](repair-sessions/5f001ef74f304a69a6a7464f91cafb4d/original.json)；当前候选 [candidate-1.json](repair-sessions/5f001ef74f304a69a6a7464f91cafb4d/candidate-1.json)；问题 。
诊断及材料：[]；重复失败：{}；显式范围/语义计划：无。
会话 `954525e8262a4133b27edaa05731224a`：repairing；候选版本 0；修复调用 0；原始候选 [original.json](repair-sessions/954525e8262a4133b27edaa05731224a/original.json)；当前候选 [candidate-0.json](repair-sessions/954525e8262a4133b27edaa05731224a/candidate-0.json)；问题 Question continuation preserves meaning; reinterpretation requires F2。
诊断及材料：[{'details': {}, 'code': 'unclassified_validation', 'category': 'semantic', 'task': 'question', 'candidate_version': 0, 'object_ids': [], 'paths': [], 'material_ids': [], 'message': 'Question continuation preserves meaning; reinterpretation requires F2', 'allowed': ['stop']}]；重复失败：{}；显式范围/语义计划：无。
会话 `8bb523588c89422b88cd250ebdb273b3`：accepted；候选版本 1；修复调用 1；原始候选 [original.json](repair-sessions/8bb523588c89422b88cd250ebdb273b3/original.json)；当前候选 [candidate-1.json](repair-sessions/8bb523588c89422b88cd250ebdb273b3/candidate-1.json)；问题 。
诊断及材料：[]；重复失败：{}；显式范围/语义计划：无。
会话 `44c5eb38072a4828b983b9444b0c3443`：repairing；候选版本 1；修复调用 3；原始候选 [original.json](repair-sessions/44c5eb38072a4828b983b9444b0c3443/original.json)；当前候选 [candidate-1.json](repair-sessions/44c5eb38072a4828b983b9444b0c3443/candidate-1.json)；问题 Explicit semantic/scope plan requested: The schema diagnostic requires adding three fields, converting alternatives to a string, and removing the extra judgment and analysis fields. The permitted representation repair operation supports value replacement only and provides no authorized deletion or parent-object replacement path, so this item cannot be made schema-valid without a deletion-capable repair operation.。
诊断及材料：[{'details': {}, 'code': 'schema_type', 'category': 'format', 'task': 'semantic_review', 'candidate_version': 1, 'object_ids': [], 'paths': ['/items/3/status', '/items/3/explanation', '/items/3/alternatives', '/items/3/counterexample_reasoning', '/items/3/judgment', '/items/3/analysis'], 'material_ids': [], 'message': "6 validation errors for ReviewReply\nitems.3.status\n  Field required [type=missing, input_value={'target_id': 'O1', 'aspe... are not established.']}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.3.explanation\n  Field required [type=missing, input_value={'target_id': 'O1', 'aspe... are not established.']}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.3.alternatives\n  Input should be a valid string [type=string_type, input_value=['Retained trailing logs ...s are not established.'], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.13/v/string_type\nitems.3.counterexample_reasoning\n  Field required [type=missing, input_value={'target_id': 'O1', 'aspe... are not established.']}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.3.judgment\n  Extra inputs are not permitted [type=extra_forbidden, input_value='needs_specific_evidence', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.3.analysis\n  Extra inputs are not permitted [type=extra_forbidden, input_value='The obligation is necess...tees remain unresolved.', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden", 'allowed': ['representation']}]；重复失败：{}；显式范围/语义计划：The schema diagnostic requires adding three fields, converting alternatives to a string, and removing the extra judgment and analysis fields. The permitted representation repair operation supports value replacement only and provides no authorized deletion or parent-object replacement path, so this item cannot be made schema-valid without a deletion-capable repair operation.。
会话 `9ebfdcb6ad9c49ef8ba6272264670046`：repairing；候选版本 1；修复调用 3；原始候选 [original.json](repair-sessions/9ebfdcb6ad9c49ef8ba6272264670046/original.json)；当前候选 [candidate-1.json](repair-sessions/9ebfdcb6ad9c49ef8ba6272264670046/candidate-1.json)；问题 12 validation errors for ReviewReply
items.2.aspect
  Field required [type=missing, input_value={'target_id': 'U_snapshot...ition_dispositions': {}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
items.2.status
  Field required [type=missing, input_value={'target_id': 'U_snapshot...ition_dispositions': {}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
items.2.explanation
  Field required [type=missing, input_value={'target_id': 'U_snapshot...ition_dispositions': {}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
items.2.alternatives
  Field required [type=missing, input_value={'target_id': 'U_snapshot...ition_dispositions': {}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
items.2.counterexample_reasoning
  Field required [type=missing, input_value={'target_id': 'U_snapshot...ition_dispositions': {}}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
items.2.object_type
  Extra inputs are not permitted [type=extra_forbidden, input_value='unit', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.version
  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.required_aspects
  Extra inputs are not permitted [type=extra_forbidden, input_value=['decomposition'], input_type=list]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.judgment
  Extra inputs are not permitted [type=extra_forbidden, input_value='needs_specific_evidence', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.analysis
  Extra inputs are not permitted [type=extra_forbidden, input_value="The selected scope is co...SnapshotStore behavior.", input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.resolves_issue_ids
  Extra inputs are not permitted [type=extra_forbidden, input_value=[], input_type=list]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden
items.2.condition_dispositions
  Extra inputs are not permitted [type=extra_forbidden, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden。
诊断及材料：[{'details': {}, 'code': 'schema_type', 'category': 'format', 'task': 'semantic_review', 'candidate_version': 1, 'object_ids': [], 'paths': ['/items/2/aspect', '/items/2/status', '/items/2/explanation', '/items/2/alternatives', '/items/2/counterexample_reasoning', '/items/2/object_type', '/items/2/version', '/items/2/required_aspects', '/items/2/judgment', '/items/2/analysis', '/items/2/resolves_issue_ids', '/items/2/condition_dispositions'], 'material_ids': [], 'message': '12 validation errors for ReviewReply\nitems.2.aspect\n  Field required [type=missing, input_value={\'target_id\': \'U_snapshot...ition_dispositions\': {}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.2.status\n  Field required [type=missing, input_value={\'target_id\': \'U_snapshot...ition_dispositions\': {}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.2.explanation\n  Field required [type=missing, input_value={\'target_id\': \'U_snapshot...ition_dispositions\': {}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.2.alternatives\n  Field required [type=missing, input_value={\'target_id\': \'U_snapshot...ition_dispositions\': {}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.2.counterexample_reasoning\n  Field required [type=missing, input_value={\'target_id\': \'U_snapshot...ition_dispositions\': {}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing\nitems.2.object_type\n  Extra inputs are not permitted [type=extra_forbidden, input_value=\'unit\', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.version\n  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.required_aspects\n  Extra inputs are not permitted [type=extra_forbidden, input_value=[\'decomposition\'], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.judgment\n  Extra inputs are not permitted [type=extra_forbidden, input_value=\'needs_specific_evidence\', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.analysis\n  Extra inputs are not permitted [type=extra_forbidden, input_value="The selected scope is co...SnapshotStore behavior.", input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.resolves_issue_ids\n  Extra inputs are not permitted [type=extra_forbidden, input_value=[], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden\nitems.2.condition_dispositions\n  Extra inputs are not permitted [type=extra_forbidden, input_value={}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden', 'allowed': ['representation']}]；重复失败：{}；显式范围/语义计划：无。
会话 `61d1d3f8c06348bab2441483995b18f8`：repairing；候选版本 0；修复调用 0；原始候选 [original.json](repair-sessions/61d1d3f8c06348bab2441483995b18f8/original.json)；当前候选 [candidate-0.json](repair-sessions/61d1d3f8c06348bab2441483995b18f8/candidate-0.json)；问题 Question continuation preserves meaning; reinterpretation requires F2。
诊断及材料：[{'details': {}, 'code': 'unclassified_validation', 'category': 'semantic', 'task': 'question', 'candidate_version': 0, 'object_ids': [], 'paths': [], 'material_ids': [], 'message': 'Question continuation preserves meaning; reinterpretation requires F2', 'allowed': ['stop']}]；重复失败：{}；显式范围/语义计划：无。
会话 `1bfdf360687b4f1d82b70c178ee19947`：repairing；候选版本 0；修复调用 0；原始候选 [original.json](repair-sessions/1bfdf360687b4f1d82b70c178ee19947/original.json)；当前候选 [candidate-0.json](repair-sessions/1bfdf360687b4f1d82b70c178ee19947/candidate-0.json)；问题 Coverage intent references unselected evidence or bindings。
诊断及材料：[{'details': {}, 'code': 'unclassified_validation', 'category': 'semantic', 'task': 'explore', 'candidate_version': 0, 'object_ids': [], 'paths': [], 'material_ids': [], 'message': 'Coverage intent references unselected evidence or bindings', 'allowed': ['stop']}]；重复失败：{}；显式范围/语义计划：无。
代码位置 `B1`：snapshot.go:125–211；锚点 source_ids=['snapshot.go:15:278'] boundary_complete=True kind='declaration' material_id='snapshot.go:15:278' start_line=125 end_line=125 symbol='Raft.takeSnapshot'；候选职责关联 ['G1', 'O1']。
代码位置 `B2`：snapshot.go:216–248；锚点 source_ids=['snapshot.go:15:278'] boundary_complete=True kind='declaration' material_id='snapshot.go:15:278' start_line=216 end_line=216 symbol='Raft.compactLogsWithTrailing'；候选职责关联 ['O1']。
代码位置 `B3`：snapshot.go:49–59；锚点 source_ids=['snapshot.go:15:278'] boundary_complete=True kind='declaration' material_id='snapshot.go:15:278' start_line=45 end_line=45 symbol='SnapshotStore'；候选职责关联 ['O1']。
代码位置 `B4`：replication.go:299–383；锚点 source_ids=['replication.go:137:387'] boundary_complete=True kind='declaration' material_id='replication.go:137:387' start_line=299 end_line=299 symbol='Raft.sendLatestSnapshot'；候选职责关联 ['G1', 'O1']。
代码位置 `B_inmem_create`：inmem_snapshot.go:37–65；锚点 source_ids=['inmem_snapshot.go:1:113'] boundary_complete=True kind='declaration' material_id='inmem_snapshot.go:1:113' start_line=37 end_line=38 symbol='InmemSnapshotStore.Create'；候选职责关联 ['G1', 'O2']。
代码位置 `B_inmem_cancel`：inmem_snapshot.go:111–113；锚点 source_ids=['inmem_snapshot.go:1:113'] boundary_complete=True kind='declaration' material_id='inmem_snapshot.go:1:113' start_line=111 end_line=111 symbol='InmemSnapshotSink.Cancel'；候选职责关联 ['O2']。
代码位置 `B_take_snapshot`：snapshot.go:125–211；锚点 source_ids=['snapshot.go:15:278'] boundary_complete=True kind='declaration' material_id='snapshot.go:15:278' start_line=125 end_line=125 symbol='Raft.takeSnapshot'；候选职责关联 ['G1', 'O2']。
单元 `U1` 的代码用途：[{'binding_id': 'B1', 'role': 'direct', 'claim_ids': ['G1', 'O1'], 'relation_ids': ['R1', 'R2'], 'source_ids': ['snapshot.go:15:278'], 'rationale': 'The unit checks the snapshot persistence and compaction sequence.', 'unverified': ['SnapshotStore durability']}, {'binding_id': 'B2', 'role': 'direct', 'claim_ids': ['O1'], 'relation_ids': ['R1'], 'source_ids': ['snapshot.go:15:278'], 'rationale': 'The unit checks the deletion boundary.', 'unverified': ['DeleteRange recovery impact']}, {'binding_id': 'B4', 'role': 'support', 'claim_ids': ['G1', 'O1'], 'relation_ids': ['R3'], 'source_ids': ['replication.go:137:387'], 'rationale': 'The unit uses snapshot installation as the recovery consumer.', 'unverified': ['Follower installation and restart behavior']}]；支撑用途不计为已检查义务。
单元 `U_snapshot_failed_replacement` 的代码用途：[{'binding_id': 'B_take_snapshot', 'role': 'direct', 'claim_ids': ['O2'], 'relation_ids': [], 'source_ids': ['snapshot.go:15:278'], 'rationale': 'The unit checks the snapshot lifecycle that initiates replacement and handles persistence failure.', 'unverified': []}, {'binding_id': 'B_inmem_create', 'role': 'direct', 'claim_ids': ['O2'], 'relation_ids': [], 'source_ids': ['inmem_snapshot.go:1:113'], 'rationale': 'The unit checks when the replacement becomes the current snapshot.', 'unverified': []}, {'binding_id': 'B_inmem_cancel', 'role': 'direct', 'claim_ids': ['O2'], 'relation_ids': [], 'source_ids': ['inmem_snapshot.go:1:113'], 'rationale': 'The unit checks the failure cleanup behavior.', 'unverified': []}]；支撑用途不计为已检查义务。

## 实验能力与执行

| 能力 | 状态 | 执行依据 |
| --- | --- | --- |
| package_tests | probe_confirmed | 9d4169a331f046aca1f0f8e909944ca8：Package build and selected existing tests; not a full suite or scheduling probe |
| precise_schedule_replay | unavailable | 无执行确认：No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites |

默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。

| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |
| --- | --- | --- | --- | --- |
| Codex 版本检查：agent_probe `a4e3ddca` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/a4e3ddca9ae94602b1a360001114d155/stdout.log) / [stderr.log](logs/a4e3ddca9ae94602b1a360001114d155/stderr.log) |
| Codex 参数检查：agent_capabilities `103cd2e1` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/103cd2e195354e269eb55b285d1a1a37/stdout.log) / [stderr.log](logs/103cd2e195354e269eb55b285d1a1a37/stderr.log) |
| Java 版本检查：java_probe `b68e1be8` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/b68e1be89f8d47d8993c2feb35a8f737/stdout.log) / [stderr.log](logs/b68e1be89f8d47d8993c2feb35a8f737/stderr.log) |
| 验证工具启动检查：verifier_probe `3e026263` | 正常完成 | 版本帮助已识别，工具可用；命令退出码 1 | 不适用：未检查性质 | [stdout.log](logs/3e02626327554869a8c7d9a92876aafc/stdout.log) / [stderr.log](logs/3e02626327554869a8c7d9a92876aafc/stderr.log) |
| 目标工具链版本检查：implementation_tool_probe `8f0ed034` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/8f0ed03431ca47da96e8aa196e46e490/stdout.log) / [stderr.log](logs/8f0ed03431ca47da96e8aa196e46e490/stderr.log) |
| 现有测试与实验能力探测：capability_probe `9d4169a3` | 正常完成 | 所执行测试通过 | 仅限实际测试覆盖；不自动证明目标或确认违反 | [stdout.log](logs/9d4169a331f046aca1f0f8e909944ca8/stdout.log) / [stderr.log](logs/9d4169a331f046aca1f0f8e909944ca8/stderr.log) |
| Agent 分析或修复：agent `a1674235` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/a16742353d174b1bab1d92927cc4f91f/stdout.log) / [stderr.log](logs/a16742353d174b1bab1d92927cc4f91f/stderr.log) / [response.json](agent/c1c5f18c28ed41d19b06b40b8ddceadd-read/response.json) |
| Agent 分析或修复：agent `33f461a1` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/33f461a13279499e8b7aeef15585dba7/stdout.log) / [stderr.log](logs/33f461a13279499e8b7aeef15585dba7/stderr.log) / [response.json](agent/093d6886c8da4fa595e7a579d66ad41b-discover/response.json) / [graph-validation-error.txt](agent/093d6886c8da4fa595e7a579d66ad41b-discover/graph-validation-error.txt) |
| Agent 分析或修复：agent `3b18966e` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/3b18966e897f4f1e8103815c0c11b1bc/stdout.log) / [stderr.log](logs/3b18966e897f4f1e8103815c0c11b1bc/stderr.log) / [response.json](agent/c0550e6f9aaf44a4aea0b12bba69b424-discover/response.json) |
| Agent 分析或修复：agent `5e9a4005` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/5e9a4005077b4204a12b3063cf852610/stdout.log) / [stderr.log](logs/5e9a4005077b4204a12b3063cf852610/stderr.log) / [response.json](agent/916a1e7b21c74f5f83b02fdf92d6824f-question/response.json) / [graph-validation-error.txt](agent/916a1e7b21c74f5f83b02fdf92d6824f-question/graph-validation-error.txt) |
| 职责覆盖探索：agent `68c8cf89` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/68c8cf890c114e89962677039b20e9bc/stdout.log) / [stderr.log](logs/68c8cf890c114e89962677039b20e9bc/stderr.log) / [response.json](agent/e2786f356e63448c802818d99c593f3b-explore/response.json) |
| 职责覆盖探索：agent `3beea56c` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/3beea56c5ec64451aed4597ae7951bf2/stdout.log) / [stderr.log](logs/3beea56c5ec64451aed4597ae7951bf2/stderr.log) / [response.json](agent/a10892d3d2a2457b9fd945ca9ec27e76-explore/response.json) |
| 职责覆盖探索：agent `bfd8f527` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/bfd8f527b0c64833aaebd56bd8960a39/stdout.log) / [stderr.log](logs/bfd8f527b0c64833aaebd56bd8960a39/stderr.log) / [response.json](agent/f78b181775a8475fa8e8ed5325a2be22-explore/response.json) / [graph-validation-error.txt](agent/f78b181775a8475fa8e8ed5325a2be22-explore/graph-validation-error.txt) |
| 职责覆盖探索：agent `51a1e0cf` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/51a1e0cf3a6342ecab39514559911dfe/stdout.log) / [stderr.log](logs/51a1e0cf3a6342ecab39514559911dfe/stderr.log) / [response.json](agent/d3c666eacbaf4a338779f17dabe3d98d-explore/response.json) |
| 目标/义务/关系语义复核：agent `827da824` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/827da82482484d5dbd81d5e4c393751c/stdout.log) / [stderr.log](logs/827da82482484d5dbd81d5e4c393751c/stderr.log) / [response.json](agent/233fa47cf8ea47e891c719901fb44b45-semantic_review/response.json) / [graph-validation-error.txt](agent/233fa47cf8ea47e891c719901fb44b45-semantic_review/graph-validation-error.txt) |
| 目标/义务/关系语义复核：agent `1a6cc6b4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/1a6cc6b464774fdbb591b86b5cb401d9/stdout.log) / [stderr.log](logs/1a6cc6b464774fdbb591b86b5cb401d9/stderr.log) / [response.json](agent/3d85f12ab36e4f36abe4c30b55a87976-semantic_review/response.json) |
| 目标/义务/关系语义复核：agent `0322fd60` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/0322fd60d17c4a96a60f0e3ce5a31769/stdout.log) / [stderr.log](logs/0322fd60d17c4a96a60f0e3ce5a31769/stderr.log) / [response.json](agent/4722e7785bf4418e9cd99bca72d48a0e-semantic_review/response.json) / [graph-validation-error.txt](agent/4722e7785bf4418e9cd99bca72d48a0e-semantic_review/graph-validation-error.txt) |
| 目标/义务/关系语义复核：agent `d236037f` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/d236037f56be495e84f997485ae955ce/stdout.log) / [stderr.log](logs/d236037f56be495e84f997485ae955ce/stderr.log) / [response.json](agent/59cd5191b9144cc98c38b49b08b3a1a4-semantic_review/response.json) |
| 目标/义务/关系语义复核：agent `784ccc53` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/784ccc53870444e6801e955521e2ecd9/stdout.log) / [stderr.log](logs/784ccc53870444e6801e955521e2ecd9/stderr.log) / [response.json](agent/c749155121b148398b4a93b3ac04551c-semantic_review/response.json) / [graph-validation-error.txt](agent/c749155121b148398b4a93b3ac04551c-semantic_review/graph-validation-error.txt) |
| 目标/义务/关系语义复核：agent `23a8a832` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/23a8a832d085431aaaa7c022ef8b91f3/stdout.log) / [stderr.log](logs/23a8a832d085431aaaa7c022ef8b91f3/stderr.log) / [response.json](agent/47946c3463e84dc79fb44a109a9e0672-semantic_review/response.json) |
| 目标/义务/关系语义复核：agent `319895e2` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/319895e2422345c09f21061ef7fab60b/stdout.log) / [stderr.log](logs/319895e2422345c09f21061ef7fab60b/stderr.log) / [response.json](agent/6839afce61b346fc9ff9258ba4c978ac-semantic_review/response.json) / [graph-validation-error.txt](agent/6839afce61b346fc9ff9258ba4c978ac-semantic_review/graph-validation-error.txt) |
| 目标/义务/关系语义复核：agent `d1e54dd4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/d1e54dd410af43e2bf5ba7073d5ba045/stdout.log) / [stderr.log](logs/d1e54dd410af43e2bf5ba7073d5ba045/stderr.log) / [response.json](agent/76a579ed122a465a9160f7a5562eb1cd-semantic_review/response.json) |
| Agent 分析或修复：agent `669b2568` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/669b25686c5541ffb455a4eca93583ec/stdout.log) / [stderr.log](logs/669b25686c5541ffb455a4eca93583ec/stderr.log) / [response.json](agent/8894a368cf9044a287dc87aa1ef628e0-question/response.json) / [graph-validation-error.txt](agent/8894a368cf9044a287dc87aa1ef628e0-question/graph-validation-error.txt) |
| 职责覆盖探索：agent `cf53c684` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/cf53c6847cd942c299e570e5e8f722da/stdout.log) / [stderr.log](logs/cf53c6847cd942c299e570e5e8f722da/stderr.log) / [response.json](agent/1f4584097bc544ce9ad42e1f5c6e26a2-explore/response.json) |
| 职责覆盖探索：agent `17291420` | 正常完成 | 回复已返回；后续工作流校验失败，见校验日志 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/17291420395243a4b4c39818aaa420fe/stdout.log) / [stderr.log](logs/17291420395243a4b4c39818aaa420fe/stderr.log) / [response.json](agent/8372c84ce20046cf96861ee8e9fc6427-explore/response.json) / [graph-validation-error.txt](agent/8372c84ce20046cf96861ee8e9fc6427-explore/graph-validation-error.txt) |

逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）：

## 模型、校准与证据范围

尚未生成并执行局部模型；没有模型层检查结论。

## 候选发现与 F1—F4

本次尚无记录的候选违反。这不代表实现没有缺陷。
本次没有实际应用的语义修订；工具错误不冒充 F1—F4。

## 未决事项与停止原因

停止原因（原文）：Inquiry work remains incomplete; exploration or review is blocked by budget, evidence or capability
控制器格式：question-checks-v1；阶段：new_run。
恢复位置：探索/复核任务 `None`；单元 `None`，模型 `None`，反例 `None`，下一动作 `select`。
- Deferred read raft.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- Deferred read replication.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- Deferred read configuration.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- Deferred read config.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- The supplied documentation describes snapshots as enabling safe log removal, but the supplied interfaces do not specify atomic durability or restart recovery semantics for concrete stores.
- The supplied material shows snapshot orchestration and transmission but does not establish that the FSM snapshot represents exactly the state implied by snapReq.index.
- Client log admission and commit-to-FSM scheduling.
- Vote and pre-vote response ownership across campaign contexts.
- Configuration activation and quorum changes.
- Leadership transfer and authority-loss handling.
- Concrete FSM restore and follower snapshot-installation behavior.
- Initial reading left the leader loop, client dispatch, AppendEntries handling, configuration implementation, and snapshot installation ranges deferred.
- No precise asynchronous schedule replay capability is available.
- No concrete store implementation evidence was acquired for durability, listing order, Open, Close, or DeleteRange.
- Cannot localize an authorized mechanical repair; explicit semantic plan required: Question continuation preserves meaning; reinterpretation requires F2
- Requested inquiry material is deferred within its protected allowance; unmet requests remain in the receipt
- The supplied material does not establish whether InmemSnapshotStore is used in the target deployment or whether failed snapshot attempts may safely discard prior snapshots.
- Restart recovery and follower catch-up consumers remain unread.
- No claim is made about overall snapshot correctness or file-store crash durability.
- The in-memory replacement behavior is a concrete implementation suspicion, not a confirmed violation of G1 until store applicability and the legal recovery consumer are established.
- The existing O1 claim is not modified; the new O2 candidate covers failed replacement attempts, which O1 did not explicitly include.
- No execution, tool call, source mutation, or authentication action was performed.
- Explicit semantic/scope plan requested: The schema diagnostic requires adding three fields, converting alternatives to a string, and removing the extra judgment and analysis fields. The permitted representation repair operation supports value replacement only and provides no authorized deletion or parent-object replacement path, so this item cannot be made schema-valid without a deletion-capable repair operation.
- Structured response repair stopped after 3 attempts: Interface repair must retain prior negative analysis and limitations; only diagnosed metadata may change
- Deferred read file_snapshot_test.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- Deferred read inmem_snapshot_test.go: Unique material allowance or protected reserve is insufficient; the entire request remains pending
- Cannot localize an authorized mechanical repair; explicit semantic plan required: Coverage intent references unselected evidence or bindings
- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。
- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认实现义务/目标违反；合法性与后果证据不足时保留未决。

## 实际运行统计

累计执行时间：830.49 秒；预算计数：`{'experiments': 1, 'agent_calls': 19, 'audit_units': 2, 'targeted_reads': 2, 'exploration_rounds': 3, 'semantic_reviews': 2}`。
首个已保存模型前耗时：尚无模型；模型仍须通过实际工具检查。
审计单元 2；范围扩展 0；语义修订 0；校准 0。
完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。


## 材料、上下文与实际产物

字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。
唯一材料 115666/120000 字符；区间并集 18/40。广度当前可分配 346、为深度保留 3988；深度可分配 4334、为广度保留 0。
建模类执行记录 0；受理且非空 Bundle 回复 0；落盘模型版本 0（仅模型阶段 0，完整组件 0）；实际性质搜索记录 0（触达与校准另列）。

| 阶段 | 新调用记录 | 已记录时长（秒） |
| --- | --- | --- |
| agent_probe | 1 | 0.01（1 条有起止时间） |
| agent_capabilities | 1 | 0.02（1 条有起止时间） |
| java_probe | 1 | 0.10（1 条有起止时间） |
| verifier_probe | 1 | 0.15（1 条有起止时间） |
| implementation_tool_probe | 1 | 0.01（1 条有起止时间） |
| capability_probe | 1 | 13.47（1 条有起止时间） |
| read | 1 | 30.08（1 条有起止时间） |
| discover | 2 | 104.74（2 条有起止时间） |
| question | 2 | 87.54（2 条有起止时间） |
| explore | 6 | 299.31（6 条有起止时间） |
| semantic_review | 8 | 260.62（8 条有起止时间） |
延期读取 `initial-reading`：raft.go:468–760；预计新增 9827 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `initial-reading`：raft.go:1244–1602；预计新增 10282 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `initial-reading`：raft.go:1603–1955；预计新增 11459 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `initial-reading`：replication.go:388–665；预计新增 9009 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `initial-reading`：configuration.go:44–372；预计新增 10675 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `initial-reading`：config.go:99–376；预计新增 11176 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `df9096b753844a428264ca94e9b0e968`：raft.go:468–760；预计新增 9827 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `aa4476f08dca405188354ad873772bd3`：replication.go:388–665；预计新增 9009 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `e3937d9f2b15466a899d3fc228888875`：raft.go:468–760；预计新增 9827 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `e3937d9f2b15466a899d3fc228888875`：replication.go:388–665；预计新增 9009 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `e3937d9f2b15466a899d3fc228888875`：configuration.go:44–372；预计新增 10675 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `e3937d9f2b15466a899d3fc228888875`：config.go:99–376；预计新增 11176 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `3c36f4b6a6c84c97affb6a00b31aac27`：file_snapshot_test.go:1–346；预计新增 7602 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
延期读取 `3c36f4b6a6c84c97affb6a00b31aac27`：inmem_snapshot_test.go:1–190；预计新增 4159 字符；Unique material allowance or protected reserve is insufficient; the entire request remains pending
缓存复用/重附加记录 33 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。

| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |
| --- | --- | --- | --- | --- |
| read/d6041320 | accepted | 116224/116226 | 1294 | 0/0 |
| discover/c464782d | executed | 127254/127256 | 23261 | 0/0 |
| discover/84bcfd6e | accepted | 40692/40692 | 22752 | 0/0 |
| question/cf205d14 | executed | 124789/124791 | 25612 | 0/9 |
| explore/7cb0f917 | accepted | 111070/111072 | 24120 | 0/11 |
| explore/537c832e | accepted | 91864/91866 | 24120 | 0/14 |
| explore/e8cb53e7 | executed | 141883/141885 | 24120 | 0/9 |
| explore/fa343f9a | accepted | 69229/69231 | 22752 | 0/0 |
| semantic_review/b57abe96 | executed | 70269/70271 | 31063 | 0/14 |
| semantic_review/0ca4ffbf | executed | 28660/28662 | 22752 | 0/0 |
| semantic_review/bfac477d | executed | 55605/55607 | 22752 | 0/0 |
| semantic_review/c0decc34 | executed | 45242/45242 | 22752 | 0/0 |
| semantic_review/3f7388f8 | executed | 77106/77108 | 31063 | 0/13 |
| semantic_review/e660d0ae | executed | 29893/29893 | 22752 | 0/0 |
| semantic_review/cce2789b | executed | 62284/62286 | 22752 | 0/0 |
| semantic_review/20e85d95 | executed | 53427/53429 | 22752 | 0/0 |
| question/cd9a812b | executed | 89359/89361 | 25612 | 0/13 |
| explore/5bcffe4c | accepted | 85039/85041 | 24120 | 0/14 |
| explore/a49a49dd | executed | 170016/170018 | 24120 | 0/7 |
复核接口修复会话 0；实际 F2 语义修订 0。二者不互相替代。

## 范围接回、复核复用与里程碑

里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。
- initial_graph：2026-09-17T06:02:07.390344+00:00
同语义复核复用记录 0；上下文准备失败 0；未发送包不消耗实际探索/复核轮数。
读取计划：当前 receipt 有新源 4、纯缓存 6；修复无进展次数 0。round9 的 targeted_reads 按取得新源的逻辑计划计数，历史用量不重算；缓存发送仍消耗实际 agent 调用与时间。
技能加载 `d604132045fc40d286bea20a0f6cccf6`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'tasks/read.md']；仅以实际发送状态为准。
技能加载 `c464782da2b3439489dba369d1c1a6fb`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/discover.md']；仅以实际发送状态为准。
技能加载 `84bcfd6ee9574c3aa96b0d78575bed9b`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/discover.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `cf205d1447f74050853147c34af09406`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/question.md']；仅以实际发送状态为准。
技能加载 `7cb0f91709e845ae9a63191043fbaa13`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md']；仅以实际发送状态为准。
技能加载 `537c832e37bd48cb91978e6ed56c19e1`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md']；仅以实际发送状态为准。
技能加载 `e8cb53e7d7ce4cd7af9d5d8d5dc77d52`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md']；仅以实际发送状态为准。
技能加载 `fa343f9a142c4521a2acf7e3593ad827`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `b57abe9696224ddd93460a3e193e8c46`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md']；仅以实际发送状态为准。
技能加载 `0ca4ffbf10fd4a3fbd31ee0d5aec9318`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `bfac477d5d244fff9a62960521445266`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `c0decc3443f14b6a8d2aeeab51fa880a`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `3f7388f82de0471fa8a4668c33e5e99b`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md']；仅以实际发送状态为准。
技能加载 `e660d0ae1b0a4eb98b97ec181cd66fe5`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `cce2789bec384a08a8a2818bfb921a76`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `20e85d9534c14f489b0be092523d7a0f`：版本 question-checks-v1，['system.md', 'skills/evidence-review/SKILL.md', 'skills/evidence-review/guide.md', 'tasks/semantic_review.md', 'skills/consensus-analysis/references/graph-repair.md', 'tasks/retry.md']；仅以实际发送状态为准。
技能加载 `cd9a812b3f234fe89785e702dd0fa4d5`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/question.md']；仅以实际发送状态为准。
技能加载 `5bcffe4ccee541bcb8ce85b0a4583c3d`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md']；仅以实际发送状态为准。
技能加载 `a49a49dd95284b08903c762f28d2a308`：版本 question-checks-v1，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/responsibilities-and-behaviors.md', 'skills/consensus-analysis/references/behavior-obligations.md', 'tasks/explore.md']；仅以实际发送状态为准。
需接回且已取得新材料的计划 0；已接回 0；连接率 无可计算分母/历史未记录。这不是语义通过率或系统覆盖率。
实际发送包中源正文累计 767581 字符（跨调用重复发送会重复计入）；schema 累计 440521 字节。无真实 token/账单字段时不换算费用。