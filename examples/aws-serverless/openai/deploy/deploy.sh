#!/bin/bash

# Create a zip file of the Lambda function code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist/data
    else
      uv pip install -r requirements.txt --target=dist/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist/data --find-links ../../../ak-py/dist agentkernel[openai,redis] || true
    fi
    cp -r lambda.py config.yaml dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

create_deployment_package $1

# Create auth deployment package
echo "Creating auth deployment package..."
pushd ../auth_deployment
if [[ ${1-} == "local" ]]; then
    ./create_auth_package.sh local
else
    ./create_auth_package.sh
fi
popd || exit 1


terraform init
terraform apply