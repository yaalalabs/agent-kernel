#!/bin/bash
set -e

create_auth_deployment_package() {
    # pushd ../ >/dev/null

    rm -rf auth_dist auth_dist.zip
    mkdir -p auth_dist

    if [[ ${1-} != "local" ]]; then
        uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist
    else
        uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist --find-links ../../../../ak-py/dist
    fi
    uv pip install -r requirements.txt --target=auth_dist

    cp -r auth_lambda.py auth_dist/
    # popd >/dev/null

    # cp Dockerfile ./auth_dist/

    cd auth_dist && zip -r ../auth_dist.zip .
}

create_auth_deployment_package "$1"

