# 共识义务驱动局部审计报告

运行标识：`f870f77411d240958b16f18d86576f49`；模式：**真实工具运行**。

问题的重要性解释系统后果，义务决定检查重点，实际代码决定模型行为。关系图用于选择与扩展，不自动推出整体正确性。

分析入口：`autonomous`。regression 表示预设开发回归，不能计为自主发现验收。


## 义务与有界审计结论
尚无已受理的有界审计问题或结论。

## 本次流程进度

工具调用完成、分析产物被接受、性质得到证据支持是不同状态。恢复时重复的版本检查不是重复验证协议。

| 阶段 | 已记录的进度 |
| --- | --- |
| 材料阅读 | 已完成首轮阅读；保存 29 个片段 |
| 义务与代码关系 | 发现结果已被工作流接受；当前图有 0 项主张、0 个审计单元 |
| 直接实现检查 | 已保存 0 个制品；完成 0 次执行；不等于整体性质成立 |
| 局部模型 | 已保存 0 个模型版本；保存不代表检查通过 |
| 轨迹校准 | 0 条校准记录；不等同于性质判定 |
| 模型搜索 | 0 次执行记录；逐项结果见下方，未执行不计通过 |
| 性质证据 | 0 条直接证据；范围与层级见证据记录 |

若 agent 回复完成而目标发现仍未被接受，不能把该回复视为已成立的关系图。历史记录未保存具体拒绝原因时，报告不补造原因。

## 分析输入与探索范围

仓库：`/home/nitro/Desktop/hashicorp-raft`
提交：`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；分支：`detached / unavailable`；脏工作区：`False`。
快照：`2ca104e03ac74495b45f52634301f592`，纳入 88 个文件；读取 29 个材料片段，仍有未读范围的文件 82 个。完整清单见 [materials.json](materials.json)、[catalogue.json](catalogue.json) 和 [snapshot.json](snapshot.json)。
候选集合不代表全部正确性要求；原始材料和机器分析字段保留英文或原文。

## 义务与选择依据

领域引导采用同一流程；不使用‘完全无先验’或‘纯独立发现’标签。实际提供的引导与参考：
- `configured_reference`：未提供协议参考清单
定向补读：Read material；关联 []；实际新增片段 ['README.md:1:80', 'docs/README.md:1:80', 'api.go:1:80', 'transport.go:1:80', 'observer.go:1:80', 'log.go:1:80', 'config.go:1:80', 'fsm.go:1:80']。
定向补读：Prioritize client consequences, then obtain implementation evidence across all seven responsibility coordinates before deeper investigation. These eight nonoverlapping ranges contain 1024 new lines and avoid all cached intervals. A provisional estimate of 45 characters per line is 46080 unique characters, below the 52917-character breadth allowance; exact source accounting must preflight the batch and shorten or defer lower-priority ranges if necessary. Existing documentation and interface statements supply candidate expectations, while requested code supplies behavior; neither establishes correctness.；关联 []；实际新增片段 ['api.go:800:895', 'commitment.go:1:104', 'raft.go:285:441', 'raft.go:1203:1291', 'fsm.go:86:245', 'api.go:500:659', 'snapshot.go:125:278', 'file_snapshot.go:397:500']。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['file_snapshot.go:1:159', 'file_snapshot.go:160:396', 'file_snapshot.go:397:551']。
定向补读：When retention reclamation consumes file_snapshot_metadata_eligible, can an entry whose state fails Open validation displace an older readable snapshot, or does publication or reclamation establish a stronger replacement guarantee before deletion?；关联 ['file_snapshot_metadata_eligible', 'file_snapshot_discover', 'file_snapshot_reap', 'file_snapshot_open', 'file_snapshot_close_first']；实际新增片段 []。
定向补读：When reclamation consumes file_snapshot_metadata_eligible, does the applicable retention or recovery contract require preserving an openable fallback if a higher-ranked eligible entry fails Open? The observed reaper permits displacement without state validation; the remaining discriminator is whether that scenario lies within a claimed recovery guarantee and permitted fault context.；关联 ['file_snapshot_metadata_eligible', 'file_snapshot_discover', 'file_snapshot_reap', 'file_snapshot_open', 'file_snapshot_close_first']；实际新增片段 ['snapshot.go:1:100', 'api.go:600:760']。
定向补读：When reclamation consumes file_snapshot_metadata_eligible, does the applicable retention or recovery contract require preserving an openable fallback if a retained eligible entry fails Open? Startup retries only the entries returned by List, and fails if that nonempty list has no restorable entry when snapshot restoration is enabled. The remaining discriminator is whether an unusable retained prefix can arise within the supported publication and storage fault contract.；关联 ['file_snapshot_metadata_eligible', 'file_snapshot_discover', 'file_snapshot_reap', 'file_snapshot_open', 'file_snapshot_close_first']；实际新增片段 []。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['log.go:1:192', 'inmem_store.go:1:133', 'log_cache.go:1:95']。
定向补读：When LogCache uses the built-in InmemStore, can a concurrent lookup refill a slot after the recorded cache-clear event but before backend deletion, allowing a lookup started after successful deletion to return a deleted entry, or does synchronization or later validation prevent this?；关联 ['f_cache_clear_event', 'b_cache_delete_range', 'b_inmem_delete_range']；实际新增片段 []。
定向补读：Expand one source-grounded implementation surface；关联 []；实际新增片段 ['fsm.go:1:285']。
定向补读：When takeSnapshot consumes F_capture_returned, what ensures that the captured object, processing coordinates, and selected configuration describe a compatible recovery point, including when single and batch application paths process filtered entries or restoration precedes capture?；关联 ['F_capture_returned', 'B_fsm_single', 'B_fsm_batch', 'B_snapshot_capture', 'B_take_snapshot', 'runtime_restore_fsm']；实际新增片段 []。
定向补读：When takeSnapshot consumes F_capture_returned, do runtime restore completion handling and committed-tuple production ensure that its processing coordinates still identify the captured state and a compatible committed configuration, especially after a Restore error?；关联 ['F_capture_returned', 'B_fsm_single', 'B_fsm_batch', 'B_snapshot_capture', 'B_take_snapshot', 'runtime_restore_fsm']；实际新增片段 ['raft.go:1000:1450']。
定向补读：When takeSnapshot consumes F_capture_returned after runtime restoration, does the network InstallSnapshot path prevent a failed, potentially state-changing Restore from being followed by publication under unchanged worker coordinates, as the user-restore path attempts through fatal error handling?；关联 ['F_capture_returned', 'B_fsm_single', 'B_fsm_batch', 'B_snapshot_capture', 'B_take_snapshot', 'runtime_restore_fsm']；实际新增片段 ['raft.go:1750:2050']。

## 候选问题与已有保护

候选解释是有来源的分析判断，不是性质证据或协议正确性证明。
候选受阻分类：evidence_blocked=1；workflow_blocked=0；resource_blocked=1
候选因证据/适用合同不足延期；未解释关闭，未确认缺陷，不是性质证据。
- 候选 `b3042e8bbbb24408943079f7e046dbd5`：Fact ['file_snapshot_metadata_eligible']；生命周期 consumption；状态 blocked / needs_specific_evidence；受阻分类 evidence_blocked。
  问题：When reclamation consumes file_snapshot_metadata_eligible, must it preserve an openable fallback if retained metadata-eligible snapshots cannot be opened? The publication sequence is now known, but whether a permitted storage failure can leave an unusable retained prefix after older snapshots are reclaimed, and whether the applicable contract requires tolerating that failure, remain unresolved.；意义：If all snapshots returned by List are unusable, startup with snapshot restoration enabled returns an error. Reclamation may already have deleted older readable snapshots. This creates a potential recovery availability consequence, but neither a supported failure history nor a violated preservation guarantee has been established.。
  适用上下文：['FileSnapshotStore retention reclamation', 'First Close reaching reclamation', 'Startup with NoSnapshotRestoreOnStart false', 'Storage failure and concurrency contracts remain unspecified']；事件路径：['getSnapshots -> metadata ordering -> ReapSnapshots -> removal beyond retained prefix', 'Close -> finalize -> writeMeta -> Rename -> conditional parent-directory Sync -> ReapSnapshots', 'restoreSnapshot -> List -> tryRestoreSingleSnapshot -> Open -> retry next listed entry on failure', 'restoreSnapshot -> nonempty list exhausted without successful restoration -> error']；来源：['file_snapshot.go:1:159', 'file_snapshot.go:160:396', 'file_snapshot.go:397:500', 'file_snapshot.go:501:551', 'snapshot.go:1:100', 'api.go:600:760']。
  已有保护/反证：['Discovery excludes temporary directories, unreadable or undecodable metadata, and unsupported versions.', 'Finalization checks buffered Flush, enabled state-file Sync, state-file Close and Stat before recording size and CRC. These errors prevent that Close invocation from reaching reclamation.', 'writeMeta checks file creation, JSON encoding, buffered Flush and enabled metadata-file Sync before returning nil. Close requires this result before rename and automatic reclamation.', 'After rename, enabled non-Windows parent-directory synchronization must succeed before that Close invocation reaches reclamation.', 'Open reads the state file, validates its CRC and rewinds the handle before returning it. Startup retries another listed snapshot after Open or FSM restoration failure.', 'NoSnapshotRestoreOnStart bypasses Open and FSM restoration; the described startup failure requires restoration to be enabled.', 'Constructor comments require retain >= 1, and the interface describes available snapshots, but neither explicitly promises retention of a corruption-tolerant fallback.', 'The private noSync field is documented as testing-only; it does not establish an ordinary production configuration that disables synchronization.', "writeMeta ignores its deferred metadata-file Close result, unlike finalize's checked state-file Close. The supplied evidence does not establish that a close-only error after successful Sync permits loss of the retained snapshot.", 'The observed sequence synchronizes files and the parent directory but does not explicitly synchronize the snapshot directory itself. Its crash consequence depends on filesystem guarantees absent from the supplied materials.']；剩余判别与限制：['Whether the applicable storage and recovery contract requires an openable fallback under corruption, read failures or partial persistence, and which component owns that guarantee.', 'A justified crash or interference history that leaves the retained prefix unusable while an older snapshot would remain readable.', 'The selected platform and filesystem guarantees for file Sync, snapshot-directory entries, rename, parent-directory Sync and delayed Close errors.', 'Caller serialization and permitted concurrent access among explicit reclamation, creation and readers.', 'The concrete retention count and deployed store configuration.', 'Caller-level handling of startup restoration failure and any broader recovery procedure outside the attached restoration routine.']。
  选择/缩窄依据：The requested metadata-publication discriminator is resolved: encoding, Flush and enabled Sync errors stop publication, while deferred metadata Close errors are ignored. These observations narrow possible failure histories without establishing their legality or an applicable fallback requirement. The candidate therefore remains evidence-blocked.；历史问题版本：3。
  升级义务：未生成；候选结论或受阻原因：Continue the same metadata-eligibility consumption question and stop provisionally with its contract gap visible. The complete publication code supplies significant protections but cannot establish the missing storage fault contract. No exact next repository range is identified as assigning corruption-tolerant retention responsibility or specifying the needed filesystem semantics. An injected corruption test would demonstrate conditional behavior without resolving applicability, so no obligation or execution check is justified yet.。
- 候选 `e37681d1e571460d9a427f20a55e9f85`：Fact ['f_cache_clear_event']；生命周期 consumption；状态 explained / explained_by_existing_mechanism；受阻分类 无。
  问题：For LogCache wrapping InmemStore, can an overlapping GetLog repopulate an invalidated slot and cause a lookup begun after successful DeleteRange to return the deleted entry, in the absence of overlapping or subsequent writes?；意义：Stale post-deletion lookup results could misrepresent retained history to protocol consumers. This review addresses only the proposed lookup-driven cache refill; consensus and recovery consequences require separate consumer evidence.。
  适用上下文：['LogCache wrapping InmemStore; deployment selection remains unknown', 'Concurrent lookup and deletion without crash', 'Ordered deletion bounds for which the uint64 deletion loop terminates', 'No overlapping or subsequent StoreLog or StoreLogs operation, direct backend reinsertion, or external mutation of stored Log objects', 'The discriminating lookup begins after DeleteRange returns successfully']；事件路径：['DeleteRange replaces the cache slice under its exclusive lock, unlocks, then delegates backend deletion.', 'An overlapping GetLog may return a previously captured cache entry or read the backend before deletion, but neither path writes a cache slot.', 'After successful backend deletion, a newly begun lookup encounters an empty cache slot and InmemStore.GetLog returns ErrLogNotFound for the deleted index under the stated scope.']；来源：['log_cache.go:1:95', 'inmem_store.go:1:133', 'log.go:1:192']。
  已有保护/反证：['LogCache.GetLog only reads the cache and forwards misses directly to the backend; it never refills the cache. The proposed lookup-driven refill step has no implementation.', 'LogCache.DeleteRange replaces all slots while holding the cache lock. A lookup beginning after successful deletion cannot capture an entry from the replaced slice.', 'InmemStore.GetLog and DeleteRange use the same RWMutex. Successful terminating deletion removes the requested keys before returning.', 'An already overlapping lookup can return an old entry after deletion by retaining a previously captured pointer. This does not establish stale behavior for a lookup begun after deletion.', 'StoreLogs, unlike GetLog, populates cache slots after backend success using a separate cache critical section. The explanation does not cover overlapping writes.', 'The selected fact describes an invalidation event only; it does not promise continued cache emptiness or backend deletion completion.']；剩余判别与限制：['The attached LogStore interface does not specify a general concurrent-operation consistency contract.', 'Actual deployment selection of this adapter composition remains unknown; InmemStore is explicitly designated for testing.', 'Caller serialization and the applicability of overlapping StoreLogs and DeleteRange remain unestablished.', 'Protocol consumers and broader consequences of stale entries from other schedules remain unmapped.']。
  选择/缩窄依据：Comparing lookup and write paths resolves the selected discriminator: cache population belongs to StoreLogs, while GetLog misses do not populate the cache. Separate cache and backend critical sections therefore do not enable the proposed lookup-only refill schedule.；历史问题版本：1。
  升级义务：未生成；候选结论或受阻原因：All requested ranges are attached, with no deferred receipt items. Source review explains the selected lookup-refill suspicion because GetLog has no cache write. This is a bounded source-grounded disposition, not execution evidence or overall correctness. Overlapping writes and already-started reads remain explicit limitations; they are not silently included in the explanation. No obligation or further reading is necessary to resolve this discriminator.。
- 候选 `a4baad92835841ae9b99fb8c68304dd6`：Fact ['F_capture_returned']；生命周期 consumption；状态 active / needs_specific_evidence；受阻分类 resource_blocked。
  问题：When takeSnapshot consumes F_capture_returned after runtime restoration, does the network InstallSnapshot path prevent a failed, potentially state-changing Restore from being followed by publication under unchanged worker coordinates, as the user-restore path attempts through fatal error handling?；意义：Publishing partially restored application state under old processing coordinates could make later recovery skip required history. Configuration mismatch and subsequent compaction could compound that consequence. No such execution or consequence has been established.。
  适用上下文：['Single and batch FSM application variants', 'Snapshot capture and publication', 'User-requested runtime restoration', 'Network snapshot installation', 'Restore errors after possible application-state mutation']；事件路径：['processLogs -> ordered nonempty tuple batches -> runFSM -> snapshot capture', 'restoreUserSnapshot -> restoreFuture error -> caller panic', 'InstallSnapshot RPC -> unread restore handling -> possible subsequent capture -> takeSnapshot publication']；来源：['fsm.go:1:285', 'snapshot.go:125:278', 'raft.go:1000:1450']。
  已有保护/反证：['runFSM serializes application, Restore and Snapshot callbacks within one worker; their callback bodies do not interleave.', 'Successful restoration assigns worker coordinates from Open-returned metadata only after Restore returns nil.', 'restoreUserSnapshot explicitly panics on a restoreFuture error because the FSM may be in a bad state. Continued normal operation after that error cannot simply be assumed for this path.', 'restoreUserSnapshot rejects an outstanding configuration change, uses the current configuration and term, assigns an index greater than both the current and supplied indexes, and updates protocol positions only after successful restoration.', 'processLogs scans increasing indexes, appends only nonnil prepared tuples and dispatches only nonempty batches. This resolves the local empty-batch concern, but does not establish all caller ordering across restoration.', 'prepareLog filters no-ops and deprecated configuration entries and forwards LogConfiguration only for protocolVersion greater than 2. Worker coordinates therefore need not advance for every committed entry.', 'The single worker path skips coordinate advancement for unsupported configuration callbacks; the batch path records the final tuple coordinate, including barriers. This difference alone does not establish invalid captured contents.', 'takeSnapshot rejects a capture older than the returned committed configuration index and checks Create, Persist and Close before updating snapshot coordinates and compacting.', 'FSM and FSMSnapshot interface comments assign snapshot contents and concurrent Apply compatibility to the application implementation; callback success does not independently establish content correctness.']；剩余判别与限制：["The InstallSnapshot handler's restore request production, error handling and subsequent protocol behavior remain unread; the user-restore panic cannot be generalized to that path.", 'Whether a capture selected after a failed Restore can reach publication before any fatal handling or other protection takes effect.', 'How committed configuration advancement and configurationsFuture responses are ordered relative to tuple dispatch and restoration.', 'Whether all relevant processLogs callers serialize tuple production with restoration and prevent stale queued work from invalidating restored coordinates.', 'Whether the selected application implementation can partially mutate state before returning a Restore error, and whether captured objects remain valid during later Restore operations.', 'Which SnapshotStore implementation is selected and whether its metadata/content association and publication semantics support the proposed execution.']。
  选择/缩窄依据：The acquired range resolves two parts of the previous discriminator: processLogs constructs increasing, nonempty batches, and restoreUserSnapshot treats restore failure as fatal. However, processRPC exposes a distinct InstallSnapshot path whose completion policy is unread. Comparing that path is the smallest useful next step; the user-restore protection neither explains all runtime restoration nor establishes a defect.；历史问题版本：2。
  升级义务：未生成；候选结论或受阻原因：继续获取证据。

## 描述性理解演化

AuditSpec：v1 → v7；Behavior：10 → 33；Fact：6 → 18。
Surface 扩展任务：planned=3 / prepared=3 / sent=3 / semantic_result=3 / accepted=3；深度分析反馈任务：5（完成 3）。这些是描述性进度，不是正确性覆盖率。
- 扩展 ['FileSnapshotStore Create, List, Open and ReapSnapshots; FileSnapshotSink.writeMeta']：completed；Expand one source-grounded implementation surface
- 扩展 ['compactLogsWithTrailing and removeOldLogs']：completed；Expand one source-grounded implementation surface
- 扩展 ['NewRaft, restoreSnapshot and runtime FSM restore']：completed；Expand one source-grounded implementation surface
- 高后果 Surface `surface:ApplyLog and Barrier`：mapped；Enqueue paths are recovered; later acceptance and completion remain partial.
- 高后果 Surface `surface:dispatchLogs and commitment aggregation`：mapped；Local storage reporting and report aggregation are mapped; remote report establishment remains deferred.
- 高后果 Surface `surface:appendConfigurationEntry`：mapped；Observed dispatch and replacement sequence is mapped; validation and activation helpers remain unresolved.
- 高后果 Surface `surface:runFSM application and capture closures`：mapped；Callbacks and coordinate updates are mapped; tuple production and full worker scheduling are not.
- 高后果 Surface `surface:takeSnapshot and FileSnapshotSink.Close`：mapped；Coordinator and concrete sink actor are separated. Successful publication is distinguished from repeated Close return.
- 高后果 Surface `surface:FileSnapshotStore Create, List, Open and ReapSnapshots; FileSnapshotSink.writeMeta`：mapped；The acquired file covers this frontier and its directly connected sink lifecycle. Mapping preserves the distinctions between metadata eligibility, rename completion, checksum validation and terminal-call results; external consumers and crash semantics remain explicit unknowns.
- 高后果 Surface `surface:runCandidate and election helpers`：deferred；Candidate loop is acquired, but distinct vote producers, role-transition effects and persistent context need bounded expansion.
- 高后果 Surface `surface:AppendEntries, InstallSnapshot and heartbeat handling`：deferred；Transport declares replication and recovery operations and constructor registers a concurrent heartbeat path. Acceptance, persistence, response validation and interaction are unread.
- 高后果 Surface `surface:VerifyLeader, leadership transfer and user restore`：deferred；API or candidate-loop evidence identifies requests; leader-side completion and authority interpretation are unresolved.
- 高后果 Surface `surface:Caller FSM implementation`：externalized；Clients provide application state transitions and snapshot content. Library callback scheduling remains inside the boundary.
- 高后果 Surface `surface:Injected LogStore, StableStore and alternative SnapshotStore implementations`：deferred；Injection is established, but built-in implementations remain within the boundary and their failure semantics cannot be externalized by assumption.
- 高后果 Surface `surface:Raft.restoreSnapshot and Raft.tryRestoreSingleSnapshot`：mapped；The attached declarations establish initialization-owned selection, fallback, bypass and subsequent metadata updates. The restoration helper remains an unresolved callee rather than an asserted FSM-restoration guarantee.
- 高后果 Surface `surface:fsmRestoreAndMeasure implementation and failure-side effects`：deferred；The startup call site establishes invocation and result handling, but the helper implementation and FSM failure semantics are not attached.
- 高后果 Surface `surface:compactLogs and compactLogsWithTrailing deletion execution`：mapped；The attached sources establish bounds, no-op branches, error propagation, and available built-in deletion implementations. Backend activation and broader caller serialization remain unknown.
- 高后果 Surface `surface:removeOldLogs helper execution`：mapped；The helper reads LastIndex and delegates with zero trailing retention. Its own implementation is available independently of the unread restore callers.
- 高后果 Surface `surface:removeOldLogs restore callers and monotonic-store selection`：deferred；Recover the actual callers, their execution ownership, IsMonotonic checks, ordering with restoration and new log insertion, and handling of removal failure. The helper comment and optional interface describe intended use but do not establish those caller behaviors.
- 高后果 Surface `surface:LogCache.GetLog`：mapped；Attached source establishes pointer capture, validation after unlocking, hit copying, and miss delegation without cache filling.
- 高后果 Surface `surface:LogCache.StoreLog and LogCache.StoreLogs`：mapped；Attached source establishes single-entry delegation, backend-first batch storage, error handling, and separately locked pointer publication. Mapping does not resolve write/delete concurrency applicability.
- 高后果 Surface `surface:NewRaft startup initialization and snapshot adoption`：mapped；Supplied source supports startup sequencing, candidate fallback, bypass and metadata-adoption branches; helper and adapter internals remain explicit unknowns.
- 高后果 Surface `surface:runFSM runtime restore handler and fsmRestoreAndMeasure`：mapped；Supplied source shows callback execution, local position updates, response ordering and worker serialization.
- 高后果 Surface `surface:Runtime restore request production and completion consumption`：deferred；The supplied handler receives restoreFuture and calls respond, but source establishing who enqueues requests, which protocol metadata surrounds them, and what consumers infer from completion is absent.

## 实现理解（支持信息）

| Activity | 适用性 | 义务 | 证据 | 未知 |
| --- | --- | --- | --- | --- |
| A1 | applicable | [] | [] | ['Follower persistence and response meaning', 'Leader commit notification consumption'] |
| A2 | applicable | [] | [] | ['Vote identity validation', 'Election persistence', 'Leader lease and stepdown paths'] |
| A3 | applicable | [] | [] | ['SnapshotStore ordering, metadata consistency, integrity checks and concrete selected implementation are not established.', 'Runtime request producers and surrounding protocol completion are outside the supplied source.', 'Application FSM state after a failed Restore is unknown.'] |
| A4 | applicable | [] | [] | ['nextConfiguration validation', 'Outstanding-change admission', 'Committed configuration activation'] |
| A5 | applicable | [] | [] | ['Complete worker select loop', 'Tuple producer and ordering', 'Future synchronization'] |
| A6 | applicable | [] | [] | ['Actual adapter selection is not supplied.', 'Restore callers, their monotonic-store checks, and their handling of deletion failures are unread.', 'Persistent backend deletion atomicity and crash recovery are not established by the supplied interface.'] |
| A7 | applicable | [] | [] | ['Future resolution semantics', 'VerifyLeader result production', 'Retry and deduplication responsibility'] |
未解释责任：runCandidate and election helpers；Candidate loop is acquired, but distinct vote producers, role-transition effects and persistent context need bounded expansion.
未解释责任：AppendEntries, InstallSnapshot and heartbeat handling；Transport declares replication and recovery operations and constructor registers a concurrent heartbeat path. Acceptance, persistence, response validation and interaction are unread.
未解释责任：VerifyLeader, leadership transfer and user restore；API or candidate-loop evidence identifies requests; leader-side completion and authority interpretation are unresolved.
未解释责任：Injected LogStore, StableStore and alternative SnapshotStore implementations；Injection is established, but built-in implementations remain within the boundary and their failure semantics cannot be externalized by assumption.
未解释责任：fsmRestoreAndMeasure implementation and failure-side effects；The startup call site establishes invocation and result handling, but the helper implementation and FSM failure semantics are not attached.
未解释责任：removeOldLogs restore callers and monotonic-store selection；Recover the actual callers, their execution ownership, IsMonotonic checks, ordering with restoration and new log insertion, and handling of removal failure. The helper comment and optional interface describe intended use but do not establish those caller behaviors.
未解释责任：Runtime restore request production and completion consumption；The supplied handler receives restoreFuture and calls respond, but source establishing who enqueues requests, which protocol metadata surrounds them, and what consumers infer from completion is absent.

| 后续任务 | 类型 | 状态/步骤 | 原因与阻塞 |
| --- | --- | --- | --- |
| `b5c2e981` | 扩展职责/交接覆盖 | pending/read | Resolve decisive understanding gaps； |
| `f2210bd6` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `58df103f` | 扩展职责/交接覆盖 | completed/done | The inventory leaves startup selection and Open consumers unread. The attached source now identifies initialization-owned restoration: List supplies candidates, Open or FSM restoration failure advances to another listed candidate, successful restoration precedes snapshot/application/configuration updates, and exhaustion of a nonempty list returns an error. NoSnapshotRestoreOnStart is a distinct bypass branch. Record these reusable consumer behaviors and boundaries without strengthening metadata eligibility into readability. This enrichment does not change the selected Fact's meaning or the remaining retention-contract discriminator.； |
| `f76d0428` | 扩展职责/交接覆盖 | completed/done | The inventory still marks recovery consumers as unread. The attached startup code establishes a distinct initialization owner that consumes List's bounded metadata results, attempts Open and FSM restoration in order, retries failures, and errors after exhausting a nonempty list. NoSnapshotRestoreOnStart bypasses these attempts. Record these branches and appropriate consumer relationships without equating CRC validation with successful FSM restoration. This reusable omission does not change the current evidence-blocked disposition.； |
| `c28109f2` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `cb97f9ad` | 扩展职责/交接覆盖 | completed/done | The inventory mentions concurrent cache fills without separately mapping their execution owner. Add distinct lookup and write behaviors: GetLog reads a cached pointer or delegates a miss without filling; StoreLogs completes its backend write before acquiring the cache lock and publishing pointers. Preserve this asynchronous boundary and the possibility of an already captured lookup pointer surviving invalidation. This reusable decomposition does not change the selected invalidation-event fact or the completed lookup-only disposition; write/delete applicability remains unresolved.； |
| `63f03352` | 扩展职责/交接覆盖 | completed/done | Expand one source-grounded implementation surface； |
| `7419c9cd` | 扩展职责/交接覆盖 | pending/analyze | The inventory omits the now-observed user-restore producer: it rejects outstanding configuration changes, aborts inflight futures, publishes supplied contents under current configuration and a newly advanced coordinate, dispatches restoration, panics on restoration error, and updates protocol positions after success. Record this distinct producer and its branches without generalizing its protection to network installation. This adds reusable context without changing F_capture_returned's weak meaning or the continuing decision.； |
| `d84a6c2f` | 扩展职责/交接覆盖 | pending/analyze | Tuple production is now partially observed: processLogs iterates increasing indexes, prepares and filters entries, dispatches nonempty batches and advances Raft's lastApplied after dispatch rather than callback completion. prepareLog forwards configurations only when protocolVersion is greater than 2. Add the producer and protocol-version boundary while preserving unknown caller serialization and commitment establishment. These observations do not strengthen F_capture_returned.； |

| 复核对象/版本 | 层面 | 判断 | 材料与推导 |
| --- | --- | --- | --- |
尚无已执行的语义复核；有来源的候选不因此变成已确认规范。

职责清单之外仍可能有未知遗漏。未复核对象、未执行义务和受阻任务保留原状态；局部模型通过不能消除它们。

## 未受理草稿分析
尚未完成自主义务发现；未补入预置义务。

## 候选修复会话

原始候选、当前版本、修复 patch 与问题计数分开保存；调用完成不等于候选或语义已接受。

## 实验能力与执行

| 能力 | 状态 | 执行依据 |
| --- | --- | --- |
| package_build | probe_confirmed | 0beee6d2841f4efeaa1498bfbef6b28a：Offline package compilation; no protocol correctness or scheduling claim |
| precise_schedule_replay | unavailable | 无执行确认：No pre-established deterministic asynchronous or crash schedule control; generated experiments must demonstrate prerequisites |

默认 bubblewrap 模式隔离可写目录并隐藏用户主目录，保留现有网络命名空间；不声称网络隔离。若显式选择 workspace 模式，则只有工作副本隔离，不能称为安全沙箱。

| 执行及用途 | 执行记录状态 | 产物 / 后续处理 | 性质判定边界 | 原始输出与诊断 |
| --- | --- | --- | --- | --- |
| Codex 版本检查：agent_probe `9d70b5a5` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/9d70b5a540074a0f81b116087df20cdd/stdout.log) / [stderr.log](logs/9d70b5a540074a0f81b116087df20cdd/stderr.log) |
| Codex 参数检查：agent_capabilities `930848ee` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/930848eecdf448a88500ff096bda2c21/stdout.log) / [stderr.log](logs/930848eecdf448a88500ff096bda2c21/stderr.log) |
| Java 版本检查：java_probe `243e2a53` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/243e2a5366c94afb8300ce92cb561209/stdout.log) / [stderr.log](logs/243e2a5366c94afb8300ce92cb561209/stderr.log) |
| 验证工具启动检查：verifier_probe `9479426a` | 正常完成 | 版本帮助已识别，工具可用；命令退出码 1 | 不适用：未检查性质 | [stdout.log](logs/9479426aea934a97aa2e7fbed92694e9/stdout.log) / [stderr.log](logs/9479426aea934a97aa2e7fbed92694e9/stderr.log) |
| 目标工具链版本检查：implementation_tool_probe `722f4952` | 正常完成 | 命令完成；版本或能力详情见原始输出 | 不适用：未检查性质 | [stdout.log](logs/722f49524c874809803839a5b96b2890/stdout.log) / [stderr.log](logs/722f49524c874809803839a5b96b2890/stderr.log) |
| 现有测试与实验能力探测：capability_probe `0beee6d2` | 正常完成 | 不适用 | 仅限实际测试覆盖；不自动证明目标或确认违反 | [stdout.log](logs/0beee6d2841f4efeaa1498bfbef6b28a/stdout.log) / [stderr.log](logs/0beee6d2841f4efeaa1498bfbef6b28a/stderr.log)；原因（原文）：Compile probe only |
| Agent 分析或修复：agent `73dcad52` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/73dcad52c7954154872b2902e9641280/stdout.log) / [stderr.log](logs/73dcad52c7954154872b2902e9641280/stderr.log) / [response.json](agent/2f7b8fc8a06d45e7b236adf779f5a6e8-read/response.json) |
| Agent 分析或修复：agent `84af9009` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/84af90097e4b4be9ac953e53e9edc7c6/stdout.log) / [stderr.log](logs/84af90097e4b4be9ac953e53e9edc7c6/stderr.log) / [response.json](agent/3a89b5ee54ee4621bd56c84af3cb2440-discover/response.json) |
| 职责覆盖探索：agent `b28638cf` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/b28638cfab1e4f0bbe46ff1f3eee529f/stdout.log) / [stderr.log](logs/b28638cfab1e4f0bbe46ff1f3eee529f/stderr.log) / [response.json](agent/33b83b5d963b4d508b04e0254b5ce4c7-spec_refine/response.json) |
| 职责覆盖探索：agent `737db942` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/737db942b41b463d993d468ad49ecfd6/stdout.log) / [stderr.log](logs/737db942b41b463d993d468ad49ecfd6/stderr.log) / [response.json](agent/39b0d652d0254fe082924623bf5513c2-spec_refine/response.json) |
| Agent 分析或修复：agent `a5a7b7e6` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/a5a7b7e61dd64b02b563257213ee721f/stdout.log) / [stderr.log](logs/a5a7b7e61dd64b02b563257213ee721f/stderr.log) / [response.json](agent/1d57e7a9d38b4a09a8db042daa985b85-derive/response.json) |
| Agent 分析或修复：agent `47a54cc4` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/47a54cc484774e03867ef8709956aa88/stdout.log) / [stderr.log](logs/47a54cc484774e03867ef8709956aa88/stderr.log) / [response.json](agent/0d859367746b44f8b33a4745708c3d51-derive/response.json) |
| Agent 分析或修复：agent `85559a22` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/85559a22f0174d46ade60cf63b082553/stdout.log) / [stderr.log](logs/85559a22f0174d46ade60cf63b082553/stderr.log) / [response.json](agent/84f0deacf4cb41b9b07eaa7792b57e0f-derive/response.json) |
| Agent 分析或修复：agent `5751a79d` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/5751a79d184348d9914a618781ae1bf4/stdout.log) / [stderr.log](logs/5751a79d184348d9914a618781ae1bf4/stderr.log) / [response.json](agent/5389eab56229451f832babf7b996a42a-derive/response.json) |
| 职责覆盖探索：agent `fdebd087` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/fdebd0871cd1413eb8f9cc7b6cfe2a4d/stdout.log) / [stderr.log](logs/fdebd0871cd1413eb8f9cc7b6cfe2a4d/stderr.log) / [response.json](agent/c48084f95001460382c5be479e643026-spec_refine/response.json) |
| 职责覆盖探索：agent `c3f4ef5b` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/c3f4ef5bee6d40f3bce0aaed836f9446/stdout.log) / [stderr.log](logs/c3f4ef5bee6d40f3bce0aaed836f9446/stderr.log) / [response.json](agent/d39cb10bf50e4df7bb9bbe294b55ee62-spec_refine/response.json) |
| 职责覆盖探索：agent `e6a451ff` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/e6a451ff3246467c9ef94624866df8d8/stdout.log) / [stderr.log](logs/e6a451ff3246467c9ef94624866df8d8/stderr.log) / [response.json](agent/699e08c98edd4735bedd43c1234a9851-spec_refine/response.json) |
| 职责覆盖探索：agent `5dc57b4f` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/5dc57b4ff11843d19cd163c8ff602316/stdout.log) / [stderr.log](logs/5dc57b4ff11843d19cd163c8ff602316/stderr.log) / [response.json](agent/df52578e479a431a9ae80b1d97bd77fc-spec_refine/response.json) |
| Agent 分析或修复：agent `1bac66b3` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/1bac66b356e940f5bc9f169a92bfc7bb/stdout.log) / [stderr.log](logs/1bac66b356e940f5bc9f169a92bfc7bb/stderr.log) / [response.json](agent/14fe4077cc424bcf85de849fabcdfc7d-derive/response.json) |
| Agent 分析或修复：agent `be40509a` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/be40509a36a14ceabd6a9d1b04212409/stdout.log) / [stderr.log](logs/be40509a36a14ceabd6a9d1b04212409/stderr.log) / [response.json](agent/9a06503f24454a13b6c5000f862d65c1-derive/response.json) |
| 职责覆盖探索：agent `1437a9b0` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/1437a9b051d8495db858614f0d03005b/stdout.log) / [stderr.log](logs/1437a9b051d8495db858614f0d03005b/stderr.log) / [response.json](agent/9c2155df78594a0ea04e47b672b219da-spec_refine/response.json) |
| 职责覆盖探索：agent `0e78b198` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/0e78b198095d47658b7ed9b4752e21a8/stdout.log) / [stderr.log](logs/0e78b198095d47658b7ed9b4752e21a8/stderr.log) / [response.json](agent/1ba2af68e45d4857a5aa12cd6140d0d8-spec_refine/response.json) |
| 职责覆盖探索：agent `f5775ac6` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/f5775ac65d8a4c60b7d3fbb25732b7d8/stdout.log) / [stderr.log](logs/f5775ac65d8a4c60b7d3fbb25732b7d8/stderr.log) / [response.json](agent/f682e9de9f3c4189bac5c18efb23d7a8-spec_refine/response.json) |
| Agent 分析或修复：agent `31173bab` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/31173bab9c04464ea7f8963fcd70c934/stdout.log) / [stderr.log](logs/31173bab9c04464ea7f8963fcd70c934/stderr.log) / [response.json](agent/8dc5a4b4c628449783c5394449c11e1f-derive/response.json) |
| Agent 分析或修复：agent `fcf213c8` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/fcf213c831324a80a8e43e578195bf0a/stdout.log) / [stderr.log](logs/fcf213c831324a80a8e43e578195bf0a/stderr.log) / [response.json](agent/493d9013d5204ae0aac63cb5cf312867-derive/response.json) |
| Agent 分析或修复：agent `11878e5d` | 正常完成 | 结构化回复已返回；不代表关系图或模型已被接受 | 不适用：生成候选分析，不是验证 | [stdout.log](logs/11878e5dc864464297097d17eca90ea8/stdout.log) / [stderr.log](logs/11878e5dc864464297097d17eca90ea8/stderr.log) / [response.json](agent/f3211512596f47d1829c52f60b7bf6c9-derive/response.json) |

逐项 checker 结果（仅汇总直接证据，不沿义务关系传播）：

## 模型、校准与证据范围

尚未生成并执行局部模型；没有模型层检查结论。

## 候选发现与 F1—F4

本次尚无记录的候选违反。这不代表实现没有缺陷。
本次没有实际应用的语义修订；工具错误不冒充 F1—F4。

## 未决事项与停止原因

停止原因（原文）：Budget exhausted: agent_calls
控制器格式：selected-question-v7；阶段：new_run。
恢复位置：探索/复核任务 `None`；单元 `None`，模型 `None`，反例 `None`，下一动作 `select`。
- Only file_snapshot.go is interpreted; no tests, caller behavior or external filesystem guarantees were examined.
- The mapped surface indicates recovered local behavior, not complete protocol coverage or verified correctness.
- Snapshot metadata types, supported-version constants, encodePeers and recovery consumers remain outside the supplied source.
- No defect or required retention, retry or durability guarantee is established by this descriptive refinement.
- No normative retention requirement or implementation violation is established.
- FileSnapshotStore-specific consumer edges are conditional on adapter selection.
- The helper implementation, bypass preparation contract and concurrent filesystem guarantees remain unresolved.
- Existing historical unknown strings on unchanged objects are not rewritten; the added behaviors supply the newly sourced startup consumer detail.
- The restoration helper implementation and its failure-side effects are not attached.
- The actual selected SnapshotStore and the preparation contract for NoSnapshotRestoreOnStart remain unresolved.
- This descriptive correction supplies no execution evidence and does not resolve the current evidence-blocked candidate.
- Other stale descriptions outside the targeted objects remain outside this focused delta.
- Only the four attached source ranges support this refinement; no execution or correctness check was performed.
- Restore caller ownership, monotonic-store activation, and serialization remain deferred.
- No claim is made that interface acknowledgement establishes crash durability, globally empty storage, or exclusion of concurrent cached reads.
- This is descriptive decomposition, not a confirmed defect or correctness result.
- Actual caller concurrency contracts and write/delete applicability remain unresolved.
- No additional reading is needed for this decomposition because the complete relevant LogCache implementation is attached.
- Only the two attached source ranges support this refinement; no tools or additional reads were used.
- FSM interface comments supply callback expectations, while the observed nil returns establish only reported callback success.
- Concrete storage behavior, configuration-option contracts, setter internals and runtime restore producers and consumers remain unresolved.
- No correctness claim, executable check, calibration or reproduction is established.
- Budget exhausted: agent_calls
- 活性、公平性、最终同步及未纳入的交互，不从有限安全性检查推断成立。
- 当前实现不会仅凭 agent 声称或生成测试断言，将模型候选升级为已确认局部或更广泛义务违反；合法性与后果证据不足时保留未决。

## 实际运行统计

累计执行时间：1728.78 秒；预算计数：`{'experiments': 1, 'agent_calls': 20, 'exploration_rounds': 3, 'targeted_reads': 6}`。
首个已保存模型前耗时：尚无模型；模型仍须通过实际工具检查。
审计单元 0；范围扩展 0；语义修订 0；校准 0。
完整命令、时间、版本与制品关联见 [state.json](state.json)，历史检查点见 `history/`，事件见 [events.jsonl](events.jsonl)。


## 材料、上下文与实际产物

字符口径为唯一源代码逻辑行（含一个换行分隔符），不等于每次发送量、token 或费用。未提供 token 数据时不推算账单。
唯一材料 106162/120000 字符；区间并集 19/40。广度当前可分配 13838、为深度保留 0；深度可分配 13838、为广度保留 0。
建模类执行记录 0；受理且非空 Bundle 回复 0；落盘模型版本 0（仅模型阶段 0，完整组件 0）；实际性质搜索记录 0（触达与校准另列）。

| 阶段 | 新调用记录 | 已记录时长（秒） |
| --- | --- | --- |
| agent_probe | 1 | 0.03（1 条有起止时间） |
| agent_capabilities | 1 | 0.03（1 条有起止时间） |
| java_probe | 1 | 0.09（1 条有起止时间） |
| verifier_probe | 1 | 0.16（1 条有起止时间） |
| implementation_tool_probe | 1 | 0.01（1 条有起止时间） |
| capability_probe | 1 | 12.29（1 条有起止时间） |
| read | 1 | 61.02（1 条有起止时间） |
| discover | 1 | 278.52（1 条有起止时间） |
| spec_refine | 9 | 800.26（9 条有起止时间） |
| derive | 9 | 543.19（9 条有起止时间） |
缓存复用/重附加记录 11 个；部分重叠只计增量。完整逐项状态及申请原文见 state.json 的 read_plans。

| 任务/包 | 状态 | prompt 字符/字节 | wire schema 字符 | 材料重复出现/省略数 |
| --- | --- | --- | --- | --- |
| read/c6213fe5 | accepted | 119031/119031 | 1294 | 0/0 |
| discover/20b027a8 | accepted | 89242/89242 | 13645 | 0/0 |
| spec_refine/93bb27b0 | accepted | 30307/30307 | 14584 | 0/0 |
| spec_refine/17c1cbb9 | accepted | 47542/47542 | 14584 | 0/0 |
| derive/cf36ded3 | accepted | 42524/42526 | 16573 | 0/0 |
| derive/86b60f58 | accepted | 65507/65509 | 16573 | 0/0 |
| derive/bc67c5a4 | accepted | 87767/87769 | 16573 | 0/0 |
| derive/dbe39cc4 | accepted | 89264/89266 | 16573 | 0/0 |
| spec_refine/83d9ae76 | accepted | 73100/73100 | 14584 | 0/0 |
| spec_refine/87692a71 | accepted | 83554/83554 | 14584 | 0/0 |
| spec_refine/8b276bef | accepted | 27770/27770 | 14584 | 0/0 |
| spec_refine/8a7fc587 | accepted | 49173/49173 | 14584 | 0/0 |
| derive/d68fb499 | accepted | 48692/48694 | 16573 | 0/0 |
| derive/290cc143 | accepted | 66742/66756 | 16573 | 0/0 |
| spec_refine/9310f1eb | accepted | 85205/85205 | 14584 | 0/0 |
| spec_refine/ef164161 | accepted | 29866/29866 | 14584 | 0/0 |
| spec_refine/1fd9065e | accepted | 48459/48459 | 14584 | 0/0 |
| derive/f658c11e | accepted | 52490/52492 | 16573 | 0/0 |
| derive/76d6da00 | accepted | 73978/73980 | 16573 | 0/0 |
| derive/006d6731 | accepted | 94263/94265 | 16573 | 0/0 |
| derive/e99d3381 | prepared | 107243/107245 | 16573 | 0/0 |
复核接口修复会话 0；实际 F2 语义修订 0。二者不互相替代。

## 范围接回、复核复用与里程碑

里程碑是本次记录首次出现该事实的时间；缺失不是零耗时。离线、mock 与真实自主运行不合并比较。
- initial_graph：2026-09-20T08:37:46.769543+00:00
同语义复核复用记录 0；上下文准备失败 0；未发送包不消耗实际探索/复核轮数。
读取计划：当前 receipt 有新源 8、纯缓存 4；修复无进展次数 0。targeted_reads 按取得新源的逻辑计划计数，历史用量不重算；缓存发送仍消耗实际 agent 调用与时间。
技能加载 `c6213fe54856438abca31e9325ccfd0e`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/references/activity-classes.md', 'tasks/read.md']；仅以实际发送状态为准。
技能加载 `20b027a81e594d84a6e332d5a9b17add`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/discover.md']；仅以实际发送状态为准。
技能加载 `93bb27b042594e9b9bdcb38a4c20bd4a`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `17c1cbb92d6844c99a0add9b32f6df9c`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `cf36ded34acb4c868a7e540faadfc62d`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `86b60f58a8e349e6ac057d5e67edb50b`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `bc67c5a4b6ce4f2baaf7e8fd26b7f34d`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `dbe39cc474c94db69461c375c5e2229a`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `83d9ae768e364c098fe7cd0011ba2c5e`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `87692a712bc84a2d9909e0e3f785fe80`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `8b276bef4b9048069703bcbc6d206e72`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `8a7fc587a543417e8d52b4d66d0cc188`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `d68fb4991f3d47af838981c74c015f11`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `290cc143f5e141ec87b065e68752cb3f`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `9310f1ebc3be4435860fa772a514a3d6`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `ef1641613d634e71a30cb13d994643fe`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `1fd9065ebd1e4a6d8b20aaed2b6b39e8`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/spec_refine.md']；仅以实际发送状态为准。
技能加载 `f658c11e77ed4ef38231789de1526823`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `76d6da00d9d344149d12ac6bc29aa1cf`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `006d6731ca18456e990df781552d2ae1`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
技能加载 `e99d3381f0224e3d9f8b342a9f5bcc0e`：版本 selected-question-v7，['system.md', 'skills/consensus-analysis/references/graph-repair.md', 'skills/consensus-analysis/SKILL.md', 'skills/consensus-analysis/guide.md', 'skills/consensus-analysis/references/activity-classes.md', 'skills/consensus-analysis/references/behavior-facts.md', 'tasks/derive.md']；仅以实际发送状态为准。
需接回且已取得新材料的计划 0；已接回 0；连接率 无可计算分母/历史未记录。这不是语义通过率或系统覆盖率。
实际发送包中源正文累计 260448 字符（跨调用重复发送会重复计入）；schema 累计 295352 字节。无真实 token/账单字段时不换算费用。