#!/bin/bash

if command -v pyenv; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi

uv sync --all-extras

uv pip install --group dev
rm -rf dist
uv build --all