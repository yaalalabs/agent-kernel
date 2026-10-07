#!/bin/bash
set -e
# Wheels are resolved for the container (python:3.12-slim, linux/amd64), not the build host, so
# building on macOS doesn't vendor darwin native extensions that crash the container.
PIP_TARGET_PLATFORM=(--python-platform x86_64-manylinux_2_28 --python-version 3.12)

# Create a zip file of the app code
create_deployment_package() {
    pushd ../
    rm -rf dist
    mkdir -p dist/data
    uv export --no-hashes > requirements.txt
    if [[ ${1-} != "local" ]]; then
      uv pip install "${PIP_TARGET_PLATFORM[@]}" -r requirements.txt --target=dist/data
    else
      uv pip install "${PIP_TARGET_PLATFORM[@]}" -r requirements.txt --target=dist/data --find-links ../ak-py/dist --upgrade-package agentkernel --reinstall-package agentkernel || true
    fi
    cp -r app.py rag_loader.py rag_system.py tool.py config.yaml rag_storage dist/data
    popd || exit 1
    cp Dockerfile ../dist/
}

cd ../
./build_index.sh --rebuild
cd -

create_deployment_package $1

terraform init
terraform apply
