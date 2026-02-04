#!/bin/bash
set -e

create_auth_deployment_package() {
    rm -rf auth_dist auth_dist.zip
    mkdir -p auth_dist
    # mkdir -p auth_dist/data # For Docker Lambda Package creation....

    if [[ ${1-} != "local" ]]; then
        uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist
        # uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist/data # For Docker Lambda Package creation....
    else
        uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist --find-links ../../../../ak-py/dist
        # uv pip install --force-reinstall --no-deps agentkernel[api,aws] --target=auth_dist/data --find-links ../../../../ak-py/dist # For Docker Lambda Package creation....
    fi
    uv pip install -r requirements.txt --target=auth_dist
    # uv pip install -r requirements.txt --target=auth_dist/data # For Docker Lambda Package creation....

    cp -r lambda.py auth_dist/
    # cp -r lambda.py auth_dist/data/ # For Docker Lambda Package creation....
    

    cp Dockerfile ./auth_dist/

    cd auth_dist && zip -r ../auth_dist.zip .
    # cd auth_dist/data && zip -r ../../auth_dist.zip . # For Docker Lambda Package creation....
}

create_auth_deployment_package "$1"

