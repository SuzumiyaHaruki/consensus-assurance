# Openraft audit reproduction notes

Source of truth: `../../source` at identity
`8815cdba2826f74e848acef361ad03f93bb1c3f8`. The captured source was never
modified; every diagnostic change is a test-only addition in `openraft/src`
or under `tests/tests/audit/`.

## Layout

- `repro/` - copies of every test-only reproduction source, for review without
  the build tree.
- `logs/` - captured stdout/stderr for each finding and model run.
- `diagnostics/openraft-audit-tests.patch` - full diff of the test-only
  additions under `openraft/src` (F3, F4, F6, F7, F12, F13, and all model
  probes). Paths are relative to the run root; `../source/openraft/src` is
  the pristine side and `openraft/src` the working side.
- `diagnostics/tests-audit.patch` - the seven cluster-level integration tests
  under `tests/tests/audit/`.
- `diagnostics/memstore-install-block.patch` - the test-only memstore hooks
  (install delay, apply/install panic) used by F9/F10.

## Rerun

From the run root:

```
cargo test -p openraft --lib
cargo test -p tests --test audit
```

Individual probes and their exact commands are listed in each finding of
`../report.md`. Full-suite tracing logs under `tests/_log` can grow to
multiple GB and are disposable; targeted output is copied to `logs/`.

## Profile notes

F12 and F13 probes assert different observable behavior in debug and release
(overflow panic vs. wrapped result), so run them with both profiles:

```
cargo test -p openraft --lib audit_next_send_max_entries_overflow -- --nocapture
cargo test --release -p openraft --lib audit_next_send_max_entries_overflow -- --nocapture
cargo test -p openraft --lib audit_snapshot_policy_max_threshold_overflow -- --nocapture
cargo test --release -p openraft --lib audit_snapshot_policy_max_threshold_overflow -- --nocapture
```
