# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。本轮有 2 项已产生观察的正式问题：已确认违反 2 项、有限检查未见违反 0 项、待调查线索 0 项；另有源码解释 0 项、探索执行 2 次。正式义务共 2 项，执行次数不等于问题数。

实际持续 **40.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、27 次 Agent 调用、12 次控制器目标执行。源码调查能力：无剩余预算。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 2400.0 | 2400.16 | 0.00 |
| Agent 调用 | 40 | 13 | 27 |
| 控制器目标执行 | 16 | 4 | 12 |
| 新 Unit | 6 | 2 | 4 |
| 语义复核 | 10 | 2 | 8 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 2 次＋探索 2 次，其中失败／未完成 0 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v41`；展示版本 `audit-products-v41`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；timeout_limit=`total_seconds`；timeout_seconds=`27.257133758008422`。
[调用记录](logs/032475a665b74e82b264ce4c74379545/check.json)；[stdout](logs/032475a665b74e82b264ce4c74379545/stdout.log)；[stderr](logs/032475a665b74e82b264ce4c74379545/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
单轮超时，具体原因未知。

## 主要结果

| 问题 | 当前结果 | 实际回答摘录 | 证据 |
| --- | --- | --- | --- |
| 1. After a committed JointImplicit change is applied while a leadership transfer is active, does Raft retain or regenerate the…（原文摘录） | 已确认违反 | The fixed direct check observed a complete forbidden recurring idle cycle after transfer timeout while the control automatically exited. Source-and-state review supports… | [claim-autoleave-continuation](state.json) |
| 2. Does Node preserve its guarantee that a configuration proposal is dropped unless there is no prior unapplied configuration, when…（原文摘录） | 已确认违反 | Fresh fixed execution reproduced second-configuration admission while first ApplyConfChange remained pending under Node early Advance. Withholding Advance produced… | [claim-node-conf-admission](state.json) |

### 1. After a committed JointImplicit change is applied while a leadership transfer is active, does Raft retain or regenerate the…（原文摘录）

**已确认违反**。要求原文：When Raft owns automatic exit from an applied implicit joint configuration, temporary rejection of its exit proposal during leadership transfer must not leave the automatic transition dependent on an unrelated application proposal after that transfer aborts. A continuing eligible leader with a responsive joint quorum and completed preceding application must retain or regenerate protocol-driven work that can propose and complete the exit.

决定性范围：Automatic exit continuation on a stable continuing leader after transfer timeout, with the joint change committed and applied, previous persistence/application drained, a responsive quorum in both voter sets, and no new application proposals required for automatic progress.
Non-Byzantine messages originate from actual nodes.；Caller serializes RawNode operations, persists before messages, applies committed configuration in order, and advances after application.；Leader remains eligible; live voter quorum processes messages and ticks; transfer target can remain unavailable.。

排除：An arbitrary numeric tick deadline for general eventual liveness.；Guarantees while quorum is unavailable or caller withholds required storage/application completion.；Safety violations, client-visible outages, or all possible configuration shapes.；Manual JointExplicit transitions.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：The fixed direct check observed a complete forbidden recurring idle cycle after transfer timeout while the control automatically exited. Source-and-state review supports recurrence without omitted random or protocol inputs in this specific heartbeat schedule. A post-result client proposal restores progress, supporting the missed continuation mechanism while limiting consequences.

制品 v1；机械比较 **观察到违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/b7d8e0dc844a409c80e01082b4f55380/assurance_generated_test.go)；[条件与检查器](direct-checks/b7d8e0dc844a409c80e01082b4f55380/plan.json)；[原始观察](logs/97aac198d2bc4b10be4e3104e70bb614/stdout.log)；[assessment](direct-checks/b7d8e0dc844a409c80e01082b4f55380/97aac198d2bc4b10be4e3104e70bb614-assessment.json)；[对应性复核](submissions/10c314d06ec64721b9c92a238744a691/accepted.json)

固定比较 `autoleave-cycle`：观察到违反；已比较 2 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） |
| --- | --- | --- |
| scenario | control | transfer_timeout |
| joint_index | 3 | 3 |
| event | cycle_result | cycle_result |
| stranded_cycle | false | true |
| applied | 4 | 3 |
| auto_leave | false | true |
| closed_cycle | true | true |
| commit | 4 | 3 |
| drained | true | true |
| exit_entries | 1 | 0 |
| heartbeat_delta | 10 | 10 |
| last_index | 4 | 3 |
| live_quorum | true | true |
| outgoing | 0 | 3 |
| pending_conf_index | 4 | 3 |
| protocol_state | {"1":{"asyncStorageWrites":false,"prevHardSt":{"Commit":4,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":2},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":1,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":4,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":4,"applying":4,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":4,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2},{"Data":null,"Index":4,"Term":2,"Type":2}],"hardState":{"Commit":4,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":5,"offsetInProgress":5,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":17,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":2,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":false,"Learners":{"4":{}},"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},null]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":4,"MsgAppFlowPaused":false,"Next":5,"PendingSnapshot":0,"RecentActive":true,"State":1,"sentCommit":0},"2":{"Inflights":{"buffer":[{"bytes":0,"index":4}],"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":4,"MsgAppFlowPaused":false,"Next":5,"PendingSnapshot":0,"RecentActive":true,"State":1,"sentCommit":4},"3":{"Inflights":{"buffer":[{"bytes":0,"index":4}],"bytes":0,"count":1,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":3,"MsgAppFlowPaused":false,"Next":5,"PendingSnapshot":0,"RecentActive":false,"State":1,"sentCommit":3},"4":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":true,"Match":0,"MsgAppFlowPaused":true,"Next":3,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]},"2":{"asyncStorageWrites":false,"prevHardSt":{"Commit":4,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":0},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":2,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":0,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":4,"applying":4,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":4,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2},{"Data":null,"Index":4,"Term":2,"Type":2}],"hardState":{"Commit":4,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":5,"offsetInProgress":5,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":13,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":0,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":false,"Learners":{"4":{}},"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},null]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"2":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":1,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"3":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"4":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":true,"Match":0,"MsgAppFlowPaused":false,"Next":3,"PendingSnapshot":0,"RecentActive":true,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]},"3":{"asyncStorageWrites":false,"prevHardSt":{"Commit":2,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":0},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":3,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":0,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":2,"applying":2,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":2,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2}],"hardState":{"Commit":2,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":4,"offsetInProgress":4,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":17,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":0,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},null]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"2":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"3":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":1,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]}} | {"1":{"asyncStorageWrites":false,"prevHardSt":{"Commit":3,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":2},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":1,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":3,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":3,"applying":3,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":3,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2}],"hardState":{"Commit":3,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":4,"offsetInProgress":4,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":14,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":2,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":true,"Learners":{"4":{}},"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},{"1":{},"2":{},"3":{}}]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":3,"MsgAppFlowPaused":false,"Next":4,"PendingSnapshot":0,"RecentActive":true,"State":1,"sentCommit":0},"2":{"Inflights":{"buffer":[{"bytes":8,"index":3}],"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":3,"MsgAppFlowPaused":false,"Next":4,"PendingSnapshot":0,"RecentActive":true,"State":1,"sentCommit":3},"3":{"Inflights":{"buffer":[{"bytes":8,"index":3}],"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":3,"MsgAppFlowPaused":false,"Next":4,"PendingSnapshot":0,"RecentActive":false,"State":1,"sentCommit":3},"4":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":true,"Match":0,"MsgAppFlowPaused":true,"Next":3,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]},"2":{"asyncStorageWrites":false,"prevHardSt":{"Commit":3,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":0},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":2,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":0,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":3,"applying":3,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":3,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2}],"hardState":{"Commit":3,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":4,"offsetInProgress":4,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":10,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":0,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":true,"Learners":{"4":{}},"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},{"1":{},"2":{},"3":{}}]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"2":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":1,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"3":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"4":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":true,"Match":0,"MsgAppFlowPaused":false,"Next":3,"PendingSnapshot":0,"RecentActive":true,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]},"3":{"asyncStorageWrites":false,"prevHardSt":{"Commit":2,"Term":2,"Vote":1},"prevSoftSt":{"Lead":1,"RaftState":0},"raft":{"Term":2,"Vote":1,"checkQuorum":true,"disableConfChangeValidation":false,"disableProposalForwarding":false,"electionElapsed":0,"electionTimeout":10,"heartbeatElapsed":0,"heartbeatTimeout":1,"id":3,"isLearner":false,"lead":1,"leadTransferee":0,"maxMsgSize":4096,"maxUncommittedSize":18446744073709551615,"msgs":null,"msgsAfterAppend":null,"pendingConfIndex":0,"pendingReadIndexMessages":null,"preVote":false,"raftLog":{"applied":2,"applying":2,"applyingEntsPaused":false,"applyingEntsSize":0,"committed":2,"maxApplyingEntsSize":4096,"storage":{"Mutex":{"_":{},"mu":{"sema":0,"state":0}},"ents":[{"Data":null,"Index":1,"Term":1,"Type":0},{"Data":null,"Index":2,"Term":2,"Type":0},{"Data":[8,1,18,4,8,3,16,4],"Index":3,"Term":2,"Type":2}],"hardState":{"Commit":2,"Term":2,"Vote":1},"snapshot":{"Data":null,"Metadata":{"ConfState":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[1,2,3],"VotersOutgoing":null},"Index":1,"Term":1}}},"unstable":{"entries":null,"offset":4,"offsetInProgress":4,"snapshot":null,"snapshotInProgress":false}},"randomizedElectionTimeout":14,"readOnly":{"option":0,"pendingReadIndex":{},"readIndexQueue":null},"readStates":null,"state":0,"stepDownOnRemoval":false,"trk":{"Config":{"AutoLeave":false,"Learners":null,"LearnersNext":null,"Voters":[{"1":{},"2":{},"3":{}},null]},"MaxInflight":256,"MaxInflightBytes":18446744073709551615,"Progress":{"1":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"2":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":0,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0},"3":{"Inflights":{"buffer":null,"bytes":0,"count":0,"maxBytes":18446744073709551615,"size":256,"start":0},"IsLearner":false,"Match":1,"MsgAppFlowPaused":false,"Next":2,"PendingSnapshot":0,"RecentActive":false,"State":0,"sentCommit":0}},"Votes":{}},"uncommittedSize":0},"stepsOnAdvance":[]}} |
| repeated | true | true |
| role | StateLeader | StateLeader |
| term | 2 | 2 |
| transfer_target | 0 | 0 |

前提关联：观察 1 → matched；观察 2 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 2. Does Node preserve its guarantee that a configuration proposal is dropped unless there is no prior unapplied configuration, when…（原文摘录）

**已确认违反**。要求原文：For callers complying with Node Ready/Advance ordering, a second proposed configuration change must not be appended as a configuration entry while an earlier committed configuration change has not yet been applied through ApplyConfChange (and has not been rejected by the application). The documented early Advance optimization does not itself apply the earlier configuration.

决定性范围：Node-level configuration-proposal admission under documented early Advance, with persisted committed first change, delayed but ordered ApplyConfChange, and configuration validation enabled.
Node interface early Advance permission applies to a Ready containing configuration entries; no captured exception restricts it to data entries.；Prior configuration is intended to apply, not cancelled.；Target runs serialized Node loop; caller uses no direct state mutations.。

排除：RawNode callers interpreting Advance as completed application.；Consensus safety failure, voter-set replacement, crash recovery and client completion.；Configurations proposed with DisableConfChangeValidation enabled.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Fresh fixed execution reproduced second-configuration admission while first ApplyConfChange remained pending under Node early Advance. Withholding Advance produced EntryNormal; applying first legitimately admitted the second. All histories completed ordered application. The reviewed discrepancy is local Node admission under its documented contract, not a demonstrated consensus safety failure.

制品 v1；机械比较 **观察到违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/776c4b0e83dc4f22b460d1207adcaff0/assurance_generated_test.go)；[条件与检查器](direct-checks/776c4b0e83dc4f22b460d1207adcaff0/plan.json)；[原始观察](logs/0658bc3db0044fef9d8fa246d1dff118/stdout.log)；[assessment](direct-checks/776c4b0e83dc4f22b460d1207adcaff0/0658bc3db0044fef9d8fa246d1dff118-assessment.json)；[对应性复核](submissions/5e956938ea9945c4b28abae18f307c14/accepted.json)

固定比较 `node-conf-admission`：观察到违反；已比较 3 项，完整见证 1 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2（违反见证） | 观察 3 |
| --- | --- | --- | --- |
| scenario | hold_advance | early_advance | apply_then_advance |
| first_index | 3 | 3 | 3 |
| event | second_appended | second_appended | second_appended |
| prior_applied_at_proposal | false | false | true |
| second_type | EntryNormal | EntryConfChange | EntryConfChange |
| learners | 1 | 0 | 1 |
| reported_applied | 3 | 3 | 3 |
| second_index | 4 | 4 | 4 |
| user_applied | 3 | 2 | 3 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


条件探索：For Candidate f42bfc0de7a44f3e8e82a2ca23af6826, does an implicit joint change applied during transfer to unavailable node 3 remain joint after transfer timeout and thirty healthy heartbeat rounds,…
所选问题／策略（原文摘录）：Resolve the accepted automatic-exit Candidate history and hidden-retry premises before fixing a bounded oracle. Use three actual RawNodes and real quorum-generated responses with serialized Ready persistence/application; no protocol state…
[受理问题、条件与来源](submissions/aff6e3c4c0cc4110959acaf7d24c1cc4/accepted.json)；[固定输入](submissions/aff6e3c4c0cc4110959acaf7d24c1cc4/inputs/autoleave_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/0d76bc251a104025a4df1481c9c815bf/check.json)；[实际输出](logs/0d76bc251a104025a4df1481c9c815bf/stdout.log)；[诊断](logs/0d76bc251a104025a4df1481c9c815bf/stderr.log)
[执行文件清单](experiments/9ce186844b3b4adda2e934aeb878265b/workspace-delta/manifest.json)；[执行文件清单](experiments/9ce186844b3b4adda2e934aeb878265b/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "joint_committed", "index": 3, "scenario": "control", "term": 2, "transfer_target": 0}
结构化观察原值（非性质判定；全部事件见日志）：{"applied": 4, "auto_leave": false, "commit": 4, "event": "after_apply", "exit_entries": 1, "has_ready": false, "heartbeat_responses": 0, "joint_index": 3, "last_index": 4, "outgoing": 0, "queue": 0, "role": "StateLeader", "scenario": "control", "term": 2, "transfer_target": 0}
执行后交接摘录：Exploration completed actual quorum commitment at index 3, application during transfer to node 3, transfer timeout by tick 10, and 30 heartbeat responses from live voter 2 with unchanged term 2 and leader role. At ticks 10/20/30 the transfer case retained…；[完整解释与剩余问题](submissions/20b56c35ffe3463486ab4691b9736c85/accepted.json)
该交接保留的未知：Fix an instrumented artifact observing admission, application, timeout, drained queues and recurring scheduling state for the same configuration operation; run it fresh and review correspondence.

条件探索：Does the Node-documented early Advance optimization permit a second configuration proposal to be appended while the previous committed configuration has not yet been passed to ApplyConfChange?…
所选问题／策略（原文摘录）：Investigate a sourced boundary between Node.Advance allowing overlap with application and ProposeConfChange requiring certainty of no prior unapplied configuration. Use the actual Node API and goroutine, not RawNode whose Advance comment…
[受理问题、条件与来源](submissions/383c0bf0b98045c6afa6ed5d2bb0c88a/accepted.json)；[固定输入](submissions/383c0bf0b98045c6afa6ed5d2bb0c88a/inputs/early_advance_explore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/66fd200abfdc4ed7b01245892d2e04b4/check.json)；[实际输出](logs/66fd200abfdc4ed7b01245892d2e04b4/stdout.log)；[诊断](logs/66fd200abfdc4ed7b01245892d2e04b4/stderr.log)
[执行文件清单](experiments/3ff8a3e38e00400a831257bf865d8e58/workspace-delta/manifest.json)；[执行文件清单](experiments/3ff8a3e38e00400a831257bf865d8e58/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"commit": 3, "event": "before_second", "first_index": 3, "learners": 0, "reported_applied": 2, "scenario": "hold_advance", "user_applied": 2}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "second_appended", "first_index": 3, "learners": 1, "reported_applied": 3, "scenario": "hold_advance", "second_index": 4, "second_type": "EntryNormal", "user_applied": 3}
执行后交接摘录：The Node exploration completed all three histories. With Advance withheld, second index 4 is EntryNormal. Early Advance reports Applied=3 while userApplied=2 and no learners are active, then appends second index 4 as EntryConfChange before first…；[完整解释与剩余问题](submissions/776c4b0e83dc4f22b460d1207adcaff0/accepted.json)
该交接保留的未知：Run the fixed check and review the Node contract interpretation, operation correlation and actual timing before attribution.

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)。
- 共识形成与推进（原文导航摘录）：A leader assigns its term and next index to admitted proposals and sends append requests. Followers match predecessor term/index, preserve committed entries, replace conflicting uncommitted suffixes and report append…
- 上下文／权威转换（原文导航摘录）：Election starts only for a promotable voter without unapplied committed configuration changes or pending snapshot. Vote grants require permitted prior-vote state and an up-to-date candidate log; current voter majorities…
- 两条主线的连接（原文导航摘录）：Authority is acquired with votes qualified by log history and local applied membership. Within that authority, durable append replies become eligible Match support for commit. Membership application changes which…

- 14:44:04 +0000（距创建墙钟 536.9 秒，含暂停间隔）；Agent 回合墙钟 386.44 秒 · 双主线概览已就绪。[当时地图](audit-spec/v1.json)

- 14:49:31 +0000（距创建墙钟 863.8 秒，含暂停间隔）；目标工具耗时 11.40 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/0d76bc251a104025a4df1481c9c815bf/check.json)

- 14:56:58 +0000（距创建墙钟 1310.8 秒，含暂停间隔）；目标工具耗时 11.57 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/97aac198d2bc4b10be4e3104e70bb614/check.json)

- 15:04:42 +0000（距创建墙钟 1774.3 秒，含暂停间隔）；目标工具耗时 14.22 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/66fd200abfdc4ed7b01245892d2e04b4/check.json)

- 15:07:50 +0000（距创建墙钟 1963.1 秒，含暂停间隔）；Agent 回合墙钟 188.30 秒 · 认识／制品更新：The Node exploration completed all three histories. With Advance withheld, second index 4 is EntryNormal. Early Advance reports Applied=3 while userApplied=2 and no learners are active, then appends…。[完整交接](submissions/776c4b0e83dc4f22b460d1207adcaff0/accepted.json)

- 15:08:07 +0000（距创建墙钟 1979.6 秒，含暂停间隔）；目标工具耗时 15.88 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/0658bc3db0044fef9d8fa246d1dff118/check.json)

- 15:12:44 +0000（距创建墙钟 2256.5 秒，含暂停间隔）；Agent 回合墙钟 119.85 秒 · 认识／制品更新：The in-repository InteractionEnv is now inspected rather than assumed external: synchronous ProcessReady calls processAppend and processApply before publishing messages and Advance. Async…。[完整交接](submissions/e8eec7b9be11434da4edaff8ba0cb2e1/accepted.json)

- 15:14:40 +0000（距创建墙钟 2372.4 秒，含暂停间隔）；Agent 回合墙钟 115.60 秒 · 认识／制品更新：InteractionEnv owns separate AppendWork, ApplyWork and application History. Its storage wrapper returns the latest History snapshot, rather than the embedded MemoryStorage snapshot. AddNodes…。[完整交接](submissions/1d06d49bc40d44c695973df24653078c/accepted.json)

- 15:15:07 +0000（距创建墙钟 2399.9 秒，含暂停间隔）；Agent 回合墙钟 27.31 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/032475a665b74e82b264ce4c74379545/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

**开放责任：README.md:118 versus node.go:74-101**

地图保留的缺口：Conflicting same-Ready persistence/send ordering statements. Example saves entries before sending, but does not resolve the weaker README permission.
尚未记录后续步骤。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

**开放责任：raft.appliedTo AutoLeave / tickHeartbeat transfer abort**

地图保留的缺口：AutoLeave proposal may be dropped during transfer; timeout aborts transfer without an explicit auto-leave retry. Need producer history and bounded completion contract.
尚未记录后续步骤。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

**开放责任：Node.run removal and proposal channel**

地图保留的缺口：Proposal channel is disabled on local removal but recalculated on leader changes; eligibility and intended forwarding after removal need further contract work.
尚未记录后续步骤。
[地图 v1：概览、Behavior／Fact 与来源](audit-spec/v1.json)

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
