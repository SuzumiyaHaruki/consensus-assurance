# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-24 10:23 HashiCorp 真实运行](2026-09-24_10-23-51-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。运行采用 A1/A2 重点、Codex Astra `low`、框架版本 `focused-continuation-v20`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 18/40 次；1588.18/2400 秒 |
| 候选与检查 | 2 个候选；1 次实际直接检查完成，另一个候选仍在调查 |
| 局部模型与校准 | 均为 0 |
| 局部结果 | `pipelineDecode` 对已交付 future 的响应访问顺序与文档前提不符；仅确认局部接口问题 |
| 停止原因 | Derivation 中候选与父候选关联需要明确的语义决定；保留原始失败与未决调查 |

直接检查使用替代完成生产者和空条目请求；未执行内建网络 pipeline，也没有证明投票端点、提交或应用后果。原始回复、观测、限制、失败和本机绝对路径按运行产物保留。

2026-09-24 按用户要求，将 Git 追踪从 `2026-09-23_13-02-24-hashicorp_raft-real-run` 切换到本次运行，并与当前代码修改一同提交、推送到 `main`。此前追踪的运行保留本地，也可从 Git 历史取得；此切换不删除其他实验。

归档排除临时锁、`.execution` 缓存、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照及实验输入、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
