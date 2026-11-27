#!/usr/bin/env bash
# Test-only: appends one line per run (with the secret it got) so tests can count runs.
set -euo pipefail
mkdir -p "$AK_BENCH_OUTPUT"
echo "destroyed secret=${AK_BENCH_AUTH_SECRET}" >> "$AK_BENCH_OUTPUT/destroy-ran.txt"
exit "${MOCK_DESTROY_EXIT:-0}"
