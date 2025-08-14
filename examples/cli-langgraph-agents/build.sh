#!/bin/bash

uv venv --allow-existing
uv sync
uv pip install --force-reinstall --find-links ../../ak-py/dist ak # Required if you changed ak after the first install
