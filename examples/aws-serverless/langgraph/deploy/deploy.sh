#!/bin/bash

# Create a zip file of the Lambda function code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    uv pip install -r requirements.txt --target=dist/data
    cp -r lambda.py custom_agent.py dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package

terraform init
terraform apply