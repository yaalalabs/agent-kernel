#!/bin/bash

# Create a deployment package for container image
create_deployment_package() {
    pushd ../
    rm -rf dist dist.zip
    mkdir -p dist/data
    uv export --no-dev --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data --find-links ../../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../../ak-py/dist agentkernel[openai,aws,multimodal] || true
    fi
    cp -r lambda.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package $1

terraform init
terraform apply
