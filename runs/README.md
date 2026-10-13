# Retained runs

Git tracks the six CA experiments below, including the four latest runs. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-13 10:13:13](2026-10-13_10-13-13-hashicorp_raft-real-run/report.md) | `audit-products-v69` | `deepseek-flash` / `high` | 60 / 60.03 minutes | 49 / 12 |
| [HashiCorp, 2026-10-13 12:35:45](2026-10-13_12-35-45-hashicorp_raft-real-run/report.md) | `audit-products-v70` | `deepseek-flash` / `high` | 60 / 60.01 minutes | 26 / 11 |
| [HashiCorp, 2026-10-13 16:13:10](2026-10-13_16-13-10-hashicorp_raft-real-run/report.md) | `audit-products-v72` | `deepseek-flash` / `high` | 60 / 60.01 minutes | 46 / 14 |
| [HashiCorp, 2026-10-13 18:31:52](2026-10-13_18-31-52-hashicorp_raft-real-run/report.md) | `audit-products-v74` | `deepseek-flash` / `high` | 60 / 51.63 minutes | 80 / 10 |
| [HashiCorp, 2026-10-13 20:21:32](2026-10-13_20-21-32-hashicorp_raft-real-run/report.md) | `audit-products-v75` | `deepseek-flash` / `high` | 60 / 60.06 minutes | 40 / 17 |
| [etcd, 2026-10-13 21:21:39](2026-10-13_21-21-39-etcd_raft-real-run/report.md) | `audit-products-v75` | `deepseek-flash` / `high` | 60 / 60.00 minutes | 51 / 14 |

The v74 HashiCorp run ended at its Agent-call budget; the other listed runs reached their total time allocation. Preserve each recorded stop reason and execution status. These are research records, not counts of independently verified defects.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
