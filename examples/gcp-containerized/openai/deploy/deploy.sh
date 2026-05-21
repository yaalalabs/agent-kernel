#!/bin/bash
set -e
# Create a deployment package for Cloud Run
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../ak-py/dist agentkernel[api,openai,redis] || true
    fi
    cp -r app.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

pushd ../../../../ak-py || exit 1
rm -rf dist
./build.sh local
popd

create_deployment_package $1

terraform init
terraform apply
