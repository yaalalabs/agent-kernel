#!/bin/bash
set -e

# Create a deployment package for container image
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    if [[ ${1-} == "local" ]]; then
      # Re-resolve the lock against the local agentkernel dist so example-level deps
      # and local-only extras (e.g. valkey) are captured before exporting requirements.
      uv lock --find-links ../../../ak-py/dist
    fi
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --no-deps --no-index --target=dist/data --find-links ../../../ak-py/dist agentkernel[openai,valkey,test] --no-cache-dir
    fi
    cp -r lambda.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package $1

terraform init
terraform apply
