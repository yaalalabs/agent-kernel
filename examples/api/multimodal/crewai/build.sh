#!/bin/bash
set -e

# Default source location
SOURCE="local"

# Parse arguments
if [ "$1" == "local" ]; then
    SOURCE="local"
elif [ "$1" == "pypi" ]; then
    SOURCE="pypi"
elif [ -n "$1" ]; then
    echo "Usage: ./build.sh [local|pypi]"
    echo "  local (default): Install agentkernel from local source"
    echo "  pypi: Install agentkernel from PyPI"
    exit 1
fi

uv sync

if [ "$SOURCE" == "local" ]; then
    echo "Installing agentkernel from local source..."
    uv pip install -e ../../../../ak-py[test,api,crewai,cli]
else
    echo "Installing agentkernel from PyPI..."
fi
