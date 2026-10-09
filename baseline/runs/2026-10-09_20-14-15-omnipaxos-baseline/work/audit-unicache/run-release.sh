#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
cargo test --release --offline --locked --manifest-path audit-unicache/Cargo.toml leadership::promoted_lru_encoder_outgrows_decoder -- --nocapture > audit-artifacts/unicache-release-output.txt 2>&1
result=$?
printf 'cargo test exit status: %s\n' "$result" >> audit-artifacts/unicache-release-output.txt
cat audit-artifacts/unicache-release-output.txt
exit "$result"
