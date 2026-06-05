#!/bin/bash

# Clean rebuild script for the scalable containerized example
# This ensures a fresh build without any cached artifacts

set -euo pipefail

echo "========================================="
echo "Clean Rebuild - Scalable Containerized"
echo "========================================="
echo ""

# Step 1: Clean
echo "Step 1: Cleaning build artifacts..."
./clean.sh
echo "✓ Clean complete"
echo ""

# Step 2: Build venv and sync dependencies
echo "Step 2: Setting up Python environment..."
./build.sh "$@"
echo "✓ Python environment ready"
echo ""

# Step 3: Deploy
echo "Step 3: Building deployment packages and deploying..."
cd deploy
./deploy.sh "$@"
cd ..
echo "✓ Deployment complete"
echo ""

echo "========================================="
echo "Rebuild complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Check CloudWatch logs for the agent-runner service"
echo "2. Test the API endpoint"
echo "3. Monitor SQS queue metrics"
echo ""
