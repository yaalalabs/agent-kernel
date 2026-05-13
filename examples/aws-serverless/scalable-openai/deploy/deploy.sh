#!/bin/bash
set -e # exit if any command in this script fails

echo "Creating request handler deployment package..."
create_request_handler_deployment_package() {
    pushd ../
    # Legacy Zip creation - commented out for Image mode
    # rm -rf dist_request_handler dist_request_handler.zip
    # mkdir -p dist_request_handler
    # uv export --no-hashes > requirements.txt
    # if [[ ${1-} != "local" ]]; then
    #   uv pip install -r requirements.txt --target=dist_request_handler
    # else
    #   uv pip install --force-reinstall --target=dist_request_handler --find-links ../../../ak-py/dist agentkernel[aws,redis] || true
    # fi
    # cp -r lambda_request_handler.py config.yaml dist_request_handler/
    # cd dist_request_handler && zip -r ../dist_request_handler.zip .
    
    # New Image creation
    rm -rf dist_request_handler
    mkdir -p dist_request_handler/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_request_handler/data
    else
      uv pip install -r requirements.txt --target=dist_request_handler/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist_request_handler/data --find-links ../../../ak-py/dist agentkernel[aws,redis] || true
    fi
    cp -r lambda_request_handler.py config.yaml dist_request_handler/data
    popd || exit 1
    cp Dockerfile.request_handler ../dist_request_handler/Dockerfile
}

# Create agent runner lambda deployment package
echo "Creating agent runner deployment package..."
create_agent_runner_deployment_package() {
    pushd ../
    rm -rf dist_agent_runner
    mkdir -p dist_agent_runner/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_agent_runner/data
    else
      uv pip install -r requirements.txt --target=dist_agent_runner/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist_agent_runner/data --find-links ../../../ak-py/dist agentkernel[aws,openai,redis] || true
    fi
    cp -r lambda_agent_runner.py config.yaml dist_agent_runner/data
    popd || exit 1
    cp Dockerfile.agent_runner ../dist_agent_runner/Dockerfile
}


echo "Creating response handler deployment package..."
create_response_handler_deployment_package() {
    pushd ../
    # Legacy Zip creation - commented out for Image mode
    # rm -rf dist_response_handler dist_response_handler.zip
    # mkdir -p dist_response_handler
    # uv export --no-hashes > requirements.txt
    # if [[ ${1-} != "local" ]]; then
    #   uv pip install -r requirements.txt --target=dist_response_handler
    # else
    #   uv pip install --force-reinstall --target=dist_response_handler --find-links ../../../ak-py/dist agentkernel[aws,redis] || true
    # fi
    # cp -r lambda_response_handler.py config.yaml dist_response_handler/
    # cd dist_response_handler && zip -r ../dist_response_handler.zip .
    
    # New Image creation
    rm -rf dist_response_handler
    mkdir -p dist_response_handler/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_response_handler/data
    else
      uv pip install -r requirements.txt --target=dist_response_handler/data  --find-links ../../../ak-py/dist
      uv pip install --force-reinstall --target=dist_response_handler/data --find-links ../../../ak-py/dist agentkernel[aws,redis] || true
    fi
    cp -r lambda_response_handler.py config.yaml dist_response_handler/data
    popd || exit 1
    cp Dockerfile.response_handler ../dist_response_handler/Dockerfile
}

create_request_handler_deployment_package $1
create_agent_runner_deployment_package $1
create_response_handler_deployment_package $1

terraform init
terraform apply