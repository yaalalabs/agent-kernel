#!/bin/bash
set -euo pipefail

rm -rf dist
mkdir -p dist

cp agent.py config.yaml lambda.py tool.py requirements-aws.txt dist/
cp deploy/Dockerfile dist/Dockerfile

echo "AWS Lambda image build context written to ./dist"
