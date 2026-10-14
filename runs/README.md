# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-14 14:15:46](2026-10-14_14-15-46-hashicorp_raft-real-run/report.md) | `audit-products-v77` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 47 / 17 |
| [etcd, 2026-10-14 15:35:47](2026-10-14_15-35-47-etcd_raft-real-run/report.md) | `audit-products-v77` | `deepseek-flash` / `high` | 80 / 15.05 minutes | 1 / 0 |

The HashiCorp run reached its total time allocation. The etcd run stopped at the first Agent turn's 900-second process deadline: raw output contains a final submission and a completed-turn event, but the process had not exited and the controller did not accept the submission. About 65 minutes remained. Preserve the recorded timeout, drafts and raw receipts; local feedback is not a formal execution. These are research records, not counts of independently verified defects.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
