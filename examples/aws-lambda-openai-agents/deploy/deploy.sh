#!/bin/bash

# Create a zip file of the Lambda function code
pushd ../
rm -rf dist dist.zip
mkdir dist
uv export --no-hashes > requirements.txt
uv pip install -r requirements.txt --target=dist
cp -r lambda.py dist/
cd dist && zip -r ../dist.zip .
popd || exit 1

terraform init
terraform apply \
  -var="region=ap-southeast-2" \
  -var="product_alias=ak-openai-lambda" \
  -var="env_alias=dev" \
  -var="module_name=examples" \

