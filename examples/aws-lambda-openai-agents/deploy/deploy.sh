#!/bin/bash

# Create a zip file of the Lambda function code
create_deployment_package() {
    pushd ../
    rm -rf dist dist.zip
    mkdir dist
    uv export --no-hashes > requirements.txt
    uv pip install -r requirements.txt --target=dist
    cp -r lambda.py dist/
    cd dist && zip -r ../dist.zip .
    popd || exit 1
}

create_deployment_package

terraform init
terraform apply