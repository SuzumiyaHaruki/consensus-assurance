# 配对运行条件

baseline 保持 [task.md](task.md) 的普通自主调查；CA 保留自己的研究对象、执行证据与知识反馈。两侧共享中性的工具环境，不共享方法提示或历史答案。

当前配置可直接通过各自 schema 加载：[HashiCorp baseline](../configs/baseline/deepseek.yaml)／[CA](../configs/ca/deepseek.yaml)。两侧引用 `configs/targets/` 中的同一中性目标定义，分别配置模型、预算与授权。模板关闭材料发送和执行授权；实际运行使用本地 `configs/local/` 配置。

| 条件 | 当前做法 |
|---|---|
| 输入 | 同一干净目标提交、模块、工具链、初始 features 与依赖；双方可显式选择目标支持的 feature 组合并记录实际构建条件；每次独立捕获源码、新会话、新工作区 |
| 模型 | 配对采用同一模型、provider、档位及 catalog；CA 显式 `codex_profile: single_agent` |
| 原生能力 | 共同 `common_settings()`；保留普通 shell、工具发现及原生压缩，关闭自动 skills/plugins/memory/hooks 和子 Agent |
| 执行 | 普通 shell 禁网；baseline `isolated_exec` 与 CA 固定执行均在独立网络中允许同次调用内的 localhost、线程及子进程 |
| 权限 | 源码、依赖及保留日志只读，工作区可写；不开放宿主网络、凭据或旧研究材料 |
| Go | 两侧每次新运行的编译缓存为空，仅在本次运行内复用；CA 正式执行保留独立源码副本。CA 使用 `-count=1`，baseline 默认 `GOFLAGS=-mod=readonly -count=1`，复用编译产物时仍实际运行测试 |
| Cargo | 共用工具定位和离线依赖环境，`CARGO_BUILD_JOBS=2`；配对 CA 设置 `cargo_seed_cache_dir: null`，两侧各自保留运行内构建复用 |
| Maven | 共用 JDK/Maven 定位、离线依赖及空私有 settings；预先在副本完成依赖准备，正式执行不下载 |
| 预算 | 配对显式设置相同总时长、调用和动作时限；当前本地配置为 7200 秒、200 回合、单回合 900 秒，CA 另限 80 次正式执行；HashiCorp 动作 600 秒，OmniPaxos/ZooKeeper 动作 1200 秒 |
| 成本 | 从源码捕获前计时，准备、编译、执行和模型等待均计入；不在截止后追加付费总结 |

CA 正式执行位于模型回合外；baseline 保留原生 MCP 调用，将受控 `isolated_exec` 的实际执行时间从模型回合计时中扣除。两侧的普通 shell 都计入模型回合，正式／受控执行都消耗总预算，并受各自单次动作上限限制。一次包含长执行的 baseline 回合，其墙钟耗时可以超过 900 秒；这不会延长 7200 秒总预算，也不允许后台进程跨调用存活。执行回执记录真正生效的 `timeout_limit`。

baseline 单回合超时保留部分输出、文件变更和原状态；只有原会话身份一致、没有明确失败／拒绝且总预算尚可继续时，才另计一次调用续接。取消、会话变化、服务错误及总期限仍终止运行。

中性构建准备只用当前干净源码和普通环境测试，不读取历史审计产物。当前 Cargo 配对不导入 CA 的跨运行编译种子：其固定路径与构建身份尚不能直接提供给 baseline。两侧离线依赖相同、初始编译缓存均为空；运行内不同的缓存策略保留。单独使用跨运行种子的 CA 配置不能混称此配对条件。

`check-env` 验证本地权限、工具、离线依赖／编译和固定 TCP；本地 Responses fixture 验证 CLI 的真实 exec/resume 与工具回传，都不调用线上模型。正式运行的原始请求、执行输出、配置和停止原因各自留存。两组可同时启动，但共享机器会竞争资源；比较耗时时宜顺序或交错运行。模型自报及 CA 解释都由同一人工标准核验，不按测试成功次数计算发现。
