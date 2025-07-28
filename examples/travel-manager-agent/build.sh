#!/bin/bash

uv venv --allow-existing
uv pip install .
uv pip install --group dev