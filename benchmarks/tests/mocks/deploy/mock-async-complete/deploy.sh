#!/usr/bin/env bash
# Test-only deployment folder: records its AK_BENCH_* inputs and points deployment.json at MOCK_WS_URL.
set -euo pipefail
env | grep '^AK_BENCH_' | sort > "$AK_BENCH_OUTPUT/deploy-env.txt"
if [ "${MOCK_DEPLOY_EXIT:-0}" != 0 ]; then exit "$MOCK_DEPLOY_EXIT"; fi
cat > "$AK_BENCH_OUTPUT/deployment.json" <<JSON
{
  "endpoint": "${MOCK_WS_URL:-ws://127.0.0.1:1}",
  "resources": {"agent": {"service": "mock-agent"}},
  "queues": {"input": {"name": "mock-in"}, "output": {"name": "mock-out"}},
  "logs": {"agent": "mock-agent-logs"},
  "settings": {"memory_mb": 512}
}
JSON
