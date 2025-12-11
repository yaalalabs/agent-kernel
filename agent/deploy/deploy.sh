#!/bin/bash

# Create a zip file of the app code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../ak-py/dist agentkernel[api,openai,redis] || true
    fi
    cp -r app.py rag_loader.py rag_system.py tool.py config.yaml rag_storage dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package $1

terraform init
terraform apply
