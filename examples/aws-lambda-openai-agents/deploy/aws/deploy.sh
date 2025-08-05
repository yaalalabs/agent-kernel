#!/bin/bash

# Create a zip file of the Lambda function code
pushd ../..
rm -rf dist dist.zip
mkdir dist
uv export --without-hashes > requirements.txt
uv pip install -r requirements.txt --target=dist
cp -r agent.py lambda.py dist/
cd dist && zip -r ../dist.zip .

popd || exit 1

# Initialize and apply Terraform with the lambda_package module
terraform init
terraform apply \
  -var="region=ap-southeast-2" \
  -var="product_alias=ak-openai-examples" \
  -var="env_alias=dev" \
  -var="module_name=agents" \
  -var="component=lambda" \
