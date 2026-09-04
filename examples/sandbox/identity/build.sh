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
