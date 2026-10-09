#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
for profile in debug release; do
    args=()
    if [ "$profile" = release ]; then args=(--release); fi
    output="audit-artifacts/trim-no-snapshot-${profile}-output.txt"
    cargo test "${args[@]}" --offline --locked --manifest-path audit-repro/Cargo.toml --test trim_no_snapshot -- --nocapture --test-threads=1 > "$output" 2>&1
    result=$?
    printf 'cargo test exit status: %s\n' "$result" >> "$output"
    cat "$output"
done
