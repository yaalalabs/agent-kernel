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
  # For local development of agentkernel, you can force reinstall from local dist
  uv sync --find-links ../../../ak-py/dist --all-extras
  uv pip install --force-reinstall --find-links ../../../ak-py/dist agentkernel[cli,openai,test] || true
fi