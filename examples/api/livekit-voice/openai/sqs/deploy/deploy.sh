#!/bin/bash

set -e

create_deployment_packages() {
    pushd ../

    uv export --no-hashes > requirements.txt

    # REST/IO Service (LiveKit Gateway) dist
    rm -rf dist-livekit-io
    mkdir -p dist-livekit-io/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-livekit-io/data
    else
        uv pip install -r requirements.txt --target=dist-livekit-io/data --find-links ../../../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel
    fi
    cp config.yaml app_livekit_io.py dist-livekit-io/data/

    # Agent Runner dist
    rm -rf dist-agent-runner
    mkdir -p dist-agent-runner/data
    if [[ ${1-} != "local" ]]; then
        uv pip install -r requirements.txt --target=dist-agent-runner/data
    else
        uv pip install -r requirements.txt --target=dist-agent-runner/data --find-links ../../../../../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel
    fi
    cp config.yaml app_agent_runner.py dist-agent-runner/data/

    rm -f requirements.txt
    popd || exit 1

    # Copy Dockerfiles into dist directories (must run from deploy/ after popd)
    cp Dockerfile.livekit-io ../dist-livekit-io/Dockerfile
    cp Dockerfile.agent-runner ../dist-agent-runner/Dockerfile
}

create_deployment_packages "$1"

terraform init
terraform apply
