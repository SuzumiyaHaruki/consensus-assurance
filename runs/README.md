# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-27 17:26 HashiCorp 真实运行](2026-09-27_17-26-13-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。采用 `gpt-6-astra` / `low`、框架版本 `native-products-v25`、`hashicorp_raft` 执行后端；无定向问题、fixture 或协议知识包，未启用 TLC。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 13/40 次；1290.90/1500 秒，约 21 分 31 秒 |
| 研究地图与候选 | 3 个地图版本；2 个已受理候选，另有 1 个未受理的领导权验证问题 |
| 检查与复核 | 1 次正式直接检查、1 次受理的对应性复核；另有原生草稿本地反馈 |
| 模型与校准 | 均为 0 |
| 当前结果 | 1 个 checked Unit；1 条范围内确认的接口调用顺序违约，未确认共识安全后果；1 个源码解释完成的候选 |
| 停止 | 连续 4 次整稿校验失败；剩余约 209 秒、27 次调用、7 次正式执行额度 |

正式检查使用转发观测包装器调用实际 `pipelineDecode`，真实内存流水线分别产生超时和成功 future。两种情况下，均观察到 `Response()` 访问前未调用同一 future 的 `Error()`；单独的合规对照先调用 `Error()`，记录的顺序正确。这与 `transport.go:137–140` 的显式接口约定不符。Go 测试 PASS 表示观测程序完成，性质判定来自事件检查器的 violated。证据见[固定计划及测试](2026-09-27_17-26-13-hashicorp_raft-real-run/direct-checks/49dd69ed2a0341d88e62bbd108a13636/plan.json)和[实际执行日志](2026-09-27_17-26-13-hashicorp_raft-real-run/logs/2f0f1d4acd0140a89420299dcb3e1288/stdout.log)。

该结论限于局部接口顺序：producer 已完成后才发布 future，超时响应为 Success=false；没有执行网络流水线，也没有建立合法选举、错误提交或应用旧读后果。后续快照问题由源码解释：接收方等待 sink.Close 和真实 FSM Restore 完成才返回成功，发送方也检查错误、任期和 Success。它不产生执行 Evidence，也不证明快照持久性和新鲜性。

最后的新问题关注更高任期领导者完成写入后，旧领导者能否仅凭 Nonvoter 联系让 VerifyLeader 成功。第 10–13 次调用依次被 Activity 坐标、缺失 Activity、责任关联、缺失 `grounding.applicability` 拒绝；最后一稿已有 derivation，但没有 applicability。该问题未受理、未执行，不能报告为缺陷。由于尚无对应的已受理候选，局部失败交接没有接住它，连续退稿触发了全局停止，而非超时或服务端拒绝。原稿和诊断保留在 [native-submissions](2026-09-27_17-26-13-hashicorp_raft-real-run/native-submissions/)。

本次 8/13 次提交被拒，对应调用耗时约 641 秒，约占总耗时一半；退稿中也有实际调查，不能全视为浪费。报告还保留了一处状态不一致：第一个 Unit 已 checked，但其 paused 候选的旧 unknown/resume_conditions 仍称尚待执行直接观测。该归档保留原状态，不事后修写实验结果。

独立性记录：初次调用为 `session_id: null、turn: 0`；显式关闭记忆读取和生成；先提交当前源码导出的 A1 部分地图，再形成接口义务、执行、复核、解释快照问题并继续选题。38 条工具命令中未发现访问其他运行目录或记忆文件的记录。后来选到相似领导权问题之前有本轮配置、VerifyLeader 和 future 源码阅读记录；相似选题本身不证明复用了历史答案。

按用户要求，将 Git 追踪从 `2026-09-27_13-22-02-hashicorp_raft-real-run` 切换到本次运行，连同当前代码修改提交。此前实验仍保留在本地及 Git 历史中。归档排除临时锁、`.execution`、原生草稿的 tmp/local-tmp/local-cache、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照、原生草稿、正式制品、实验输入差异和原始日志。归档不作为新实验的发现输入。
