# HashiCorp Raft 实验使用

默认以真实仓库为对象，自主选择目标，不预设选举、提交或快照性质。优先使用 `--repo`，其次是配置路径；都未提供才检查实际桌面位置。不存在时报告路径问题，不下载替代目标。

## 前置检查

需要已安装的 Python 环境、Codex CLI、Java/TLC、Go 及目标依赖缓存；默认隔离还需要 bubblewrap。工具配置见 [环境要求](环境要求.md)。

```bash
cd /home/nitro/Desktop/consensus-assurance
export TLC_JAR="$PWD/.tools/tla2tools.jar"
.venv/bin/consensus-assurance inspect --repo /home/nitro/Desktop/hashicorp-raft
.venv/bin/consensus-assurance estimate --config configs/targets/hashicorp_raft.round9.yaml
.venv/bin/consensus-assurance doctor
```

`estimate` 是计划下限，不保证完成所有复核、补读和实验。默认有限配置保留 20 次 agent 调用、2 个审计单元、3 次模型检查、6 个新源读取计划、2400 秒；源码字符、发送上下文和工具次数分别计量。不会自动增加额度。

## 明确授权后运行

真实运行会将选定材料发送到现有认证连接的 Codex 后端，并在隔离副本执行目标测试。只有在用户授权这些操作后，才生成本地权限覆盖配置：

```bash
# 若 codex 已在 PATH，不需要修改 PATH。否则按实际安装位置加入其目录。
export PATH="/实际安装位置/codex所在目录:$PATH"
export TLC_JAR="$PWD/.tools/tla2tools.jar"

sed -e 's/^allow_agent_materials: false$/allow_agent_materials: true/' \
    -e 's/^allow_experiments: false$/allow_experiments: true/' \
    configs/targets/hashicorp_raft.round9.yaml \
    > configs/targets/hashicorp_raft.round9.run.yaml

.venv/bin/consensus-assurance run \
  --config configs/targets/hashicorp_raft.round9.run.yaml
```

`*.run.yaml` 不提交 Git；可复制示例并调整真实目标路径和预算，不应修改已保存运行的 config 来伪装恢复。配置文件名中的 round9 对应当前控制器配置，不是某个预设目标。

## 查看与恢复

每次新运行独立命名，终端输出报告路径。阅读 `report.md`、`state.json`、`packets/`、`repair-sessions/` 及原始工具日志；不能仅根据退出码判断性质成立。

```bash
.venv/bin/consensus-assurance report --run /实际路径/运行目录
.venv/bin/consensus-assurance resume --run /实际路径/运行目录 --action-timeout 600
```

恢复会核对输入、配置和控制器版本，并保留已消耗预算。总时长耗尽、上下文超限或未解释的语义问题不能靠增加单动作超时解决。异版运行使用明确的新阶段或离线回放，不把历史失败改成当前成功。

实验原仓库只读；生成测试和模型单独保存。保持存储契约、成员上下文、故障边界和未覆盖责任，不用有限模型或测试通过推断整个协议正确。
