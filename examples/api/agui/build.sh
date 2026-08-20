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

# The React frontend. Optional on purpose: the AG-UI routes and app_test.py do not need it, so a
# missing npm must warn rather than fail. A *failed* build warns too, and that is the deliberate part:
# this example is registered in .github/test-config.yaml and GitHub runner images ship npm, so failing
# hard here would let a frontend type error — or a flaky npm install — break the example's CI job over
# something no test touches. Run `npm run build` or `npm run typecheck` directly for a gating check.
# `npm ci` rather than `npm install`, so the committed package-lock.json is what gets installed.
if command -v npm >/dev/null 2>&1; then
  echo "Building the frontend..."
  if ! (cd frontend && npm ci --no-audit --no-fund && npm run build); then
    echo "WARNING: the frontend build failed. The /agui routes still work; GET / will explain how to build."
  fi
else
  echo "npm not found — skipping the frontend build. The /agui routes still work; GET / will explain."
fi
