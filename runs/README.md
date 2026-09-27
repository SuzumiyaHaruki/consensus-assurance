# 保留运行

当前 Git 仅追踪用户指定的 [2026-09-27 20:36 HashiCorp 真实运行](2026-09-27_20-36-05-hashicorp_raft-real-run/report.md)。目标为 `/home/nitro/Desktop/hashicorp-raft`，源码提交 `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`，快照记录工作区无修改。采用 `gpt-6-astra` / `low`、框架版本 `native-products-v26`、`hashicorp_raft` 执行后端；无定向问题、fixture 或协议知识包，未启用 TLC。实际工具为 Codex CLI `0.155.0-alpha.16`、Go `1.25.8`。

| 项目 | 实际记录 |
| --- | --- |
| Agent 调用与总耗时 | 12/40 次；1500.11/1500 秒，约 25 分钟 |
| 初始理解 | 1 个已受理地图版本；7 类 Activity、19 个 Behavior、8 个 Fact、5 个 Surface；双主线概览为 usable，数量不代表覆盖完整 |
| 问题与执行 | 2 个已受理 Candidate；1 个 checked Unit；1 次正式直接检查，含两个独立子场景；1 次受理复核 |
| 结果 | 1 条范围内确认的 VerifyLeader 支持资格义务违反；1 个源码解释完成的问题 |
| 模型与校准 | 均为 0；不能据此评价模型工具增益 |
| 退稿 | 6/12 次；对应调用耗时 930.61 秒，约占总耗时 62%，其中也包含实际调查与构造 |
| 停止 | 总时间耗尽；最后一次调用仅剩 30.78 秒，超时后进程组被终止；仍余 28 次 Agent 调用和 7 次正式实验额度 |

## 初始理解与实际检查

首轮实际阅读覆盖 Apply、复制与提交、FSM 完成、选举与投票、领导权失效、成员资格、快照和恢复。第一次组合提交因 Fact 的未映射消费者、问题直接边及引用不足被拒；第二次在约 8 分 40 秒时受理[双主线概览和首个问题](2026-09-27_20-36-05-hashicorp_raft-real-run/audit-spec/v1.json)，此时尚未生成义务或正式执行。概览解释了操作形成决定、权威取得和失效、旧 worker／回复的归属，以及配置和持久化对两条主线的约束。它比上一轮仅有复制片段及 leader 初始化的地图更完整，但 usable 仍是有来源的分析判断，不是实现正确性的证明。

首个问题检查固定混合成员配置下，Nonvoter 通知是否能替代 VerifyLeader 所需的 voter 支持。[固定测试程序](2026-09-27_20-36-05-hashicorp_raft-real-run/direct-checks/b9d3b158da904229a7c1eb7191468b14/assurance_generated_test.go)调用真实 BootstrapCluster／NewRaft，建立 3 个 voter 和 1 个 nonvoter；等待实际选举，完成 Apply 并检查 FSM 返回，通过 GetConfiguration 核对成员身份与角色。测试采用接口允许的非 pipeline 传输，在各远端的串行复制和心跳发送线程进入下一次调用时暂停请求；六个线程全部到达后才调用 VerifyLeader，用这段源码对应关系排除此前尚未消费的回复。没有直接设置协议关键状态，也没有直接注入 notifyAll(true)。

[正式执行日志](2026-09-27_20-36-05-hashicorp_raft-real-run/logs/13d1ff41f04c4d28a41c8b0eaee0560d/stdout.log)记录了两个各自拥有合法前缀的独立场景：

| 场景 | 合格支持上界（含自身） | 阈值 | 公开结果 |
| --- | ---: | ---: | --- |
| voter_control：放行全部成员 | 3 | 2 | VerifyLeader.Error() 返回 nil |
| nonvoter_only：仅放行 n0 | 1；远端 voter 放行数为 0 | 2 | VerifyLeader.Error() 仍返回 nil |

nonvoter_only 中真实 n0 心跳及复制回复已产生，完成时仍处于同一 term 2／Leader。其他 voter 的回复出现在结果后的清理放行阶段，不能解释先前已经完成的 future。检查器用实际正向 voter 返回数的上界判定；它不证明每条回复确实被消费，但当上界也不足时，足以排除合格 voter quorum 解释。源码对应为：verifyLeader 的阈值取 voter 数，却向全部复制 peer 登记 future；vote(bool) 不再携带成员身份和 suffrage。

控制器将该结果记录为 `implementation_semantics`／`implementation_obligation`，见[固定计划](2026-09-27_20-36-05-hashicorp_raft-real-run/direct-checks/b9d3b158da904229a7c1eb7191468b14/plan.json)和[状态中的评估与复核](2026-09-27_20-36-05-hashicorp_raft-real-run/state.json)。合格支持要求是从 API 的权威确认用途、成员资格语义及实现阈值推导的必要条件，并非 API 明文给出的一句 quorum 公式。没有观察到新领导者、旧应用读、冲突提交、崩溃恢复或动态成员变更；不能把该局部见证直接称为共识安全性破坏。Go 测试 PASS 仅表示观测程序完成，违反来自事件判据。

## 连续调查、回流与剩余问题

正式检查后，Agent 完成对应性复核，把首个 Candidate 的 producer、合法前缀和公开完成未知更新为更广后果及其他变体；历史描述保留，实际 CheckRun 进度可见。随后它独立调查“实际 stale-term 心跳拒绝是否被转换为正向 VerifyLeader 支持”，根据接收端 Success=false 及发送端原样调用 notifyAll(resp.Success) 作出源码解释，未生成新的执行 Evidence。这个解释不解决 lastContact 刷新及其租约消费者的另一个问题。

之后的地图回流尚未受理：Agent 新增 F-contact-budget 和 B-lease-check，区分连接活性预算与正向权威支持。三次退稿依次要求补充 A2／Surface 改动说明、重连旧 Candidate、再对旧 Unit 提交 F3。完整原稿和诊断分别见[首次扩展](2026-09-27_20-36-05-hashicorp_raft-real-run/native-submissions/9882ecc6437a4452a3f8de4af3992683/diagnostics.json)、[Candidate 重连要求](2026-09-27_20-36-05-hashicorp_raft-real-run/native-submissions/7b36adf428e947cd9db2a385cf10d0b0/diagnostics.json)、[F3 要求](2026-09-27_20-36-05-hashicorp_raft-real-run/native-submissions/8ee39357f81440d3ab3427d9207fff12/diagnostics.json)。最后一轮正在读取 F3 产品结构时总时间到期。这些退稿归属同一草稿，诊断变化计作进展，没有触发旧版的全局连续退稿退出。

主要工程限制是地图依赖影响判定仍以整个 Behavior 为单位：对已有 Behavior 增补一个独立输出 Fact，也会因为该 Behavior 被旧问题引用而触发旧 Unit 的 F3 要求。这里既有字段说明遗漏，也有独立关系扩展被过粗地关联到旧义务的问题；改进方向应区分当前命题的实际依赖变化和独立知识增补，而不是放松真正的 F2/F3 保护。最后约 256 秒用于这条回流修订链，已受理地图最终仍只有 v1。

其他成本与边界：一次义务提交误填非暂停 Candidate 的 resume_conditions；一次复核误用 obligation 作为当前接口不接受的 review target，两者均修复后受理。暂停候选在紧凑投影中没有完整问题，重连时又需从本次已保存原稿补取字段。目标辅助文件虽然已加载，正式 harness 仍自行构造集群和传输包装，没有调用 NewAssuranceClusterWithSuffrage；这不否定其真实 producer 见证，也不能声称辅助层已被实际复用。Candidate 的当前未知已回流，但 Claim.pending／grounding.unresolved 中仍留有最初“待执行”的措辞，应以实际 CheckRun、评估和版本解释。停止记录 pending_work 为空只表示没有未完成的已受理 Unit／复核问题，不表示未受理草稿及研究前沿已经穷尽。

## 独立性与归档

第一次调用记录 `session_id: null、turn: 0`，关闭记忆读取和生成；后续沿同一精确 session ID 续写。47 条已记录原生工具命令中未见访问其他实验目录、记忆文件或凭据路径；首题之前有本轮源码阅读。再次选择 Nonvoter 问题本身不证明复用了旧答案，这些日志也不构成对未记录行为的绝对证明。

本次分析只读取原始制品，没有重新执行目标、调用模型或覆盖历史评估。按用户要求，将 Git 追踪从 `2026-09-27_17-26-13-hashicorp_raft-real-run` 切换到本次运行，连同当前代码、资源和测试清理提交；旧运行保留在本地及 Git 历史中。归档排除凭据、虚拟环境、临时锁、.execution、原生草稿的 tmp/local-tmp/local-cache、可重建的 experiments/**/workspace 和本地权限覆盖配置；保留源快照、草稿、正式制品、实验输入差异和原始日志。归档不作为新实验的发现输入。
