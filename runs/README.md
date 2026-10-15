# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-15 12:22:18](2026-10-15_12-22-18-hashicorp_raft-real-run/report.md) | `audit-products-v80` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 69 / 20 |
| [etcd, 2026-10-15 13:42:19](2026-10-15_13-42-19-etcd_raft-real-run/report.md) | `audit-products-v80` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 44 / 16 |

Both runs reached their total time allocation. The controller terminated HashiCorp's final Agent process shortly after launch; etcd exhausted its allocation before the next Agent process started. The etcd run also retained and continued from an earlier single-turn timeout. All formal target executions completed, which does not establish the semantic validity of their observations or model claims.

HashiCorp retained five asserted and two refuted accounts across seven questions, investigating non-voter verification, explicit leadership transfer, shutdown futures, configuration history, batched FSM callbacks and failed log storage. The final stale-read account still lacks non-overlapping read/write order, and the stronger log-hole consequence uses an incompatible sequence of leader messages. The etcd run retained three asserted accounts: pending ReadIndex release, removed-leader reads and proposal-channel recovery after re-admission. A new read issued after the remaining singleton committed supports the narrow ReadIndex concern; forwarded concurrent reads and a correctly counted current-voter quorum do not support all of the report's extensions. The re-admission contract and supplied committed prefix remain relevant limits. Both runs explored independent mechanisms and corrected some earlier constructions; current explanations and shared knowledge also retain errors. Local feedback is not a formal execution, and question or claim counts are not independently verified defect counts.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
