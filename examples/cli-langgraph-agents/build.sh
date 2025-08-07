#!/bin/bash

uv venv --allow-existing
uv sync
uv pip install --force-reinstall --find-links ../../ak-py/dist ak-langgraph # Required if you changed ak-agents after the first install
