#!/bin/bash

set -euo pipefail
if command -v pyenv >/dev/null 2>&1; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi

if [[ ${1-} != "local" ]]; then
  # Installs exactly the extras this example declares in pyproject.toml, plus the dev group.
  uv sync
else
  # Local development of agentkernel: re-resolve it (and the extras this example declares in
  # pyproject.toml) against the freshly built local dist instead of PyPI. --upgrade-package
  # forces re-resolution so the local wheel wins even when its version matches the published
  # one, pulling a newly added extra's dependencies that the published release doesn't have yet.
  # Note: this rewrites uv.lock to the local dist source for the duration; do not commit that
  # lock — commit the PyPI-resolved lock produced by `uv lock` after the extra is published.
  uv sync --find-links ../../../ak-py/dist --upgrade-package agentkernel
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
