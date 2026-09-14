# 后续 Hashicorp Raft 受限实验准备

**以下正式目标命令本轮尚未执行。用户先检查第二轮增量，再决定是否启动。**

独立配置为 [hashicorp_raft.review.yaml](../configs/targets/hashicorp_raft.review.yaml)。它没有固定 goal、投票模型、已知缺陷答案或历史回归结论；默认不添加 Raft 性质清单，通用 inquiry 提供领域调查结构。

配置包含实际目标路径 `/home/nitro/Desktop/hashicorp-raft`，CLI `--repo` 可以覆盖；路径不存在就报错，不下载替代版本。首次正式运行会重新建立包含未提交修改的实际输入副本，而不只分析提交版本。

用户决定启动时，先检查路径、工具及本地 Go 缓存。准备的命令如下，**尚未执行**：

```bash
.venv/bin/consensus-assurance inspect --config configs/targets/hashicorp_raft.review.yaml
.venv/bin/consensus-assurance doctor --config configs/targets/hashicorp_raft.review.yaml
```

配置目前 `allow_agent_materials: false` 和 `allow_experiments: false`。正式分析需要用户随后明确允许：将选取材料发给现有认证连接的 Codex 后端，以及在独立副本执行目标实验。两项获准后再修改这两个现有布尔配置；不新增审批平台、不改变认证或付费方式。

随后可执行的命令，**尚未执行**：

```bash
export TLC_JAR="/实际路径/tla2tools.jar"
.venv/bin/consensus-assurance run --config configs/targets/hashicorp_raft.review.yaml
```

预算限制为一个审计单元、12 次 agent 调用、3 次模型搜索、3 轮定向补读、4 次实验/能力执行和2次重放；单动作最多180秒，总计最多1200秒。读取累计不超过30个片段、80000字符。目标测试与重放使用 bubblewrap；源码副本、原始日志和制品都保存在独立 run，原始目标只读。

验收应检查目标与关系的适用性、实际代码映射、模型/检查器分离、观测充分性，以及反例前提和结果归属，不要求发现某个固定目标或真实缺陷。若只得到候选问题和明确缺口，也要保留完整证据范围。正式效果与额度/服务可用性仍需这次授权后的真实运行确认。
