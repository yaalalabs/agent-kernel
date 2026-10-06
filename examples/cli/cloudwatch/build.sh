#!/bin/bash

set -euo pipefail
if command -v pyenv >/dev/null 2>&1; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi

if [[ ${1-} != "local" ]]; then
  uv sync --all-extras
else
  uv sync --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel || true
  uv pip install "opentelemetry-sdk>=1.30.0" "opentelemetry-exporter-otlp-proto-http>=1.30.0" "botocore>=1.41.4" "requests>=2.32.0"
fi
