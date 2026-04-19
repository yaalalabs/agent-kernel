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
  # For local development of agentkernel, install from local source to preserve latest extras and modules.
  uv sync --all-extras --no-install-project
  uv pip install --force-reinstall "../../../../../ak-py[cli,openai,test,knowledgebase-neo4j]"
fi