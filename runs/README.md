# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-28 14:56 HashiCorp 真实运行](2026-09-28_14-56-02-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`。采用 `gpt-6-astra` / `low`、框架版本 `audit-products-v28`、通用 `go_module` 执行后端；无定向问题、fixture 或协议知识包，未启用 TLA+／TLC。

预算为 40 分钟、40 次 Agent 调用、8 次实验。实际耗时 2400.12 秒，使用 16 次 Agent 调用，完成 2 次探索实验、2 次正式直接检查和 2 次语义复核。最后一轮的实际期限是总预算剩余的 98.42 秒，随后进程组被终止；停止时仍剩 24 次调用额度。这次停止来自总时间耗尽，未出现上次的网安拒绝。依据见[最后执行记录](2026-09-28_14-56-02-hashicorp_raft-real-run/logs/1ad2dda3f9c845a38bc9778f53630b9a/check.json)和[状态记录](2026-09-28_14-56-02-hashicorp_raft-real-run/state.json)。

两项正式结果均为限定范围内的实现义务违反，使用隔离源码副本中的 Go 直接检查：

- VerifyLeader：真实选举、配置变更和分区形成三个 voter、一个 nonvoter 的历史。B 在 term 3 完成 index 8 的命令应用后，仍处于 term 2 的 A 的 VerifyLeader 返回 nil。保留了旧 voter 回复排空、新 leader 应用与目标操作完成的关联观察。适用范围包括异构超时、内存存储和禁用可选 pipeline；未证明实际应用旧读、冲突提交或非投票节点回调的唯一因果归属。见[原始输出](2026-09-28_14-56-02-hashicorp_raft-real-run/logs/f3ad8013413542dd8759d95a1e2347b5/stdout.log)。
- Pipeline：真实双节点运行中，记录到同一 AppendFuture 的 Response 在 Error 尚未返回时被调用，违反源码接口的显式访问顺序约定。该次响应有效且 Apply 完成；生产者在发布 future 前已经完成它，这是限制危害推断的重要机制。结果未证明错误提交、响应数据损坏或应用失败。见[原始输出](2026-09-28_14-56-02-hashicorp_raft-real-run/logs/59614562669b48149511f09b7690de2d/stdout.log)。

测试进程的 PASS 表示测量完成；性质违反由实际事件和独立比较得到，不能将 PASS 解释成性质成立。详细适用性、检查对应关系和未建立后果见[报告](2026-09-28_14-56-02-hashicorp_raft-real-run/report.md)与[研究记录](2026-09-28_14-56-02-hashicorp_raft-real-run/research.json)。

第三个方向仅完成探索：候选人字节写入失败而 term 写入成功时，保存的配对变为 term 4／候选人 A，随后 A 的旧日志请求获准；无故障控制组保存 term 4／B 并拒绝该请求。该测试通过 BootstrapCluster 和实际 processRPC 构造接收端状态，但使用受控 RPC 输入且通过 skipStartup 省略后台工作线程。仍缺真实存储后端的失败约定、完整远端生产者历史和系统后果，不能提升为第三项确认。见[探索输出](2026-09-28_14-56-02-hashicorp_raft-real-run/logs/da9b654016f545318f870d580690ad76/stdout.log)。最后的[回流草稿](2026-09-28_14-56-02-hashicorp_raft-real-run/draft/submission-vote-frontier.json)已经写出，但 Agent 在返回回执前超时，未受理到当前 v5 地图或正式 Candidate。

本轮完成了双主线理解、第一次检查、共享地图增量补充、保留前一结论后换题、第二次检查和第三方向探索。仍有 5 次退稿：未知适用性缺具体缺口、引用行号越界、主线概述缺 Fact／来源、问题缺关联来源、复核提交到未请求的对象；对应调用耗时合计约 15 分 25 秒，包含有效调查，不能全部计为纯修复浪费。首次正式检查在运行约 24 分 45 秒后完成。研究投影顶层 remaining_seconds／remaining_agent_calls 仍为末轮开始前的数值（98.45／25），最终 stop 和 state 记录为 0／24；报告交接中的“Pipeline ordering has not yet executed”也是交接时历史，第二项检查实际已完成。分析应以最终执行和结论记录为准，不能把这些旧值当作当前待办或预算。

本次将 Git 追踪从 `2026-09-28_12-40-13-hashicorp_raft-real-run` 切换到上述运行，旧运行保留在本地及 Git 历史中。归档排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录与编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置；保留源快照、草稿、固定制品、版本记录、实验输入差异及原始日志。归档不作为新实验的发现输入。
