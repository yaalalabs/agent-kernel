#!/bin/bash

set -e

create_deployment_packages() {
    local mode="${1-}"
    pushd ../

    uv export --no-hashes > requirements.txt

    for target in dist-rest-service dist-agent-runner; do
        rm -rf "$target"
        mkdir -p "$target/data"

        if [[ "$mode" != "local" ]]; then
            uv pip install -r requirements.txt --target="$target/data"
        else
            uv pip install -r requirements.txt --target="$target/data" \
                --find-links ../../../ak-py/dist
            uv pip install --force-reinstall --target="$target/data" \
                --find-links ../../../ak-py/dist \
                agentkernel[adk,api,aws,test] || true
        fi

        cp config.yaml "$target/data/"
    done

    cp app_rest_service.py dist-rest-service/data/
    cp deploy/Dockerfile.rest-service dist-rest-service/Dockerfile

    cp app_agent_runner.py dist-agent-runner/data/
    cp deploy/Dockerfile.agent-runner dist-agent-runner/Dockerfile

    rm -f requirements.txt
    popd || exit 1
}

create_deployment_packages "$1"

terraform init
terraform apply
