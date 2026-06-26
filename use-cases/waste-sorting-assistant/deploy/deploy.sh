#!/bin/bash
set -euo pipefail

echo "Creating Lambda image build context..."
pushd ../ >/dev/null
rm -rf dist
mkdir -p dist

uv export --no-hashes >dist/requirements.txt
cp agent.py config.yaml lambda.py tool.py dist/
cp deploy/Dockerfile dist/Dockerfile
popd >/dev/null || exit 1

terraform init
terraform apply
