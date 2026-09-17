# 运行制品

当前保留并跟踪 [2026-09-16_21-58-16-hashicorp_raft-real-run](2026-09-16_21-58-16-hashicorp_raft-real-run/report.md)。原始回复、配置、源码快照、历史检查点和日志保留；临时锁与可重建的执行缓存不归档。

其他运行默认由 .gitignore 排除。清理活动运行前必须确认进程已停止；归档选择或删除旧实验须由用户明确授权。历史已提交记录仍可从 Git 历史读取，本地删除不改写提交历史。

一般回归使用 tests/fixtures；工作集与上下文的离线回归还会只读已选归档，它们不进入 runtime discovery。使用和证据边界见 [运行工作流](../docs/运行工作流.md)。

最新 CFT 运行已形成具体问题，尚无受理模型、TLC 搜索、校准或直接性质证据。

未来选定归档保留 run/source、执行前的 workspace-delta/manifest.json 与新增/改动文件、
执行后的 workspace-outcome 差异、原始日志、action 输入/结果和环境元数据；不再重复提交整个 experiment workspace。
现有已跟踪 workspace 不删除。重建使用
`adapters.storage.workspace_delta.restore(source, manifest, new_destination)`，
校验实际源版本后生成新隔离副本。运行目录中的 workspace 本地仍保留，
默认不自动清理；缓存和外部依赖不属于可重建源码承诺。
