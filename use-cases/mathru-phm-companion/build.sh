#!/bin/bash
set -euo pipefail

uv venv
uv sync --all-extras --dev
