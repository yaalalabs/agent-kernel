#!/bin/bash

set -euo pipefail

domain=yaalalabs
owner=110597261937
region=ap-southeast-2
repo=agent-kernel

# Get a fresh CodeArtifact authorization token (expires in ~12h)
AUTH_TOKEN=$(aws codeartifact get-authorization-token \
  --domain "$domain" \
  --domain-owner "$owner" \
  --region "$region" \
  --query authorizationToken \
  --output text)

# Construct the authenticated simple index URL for CodeArtifact
CA_SIMPLE_URL="https://aws:${AUTH_TOKEN}@${domain}-${owner}.d.codeartifact.${region}.amazonaws.com/pypi/${repo}/simple"

# Tell uv/pip to use CodeArtifact as the primary index. Keep PyPI as an extra index via pyproject.
export UV_EXTRA_INDEX_URL="$CA_SIMPLE_URL"
export PIP_EXTRA_INDEX_URL="$CA_SIMPLE_URL"

#uv pip install ak[cli,openai]==0.1.0a1

uv venv --allow-existing
uv sync

# For local development of ak, you can force reinstall from local dist
#uv pip install --force-reinstall --find-links ../../../ak-py/dist ak || true # optional, only if local ak is present