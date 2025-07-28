#!/bin/bash

uv venv --allow-existing
uv pip install -e ak-*
uv pip install --group dev
rm -rf dist
uv build --all