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
  # For local development of agentkernel, you can force reinstall from local dist.
  # --no-cache matters here: a locally built wheel usually carries the same version as the
  # published one, so without it uv can satisfy the install from its cache and quietly hand you
  # the release instead of your build.
  uv sync --find-links ../../../ak-py/dist --all-extras
  uv pip install --force-reinstall --no-deps --no-index --no-cache --find-links ../../../ak-py/dist agentkernel[api,openai,kafka,valkey,test]
fi
