#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
cargo test --offline --locked --manifest-path audit-unicache/Cargo.toml -- --nocapture --test-threads=1 > audit-artifacts/unicache-output.txt 2>&1
result=$?
printf 'cargo test exit status: %s\n' "$result" >> audit-artifacts/unicache-output.txt
cat audit-artifacts/unicache-output.txt
exit "$result"
