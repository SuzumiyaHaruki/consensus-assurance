# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-13 10:13:13](2026-10-13_10-13-13-hashicorp_raft-real-run/report.md) | `audit-products-v69` | `deepseek-flash` / `high` | 60 / 60.03 minutes | 49 / 12 |
| [HashiCorp, 2026-10-13 12:35:45](2026-10-13_12-35-45-hashicorp_raft-real-run/report.md) | `audit-products-v70` | `deepseek-flash` / `high` | 60 / 60.01 minutes | 26 / 11 |

Both runs reached their total time allocation. The v69 stop message is `Agent stopped: Action timeout exceeded; process group killed`; v70 distinguishes the total deadline as `Agent stopped: Total runtime budget exhausted; process group killed`. All recorded formal executions completed. Each run contains three investigations and nine fixed experiment versions; v69 retains twelve interpretations and v70 nine. These are research records, not counts of independently verified defects.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
