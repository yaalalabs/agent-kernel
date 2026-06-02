#!/bin/bash

set -euo pipefail

# Create a deployment package for Cloud Run
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../ak-py/dist agentkernel[api,openai,redis] || true
    fi
    cp -r app.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package ${2-}

terraform init
terraform apply -var="openai_api_key=${OPENAI_API_KEY}"

echo ""
echo "=== Test environment variables ==="
echo "export AK_TEST_ENDPOINT=$(terraform output -raw agent_invoke_url)"
echo "export AK_TEST_AUDIENCE=$(terraform output -raw service_url)"
