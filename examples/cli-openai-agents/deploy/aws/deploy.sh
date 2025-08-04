#!/bin/bash

terraform init
terraform apply \
  -var="region=ap-southeast-2" \
  -var="product_alias=ak-openai-examples" \
  -var="env_alias=dev" \
  -var="module_name=agents" \
  -var="component=Lambda" \
