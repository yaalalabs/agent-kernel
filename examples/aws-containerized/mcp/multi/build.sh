#!/bin/bash

set -euo pipefail
uv venv --allow-existing

if [[ ${1-} != "local" ]]; then
  uv sync --all-extras
else
  uv sync --find-links ../../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel || true
fi