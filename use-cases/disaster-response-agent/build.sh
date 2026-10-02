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
  # For local development against a locally-built agentkernel wheel
  uv sync --find-links ../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel --all-extras
fi
