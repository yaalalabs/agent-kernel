#!/bin/bash

set -euo pipefail
if command -v pyenv >/dev/null 2>&1; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi
image_name=yaalalabs/ak-openai-demo

if [[ ${1-} != "local" ]]; then
  uv sync --all-extras
else
  uv sync --find-links ../../../ak-py/dist --upgrade-package agentkernel || true
fi

create_docker_image() {
    rm -rf dist || true
    mkdir -p dist/
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist
    else
      uv pip install -r requirements.txt --target=dist --find-links ../../../ak-py/dist --upgrade-package agentkernel || true
    fi
    cp -r app.py tool.py dist/
    
    DOCKER_BUILDKIT=0 docker build -t $image_name:latest .
}

create_docker_image ${1-""}
