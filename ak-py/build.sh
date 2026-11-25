#!/bin/bash

if command -v pyenv >/dev/null 2>&1; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi


# `crewai` conflicts with `test` (incompatible posthog versions) and with `mcp` (crewai pins mcp<2,
# fastmcp 4 needs mcp>=2.3); see pyproject.toml [tool.uv.conflicts].
# `test` and `mcp` must always be installed, so it's `crewai` that's excluded from --all-extras.
uv sync --all-extras --no-extra crewai

uv pip install --group dev
rm -rf dist
uv build --all