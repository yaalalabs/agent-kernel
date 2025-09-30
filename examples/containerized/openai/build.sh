#!/bin/bash

set -euo pipefail

domain=yaalalabs
owner=110597261937
region=ap-southeast-2
repo=agent-kernel
image_name=yaalalabs/ak-openai-demo

uv venv --allow-existing

if [[ ${1-} != "local" ]]; then
  AUTH_TOKEN=$(aws codeartifact get-authorization-token \
    --domain "$domain" \
    --domain-owner "$owner" \
    --region "$region" \
    --query authorizationToken \
    --output text)

  CA_SIMPLE_URL="https://aws:${AUTH_TOKEN}@${domain}-${owner}.d.codeartifact.${region}.amazonaws.com/pypi/${repo}/simple"

  # Tell uv/pip to use CodeArtifact as the extra index. Keep PyPI as the primary
  export UV_EXTRA_INDEX_URL="$CA_SIMPLE_URL"
  export PIP_EXTRA_INDEX_URL="$CA_SIMPLE_URL"
  uv sync
else
  # For local development of ak, you can force reinstall from local dist
  uv sync --find-links ../../../ak-py/dist --all-groups
  uv pip install --force-reinstall --find-links ../../../ak-py/dist ak[openai,api,test] || true # optional, only if local ak is present
fi

create_docker_image() {
    mkdir -p dist/
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../ak-py/dist ak[openai,api,test] || true
    fi
    cp -r app.py tool.py dist/
    
    DOCKER_BUILDKIT=0 docker build -t $image_name:latest .
}

create_docker_image $1
