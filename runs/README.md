# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-24 16:33 HashiCorp 真实运行](2026-09-24_16-33-34-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。采用 A1/A2 重点、`gpt-6-astra` / `low`、框架版本 `native-products-v22`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 8/40 次；1331.92/1500 秒（约 22.2 分钟） |
| 候选与检查 | 4 个候选；2 个审计单元；2 次正式直接检查、1 次探索执行 |
| 局部模型与校准 | 均为 0 |
| 局部结果 | 失败的内存 timeout future 被调用 Response；带部分 Success=true 的网络响应在 EOF 解码失败后仍推进 peer match |
| 停止原因 | Agent 主动结束已完成的局部检查；未建立支持继续扩展到不安全决定的具体前提 |

第二项检查中，截断响应使 peer match 从 0 推进到 2；空输入对照保持 0，完整响应对照推进到 2 且无错误。所有观察到的 commit index 均为 0。生成完整响应的端点是脚本化 fixture，未关联真实 follower 存储执行，因此上述结果只限于局部接口使用与响应接受，不能据此确认虚假持久支持、错误 quorum 决定或共识安全失败。原始源码解释、探索输出、正式检查、复核、未知和范围限制分别保留，具体依据见原报告和 state.json。

按用户要求，将 Git 追踪从 `2026-09-24_10-23-51-hashicorp_raft-real-run` 切换到本次运行。此前追踪的运行保留在本地，也可从 Git 历史取得；此切换不删除其他实验。

归档排除临时锁、`.execution` 缓存、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照、原生草稿、正式制品、实验输入差异、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
