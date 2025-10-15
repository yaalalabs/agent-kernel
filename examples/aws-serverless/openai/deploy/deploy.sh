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
      uv pip install -r requirements.txt --target=dist --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist --find-links ../../../ak-py/dist agentkernel[openai,aws] || true
    fi
    cp -r lambda.py config.yaml dist/
    cd dist && zip -r ../dist.zip .
    popd || exit 1
}

create_deployment_package $1

terraform init
terraform apply