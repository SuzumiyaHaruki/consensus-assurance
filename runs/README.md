# Retained runs

Git tracks the two latest CA experiments below. Earlier runs remain locally and in Git history; the existing `baseline/runs` archive is unchanged.

| Run | Method | Model / effort | Budget / elapsed | Agent calls / formal executions |
| --- | --- | --- | --- | --- |
| [HashiCorp, 2026-10-15 18:00:28](2026-10-15_18-00-28-hashicorp_raft-real-run/report.md) | `audit-products-v81` | `deepseek-flash` / `high` | 80 / 80.01 minutes | 57 / 20 |
| [OmniPaxos, 2026-10-15 19:20:29](2026-10-15_19-20-29-omnipaxos-real-run/state.json) | `audit-products-v81` | `deepseek-flash` / `high` | 80 / 39.40 minutes at the last checkpoint | 16 / 9 reserved attempts |

HashiCorp reached its total time allocation. Its 20 formal executions include 18 passing test processes and two test failures; these statuses are not defect verdicts. OmniPaxos was interrupted during the reported disk-space incident: seven formal executions completed, one failed during linking, and the ninth attempt has only a running cache-copy receipt. Its state still says `Not started`, has no final stop record, and no final report was produced. The incomplete state and raw failure records are retained without reconstructing a successful ending.

HashiCorp retained eight asserted question accounts spanning approximately five mechanisms: committed-configuration recovery, startup recovery blocking, configuration-index reporting, transfer-message admission and non-voter leader verification. Several questions share the configuration-recovery cause. The captured commit is tagged `v1.8.0`; the report's inference that the feature is unreleased from its changelog is incorrect. Supplied message provenance, application completion and some causal attributions remain limits of the retained claims. The cumulative generated harness also reran many unrelated earlier cases.

OmniPaxos retained five questions and one asserted failure family involving compaction and log-update construction, with a separate actor subscription-cursor lead recorded in shared knowledge. The real cluster observation and supplied-prefix backend contrasts have different evidential scope. Some passing probes do not exercise their original discriminators, and the final next-configuration check never ran. Local feedback is not a formal execution, and question or claim counts are not independently verified defect counts.

Reports, fixed inputs, model interpretations and raw receipts are retained as recorded, including incorrect measurements, disputed claims and unresolved consequences. Use each run's captured method and configuration to interpret its records; current code must not silently resume an older method. Historical findings must not become inputs to fresh autonomous experiments.

Archives include captured source, configuration records, fixed experiments, submissions, execution deltas and raw logs. Credentials, virtual environments, transient locks and state-write temporary files, `.execution`, build caches, reconstructible `experiments/**/workspace` copies and local permission overrides are excluded.
