#!/bin/bash

uv venv --allow-existing
uv sync
uv pip install --force-reinstall --find-links ../../ak-py/dist ak ak-openai ak-aws # Required if you changed ak-agents after the first install
