#!/bin/bash

set -euo pipefail
uv venv --allow-existing

if [[ ${1-} != "local" ]]; then
  uv sync --all-extras
else
  # For local development of agentkernel, you can force reinstall from local dist
  uv sync --find-links ../ak-py/dist --all-extras
  uv pip install --force-reinstall --find-links ../ak-py/dist agentkernel[api,openai,redis,test] || true
fi


# Check if repository is cloned
echo ""
echo "Checking for agent-kernel repository clone..."
REPO_PATH="/tmp/agent-kernel-rag"
if [ ! -d "$REPO_PATH" ]; then
    echo "Repository not found at $REPO_PATH"
    echo "Cloning agent-kernel repository..."
    cd /tmp
    rm -rf agent-kernel-rag
    git clone --depth 1 git@github.com:yaalalabs/agent-kernel.git agent-kernel-rag
    echo "✓ Repository cloned successfully"
else
    echo "✓ Repository already cloned at $REPO_PATH"
    pushd $REPO_PATH
    git pull origin develop
    popd
fi