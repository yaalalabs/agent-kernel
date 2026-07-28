# Agent Kernel running Pydantic AI Agents

This package contains a demo of Agent Kernel running agents built with Pydantic AI. Users may
interact with agents via the Agent Kernel CLI.

## Model provider

`agentkernel[pydanticai]` installs the provider-agnostic `pydantic-ai-slim` core only — it ships no
model provider. Pick one explicitly (this demo declares `pydantic-ai-slim[openai]` in
`pyproject.toml` and uses the `openai:gpt-4o-mini` model, so it needs an `OPENAI_API_KEY`). Pydantic
AI's strength is that switching providers is a one-line change to the model string in `demo.py`
(e.g. `anthropic:...`, `google-gla:...`, `bedrock:...`) once the matching provider extra is
installed (`pydantic-ai-slim[anthropic]`, `[google]`, …).

## Multi-agent routing

Pydantic AI has no `handoffs=` primitive. This demo routes with **delegation-via-tool**: a `triage`
agent calls `ask_math` / `ask_weather` / `ask_general` tools that each run the matching specialist
agent and return its answer.

## Running

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s

> Note: until a release of `agentkernel` that includes the `pydanticai` extra is published to PyPI,
> build with `./build.sh local` against a locally built `ak-py/dist`.
