#!/bin/bash

set -e

create_deployment_packages() {
    pushd ../

    uv export --no-hashes > requirements.txt

    # REST Service dist
    rm -rf dist-rest-service
    mkdir -p dist-rest-service/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-rest-service/data
    else
        uv pip install -r requirements.txt --target=dist-rest-service/data --find-links ../../../ak-py/dist
        uv pip install --force-reinstall --target=dist-rest-service/data --find-links ../../../ak-py/dist agentkernel[adk,api,aws,test]
    fi
	cp config.yaml app_rest_service.py dist-rest-service/data/

    # Agent Runner dist
    rm -rf dist-agent-runner
    mkdir -p dist-agent-runner/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-agent-runner/data
    else
        uv pip install -r requirements.txt --target=dist-agent-runner/data --find-links ../../../ak-py/dist
        uv pip install --force-reinstall --target=dist-agent-runner/data --find-links ../../../ak-py/dist agentkernel[adk,api,aws,test]
    fi
    cp config.yaml app_agent_runner.py dist-agent-runner/data/

    rm -f requirements.txt
    popd || exit 1

    # Copy Dockerfiles into dist directories (must run from deploy/ after popd)
    cp Dockerfile.rest-service ../dist-rest-service/Dockerfile
    cp Dockerfile.agent-runner ../dist-agent-runner/Dockerfile
}

pushd ../../../../ak-py || exit 1
rm -rf dist
./build.sh local
popd

create_deployment_packages $1

terraform init
terraform apply
