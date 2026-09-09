#!/bin/bash

if command -v pyenv >/dev/null 2>&1; then
  uv venv --python "$(pyenv which python)" --allow-existing
else
  uv venv --allow-existing
fi


# `crewai` and `test` extras are declared as mutually exclusive (see pyproject.toml
# [tool.uv.conflicts]) because they pull incompatible posthog versions transitively.
# `test` must always be installed, so it's `crewai` that's excluded from --all-extras.
uv sync --all-extras --no-extra crewai

uv pip install --group dev
rm -rf dist
uv build --all