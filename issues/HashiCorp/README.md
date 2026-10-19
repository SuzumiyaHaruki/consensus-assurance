# HashiCorp Raft 问题整理与上游状态

核对日期：2026-10-17。本文合并历次 CA 与 baseline 的发现，按独立根因去重；实验中的多次执行、多个影响变体不分别计为新问题。

**发布状态：本轮创建的上游 #725–#729 已全部按用户要求关闭，属于主动撤回，不是维护者否定。以后只有用户明确授权发布具体内容，才操作账号提交、评论或推送。本文仅为本地研究整理。**

## 1. 版本、证据与检索范围

- 最新核对的稳定版本为 [v1.8.0](https://github.com/hashicorp/raft/releases/tag/v1.8.0)，上游提交 `0f543c056e7e577a54b819a62116335c9661a13a`。
- 10 月 17 日配对实验捕获的是准备副本 `cc91171013bec7a55e35d8e3043a7611ecd9795e`：包含嵌套模块依赖准备和 fuzzy 的 PreVote 解码修正；根目录 Raft 生产实现与上述上游提交一致，不能将整个准备副本称为未经修改的上游。
- 10 月 9 日 baseline、10 月 12 日部分 CA 使用 v1.7.3，提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`；历史证据不自动等价于在新版本重现。
- 本次读取了上游全部状态的 718 条 issue/PR 记录，并对相关条目检查正文、讨论和修复差异。“未检索到重复”指截至核对日期的公开记录，不包含私下报告。
- 本文中的测试成功、观察成立、模型判断和上游接受是不同事实。下面只按实际证据说明问题，关闭但未合并的 PR 不算修复。

主要材料：

| 材料 | 内容与归档 |
| --- | --- |
| [10-17 17:50 CA](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/report.md) | 最新 CA；公开归档提交 `038c831f2bba99bfe046775f908a247b76f965e6` |
| [10-17 16:03 baseline](../../baseline/runs/2026-10-17_16-03-24-hashicorp_raft-baseline/work/report.md) | 恢复路径及进一步后果；当前只在本地，不应给出假定存在的 GitHub 文件链接 |
| [10-17 09:39 baseline](../../baseline/runs/2026-10-17_09-39-48-hashicorp_raft-baseline/work/report.md) | 恢复问题的较早证据；已公开归档 |
| [10-09 baseline 归档](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/5848bc2431fbce3d5fa1d42ef5fa496b9ebd6ea4/baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/work/report.md) | VerifyLeader、投票持久化中断、并发心跳 |
| [10-15 CA 归档](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/6d54c56e25a9fba76d1aa9465fa752968384b333/runs/2026-10-15_12-22-18-hashicorp_raft-real-run/report.md) | Shutdown Future、FSM 接口组合、日志截断后错误路径 |

## 2. 总览

| 编号 | 独立问题 | 已有证据 | 上游状态及处理 |
| --- | --- | --- | --- |
| H1 | RestoreCommittedLogs 恢复时跳过已提交成员配置 | baseline；本轮最小复现 | 未检索到此前同根因报告；本轮 [#728](https://github.com/hashicorp/raft/issues/728) 已主动撤回 |
| H2 | 启动恢复填满 FSM 队列，消费者尚未启动 | baseline、CA；本轮最小复现 | 未检索到此前同根因报告；本轮 [#729](https://github.com/hashicorp/raft/issues/729) 已主动撤回 |
| H3 | 配置日志写入失败后，未持久化成员集合仍生效 | 最新 CA，实际节点与故障对照 | 未检索到此前同根因报告；本轮 [#726](https://github.com/hashicorp/raft/issues/726) 已主动撤回 |
| H4 | VerifyLeader 把非投票节点确认计入多数 | 历史 baseline、最新 CA | 未检索到此前针对该路径的报告；本轮 [#725](https://github.com/hashicorp/raft/issues/725) 已主动撤回 |
| H5 | 显式领导权转移接受非投票目标，触发无益选举 | 最新 CA，单次显式调用与 voter 对照 | [#398](https://github.com/hashicorp/raft/pull/398) 仅修自动选择；本轮 [#727](https://github.com/hashicorp/raft/issues/727) 已主动撤回 |
| H6 | 并发心跳更新使当前及持久 term 回退 | 历史 baseline、最新 CA | 已有 [#695](https://github.com/hashicorp/raft/issues/695)；[#701](https://github.com/hashicorp/raft/pull/701) 关闭但未合并，不重复提交 |
| H7 | InstallSnapshot 保留冲突日志，阻碍后续复制或重新传播旧内容 | 历史 CA；上游有更强后果报告 | 已有 [#697](https://github.com/hashicorp/raft/issues/697)、[#721](https://github.com/hashicorp/raft/issues/721)；[#704](https://github.com/hashicorp/raft/pull/704) 关闭未合并 |
| H8 | GetConfiguration().Index() 返回 0 | 历史 CA，配置更新前后对照 | 已有 [#722](https://github.com/hashicorp/raft/issues/722)、开放 PR [#723](https://github.com/hashicorp/raft/pull/723) |
| H9 | 回退旧快照后缺少必要日志，启动发生 panic | 历史 CA，实际快照存储 | 已有 [#85](https://github.com/hashicorp/raft/issues/85)，不重复提交 |
| H10 | Shutdown 后部分缓冲请求的 Future 无完成路径 | 历史 CA，缓冲与非缓冲对照 | 与 [#498](https://github.com/hashicorp/raft/issues/498) 同类；[#504](https://github.com/hashicorp/raft/pull/504) 关闭未合并，宜在原问题下区分具体 API |
| H11 | 投票持久字段中断后形成新 term／旧 candidate，绕过日志新旧检查 | 10-09 baseline 的实际处理器及存储错误路径 | 与已关闭 [#661](https://github.com/hashicorp/raft/issues/661) 相关，但原报告的被否定构造不同；需在新版本复核，再考虑补充旧 issue |

H1–H5 是本轮整理出的明确、此前未找到相同公开报告的五个根因，不代表已经被上游确认。H11 保留为有具体旧版本证据、需要更新复核的条目，不纳入本轮新提交。

## 3. 五个问题的证据与边界

### H1：恢复跳过已提交配置

**条件：**显式启用 `RestoreCommittedLogs`，并使用实现 `CommitTrackingLogStore` 的日志存储。默认配置不能直接套用此结论。

`NewRaft` 先调用 `restoreFromCommittedLogs`，通过 `processLogs` 推进 `lastApplied`；随后扫描配置日志时，却从 `max(snapshotIndex, lastApplied) + 1` 开始。FSM 重放没有完成 Raft 自身成员配置重建，配置扫描又跳过了这些条目。无快照时可得到空配置；有快照时可能保留过旧配置。

本轮在 v1.8.0 临时副本中，用公开 API 完成 BootstrapCluster、正常选举、三次成功 Apply、Shutdown、NewRaft。存储适配器将暂存提交索引随下一次成功 StoreLogs 保存。重新启用恢复后配置为空；关闭恢复的对照保留单 voter 配置。原上游实现、测试及模块文件未改动，完整短复现保留在 [#728](https://github.com/hashicorp/raft/issues/728)。

10-17 下午 baseline 还包含正常 AddVoter、Snapshot、重启及分区形成的旧配置后果，见 [实际集群输出](../../baseline/runs/2026-10-17_16-03-24-hashicorp_raft-baseline/work/audit_results/finding1_real_cluster_conflict.txt)。这是内存存储保留后的节点生命周期实验，不是磁盘断电持久性验证；本轮上游报告采用的是更小的成员配置丢失复现。

引入路径关联 [PR #613 的启动顺序讨论](https://github.com/hashicorp/raft/pull/613#issuecomment-2340104819)，该功能 PR 本身不是已存在的缺陷报告。

### H2：恢复填满队列，NewRaft 无法返回

**条件：**同样需要启用恢复和支持提交索引的存储；需要重放的 FSM 批次数超过启动队列容量。

`fsmMutateCh` 容量为 128。构造函数先同步重放日志，之后才启动 `runFSM`。第 129 次向队列发送时，没有消费者能够运行，构造函数也无法继续到启动消费者的位置。

应按**真正分派的 FSM 批次**描述阈值，不把所有日志条目数量直接等同于批次数；no-op 等条目可能被过滤。

最新 CA 已对实际提交前缀和快照后的 128／129 边界进行观察，见 [回执](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/logs/791d25b96017428eb74a6280f460203e/observations.json)。本轮另将 `MaxAppendEntries=1`，正常提交 130 条命令后重启：关闭恢复的对照通过；开启后 3 秒定向测试超时，堆栈停在 `processLogs → restoreFromCommittedLogs → NewRaft`。死锁判断还由消费者尚未启动的代码顺序支持，不只依赖等待时间。完整复现见 [#729](https://github.com/hashicorp/raft/issues/729)。

### H3：配置追加失败后仍安装未落盘成员集合

`appendConfigurationEntry` 调用 `dispatchLogs` 后，无条件执行 `setLatestConfiguration`，并调整提交和复制配置。但 `dispatchLogs` 在 `StoreLogs` 失败时只返回错误、退为 Follower，没有向调用方返回可阻止后续安装的成功状态。

最新 CA 使用三个进程内真实 Raft 实例：A、B 是已提交 voter，C 是正常启动、尚未加入的空配置节点。AddVoter(C) 对应的一次 StoreLogs 返回错误且没有写入。节点内存中的配置索引仍变成 3，而持久日志最后索引为 2。隔离另一名已提交 voter 后，原 Leader 依靠 C 再次当选，普通 Apply 成功并提交至索引 4；断开 C 的对照不能完成。

证据：[固定测试](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/fixed-experiments/8bae228d12434bd8a6b6cc0b3d55f9d1-experiment/assurance_generated_test.go)、[执行观察](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/logs/bf075fd407864dbe8ea835a79774a344/observations.json)。

明确成立的是**不存在于日志中的配置被用于后续选举及提交**。本轮不把它扩写为已执行的两个冲突提交或永久数据丢失。[#614](https://github.com/hashicorp/raft/issues/614) 的持续坏盘重选问题不是这个根因。本轮撤回报告：[#726](https://github.com/hashicorp/raft/issues/726)。

### H4：VerifyLeader 接受非投票节点的确认

`verifyLeader` 根据 voter 数量计算多数，却把验证 Future 注册到所有复制流，包括 Nonvoter。其心跳响应通过同一个 `verifyFuture.vote` 累加，未保留 voter 资格限制。

最新 CA 的四实例实验先用 DemoteVoter 建立三个 voter、一个 nonvoter，确认降级已传播，再断开 Leader 与另外两个 voter。只连通 nonvoter 时 VerifyLeader 返回 nil；连 nonvoter 也断开的对照失败。见 [固定测试](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/fixed-experiments/f022aa8bf09f46fdb75241ad9ae583c8-experiment/assurance_generated_test.go)、[回执](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/logs/c211ca53de834d06a9b84e80fc18f1b7/observations.json)。

10-09 baseline 的旧版本实验还有更强的时序证据：多数侧先选出新 Leader 并提交写入，旧 Leader 随后 VerifyLeader 成功，读取的 FSM 尚无该写入。它利用通过配置校验的不同节点超时参数扩大窗口，不应被最新 CA 关于“同节点 lease 不超过 heartbeat”的论证否定；后者不能推出不同节点超时必须相等。见上述 [10-09 归档](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/5848bc2431fbce3d5fa1d42ef5fa496b9ebd6ea4/baseline/runs/2026-10-09_16-23-12-hashicorp_raft-baseline/work/report.md)。

本轮对 v1.8.0 提交的是较窄的验证多数误计，不将旧版本的更强后果冒充新版本重现。[PR #308](https://github.com/hashicorp/raft/pull/308) 已合入，但修的是 checkLeaderLease，未修这一验证路径。本轮撤回报告：[#725](https://github.com/hashicorp/raft/issues/725)。

### H5：显式转移缺少目标 voter 资格检查

自动 `LeadershipTransfer()` 的 `pickServer` 已排除 nonvoter；显式 `LeadershipTransferToServer` 则从复制映射取得目标，没有相同的资格检查。向已经降级的成员发送 TimeoutNow 后，该成员发起不能获准的选举，原 Leader 因更高 term 退位。

最新 CA 使用独立集群、单次显式请求和 voter 对照，排除了早期测试先自动转移、再显式转移导致的干扰。非投票目标案例返回 nil，目标未当选，任期 2→4；voter 对照目标当选，任期 2→3。五秒观察窗内无 Leader 采样分别为 7/472 与 1/470，采样数不能当作严格连续停机时长。

证据：[固定测试](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/fixed-experiments/8570d0703c8e4132968626ba58c059c2-experiment/assurance_generated_test.go)、[重复回执](../../runs/2026-10-17_17-50-22-hashicorp_raft-real-run/logs/021ad9476e0044e295afa4d5730d9725/observations.json)。

API 只说目标很可能当选，不承诺每次 nil 都意味着指定目标完成接任。因此问题应限定为**接受已知不具资格的目标，产生可避免的选举扰动**，不宣称永久不可用或数据丢失。[#398](https://github.com/hashicorp/raft/pull/398) 只修自动选择。本轮撤回报告：[#727](https://github.com/hashicorp/raft/issues/727)。

## 4. 已有报告及需要区别处理的历史发现

### H6–H10：不重复上报的生产问题

- **并发心跳 term 回退：**[#695](https://github.com/hashicorp/raft/issues/695) 的 Alternate Manifestation 已描述旧心跳与更新 term 的并发覆盖，与我们的局部根因一致。10-09 baseline 使用实际 NetworkTransport、线程安全存储操作延迟和串行对照；最新 CA 又观察了后续日志/FSM 现象。不同后果不拆成多个新 issue。
- **InstallSnapshot 冲突日志：**[#697](https://github.com/hashicorp/raft/issues/697) 已报告复制停滞；[#721](https://github.com/hashicorp/raft/issues/721) 已给出更强的错误日志再传播后果。我们的 [10-12 研究](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/57ec527e905d647fa67d6d4b94e4910f33bea4f0/runs/2026-10-12_09-55-08-hashicorp_raft-real-run/report.md) 可作为独立证据，不能把别人的更强后果算成自己已执行的发现。
- **配置索引为零：**[#722](https://github.com/hashicorp/raft/issues/722) 与开放 PR [#723](https://github.com/hashicorp/raft/pull/723) 已覆盖配置版本保护失效。我们的 [10-12 本地材料](../../runs/2026-10-12_21-19-58-hashicorp_raft-real-run/report.md) 有读配置及真实索引对照。
- **旧快照回退 panic：**[#85](https://github.com/hashicorp/raft/issues/85) 已覆盖旧快照与保留日志之间缺口。我们的同轮 [回执](../../runs/2026-10-12_21-19-58-hashicorp_raft-real-run/logs/650de4b00d334187b3a1bdfc19628f9e/observations.json) 使用公开恢复接口和真实文件快照；不能推导任意旧快照都有恢复完整状态的保证。
- **Shutdown Future：**10-15 CA 观察到 buffered VerifyLeader，以及开启 BatchApplyCh 后的 Apply/Barrier 未完成；见 [该轮报告](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/6d54c56e25a9fba76d1aa9465fa752968384b333/runs/2026-10-15_12-22-18-hashicorp_raft-real-run/report.md)。[#498](https://github.com/hashicorp/raft/issues/498) 已有 Apply/Shutdown 讨论，适合在原主题内补充具体覆盖，不新建笼统重复报告。

### H11：投票字段持久化中断不能简单标成“已有且无效”

[#661](https://github.com/hashicorp/raft/issues/661) 被关闭时，维护者指出原测试篡改旧投票 term，并把受害节点的较新日志身份用于落后 candidate，前提不合法。

10-09 baseline 的构造不同：真实 RequestVote 处理器先保存新投票 term，在保存 candidate 前遇到注入存储错误，产生新 term／旧 candidate 的组合；节点重新创建后，旧 candidate 明确使用自己的落后日志身份，却被重复投票分支在 freshness 检查之前接受。完整写入 candidate 的对照拒绝它。

这支持旧版本的局部投票资格错误，不等价于完整集群双 Leader 或冲突提交。本轮未在 v1.8.0 重新复核，暂不追加评论或另开 issue。后续若获授权，应说明与原问题被否定构造的差别，而不是重复原来的 split-brain 标题。

## 5. 测试设施问题，单独分类

| 问题 | 已有材料及上游情况 | 当前处理 |
| --- | --- | --- |
| EnsureSamePeers 只在重试前读取预期配置，之后不更新 | 多轮 baseline 观察到成员变更后 helper 假失败；[#711](https://github.com/hashicorp/raft/issues/711) 报告相同测试形态，开放 [#718](https://github.com/hashicorp/raft/pull/718) 只增加等待时间 | 不计生产共识缺陷；可在以后授权后补充固定期望值的根因证据 |
| fuzzy transport 缺少 RequestPreVote 解码 | [#678](https://github.com/hashicorp/raft/pull/678) 已包含修复；本地准备副本已显式修正并记录 | 不重复提交，不将其混入新发现数量 |

相关 baseline 记录见 [10-11 归档](https://github.com/SuzumiyaHaruki/consensus-assurance/blob/e9d265c912ce601dbceaafe58e3d2a3724e568a3/baseline/runs/2026-10-11_16-25-33-hashicorp_raft-baseline/work/report.md)。

## 6. 暂不列为明确新缺陷的观察

| 观察 | 尚缺的关键依据或已经发现的反证 |
| --- | --- |
| BatchingFSM 与 ConfigurationStore 组合时没有 StoreConfiguration 回调 | ApplyBatch 实际收到配置日志，且 [#364](https://github.com/hashicorp/raft/pull/364) 有相应设计背景；属于组合合同需要澄清，不能直接宣称丢配置 |
| 截断日志后 StoreLogs 失败，lastLog 缓存未回退 | 源码已有 TODO；局部构造 RPC 观察尚未补足真实 Leader 的后续生产路径，不直接宣称已证明完整提交错误 |
| shouldSnapshot 无符号差值下溢 | 局部判断和冗余快照已观察；公开 Restore 路径的后续测试遇到 trailing noop 保护，不能声称默认流程无限快照 |
| AddVoter 未实现 staging | [#486](https://github.com/hashicorp/raft/pull/486) 已解释历史设计和 autopilot 职责，旧文档不足以单独确立新缺陷 |
| TimeoutNow 的重复或延迟消息引发选举 | 部分实验缺少合法生产者、兼容前史，不能直接扩大成任意节点夺权；与 H5 的公开 API 资格遗漏分别处理 |
| commit index 滞后、LogCache 不暴露提交追踪接口 | 前者可能符合“下一次写入时保存”的合同，后者涉及可组合性义务；不能凭观察自动判为安全缺陷 |
| 直接并发修改导出的 RestoreCommittedLogs 字段 | 没有证明支持运行期线程安全热更新，字段导出本身不是该义务 |
| 未知日志类型、非法编码触发 panic | 尚未建立正常 CFT 生产者能够产生这些输入，不作为明确共识缺陷 |

## 7. 本轮验证与发布记录

本轮未运行全量测试或付费模型实验。除读取已有固定测试和原始回执外，只在 `/tmp` 的未修改 v1.8.0 副本中运行四个短测试：成员恢复关闭对照通过、成员恢复开启时配置丢失、队列恢复关闭对照通过、队列恢复开启时在预期发送位置超时。目标源码和历史运行未修改。

| 上游条目 | 创建内容 | 最终状态 |
| --- | --- | --- |
| [#725](https://github.com/hashicorp/raft/issues/725) | VerifyLeader 非投票确认 | 用户要求撤回，已关闭 |
| [#726](https://github.com/hashicorp/raft/issues/726) | 配置写入失败后仍生效 | 用户要求撤回，已关闭 |
| [#727](https://github.com/hashicorp/raft/issues/727) | 显式转移接受非投票目标 | 用户要求撤回，已关闭 |
| [#728](https://github.com/hashicorp/raft/issues/728) | 启动恢复遗漏成员配置 | 用户要求撤回，已关闭 |
| [#729](https://github.com/hashicorp/raft/issues/729) | 启动恢复队列死锁 | 用户要求撤回，已关闭 |

关闭保留公开页面，并不等于删除。上述撤回不改变原始执行证据，也不代表维护者已经认可或否定结论。后续先在本文维护证据与状态，发布动作单独等待用户明确授权。
