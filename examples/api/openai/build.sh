#!/bin/bash

set -euo pipefail

uv venv --allow-existing

uv sync --find-links ../../../ak-py/dist --all-groups
uv pip install --force-reinstall --find-links ../../../ak-py/dist ak[cli,openai,test] || true # optional, only if local ak is present

create_docker_image() {
    mkdir -p dist/
    uv export --no-hashes > requirements.txt
    uv pip install -r requirements.txt --target=dist  --find-links ../../../ak-py/dist
    uv pip install --force-reinstall --target=dist --find-links ../../../ak-py/dist ak || true
    cp -r app.py tool.py config.yaml dist/
    
    DOCKER_BUILDKIT=0 docker build -t linearsix/lime-ai-ak:latest .
}

create_docker_image
