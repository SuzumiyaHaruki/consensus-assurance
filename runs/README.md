# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [OmniPaxos, 2026-10-15 21:49:09](2026-10-15_21-49-09-omnipaxos-real-run/report.md) | `audit-products-v82` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 44 / 16 |
| [HashiCorp, 2026-10-15 23:09:10](2026-10-15_23-09-10-hashicorp_raft-real-run/report.md) | `audit-products-v82` | `deepseek-flash` / `high` | 80 / 80.88 minutes | 22 / 13 |

Both runs reached their total time allocations. All 29 formal test processes completed with exit code zero; process success is not a defect verdict or proof of complete comparisons. HashiCorp's repeated snapshot output exposed expensive reparsing of historical logs at each controller checkpoint, including after the final model process stopped. OmniPaxos completed without the earlier disk-space interruption.

HashiCorp retained four questions: three asserted accounts spanning snapshot-recovery starvation and transfer-message replay, plus one refuted older-term heartbeat suspicion. The snapshot question and its vote/configuration consequences share a cause. Some message-producer premises remain unestablished, and the final prose contains mismatched figures and a knowledge revision that dropped receipt references after an identifier typo. Selected execution ran 22 top-level tests across 13 invocations without implicitly rerunning every accumulated case.

OmniPaxos retained four questions. Two asserted accounts cover actor completion/assignment behavior and trimming with sparse node IDs; two other accounts retain bounded negative results for message schedules. The actor investigation contains two proposed mechanisms with distinct evidence. Its final merged explanation does not preserve all earlier receipt links and scope distinctions. Local feedback is not a formal execution, and question or claim counts are not independently verified defect counts.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks and state-write temporary files, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.

Three HashiCorp stdout files above 50 MiB are tracked as adjacent `stdout.log.gz` files; one uncompressed file exceeds GitHub's 100 MiB limit. Compression is lossless and was verified against the original bytes. Local originals and recorded receipt paths are unchanged. On a fresh checkout, restore these logs before following their report links or parsing raw output:

```bash
find runs/2026-10-15_23-09-10-hashicorp_raft-real-run/logs -name '*.log.gz' -exec gzip -dk -- {} +
```

The command preserves the compressed archives and does not overwrite existing raw logs. Restore logs for inspection only; use the recorded method revision for any historical execution.
