#!/bin/bash

uv venv --allow-existing
uv sync --all-extras

uv pip install --group dev
rm -rf dist
uv build --all