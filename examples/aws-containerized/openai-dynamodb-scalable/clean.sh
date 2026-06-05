#!/bin/bash

# Clean all build artifacts and dist directories

set -euo pipefail

echo "Cleaning build artifacts..."

# Remove dist directories
rm -rf dist dist-rest-service dist-agent-runner

# Remove virtual environment
rm -rf .venv

# Remove Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Remove requirements.txt if it exists
rm -f requirements.txt

echo "Clean complete!"
