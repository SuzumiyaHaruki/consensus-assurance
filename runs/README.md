# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-27 10:33 HashiCorp 真实运行](2026-09-27_10-33-24-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。采用 A1/A2 重点、`gpt-6-astra` / `low`、框架版本 `native-products-v23`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与耗时 | 16/40 次；1500.06/1500 秒，耗尽 25 分钟总预算 |
| 研究地图与候选 | 2 个地图版本；2 个候选，分别为 explained、escalated |
| 检查与复核 | 4 次探索执行、1 次正式直接检查、1 次对应性复核 |
| 模型与校准 | 均为 0 |
| 当前结果 | 1 个 pending Unit；Evidence 0，Finding 0；无已确认问题 |
| 停止 | 最后一次原生调用只剩约 26 秒并超时；原记录分类为 tool_gap，实际限制为总时间 |

正式输出记录：在手工初始化的三投票者场景中，F 实际当选 term 8 leader 后，L 的公开 `VerifyLeader().Error()` 仍借此前产生、延迟交付的 term 7 回复返回成功。这是有条件的局部观察；构造器启动、L 的初始当选、完整 worker 并发和应用读取后果尚未执行。

检查器记录 `violated`，但同时因 `fresh` 对照事件被错误地先做前置条件关联而标记不完整，因此没有生成 Evidence。原计划已有场景适用条件；问题在检查器的判断顺序。研究索引遗漏具体不完整原因、停止提交被对象校验拒绝，也增加了收尾成本。详见 [实验分析](../docs/实验分析-2026-09-27-HashiCorp.md)，其中区分实际观察、框架问题和未验证的系统后果。

按用户要求，将 Git 追踪从 `2026-09-24_16-33-34-hashicorp_raft-real-run` 切换到本次运行。此前追踪的运行保留在本地，也可从 Git 历史取得；此切换不删除其他实验。

归档排除临时锁、`.execution` 缓存、原生草稿临时目录、可重建的 `experiments/**/workspace` 和本地权限配置；保留源快照、原生草稿、正式制品、实验输入差异、结果和日志。其他 runs 不纳入 Git。归档不作为 runtime discovery 答案；不同框架版本需要显式迁移或新运行。
