# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-14 09:22:37](2026-10-14_09-22-37-hashicorp_raft-real-run/report.md) | `audit-products-v76` | `deepseek-flash` / `high` | 80 / 80.02 minutes | 76 / 28 |
| [etcd, 2026-10-14 10:42:39](2026-10-14_10-42-39-etcd_raft-real-run/report.md) | `audit-products-v76` | `deepseek-flash` / `high` | 80 / 75.07 minutes | 79 / 15 |

The HashiCorp run reached its total time allocation. The etcd run was cancelled by the user with about five minutes and one Agent call remaining. Preserve each recorded stop reason and execution status. These are research records, not counts of independently verified defects.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
