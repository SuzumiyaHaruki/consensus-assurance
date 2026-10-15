# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-14 22:44:04](2026-10-14_22-44-04-hashicorp_raft-real-run/report.md) | `audit-products-v79` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 44 / 20 |
| [etcd, 2026-10-15 00:04:05](2026-10-15_00-04-05-etcd_raft-real-run/report.md) | `audit-products-v79` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 66 / 17 |

Both runs reached their total time allocation; the controller terminated the final Agent process. HashiCorp retained four explicit claims across five questions, centered on two RestoreCommittedLogs causes: missed configuration recovery and blocked startup replay. Its real cluster history supports conflicting commits and applied-state divergence; the outsider-election extension still lacks a shared legal history. The etcd run retained six explicit claims across fourteen questions, all variants of one local-message filtering omission. The injected message has no correct-peer producer, so the observed effects do not establish a CFT-reachable consensus defect. Both runs contain useful corrections and negative results, as well as measurement errors and incomplete reconciliation of earlier accounts. Local feedback is not a formal execution, and question or claim counts are not independently verified defect counts.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
