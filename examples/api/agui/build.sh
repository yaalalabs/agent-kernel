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
  # --no-cache: a local wheel often shares the published version, so uv would serve the cache.
  # Drop the lock first: the unpublished `agui` extra is otherwise dropped silently against PyPI.
  rm -f uv.lock
  uv sync --find-links ../../../ak-py/dist --all-extras
  uv pip install --force-reinstall --no-deps --no-index --no-cache --find-links ../../../ak-py/dist agentkernel[api,openai,agui,test]
  # --no-deps skips the extra's own dependency; drop this line once a released agentkernel carries `agui`.
  uv pip install --no-cache 'ag-ui-protocol>=0.1.16'
fi
