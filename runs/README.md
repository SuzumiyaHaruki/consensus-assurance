# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-14 18:14:25](2026-10-14_18-14-25-hashicorp_raft-real-run/report.md) | `audit-products-v78` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 64 / 18 |
| [etcd, 2026-10-14 19:34:26](2026-10-14_19-34-26-etcd_raft-real-run/report.md) | `audit-products-v78` | `deepseek-flash` / `high` | 80 / 80.21 minutes | 57 / 19 |

Both runs reached their total time allocation; the controller terminated the final Agent process. HashiCorp retained two explicit defect claims concerning membership recovery and startup replay with RestoreCommittedLogs, plus an unexecuted snapshot-propagation question. The etcd run withdrew its joint-configuration defect claim after identifying inconsistent harness state; its earlier negative interpretations and shared knowledge still need reconciliation with that correction. Preserve the recorded claims, counterevidence, construction failures and unresolved work. Local feedback is not a formal execution, and these are research records rather than counts of independently verified defects.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded. The etcd draft's `ws1` through `ws22` copies match captured source except for `assurance_generated_test.go`; those generated checks are retained and the duplicate source files are excluded.
