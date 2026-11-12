#!/bin/bash
set -e # exit if any command in this script fails

# Create request handler lambda deployment package
echo "Creating request handler deployment package..."
create_request_handler_deployment_package() {
    pushd ../
    rm -rf dist_request_handler
    mkdir -p dist_request_handler/data
    uv export --extra request_handler --no-hashes --no-dev > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_request_handler/data
    else
      uv pip install --target=dist_request_handler/data --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel agentkernel[aws,api,thread]
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
    uv export --extra agent_runner --no-hashes --no-dev > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_agent_runner/data
    else
      uv pip install --target=dist_agent_runner/data --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel agentkernel[aws,api,openai]
    fi
    cp -r lambda_agent_runner.py agent.py config.yaml dist_agent_runner/data
    popd || exit 1
    cp Dockerfile.agent_runner ../dist_agent_runner/Dockerfile
}

echo "Creating response handler deployment package..."
create_response_handler_deployment_package() {
    pushd ../
    rm -rf dist_response_handler dist_response_handler.zip
    mkdir -p dist_response_handler
    uv export --extra response_handler --no-hashes --no-dev > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_response_handler
    else
      uv pip install --target=dist_response_handler --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel agentkernel[aws]
    fi
    cp -r lambda_response_handler.py config.yaml dist_response_handler/
    cd dist_response_handler && zip -r ../dist_response_handler.zip .
    popd || exit 1
}

echo "Creating auth deployment package..."
create_auth_deployment_package() {
    pushd ../
    rm -rf dist_auth dist_auth.zip
    mkdir -p dist_auth
    uv export --extra authorizer --no-hashes --no-dev > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install -r requirements.txt --target=dist_auth
    else
      uv pip install --target=dist_auth --find-links ../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel agentkernel[aws]
    fi
    cp -r lambda_auth.py config.yaml dist_auth/
    cd dist_auth && zip -r ../dist_auth.zip .
    popd || exit 1
}

create_request_handler_deployment_package $1
create_agent_runner_deployment_package $1
create_response_handler_deployment_package $1
create_auth_deployment_package $1

terraform init
terraform apply
