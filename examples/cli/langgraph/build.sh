#!/bin/bash

set -euo pipefail

domain=yaalalabs
owner=110597261937
region=ap-southeast-2
repo=agent-kernel

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
  uv sync --find-links ../../../ak-py/dist
  uv pip install --force-reinstall --find-links ../../../ak-py/dist ak[cli,langgraph] || true # optional, only if local ak is present
fi