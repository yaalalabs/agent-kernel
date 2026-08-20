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
  # The lock is removed first, and that matters: `agui` is a new extra that the published
  # agentkernel does not carry yet, and uv resolves `agentkernel>=0.8.1` against PyPI — where the
  # version matches but the extra does not exist — and then drops the unknown extra *silently*
  # rather than failing. A lock written that way records `extra = ["api", "openai"]` and no
  # ag-ui-protocol, and a later `uv sync` happily satisfies it.
  rm -f uv.lock
  uv sync --find-links ../../../ak-py/dist --all-extras
  uv pip install --force-reinstall --no-deps --no-index --no-cache --find-links ../../../ak-py/dist agentkernel[api,openai,agui,test]
  # --no-deps above installs the local wheel's files only, so the new extra's own dependency has to
  # be named here. Drop this line once a released agentkernel carries the `agui` extra.
  uv pip install --no-cache 'ag-ui-protocol>=0.1.16'
fi

# The React frontend. Optional on purpose: the AG-UI routes and app_test.py do not need it, and no CI
# job sets up a Node toolchain for this example, so a missing npm must warn rather than fail.
# `npm run build` type-checks before it bundles, so where npm *is* present (a GitHub runner image
# ships one) a frontend type error fails this script rather than shipping.
if command -v npm >/dev/null 2>&1; then
  echo "Building the frontend..."
  (cd frontend && npm install --no-audit --no-fund && npm run build)
else
  echo "npm not found — skipping the frontend build. The /agui routes still work; GET / will explain."
fi
