#!/usr/bin/env bash
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
log_dir="$repo_root/repro/logs"
mkdir -p "$log_dir"

run_case() {
    local name="$1"
    shift
    echo "Running $name"
    "$@" >"$log_dir/$name.log" 2>&1
    local status=$?
    echo "$name exit=$status"
    return 0
}

cd "$repo_root"

run_case core_default cargo test -p omnipaxos --tests --no-fail-fast
run_case runtime_default cargo test -p omnipaxos_runtime --features tokio_runtime --tests --no-fail-fast
run_case runtime_all_features cargo test -p omnipaxos_runtime --all-features --tests --no-fail-fast
run_case feature_matrix bash -lc 'cd omnipaxos && ./test_all_features.sh -c'
run_case workspace_default cargo check --workspace --all-targets

run_case audit_core \
    cargo test -p omnipaxos \
    --test audit_buffered_stopsign \
    --test audit_config_validation \
    --test audit_duplicate_nodes \
    --test audit_error_source \
    --test audit_pending_reconfigure \
    --test audit_read_bounds \
    --test audit_read_empty_range \
    --test audit_sparse_ids_trim \
    --test audit_sync_decided_regression \
    --test audit_sync_delta_snapshot \
    --test audit_trim_decidedness \
    --test audit_zero_flush_timeout \
    --no-fail-fast -- --nocapture

run_case audit_lfu_clone cargo test -p omnipaxos --features unicache --test audit_lfu_clone -- --nocapture
run_case audit_lfu_protocol cargo test -p omnipaxos --features unicache --test audit_lfu_protocol -- --nocapture
run_case audit_lru_serde cargo test -p omnipaxos --features 'serde,unicache' --test audit_lru_serde -- --nocapture
run_case audit_logger_path cargo test -p omnipaxos --features logging --test audit_logger_path -- --nocapture
run_case audit_runtime_timeout cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_timeout_retry -- --nocapture
run_case audit_runtime_subscribers cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_subscriber_reuse -- --nocapture
run_case audit_runtime_zero_outgoing cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_zero_outgoing -- --nocapture

run_case audit_core_checks \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-target" \
    cargo run --manifest-path audit_runner/Cargo.toml --offline --bin core_checks
run_case audit_crash_snapshot \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-target" \
    cargo run --manifest-path audit_runner/Cargo.toml --offline --bin core_crash_fuzz
run_case audit_runtime_event_stall \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-target" \
    cargo run --manifest-path audit_runner/Cargo.toml --offline --bin runtime_event_stall_check
run_case audit_runtime_subscription \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-target" \
    cargo run --manifest-path audit_runner/Cargo.toml --offline --bin runtime_compaction_check

run_case audit_persistent_atomicity \
    env CARGO_TARGET_DIR="$repo_root/.runtime/cargo-target" \
    cargo run --manifest-path persistent_check/Cargo.toml --offline
run_case audit_persistent_direct_append \
    env CARGO_TARGET_DIR="$repo_root/.runtime/cargo-target" \
    cargo run --manifest-path persistent_check/Cargo.toml --offline --bin append_error_state
run_case audit_persistent_append_on_prefix \
    env CARGO_TARGET_DIR="$repo_root/.runtime/cargo-target" \
    cargo run --manifest-path persistent_check/Cargo.toml --offline --bin append_on_prefix_error

run_case audit_lru_serde_bincode \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-unicache-target" \
    cargo run --manifest-path unicache_check/Cargo.toml --offline --bin lru_serde_sync_check
run_case audit_runtime_feature_unification \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-feature-target" \
    cargo check --manifest-path feature_unification_check/Cargo.toml --offline
run_case audit_unicache_macro \
    env CARGO_TARGET_DIR="$repo_root/.runtime/audit-repro-unicache-target" \
    cargo check --manifest-path unicache_macro_check/Cargo.toml --offline

echo "Logs written to $log_dir"
