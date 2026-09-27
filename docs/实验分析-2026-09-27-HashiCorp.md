# HashiCorp 实验分析（2026-09-27 10:33）

本次运行建立了显式研究地图，并沿一个问题连续改进实际检查，得到有价值的局部异常观察；但没有完成 Evidence 归档和义务收尾，也没有确认共识安全问题。结束的直接原因是 25 分钟总预算耗尽。检查器和研究流程中的具体缺陷增加了不必要的修复成本，不能把这次结束简单归因于 Codex 不会调查或目标测试卡死。

本分析读取保存的源码、草稿、执行日志、评估和当前控制器代码，并用既有事件离线重放监视器。没有重跑目标测试、启动新的模型调用、运行完整测试集或修改原始实验结论。

## 运行与资源

原始入口：[报告](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/report.md)、[状态](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/state.json)、[研究索引](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/research.json)。

| 项目 | 记录 |
| --- | --- |
| 目标 | `/home/nitro/Desktop/hashicorp-raft`，提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，无工作区修改 |
| 方法 | real / autonomous，A1/A2 重点，`protocol=none`，`native-products-v23` |
| Agent | `gpt-6-astra` / `low`，一个原生会话 |
| 总预算 | 1500 秒、40 次 Agent 调用、8 次目标执行 |
| 实际消耗 | 1500.06 秒、16 次 Agent 调用、5 次目标执行 |
| 产品 | 地图 v1/v2，2 个 Candidate，1 个 Unit，1 个正式直接检查，1 次复核 |
| 执行种类 | 4 次探索、1 次正式直接检查；没有模型或校准执行 |
| 收尾状态 | Unit pending，Evidence 0，Finding 0，未关闭义务 1 个 |

15 次原生调用完成：9 次提交受理、6 次提交被拒；第 16 次超时。返回被拒草稿的调用共耗时 626.60 秒，占总时间约 41.8%。这些调用也包含调查和构造，不能全部算作纯浪费。5 次目标执行合计 66.96 秒，主要时间消耗在原生调查与提交往返。

最后一次调用从北京时间 10:57:58.350 到 10:58:24.403，约 26.05 秒，退出码 -9。[调用回执](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/logs/69b1d7667a9641a483e920a57b45ae20/check.json)记录 `Action timeout exceeded; process group killed`。控制器以 `min(remaining, native_turn_timeout)` 设置调用期限，结束时剩余秒数为 0、剩余调用数为 24。因此触发的是总时间边界，不是耗尽调用数，也不是某个 Go 检查运行了 600 秒。原记录的 `run_stop.reason=tool_gap` 是分类问题：预算内调用以超时异常退出后被归入工具缺口，未正确体现总预算耗尽。

## 实际调查了什么

第一个 Candidate 研究较新任期的拒绝回复仍刷新 heartbeat contact，是否让 lease 消费者误用旧权威。地图将 `b-heartbeat-contact`、`b-lease-consume` 与 `f-heartbeat-contact` 的消费关系接起来。源码解释指出，lease 接口约束的是联系状态；普通或流水线复制的较新任期回复，以及仍待完成的验证收到否定票，另有退位路径。因此“contact 被直接强化为任期认可”的局部猜测被 explained。及时退位的时间界、合法延迟调度和读写后果仍未知；源码解释没有冒充执行 Evidence。

第二个 Candidate 转向验证支持的新鲜性：请求登记前已产生的成功回复，之后被交付，能否使旧 leader 的公开验证成功。地图 v2 加入 `b-verify-positive-threshold`、`b-verify-success-consume`、`f-verify-threshold`。4 次探索依次补上内部支持阈值、真实接收端产生回复、公开 Future 完成、真实替代选举；再合并提交 Candidate、局部义务和正式检查。这个过程说明调查能够在同一会话内连续缩小证据缺口，而不是机械地做完一张地图就停止。

正式 Unit 为 `unit-verify-no-success-after-replacement`，义务为 `verify-no-success-after-replacement`。判据是：若另一投票者已在调用前赢得较新任期的多数支持，且 L 没有重新取得领导权，则 L 不应仅凭此前扣留的回复完成成功验证。规范依据来自实际 API 和仓库文档，检查范围明确保留初始状态假设。

## 正式执行观察及其边界

[固定计划](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/direct-checks/973ac7105eae4590a963ef51f7c9992a/plan.json)、[测试制品](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/direct-checks/973ac7105eae4590a963ef51f7c9992a/assurance_generated_test.go)、[原始输出](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/logs/cf548422b333468f8168df15d712e0d1/stdout.log)共同记录了如下顺序。事件索引从 0 开始。

| 索引 | 场景 | 实际观察 |
| --- | --- | --- |
| 0 | elected_before_verify | 接收端产生 term 7、success=true 的回复；此时尚未调用验证 |
| 1 | elected_before_verify | F 实际走 follower/candidate 路径，在 term 8 成为 Leader；N 持久保存 term 8 投票 |
| 2 | elected_before_verify | 调用 L 的公开 VerifyLeader，登记完成，释放回复前仅有一次 heartbeat RPC |
| 3 | elected_before_verify | 交付旧回复后，公开 Future 完成且返回成功；F 为 term 8，回复仍为 term 7 |
| 4–6 | fresh | 无替代选举的对照：验证触发回复，公开 Future 同样完成成功 |

这不是直接把 `success=true` 填进观测字段：测试调用真实 `appendEntries`、`requestVote`、`runCandidate`、heartbeat 和公开验证完成路径。目标 Go 测试退出 0 表示采集程序正常结束；真正的否定性质由控制器比较，因此测试 PASS 与局部 `violated` 可以同时出现。

但测试直接初始化 `Raft`、任期、leaderState、配置索引及部分持久状态，没有执行 `NewRaft`、L 初始当选及完整日志前史。只启动部分 worker，普通复制、N heartbeat、新 leader 的 runLeader/noop、真实网络分派未整体运行。L 的 lease 和选举相关超时为一小时，F 使用较短且经过 ValidateConfig 的超时；pre-vote 被关闭。完整集群是否存在同样合法窗口仍待证明。没有执行应用旧读、FSM 新鲜性或分叉提交，不能把局部结果提升为这些系统后果。

复核 `b4662ab899104aa3b5c36e71ce174c50` 为 `no_issue_found`，并保留上述条件。它只针对该制品的局部对应性，是同一调查会话内的判断，不是独立证明或另一个投票。

## 为什么有 violated 却没有 Evidence

这里有可直接复现的控制器问题，不是 Agent 忘记声明场景选择条件。

正式 monitor 已声明三个适用条件：`operation == elected_before_verify`、`completed == true`、`calls == 1`；共享性质按 `operation` 关联事件，要求 `success == false`。索引 3 满足前置事件关联，且违反这一否定性质。

但 [observations.py](../src/consensus_assurance/workflow/observations.py) 的 `monitor_events` 先执行前置条件关联，之后才判断 `applicability_conditions`。对索引 6 的 `fresh` 结果，前置条件要求替代选举，关联自然失败；代码随即记录 missing 并跳过，来不及发现它本来就不属于该 monitor 的场景。

对保存的 7 个事件和原计划离线重放，结果与原评估一致：

```text
outcome: violated
witness_indices: [3]
missing_indices: [6]
outside_applicability_indices: []
fresh 的三个适用条件: [False, True, True]
```

所以当前 `comparison_complete`、`bounded_complete`、`reviewed_complete`、`confirmed` 都是 false。[direct_checks.py](../src/consensus_assurance/workflow/direct_checks.py) 遇到不完整比较时不创建 Evidence，Unit 继续 pending。无 open issue、复核通过、顶层 `blockers=[]` 都不会自动覆盖该状态。

另一个诊断缺陷在 [modeling.py](../src/consensus_assurance/workflow/modeling.py)：未完成摘要只拼接顶层 blockers，漏掉 `properties[].limitations`，于是研究索引只显示 `Direct check … is incomplete: `。Agent 在最后停止草稿中准确报告了这个空原因，却无法从当前摘要获得具体修复方向。

后续应在现有监视器中处理可独立判定的适用范围，再做必要的前置关联；依赖前置事件别名的条件和真正缺失的字段仍须保持不完整，不能把所有关联失败都当作范围外。修复时保留原始评估，另行记录修复后的解释；若更改已执行 checker/harness，应按现有制品规则重新执行、复核。

## 提交往返与收尾问题

6 次拒绝均留存原稿和诊断：

| 提交前缀 | 拒绝原因 | 分析 |
| --- | --- | --- |
| 32d11948 | Question Behavior 与主 Fact 的关系不符 | 上下文接收端行为被列入直接 Fact 关系；下一稿修正。保留这种实质关联约束有价值 |
| e5aa7874 | 未解释删除反证/未知 | 原 unknowns 被细化改写，但缺独立的 resolution 字段 |
| 97ba9a20 | 同一错误再次出现 | 已添加详细来源化解释，但反馈 ref_ids 只有已接受操作 ID；代码额外要求 ref_ids 包含 Material ID，未在错误中指出 |
| 6a6a0454 | Refine the current inventory version | 草稿填 version=2，接口要求提交旧 version=1 再由控制器递增；原错误没有给出期望值 |
| e866c09f | 两个 Binding 缺已验证的声明锚点 | 补读完整源码区间后受理；不应为减少往返而删除来源身份要求 |
| 86e7ac49 | Work disposition must identify current unfinished work | resource_limit 停止已列出 pending Unit，同时列出其已升级 Candidate，后者不在派生待办集合，导致整份停止被拒 |

反证保护目前把 unknowns 的文字改写也按“删除反证”检查。第三次 explained 提交通过的方式是保留所有旧 unknowns 再追加新描述；这保留历史，却也让已被部分回答的问题继续混在当前未知中。应使已有来源解释能够明确更新当前未知，历史由 Candidate.history 保留；不能用强制原文累加代替语义回流。

最后的[停止原稿](../runs/2026-09-27_10-33-24-hashicorp_raft-real-run/native-submissions/86e7ac493a02448093b966f1ca1ac50e/raw.json)明确选择 `scope=run / reason=resource_limit`，保留 pending、条件边界和恢复步骤，没有声称 focus 完成。`pending_work` 已用 Unit 代表该 Candidate 的未完成工作，但 `record_decision` 对额外 Candidate ID 仍整体拒绝；资源退出的豁免没有覆盖此校验。接下来只剩约 26 秒，修复停止草稿的调用最终超时。需要改进资源退出的记录能力和精确诊断，不应要求临近截止时再靠一次模型调用才能诚实停止。

## 方法效果与后续优先级

相对 9 月 24 日所选运行的空地图、空 Behavior/Fact 引用，本次真实 Codex 建立并使用了地图、依据关系、候选解释、局部义务和实际执行反馈。它没有把单次观测改写成通用 Fact，保留了未展开的 A1/A2 范围。这是本次方法链生效的具体证据，但一次运行不能证明所有语义判断可靠或整体覆盖改善。

当前最优先的是修复已有控制器的三个局部问题：适用范围与前置关联顺序、不完整原因的完整传递、资源退出的收尾与分类。接着减少解释更新和地图版本的非语义往返，保留来源边界，不增加另一套调度框架。目标调查的下一判别应是通过构造器启动三个节点、实际建立初始 leader、保留普通复制 worker，仅用受控传输延迟复现同一替代选举和公开验证顺序；增加调用次数本身不能解决这些证据缺口。

本次提交包含此前完成的研究链代码、资源和测试修改，以及本分析和选定实验归档。此前离线修改的 155 项定向验证及其限制见 [研究链流程验证](研究链流程验证.md)；那份文档描述修改当时的验证状态，本次真实运行补充了自主使用效果，也暴露了上述尚未修复的真实流程问题。
