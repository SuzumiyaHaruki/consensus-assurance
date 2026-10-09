#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
cargo test --offline --locked --manifest-path audit-repro/Cargo.toml -- --nocapture --test-threads=1 > audit-artifacts/reproduction-output.txt 2>&1
result=$?
printf 'cargo test exit status: %s\n' "$result" >> audit-artifacts/reproduction-output.txt
cat audit-artifacts/reproduction-output.txt
exit "$result"
