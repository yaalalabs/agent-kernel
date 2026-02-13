#!/bin/bash

# Create a zip file of the Lambda function code
create_deployment_package() {
    pushd ../
    rm -rf dist dist.zip
    mkdir dist
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist
    else
      echo "Using local ak-py"
      uv pip install -r requirements.txt --target=dist --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist --find-links ../../../ak-py/dist agentkernel[openai,redis,azure] --no-cache-dir
    fi
    cp -r src/. dist/
    cd dist && zip -r -q ../dist.zip .
    popd || exit 1
}

pushd ../../../../ak-py || exit 1
rm -rf dist
./build.sh local
popd

create_deployment_package $1
terraform init
terraform apply
