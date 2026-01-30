#!/bin/bash
set -e

create_auth_deployment_package() {
    # pushd ../ >/dev/null

    rm -rf auth_dist auth_dist.zip
    mkdir -p auth_dist/data

    uv export --no-hashes | grep -v "^agentkernel" > requirements.txt

    if [[ ${1-} != "local" ]]; then
        # uv pip install -r requirements.txt --target=auth_dist/data
        uv pip install agentkernel[api,aws] --target=auth_dist/data
    else
        # uv pip install -r requirements.txt --target=auth_dist/data --find-links ../../../../ak-py/dist
        uv pip install --force-reinstall --no-deps agentkernel[api,deployment] --target=auth_dist/data --find-links ../../../../ak-py/dist
        # uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist/data
    fi

    cp -r auth_lambda.py auth_dist/data
    # popd >/dev/null

    # cp Dockerfile ./auth_dist/

    cd auth_dist && zip -r ../auth_dist.zip .
}

create_auth_deployment_package "$1"

