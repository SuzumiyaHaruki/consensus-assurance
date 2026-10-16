# Retained runs

Git tracks the latest CA experiment below. Previously tracked runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [OmniPaxos, 2026-10-16 09:22:17](2026-10-16_09-22-17-omnipaxos-real-run/report.md) | `audit-products-v83` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 59 / 12 |

The run captured clean OmniPaxos commit `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12` and reached its total time allocation during the final Agent turn. All 12 formal test processes completed with exit code zero; process success is not a defect verdict or proof of complete comparisons. Cached observations were reused, and controller handoffs no longer showed the preceding HashiCorp run's repeated log-parsing delays.

Six questions retained four asserted claims, one scoped source explanation/refutation and one unresolved question. Three asserted accounts concern the same StopSign resynchronization index drift and its trim/snapshot consequences. Public API histories support the local index and read anomalies, including a leader-change path without a reconnect notification. Local snapshot payload loss is observed, but the claimed propagation to a lagging replica is not established: the recorded receiver index exceeds the sender's compacted boundary, and the short returned representation predates the purported trigger. The separate NoSnapshot panic is observed; its calling-contract responsibility remains disputed. These are not four independently verified defects.

A knowledge correction narrowed when decided indices follow accepted-index drift and triggered review of seven recorded uses. Other unsupported interpretations also entered shared knowledge and were reused, despite traceable receipt links. All 12 executions omitted the optional test selector, producing 83 top-level test starts as cases accumulated; this was Agent selection, not forced executor behavior. Some comparisons remained unknown because scenario identities or measured field names did not match their declarations.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks and state-write temporary files, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
