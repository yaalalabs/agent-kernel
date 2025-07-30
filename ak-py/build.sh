#!/bin/bash

uv venv --allow-existing
uv sync --all-packages

uv pip install --group dev
rm -rf dist
uv build --all