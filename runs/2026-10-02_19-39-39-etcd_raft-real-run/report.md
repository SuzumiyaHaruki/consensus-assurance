# 共识审计研究报告

## 运行概览

审计目标 **etcd_raft**。本轮有 5 项已产生观察的正式问题：已确认违反 0 项、有限检查未见违反 5 项、待调查线索 0 项；另有源码解释 0 项、探索执行 5 次。正式义务共 5 项，执行次数不等于问题数。

实际持续 **80.00 分钟**；结束类型：**控制器记录的资源边界**。
剩余 0.00 秒、14 次 Agent 调用、6 次控制器目标执行。源码调查能力：无剩余预算。

| 资源 | 配置 | 已用 | 剩余 |
| --- | ---: | ---: | ---: |
| 总时间（秒） | 4800.0 | 4800.11 | 0.00 |
| Agent 调用 | 40 | 26 | 14 |
| 控制器目标执行 | 16 | 10 | 6 |
| 新 Unit | 6 | 5 | 1 |
| 语义复核 | 10 | 5 | 5 |
| 修订 | 6 | 0 | 6 |

目标执行组成：正式检查 5 次＋探索 5 次，其中失败／未完成 1 次；失败和重试照常计数。会话内本地试跑不属于此控制器计数；总时间不叠加内部工具耗时，缺失 token 用量保持未知。
新 Unit 入场能力不保证剩余额度足够完成检查与复核。

元数据：源码 `91180476b404beeb5326194e3fcdfa1758d4f222`；实际方法 `audit-products-v40`；展示版本 `audit-products-v40`；模式 real/autonomous；执行后端 `go_module`／包 `.`；模型 `gpt-6-astra`／`low`。重新渲染不代表重新审计。

停止依据（记录摘录）：Agent stopped: Action timeout exceeded; process group killed；[完整停止记录](state.json)。

中断调用 `agent_turn`：status=`timeout`；timeout_limit=`total_seconds`；timeout_seconds=`8.690348766998795`。
[调用记录](logs/563e0acc9e744266a767558b98224799/check.json)；[stdout](logs/563e0acc9e744266a767558b98224799/stdout.log)；[stderr](logs/563e0acc9e744266a767558b98224799/stderr.log)
可靠完成回执：未记录；未完成草稿不受理。
单轮超时，具体原因未知。

## 主要结果

| 问题 | 当前结果 | 实际回答摘录 | 证据 |
| --- | --- | --- | --- |
| 1. For a fresh normal entry proposed by an elected leader with three fixed voters and AsyncStorageWrites enabled, does commitment…（原文摘录） | 有限检查未见违反 | Execution b617d2d55bac4add81288c1f82e19cd0 measured the implication at all four declared checkpoints. A single completed follower did not commit the new entry; two… | [C_append_completed_quorum](state.json) |
| 2. For one unique outstanding ReadOnlySafe request retained while an explicit joint configuration is applied, can acknowledgments…（原文摘录） | 有限检查未见违反 | Execution e5a5dd0477a44775af322e051af102a8 observed no ReadState with outgoing-only majority (1 incoming, 3 outgoing), then exactly one matching-context ReadState when… | [C_read_joint_eligibility](state.json) |
| 3. With a full snapshot pending on a voter using AsyncStorageWrites, can completion of older normal-entry application work allow an…（原文摘录） | 有限检查未见违反 | Formal execution d686bc84b11b41479b42297a35cca17a measured the local campaign implication at all three declared checkpoints. Older normal application advanced applied… | [C_snapshot_campaign_barrier](state.json) |
| 4. After a candidate starts a second real campaign, can delayed genuine grant responses from its first campaign contribute to…（原文摘录） | 有限检查未见违反 | Execution 9f6e375680194d83847ef7ce1e57ee6a kept node 1 candidate after all three term-2 grants arrived in campaign term 3. One current grant also left it pending; a… | [C_current_campaign_grants](state.json) |
| 5. Can a delayed genuine pre-vote grant carrying the same numeric term as a newly entered real campaign count toward leadership…（原文摘录） | 有限检查未见违反 | Execution c7ea5ccf832c47b28617b48efbfb3d73 demonstrated the same-term distinction: delayed MsgPreVoteResp(term 2) did not supply real-campaign support at term 2.… | [C_real_vote_type](state.json) |

### 1. For a fresh normal entry proposed by an elected leader with three fixed voters and AsyncStorageWrites enabled, does commitment…（原文摘录）

**有限检查未见违反**。要求原文：Under a compliant asynchronous storage caller, an elected leader must not commit a fresh current-term entry in a fixed three-voter configuration unless copies of that entry have completed stable append on a voter majority. The leader need not belong to that completed majority.

决定性范围：Fresh current-term normal entry in a fixed three-voter RawNode cluster with AsyncStorageWrites, following a completed election and committed/applied leader no-op.
Crash-free, non-Byzantine execution with actual protocol-produced messages.；Each local append target is processed reliably in FIFO order; attached responses are delivered only after modeled stable writes complete.；MemoryStorage represents the stable-storage API boundary for this no-crash schedule; a completed append is not physical disk durability evidence.；No membership changes after bootstrap, leader transfer, compaction or snapshots in the measured suffix.。

排除：Overall consensus correctness, physical crash durability, restart loss and client-visible safety consequences.；General liveness; the remote-majority phase is a permitted control, not a deadline claim.；Other configurations, term transitions and arbitrary network reorderings.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution b617d2d55bac4add81288c1f82e19cd0 measured the implication at all four declared checkpoints. A single completed follower did not commit the new entry; two completed followers did commit it with the leader append still pending; final leader completion advanced its application. This answers the accepted fresh-entry support-consumption discriminator within the modeled-storage scope, subject to controller correspondence assessment.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/e14610991e7a445da8c0542f5505adad/assurance_generated_test.go)；[条件与检查器](direct-checks/e14610991e7a445da8c0542f5505adad/plan.json)；[原始观察](logs/b617d2d55bac4add81288c1f82e19cd0/stdout.log)；[assessment](direct-checks/e14610991e7a445da8c0542f5505adad/b617d2d55bac4add81288c1f82e19cd0-assessment.json)；[对应性复核](submissions/13a9438b5f0a4f24b6648a046f01bd73/accepted.json)

固定比较 `quorum_completion`：有限检查未见违反；已比较 4 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 | 观察 4 |
| --- | --- | --- | --- | --- |
| request | fresh-entry-1 | fresh-entry-1 | fresh-entry-1 | fresh-entry-1 |
| phase | all_appends_held | one_follower_completed | two_followers_completed | leader_completed |
| event | quorum_observed | quorum_observed | quorum_observed | quorum_observed |
| committed | false | false | true | true |
| append_completed_majority | false | false | true | true |
| admitted.prefix_complete | true | true | true | true |
| admitted.proposal_accepted | true | true | true | true |
| commit_index | 4 | 4 | 5 | 5 |
| entry_index | 5 | 5 | 5 | 5 |
| entry_term | 2 | 2 | 2 | 2 |
| leader_applied | 4 | 4 | 4 | 5 |
| leader_role | StateLeader | StateLeader | StateLeader | StateLeader |
| leader_term | 2 | 2 | 2 | 2 |
| schedule_complete | true | true | true | true |
| stored_copies | 0 | 1 | 2 | 3 |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 2. For one unique outstanding ReadOnlySafe request retained while an explicit joint configuration is applied, can acknowledgments…（原文摘录）

**有限检查未见违反**。要求原文：For a single outstanding ReadOnlySafe request consumed while an explicit joint voter configuration is active, release of its ReadState requires acknowledgment support satisfying both incoming and outgoing voter majorities. Support from only the outgoing majority must not authorize release.

决定性范围：One unique outstanding ReadOnlySafe context across application of an explicit joint change from five voters to incoming {1,4,5}, outgoing {1,2,3,4,5}, with leader 1 retained in the same term.
Actual RawNode-generated heartbeat responses, held and later delivered unchanged.；Current-term leader entry committed/applied before ReadIndex; joint change proposed, replicated, committed and applied through public APIs.；Exactly one ReadIndex invocation with a fresh nonempty context; no retries or later requests can release a queue prefix.；Single-threaded RawNode calls, reliable FIFO asynchronous storage handling, MemoryStorage as a no-crash completion adapter.；No ticks, role changes, term changes, further configuration changes or client read service during the observed suffix.。

排除：Client-visible linearizability or stale-value outcomes.；Multiple read request batching, reused request contexts, lease-based reads and singleton fast paths.；Physical storage durability and crash/restart behavior.；General liveness; absence of release is permitted until qualified support.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution e5a5dd0477a44775af322e051af102a8 observed no ReadState with outgoing-only majority (1 incoming, 3 outgoing), then exactly one matching-context ReadState when both majorities were present (2 incoming, 4 outgoing). The same-term, actual applied joint transition and emission-time counts answer the selected local eligibility discriminator. The returned index remained the request-time index 6, not current commit 7, which is allowed by the fixed claim.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/0ded4360ccc14ee587df56f98024cc86/assurance_generated_test.go)；[条件与检查器](direct-checks/0ded4360ccc14ee587df56f98024cc86/plan.json)；[原始观察](logs/e5a5dd0477a44775af322e051af102a8/stdout.log)；[assessment](direct-checks/0ded4360ccc14ee587df56f98024cc86/e5a5dd0477a44775af322e051af102a8-assessment.json)；[对应性复核](submissions/05a40c72d5624545acf6917d6e454540/accepted.json)

固定比较 `read_joint_eligibility`：有限检查未见违反；已比较 5 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 | 观察 4 | 观察 5 |
| --- | --- | --- | --- | --- | --- |
| request | unique-read-joint-1 | unique-read-joint-1 | unique-read-joint-1 | unique-read-joint-1 | unique-read-joint-1 |
| phase | self_only | one_outgoing_reply | outgoing_majority_only | both_majorities | remaining_reply |
| event | read_support_observed | read_support_observed | read_support_observed | read_support_observed | read_support_observed |
| read_emitted | false | false | false | true | true |
| both_majorities | false | false | false | true | true |
| joint_admission.joint_applied | true | true | true | true | true |
| incoming_count | 1 | 1 | 1 | 2 | 3 |
| leader_applied | 7 | 7 | 7 | 7 | 7 |
| leader_commit | 7 | 7 | 7 | 7 | 7 |
| leader_role | StateLeader | StateLeader | StateLeader | StateLeader | StateLeader |
| leader_term | 2 | 2 | 2 | 2 | 2 |
| outgoing_count | 1 | 2 | 3 | 4 | 5 |
| read_count | 0 | 0 | 0 | 1 | 1 |
| read_index | 0 | 0 | 0 | 6 | 6 |
| schedule_complete | true | true | true | true | true |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched；观察 5 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 3. With a full snapshot pending on a voter using AsyncStorageWrites, can completion of older normal-entry application work allow an…（原文摘录）

**有限检查未见违反**。要求原文：For a follower with a full snapshot pending, completion of older normal application work must not permit an explicit Campaign to start an election before the matching snapshot append completion is consumed.

决定性范围：One full snapshot at index 7 from an actually committed/applied leader prefix to a lagging voter with one earlier normal apply batch at index 5 outstanding. Explicit Campaign is observed before and after that apply response and after snapshot completion.
Sequential RawNode API calls and per-target reliable FIFO processing.；MemoryStorage models completed storage in a crash-free schedule; actual application snapshot data is installed before attached completion is returned.；Fixed three voters after completed bootstrap, PreVote disabled, no ticks or external messages between Campaign and its immediate BasicStatus observation.。

排除：General consensus safety or liveness, client consequences and physical crash durability.；Old configuration batches, snapshot replacement, stale-term completion and restart.；A guarantee that every post-completion campaign must win.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Formal execution d686bc84b11b41479b42297a35cca17a measured the local campaign implication at all three declared checkpoints. Older normal application advanced applied from 4 to 5 without permitting a campaign while snapshot 7 remained pending. Matching snapshot completion advanced applied to 7, after which Campaign entered candidate/term 3. This answers the selected normal-application substitution question within its fixed source-defined eligibility scope.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/7736ac8bd1834af584d0f14df7375acf/assurance_generated_test.go)；[条件与检查器](direct-checks/7736ac8bd1834af584d0f14df7375acf/plan.json)；[原始观察](logs/d686bc84b11b41479b42297a35cca17a/stdout.log)；[assessment](direct-checks/7736ac8bd1834af584d0f14df7375acf/d686bc84b11b41479b42297a35cca17a-assessment.json)；[对应性复核](submissions/14ca165c87b6488ba6c2ee7064c7cd56/accepted.json)

固定比较 `snapshot_campaign_barrier`：有限检查未见违反；已比较 3 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 |
| --- | --- | --- | --- |
| request | snapshot-campaign-1 | snapshot-campaign-1 | snapshot-campaign-1 |
| phase | snapshot_and_apply_held | older_apply_completed | snapshot_completed |
| node | 3 | 3 | 3 |
| snapshot_index | 7 | 7 | 7 |
| event | campaign_observed | campaign_observed | campaign_observed |
| campaign_started | false | false | true |
| snapshot_completed | false | false | true |
| campaign_input.snapshot_delivered | true | true | true |
| after_role | StateFollower | StateFollower | StateCandidate |
| after_term | 2 | 2 | 3 |
| app_applied | 4 | 5 | 7 |
| applied | 4 | 5 | 7 |
| before_term | 2 | 2 | 2 |
| call_completed | true | true | true |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 4. After a candidate starts a second real campaign, can delayed genuine grant responses from its first campaign contribute to…（原文摘录）

**有限检查未见违反**。要求原文：An ordinary candidate must not acquire leadership in its current campaign by counting delayed lower-term vote grants; a majority of delivered grants for the current campaign term is necessary.

决定性范围：Two consecutive real campaigns by node 1 in a fixed three-voter async cluster; all genuine first- and second-term grants are stored then delayed by transport and released in six fixed phases.
PreVote disabled; no timers, configuration changes, snapshots, restarts or external term inputs during the measured suffix.；Sequential RawNode calls, reliable FIFO local append/apply workers; only network vote response delivery is delayed.；MemoryStorage models the stable vote completion boundary in a no-crash schedule.。

排除：General consensus correctness, split-brain history, client effects and physical crash durability.；Pre-vote, joint membership and arbitrary concurrent competing candidates.；A liveness guarantee that sufficient grants must produce leadership by a deadline.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution 9f6e375680194d83847ef7ce1e57ee6a kept node 1 candidate after all three term-2 grants arrived in campaign term 3. One current grant also left it pending; a current-term majority yielded leadership. All six correlated comparisons completed. This answers the selected stale-term grant discriminator within its fixed scope.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/fb3f8314acbe4a5886ec686005617442/assurance_generated_test.go)；[条件与检查器](direct-checks/fb3f8314acbe4a5886ec686005617442/plan.json)；[原始观察](logs/9f6e375680194d83847ef7ce1e57ee6a/stdout.log)；[assessment](direct-checks/fb3f8314acbe4a5886ec686005617442/9f6e375680194d83847ef7ce1e57ee6a-assessment.json)；[对应性复核](submissions/f7a15379324b404b85c059734bf7bc18/accepted.json)

固定比较 `current_campaign_grants`：有限检查未见违反；已比较 6 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 | 观察 4 | 观察 5 | 观察 6 |
| --- | --- | --- | --- | --- | --- | --- |
| request | consecutive-campaigns-1 | consecutive-campaigns-1 | consecutive-campaigns-1 | consecutive-campaigns-1 | consecutive-campaigns-1 | consecutive-campaigns-1 |
| phase | old_self | old_peer_2 | old_peer_3 | current_self | current_peer_2 | current_peer_3 |
| node | 1 | 1 | 1 | 1 | 1 | 1 |
| campaign_term | 3 | 3 | 3 | 3 | 3 | 3 |
| event | election_observed | election_observed | election_observed | election_observed | election_observed | election_observed |
| leader | false | false | false | false | true | true |
| current_majority | false | false | false | false | true | true |
| release_input.prefix_ready | true | true | true | true | true | true |
| actual_term | 3 | 3 | 3 | 3 | 3 | 3 |
| current_grants | 0 | 0 | 0 | 1 | 2 | 3 |
| held_grants | 5 | 4 | 3 | 2 | 1 | 0 |
| role | StateCandidate | StateCandidate | StateCandidate | StateCandidate | StateLeader | StateLeader |
| schedule_complete | true | true | true | true | true | true |
| senders.1 | 未记录 | 未记录 | 未记录 | true | true | true |
| senders.2 | 未记录 | 未记录 | 未记录 | 未记录 | true | true |
| senders.3 | 未记录 | 未记录 | 未记录 | 未记录 | 未记录 | true |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched；观察 5 → matched；观察 6 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


### 5. Can a delayed genuine pre-vote grant carrying the same numeric term as a newly entered real campaign count toward leadership…（原文摘录）

**有限检查未见违反**。要求原文：A real candidate must not acquire leadership using pre-vote grants, even when their numeric term matches; a majority of delivered real vote grants for that campaign is necessary.

决定性范围：One actual pre-vote campaign advances through a pre-vote majority into real candidacy; a third pre-vote grant with matching numeric term is delivered before real self and peer grants.
Three fixed voters, PreVote enabled and AsyncStorageWrites; sequential RawNode calls and FIFO local work.；No timers, competing candidates, configuration changes, snapshots or restart in the measured suffix.；MemoryStorage models no-crash storage completion; real grant capture verifies actual stored term/vote.。

排除：General consensus correctness, physical crash safety or client consequences.；General pre-vote liveness, clock/lease assumptions and arbitrary candidate interactions.。

本次回答（沿用复核文案；无中文摘要时保留原文，判定与数值以下方记录为准）：Execution c7ea5ccf832c47b28617b48efbfb3d73 demonstrated the same-term distinction: delayed MsgPreVoteResp(term 2) did not supply real-campaign support at term 2. Leadership appeared only after the second genuine real grant; all four comparisons and the final drain completed.

制品 v1；机械比较 **有限检查未见违反**；对应性复核 no_issue_found；独立场景完整处置：True。
[固定测试](direct-checks/28cccd2edbbb499d8d37d5f129639d5f/assurance_generated_test.go)；[条件与检查器](direct-checks/28cccd2edbbb499d8d37d5f129639d5f/plan.json)；[原始观察](logs/c7ea5ccf832c47b28617b48efbfb3d73/stdout.log)；[assessment](direct-checks/28cccd2edbbb499d8d37d5f129639d5f/c7ea5ccf832c47b28617b48efbfb3d73-assessment.json)；[对应性复核](submissions/fbd1d01a93d947a0bb82aecb56f51e3b/accepted.json)

固定比较 `real_vote_type`：有限检查未见违反；已比较 4 项，完整见证 0 项，缺失 0 项。

| 记录字段 | 观察 1 | 观察 2 | 观察 3 | 观察 4 |
| --- | --- | --- | --- | --- |
| request | prevote-real-campaign-1 | prevote-real-campaign-1 | prevote-real-campaign-1 | prevote-real-campaign-1 |
| phase | delayed_pre_vote | real_self | real_peer_2 | real_peer_3 |
| node | 1 | 1 | 1 | 1 |
| campaign_term | 2 | 2 | 2 | 2 |
| event | election_observed | election_observed | election_observed | election_observed |
| leader | false | false | true | true |
| current_majority | false | false | true | true |
| release_input.prefix_ready | true | true | true | true |
| actual_term | 2 | 2 | 2 | 2 |
| current_grants | 0 | 1 | 2 | 3 |
| held_grants | 3 | 2 | 1 | 0 |
| role | StateCandidate | StateCandidate | StateLeader | StateLeader |
| schedule_complete | true | true | true | true |
| senders.1 | 未记录 | true | true | true |
| senders.2 | 未记录 | 未记录 | true | true |
| senders.3 | 未记录 | 未记录 | 未记录 | true |

前提关联：观察 1 → matched；观察 2 → matched；观察 3 → matched；观察 4 → matched。嵌套结构、前提原值及编码数据见原始观察；不猜测解码。


条件探索：Can the three-voter public-entry history produce an automatic full snapshot while an older normal-entry apply batch is outstanding, and what do explicit Campaign calls do before old apply completion,…
所选问题／策略（原文摘录）：Construct the accepted pending-snapshot discriminator through actual RawNode producers before fixing an obligation. This run tests reachability and records effects without claiming formal Evidence.
[受理问题、条件与来源](submissions/c1fbd63ff7be40c9a68cf5c52d3aa169/accepted.json)；[固定输入](submissions/c1fbd63ff7be40c9a68cf5c52d3aa169/inputs/snapshot_campaign_test.go)
探索执行失败或未完成；没有正式性质判定。[执行记录](logs/9a5cebc41e534ebab825feb8e52e1d62/check.json)；[实际输出](logs/9a5cebc41e534ebab825feb8e52e1d62/stdout.log)；[诊断](logs/9a5cebc41e534ebab825feb8e52e1d62/stderr.log)
[执行文件清单](experiments/c585f125eac140ae9e6249f9aba4f26a/workspace-delta/manifest.json)；[执行文件清单](experiments/c585f125eac140ae9e6249f9aba4f26a/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 1, "phase": "prefix", "request": "snapshot-campaign-1", "responses": 1}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 2, "phase": "prefix", "request": "snapshot-campaign-1", "responses": 1}
执行后交接摘录：The repaired exploration b24b00617a78411f8e23ab629496c70d reached snapshot index 7 from follower stored index 5 with one old apply batch. Campaign observations remained follower/term 2 at applied indexes 4 and 5; after snapshot completion it entered…；[完整解释与剩余问题](submissions/7736ac8bd1834af584d0f14df7375acf/accepted.json)
该交接保留的未知：Fresh formal execution and checker correspondence are required for this fixed obligation and updated observation ledger.；The older-configuration application-ordering question remains independent.

条件探索：Can the three-voter public-entry history produce an automatic full snapshot while an older normal-entry apply batch is outstanding, and what do explicit Campaign calls do before old apply completion,…
所选问题／策略（原文摘录）：Repair the exploration scheduler: the first execution reached an actual optimistic append probe but held the append completion needed to release its rejection, so it never reached snapshot fallback.
[受理问题、条件与来源](submissions/063257bd55184696a61aea59e69818e9/accepted.json)；[固定输入](submissions/063257bd55184696a61aea59e69818e9/inputs/snapshot_campaign_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/b24b00617a78411f8e23ab629496c70d/check.json)；[实际输出](logs/b24b00617a78411f8e23ab629496c70d/stdout.log)；[诊断](logs/b24b00617a78411f8e23ab629496c70d/stderr.log)
[执行文件清单](experiments/46df9e958ff246e583c33ec3cab3fd95/workspace-delta/manifest.json)；[执行文件清单](experiments/46df9e958ff246e583c33ec3cab3fd95/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 1, "phase": "prefix", "request": "snapshot-campaign-1", "responses": 1}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 2, "phase": "prefix", "request": "snapshot-campaign-1", "responses": 1}
执行后交接摘录：The repaired exploration b24b00617a78411f8e23ab629496c70d reached snapshot index 7 from follower stored index 5 with one old apply batch. Campaign observations remained follower/term 2 at applied indexes 4 and 5; after snapshot completion it entered…；[完整解释与剩余问题](submissions/7736ac8bd1834af584d0f14df7375acf/accepted.json)
该交接保留的未知：Fresh formal execution and checker correspondence are required for this fixed obligation and updated observation ledger.；The older-configuration application-ordering question remains independent.

条件探索：When a real committed learner-add entry is already queued for application on a lagging follower, then a newer full snapshot from the same history carries the later learner removal, what configuration…
所选问题／策略（原文摘录）：Investigate the distinct older-configuration entry boundary with producer-derived inputs; caller-contract applicability remains unresolved and no obligation or safety outcome is asserted.
[受理问题、条件与来源](submissions/a7ac4e2672d745c1975e17341bd1f23d/accepted.json)；[固定输入](submissions/a7ac4e2672d745c1975e17341bd1f23d/inputs/snapshot_old_config_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/71b0b0216b9f493dabbfcc7ac791b691/check.json)；[实际输出](logs/71b0b0216b9f493dabbfcc7ac791b691/stdout.log)；[诊断](logs/71b0b0216b9f493dabbfcc7ac791b691/stderr.log)
[执行文件清单](experiments/3c39bbedba13490ea5b0e7427f241fdf/workspace-delta/manifest.json)；[执行文件清单](experiments/3c39bbedba13490ea5b0e7427f241fdf/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 1, "phase": "prefix", "request": "snapshot-old-config-1", "responses": 1}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 2, "phase": "prefix", "request": "snapshot-old-config-1", "responses": 1}
执行后交接摘录：Exploration bdd27761fdf74acaa83870729e1c5433 completed with old live learner set {4}, saved snapshot learner set empty, and fresh-instance learner set empty. Saved and reconstructed term/vote/commit were 2/1/7; caller Applied 7 yielded fresh applied 7 and…；[完整解释与剩余问题](submissions/8b7df6efd2d04f5c8cf3990799e627a6/accepted.json)
该交接保留的未知：The configuration Candidate remains paused on ownership of ApplyConfChange ordering versus network snapshot restore. Reconstruction does not resolve or excuse the earlier conditional discrepancy.；No crash, partial persistence or old-completion delivery into a replacement instance was executed. Fresh channels and empty-queue construction do not establish a general worker-retirement contract.；The accepted shared read-support Fact still contains an old execution-progress note about joint history; its historical requirement basis and actual completed check/review should be distinguished if the map is next substantively revised.

条件探索：Does applying the already issued learner-add batch immediately before Step receives the actual newer snapshot, while leaving its storage-apply response queued, avoid the membership difference…
所选问题／策略（原文摘录）：Compare one explicit caller ordering control against the retained after-restore exploration, keeping the actual producer history and snapshot unchanged.
[受理问题、条件与来源](submissions/eb729892bf214d2abe951f0e395a6fcb/accepted.json)；[固定输入](submissions/eb729892bf214d2abe951f0e395a6fcb/inputs/snapshot_config_before_restore_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/228dac2c1026445282000ac0b43f2237/check.json)；[实际输出](logs/228dac2c1026445282000ac0b43f2237/stdout.log)；[诊断](logs/228dac2c1026445282000ac0b43f2237/stderr.log)
[执行文件清单](experiments/e5ec45c37a7a48c5ae0a0378be58e9a2/workspace-delta/manifest.json)；[执行文件清单](experiments/e5ec45c37a7a48c5ae0a0378be58e9a2/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 1, "phase": "prefix", "request": "snapshot-config-before-restore-1", "responses": 1}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 2, "phase": "prefix", "request": "snapshot-config-before-restore-1", "responses": 1}
执行后交接摘录：Exploration bdd27761fdf74acaa83870729e1c5433 completed with old live learner set {4}, saved snapshot learner set empty, and fresh-instance learner set empty. Saved and reconstructed term/vote/commit were 2/1/7; caller Applied 7 yielded fresh applied 7 and…；[完整解释与剩余问题](submissions/8b7df6efd2d04f5c8cf3990799e627a6/accepted.json)
该交接保留的未知：The configuration Candidate remains paused on ownership of ApplyConfChange ordering versus network snapshot restore. Reconstruction does not resolve or excuse the earlier conditional discrepancy.；No crash, partial persistence or old-completion delivery into a replacement instance was executed. Fresh channels and empty-queue construction do not establish a general worker-retirement contract.；The accepted shared read-support Fact still contains an old execution-progress note about joint history; its historical requirement basis and actual completed check/review should be distinguished if the map is next substantively revised.

条件探索：After the retained conditional old-configuration/snapshot history fully drains, what membership, term/vote, commit and applied state does a fresh NewRawNode reconstruct from the actual saved…
所选问题／策略（原文摘录）：Use a small reconstruction endpoint to distinguish the retained volatile membership discrepancy from saved snapshot state, without resolving or strengthening the paused caller-contract question.
[受理问题、条件与来源](submissions/7dc599259c644cc49924252c762b39a6/accepted.json)；[固定输入](submissions/7dc599259c644cc49924252c762b39a6/inputs/snapshot_config_restart_test.go)
条件观察完成；没有正式性质判定。[执行记录](logs/bdd27761fdf74acaa83870729e1c5433/check.json)；[实际输出](logs/bdd27761fdf74acaa83870729e1c5433/stdout.log)；[诊断](logs/bdd27761fdf74acaa83870729e1c5433/stderr.log)
[执行文件清单](experiments/c7458a6e03344a89b3572ad54e5716d2/workspace-delta/manifest.json)；[执行文件清单](experiments/c7458a6e03344a89b3572ad54e5716d2/workspace-outcome/manifest.json)
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 1, "phase": "prefix", "request": "snapshot-config-restart-1", "responses": 1}
结构化观察原值（非性质判定；全部事件见日志）：{"event": "append_completed", "last": 3, "node": 2, "phase": "prefix", "request": "snapshot-config-restart-1", "responses": 1}
执行后交接摘录：Exploration bdd27761fdf74acaa83870729e1c5433 completed with old live learner set {4}, saved snapshot learner set empty, and fresh-instance learner set empty. Saved and reconstructed term/vote/commit were 2/1/7; caller Applied 7 yielded fresh applied 7 and…；[完整解释与剩余问题](submissions/8b7df6efd2d04f5c8cf3990799e627a6/accepted.json)
该交接保留的未知：The configuration Candidate remains paused on ownership of ApplyConfChange ordering versus network snapshot restore. Reconstruction does not resolve or excuse the earlier conditional discrepancy.；No crash, partial persistence or old-completion delivery into a replacement instance was executed. Fresh channels and empty-queue construction do not establish a general worker-retirement contract.；The accepted shared read-support Fact still contains an old execution-progress note about joint history; its historical requirement basis and actual completed check/review should be distinguished if the map is next substantively revised.

## 研究过程与认识增长

A1 共识形成与推进、A2 上下文／权威转换及其连接由双主线概览导航；地图条目和检查数量不是责任覆盖率。
[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)。
- 共识形成与推进（原文导航摘录）：A RawNode proposal synchronously enters Step; Node serializes the same proposal in node.run and returns the Step result. Followers forward or drop, candidates drop, and leaders reject removal/transfer/quota cases.…
- 上下文／权威转换（原文导航摘录）：Ticks or Campaign enter hup only when own progress is eligible, no snapshot is pending and no committed configuration change remains unapplied. Pre-vote leaves term/vote unchanged; real candidacy raises term and sends…
- 两条主线的连接（原文导航摘录）：Authority transitions rebuild progress and vote tracking but preserve established committed log state. Delayed ordinary support from older terms is excluded; newly appended self support is not admitted until append…

- 11:51:34 +0000（距创建墙钟 714.1 秒，含暂停间隔）；Agent 回合墙钟 442.38 秒 · 双主线概览已就绪。[当时地图](audit-spec/v2.json)

- 11:57:27 +0000（距创建墙钟 1067.3 秒，含暂停间隔）；目标工具耗时 15.49 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/b617d2d55bac4add81288c1f82e19cd0/check.json)

- 12:09:52 +0000（距创建墙钟 1812.5 秒，含暂停间隔）；目标工具耗时 15.39 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/e5a5dd0477a44775af322e051af102a8/check.json)

- 12:25:09 +0000（距创建墙钟 2729.2 秒，含暂停间隔）；目标工具耗时 16.07 秒 · 实际执行：条件探索；探索执行失败或未完成。[执行记录](logs/9a5cebc41e534ebab825feb8e52e1d62/check.json)

- 12:26:58 +0000（距创建墙钟 2838.2 秒，含暂停间隔）；目标工具耗时 14.94 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/b24b00617a78411f8e23ab629496c70d/check.json)

- 12:30:28 +0000（距创建墙钟 3048.8 秒，含暂停间隔）；目标工具耗时 15.75 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/d686bc84b11b41479b42297a35cca17a/check.json)

- 12:35:17 +0000（距创建墙钟 3337.5 秒，含暂停间隔）；目标工具耗时 16.33 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/71b0b0216b9f493dabbfcc7ac791b691/check.json)

- 12:39:23 +0000（距创建墙钟 3583.4 秒，含暂停间隔）；目标工具耗时 13.66 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/228dac2c1026445282000ac0b43f2237/check.json)

- 12:47:53 +0000（距创建墙钟 4093.6 秒，含暂停间隔）；目标工具耗时 13.50 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/9f6e375680194d83847ef7ce1e57ee6a/check.json)

- 12:53:10 +0000（距创建墙钟 4410.1 秒，含暂停间隔）；目标工具耗时 14.19 秒 · 实际执行：直接实现检查；执行完成；比较见 assessment。[执行记录](logs/c7ea5ccf832c47b28617b48efbfb3d73/check.json)

- 12:56:34 +0000（距创建墙钟 4614.5 秒，含暂停间隔）；Agent 回合墙钟 111.47 秒 · 认识／制品更新：RestartNode documents membership reconstruction from Storage. newRaft creates new progress/read state, restores InitialState ConfState, loads HardState, accepts caller Applied and enters follower…。[完整交接](submissions/7dc599259c644cc49924252c762b39a6/accepted.json)

- 12:56:47 +0000（距创建墙钟 4627.5 秒，含暂停间隔）；目标工具耗时 12.54 秒 · 实际执行：条件探索；条件观察完成。[执行记录](logs/bdd27761fdf74acaa83870729e1c5433/check.json)

- 12:58:08 +0000（距创建墙钟 4708.7 秒，含暂停间隔）；Agent 回合墙钟 80.92 秒 · 认识／制品更新：Exploration bdd27761fdf74acaa83870729e1c5433 completed with old live learner set {4}, saved snapshot learner set empty, and fresh-instance learner set empty. Saved and reconstructed term/vote/commit…。[完整交接](submissions/8b7df6efd2d04f5c8cf3990799e627a6/accepted.json)

- 12:59:30 +0000（距创建墙钟 4790.7 秒，含暂停间隔）；Agent 回合墙钟 81.77 秒 · 认识／制品更新：The snapshot-send recovery path separates transport status from replication support. In StateSnapshot, leader MsgSnapStatus success enters Probe with Next=max(Match+1,pendingSnapshot+1); failure…。[完整交接](submissions/468319f10ee843a1b7b7de99e2bd3444/accepted.json)

- 12:59:39 +0000（距创建墙钟 4799.7 秒，含暂停间隔）；Agent 回合墙钟 8.71 秒 · Agent 调查中断；后续记录不抹掉此失败。[中断记录](logs/563e0acc9e744266a767558b98224799/check.json)

[完整运行时序](events.jsonl)；[完整研究交接与执行历史](state.json)

## 当前未决事项

已选检查暂无欠账；研究范围仍可开放。

**开放责任：raft.stepLeader MsgReadIndex and MsgHeartbeatResp**

地图保留的缺口：Mapped context-keyed pending support and current-configuration consumption. A single-request joint transition is selected; batching, configuration-history linearizability and client read endpoints remain separate.
尚未记录后续步骤。
[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)

**开放责任：Config.DisableConfChangeValidation**

地图保留的缺口：The caller may bypass best-effort propose checks only with its own serialized validation; no such caller policy has been selected.
尚未记录后续步骤。
[地图 v6：概览、Behavior／Fact 与来源](audit-spec/v6.json)

候选：What caller responsibility preserves snapshot-established membership when an earlier committed configuration entry was already handed out but its ApplyConfChange runs after full snapshot restore?
保存的语义未知：The captured contracts do not explicitly assign the ordering responsibility for already-issued configuration calls versus network snapshot restore; an applicable required endpoint invariant is likewise not established.
恢复条件：Acquire a specific applicable caller contract or repository policy that settles older ApplyConfChange permission after restore, or a distinct required endpoint invariant covering that history.
[候选原文与历史](state.json)

## 证据与运行说明

[完整状态、版本与争议](state.json)；[当前研究索引](research.json)；[实际配置](config.json)；[事件时序](events.jsonl)；[实际加载方法](audit-method.md)
环境探测不检查性质；探索成功不代表性质成立；失败驱动不是目标违反。脚本化 Agent 产品不证明自主发现。
- 失败／未完成：[exploration](logs/9a5cebc41e534ebab825feb8e52e1d62/stdout.log)；[stderr](logs/9a5cebc41e534ebab825feb8e52e1d62/stderr.log)；[执行记录](logs/9a5cebc41e534ebab825feb8e52e1d62/check.json)
