#!/bin/bash

# Build script for WhatsApp integration example

set -e

echo "Building WhatsApp integration example..."

# Check if we should use local agent-kernel
if [ "$1" = "local" ]; then
    echo "Using local agent-kernel source..."
    uv sync --extra openai
    uv pip install -e ../../../ak-py
else
    echo "Using published agent-kernel..."
    uv sync --extra openai
fi

echo "Build complete!"
echo ""
echo "To run the server:"
echo "  uv run server.py"
