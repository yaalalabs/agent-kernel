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
  uv sync --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel
fi

# The React frontend, for local runs only. CI never serves the UI, so building it there costs install
# time on every e2e job for a result nothing reads. A failed build warns rather than exits: the routes
# and app_test.py work without it. Run `npm run build` or `npm run typecheck` directly for a gating check.
if [ -z "${CI:-}" ] && command -v npm >/dev/null 2>&1; then
  echo "Building the frontend..."
  if ! (cd frontend && npm ci --no-audit --no-fund && npm run build); then
    echo "WARNING: the frontend build failed. The /agui routes still work; GET / will explain how to build."
  fi
else
  echo "Skipping the frontend build (CI, or npm not found). The /agui routes still work; GET / will explain."
fi
