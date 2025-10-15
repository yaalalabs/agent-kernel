#!/bin/bash

set -euo pipefail
uv venv --allow-existing

if [[ ${1-} != "local" ]]; then
  uv sync --all-extras
else
  # For local development of agentkernel, you can force reinstall from local dist
  uv sync --find-links ../../../ak-py/dist --all-extras
  uv pip install --force-reinstall --find-links ../../../ak-py/dist agentkernel[cli,langgraph,test] || true
fi