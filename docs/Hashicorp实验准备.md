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

## 第五轮准备入口（本轮未启动正式实验）

新配置 `configs/targets/hashicorp_raft.round5.yaml` 固定实现和有限预算，不固定选举、投票或快照目标。路径校验可运行：

```bash
cd /home/nitro/Desktop/consensus-assurance
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.round5.yaml
```

此命令仅检查路径存在并输出预算计划，不探测 agent，不发送材料，不运行目标代码。若仓库移动，使用 `--repo /实际路径/hashicorp-raft` 覆盖。完整运行默认隔离方式为 bubblewrap；所需能力缺失时报告受阻，不降级。

**以下命令准备就绪，但本轮未执行。** 用户检查代码并明确允许将筛选材料交给现有 Codex 后端、在隔离副本执行目标后，才创建本地授权配置并启动：

```bash
sed -e 's/^allow_agent_materials: false$/allow_agent_materials: true/' \
    -e 's/^allow_experiments: false$/allow_experiments: true/' \
    configs/targets/hashicorp_raft.round5.yaml > configs/targets/hashicorp_raft.round5.run.yaml
TLC_JAR="$PWD/.tools/tla2tools.jar" .venv/bin/consensus-assurance run \
    --config configs/targets/hashicorp_raft.round5.run.yaml
```

沿用已有认证和账户；不自动购买额度。`20` 次 agent 调用是总上限，补读、复核和技术修复都消耗它，不能保证两个局部单元都完成；TLC 搜索 `3` 次、触发检查 `3` 次、后果规划 `1` 次，合计时长不超过 `2400` 秒。开始后应查看材料范围、实际选择的单元版本、未决语义、触发与校准状态，而不是只看工具是否完成。现场 Codex 路径与实际认证可用性仍需用户环境确认，本轮没有调用真实后端验证。

## 第六轮待执行入口

先检查 [第六轮验收](第六轮关联诊断与修复会话.md)。本轮只做本地回归和原回复离线播放，没有执行以下新自主运行。用户确认允许材料发送及隔离目标执行后，可使用：

```bash
cd /home/nitro/Desktop/consensus-assurance
sed -e 's/^allow_agent_materials: false$/allow_agent_materials: true/' \
    -e 's/^allow_experiments: false$/allow_experiments: true/' \
    configs/targets/hashicorp_raft.round6.yaml > configs/targets/hashicorp_raft.round6.run.yaml
TLC_JAR="$PWD/.tools/tla2tools.jar" .venv/bin/consensus-assurance run \
    --config configs/targets/hashicorp_raft.round6.run.yaml
```

沿用用户现有 Codex 路径和认证，不更换账户。配置没有 directed_question，protocol 为 none；总 agent_calls 仍为 20，总时长 2400 秒。修复总次数 4、每问题重复失败上限 1、无进展/循环阈值 2；这些不是额外赠送的调用，全部占用原总预算。依赖、工具或语义无法继续时如实受阻。旧 2026-09-15 失败运行不直接覆盖恢复，新运行会生成独立时间目录。
