# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-28 18:02 HashiCorp 真实运行](2026-09-28_18-02-29-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`。采用 `gpt-6-astra` / `low`、框架版本 `audit-products-v29`、通用 `go_module` 执行后端；无定向问题、fixture 或协议知识包，未启用 TLA+／TLC。

预算为 40 分钟、40 次 Agent 调用、8 次目标执行。实际耗时 1692.17 秒（约 28 分 12 秒），使用 8 次 Agent 调用，完成 2 次正式直接检查和 2 次语义复核；没有正式探索执行或退稿。停止时剩余 707.83 秒和 32 次调用。第 8 轮因 Codex 返回内容安全错误中断，未完成回执；不是总预算或动作超时。依据见[最后执行记录](2026-09-28_18-02-29-hashicorp_raft-real-run/logs/c0c56bbeb4934849860259ecde34b574/check.json)、[原始错误](2026-09-28_18-02-29-hashicorp_raft-real-run/logs/c0c56bbeb4934849860259ecde34b574/stdout.log)和[状态记录](2026-09-28_18-02-29-hashicorp_raft-real-run/state.json)。

两项正式结果均为限定范围内的 VerifyLeader 实现义务违反，使用隔离源码副本中的 Go 直接检查及实际对应性复核：

- **非投票节点被用作验证支持。** 固定三个 voter、一个 nonvoter 的配置，经实际选举与 Apply 建立前缀。排空旧回复并暂停两个远端 voter 的普通复制与心跳发送后，只放行 nonvoter，VerifyLeader 仍成功：`voter_replies=0`、`nonvoter_replies=3`、`success=true`。只放行 voter 的对照组也成功。命题是验证参与者资格，回复次数不等于内部投票次数，不能把它写成 nonvoter 投了三票。见[原始观察](2026-09-28_18-02-29-hashicorp_raft-real-run/logs/a5644db0464f44ccb5dfc352dcff28b0/stdout.log)及[固定测试](2026-09-28_18-02-29-hashicorp_raft-real-run/direct-checks/2a3711628c58423587c2ef66f2df64ee/assurance_generated_test.go)。
- **旧上下文的回复使过期 leader 验证成功。** 固定三个 voter，在 term 2 实际生成并扣留回复，再隔离旧 leader，由其余节点真实选出 term 3 的新 leader。新 leader 的 index 5 命令完成后，才调用旧节点的 VerifyLeader 并释放扣留回复；旧节点仍在 term 2，却返回成功，其 FSM 中没有该新命令。当前 leader 对照成功且包含该命令。正式命题是新权威已在调用前建立时旧验证不应成功；FSM 内容是附加观测。见[原始观察](2026-09-28_18-02-29-hashicorp_raft-real-run/logs/a00213ac48c64ad09b67140a5fa792fe/stdout.log)及[固定测试](2026-09-28_18-02-29-hashicorp_raft-real-run/direct-checks/adb25a646ba74d49b3c36b835a6c4601/assurance_generated_test.go)。

两项结果分别检验支持者资格和回复上下文的新鲜性，使用独立义务，没有因为共享 VerifyLeader 路径而合并。已保存的实际见证和复核均无当前 blocker。执行条件包括内存存储、受控传输延迟、禁用可选 pipeline；第二项还通过公开 ReloadConfig 调整远端超时，使新选举在旧 leader 的租约到期前完成，租约和协议线程仍运行。未执行真实 TCP 调度、等超时部署或一般性日志安全验证。测试 PASS 表示测量执行完成；性质违反由关联事件与独立比较判定。完整条件见报告和研究索引，不因后续调查被拦截而撤销两项已完成结果。

本轮第一层优化已有真实运行证据：Agent 在同一会话调用预检，日志保留 10 个结构化结果（2 次拒绝、8 次通过）。初始地图的生产者／消费者未知说明及主线引用缺项、随后问题的来源缺项，都在各自工具回合内修正，正式受理未发生退稿。首项正式检查在启动约 15 分 12 秒后完成。此前保留运行有 5 次正式退稿、首次检查约 24 分 45 秒；两次自主选题和上下文不同，不能将时间差全归因于预检或承诺固定提速。

当前地图保持 v1，两次独立义务使用同一已建立的双主线关系，检查后反馈随复核／下一义务正式保存。普通反馈进入当前交接，报告直接展示两项确认，当前 capacity 与最终 state 一致，没有重复顶层预算。此次没有提交 feedback-only 产品，因此不能把它当作独立轻量交接的真实实验验收；也没有验证新增地图知识后的继续调查。Pipeline 仅保留源码调查结论与具体缺口，未作为第三项执行发现。

网安拦截发生在最后一轮准备调查存储故障时：Agent 声明要检查部分写入是否影响后续投票，随后只读查看 stable store、`raft.go:1685–1733` 的重复投票分支和 `raft.go:2130–2148` 的投票／term 持久化。该工具命令退出 0，接着原始 JSONL 第 6、7 行出现 `error`／`turn.failed`，内容为 `This content was flagged for possible cybersecurity risk`；stderr 为空，未生成第三项可靠产品。这将失败定位到 Codex 的内容安全处理，未见本地预检、沙箱权限或目标执行失败。框架如实保存失败并停止，没有将拒绝后的草稿自动受理。

对照本地 12:40 旧运行，同样的错误出现在读取 `DeleteRange → StoreLogs` 失败后的日志状态及其投票／复制影响时；本次是 `SetUint64(LastVoteTerm) → Set(LastVoteCand)` 的部分写入及其重复投票影响。共同上下文是共识实现的存储故障与可复现的安全性质调查，但日志没有分类分数、命中的规则或具体触发片段，不能断言某个词、某行代码、账户限制或某个已确认发现就是原因，也不能据此认定正式目标有第三个漏洞。两次位置相似只支持这一排查方向，不证明服务端因果。

[OpenAI 官方说明](https://developers.openai.com/codex/cyber-safety/)承认合法研究或无关活动也可能被安全措施拦截，并建议通过可用的 `/feedback` 报告疑似误报；授权网络安全工作的访问资格由 Trusted Access／Daybreak 按身份和产品入口审批。若需要提交误报材料，可提供本次会话 `01a0e777-4da5-75f1-8ed0-8f21aa6bbcc7`、北京时间 18:30:02–18:30:41、Codex 版本 `0.155.0-alpha.16` 和上述最后日志。当前分析未发送反馈、变更账号配置、换模型或重试实验。服务端的精确分类原因仍需服务方确认，放宽本地隔离或提高超时不能据此解决内容审查。

本次同时提交 v29 系统修改与上述实验，将 Git 追踪从 `2026-09-28_14-56-02-hashicorp_raft-real-run` 切换到本次运行；旧运行保留在本地及 Git 历史中。系统修改此前完成 193 项相关测试，后续对应路径补测 61 项通过，本次归档不重跑全量测试。归档排除凭据、虚拟环境、临时锁、`.execution`、草稿临时目录与编译缓存、可重建的 `experiments/**/workspace` 和本地权限覆盖配置；保留源快照、草稿、固定制品、版本记录、实验输入差异及原始失败。归档不作为新实验的发现输入。
