# Agent Kernel running Pydantic AI Agents on a REST API

This package contains a demo of Agent Kernel running agents built with Pydantic AI. Users can
interact with agents via the Agent Kernel REST API. The example also demonstrates how to add a
custom route to the Agent Kernel REST API, and how to add a custom middleware (pre-hook) to manage
additional context passed to the agent (RAG-style).

Multi-agent routing uses **delegation-via-tool** (Pydantic AI has no `handoffs=` primitive): the
`triage` agent calls `ask_general` / `ask_support` tools that run the matching specialist.

## Model provider

`agentkernel[pydanticai]` installs the provider-agnostic `pydantic-ai-slim` core only. This demo
declares `pydantic-ai-slim[openai]` and uses `openai:gpt-4.1-mini`, so it needs an `OPENAI_API_KEY`.
Multimodal description/analysis also uses an OpenAI vision model via LiteLLM. Switching the agent
provider is a one-line change to the model string in `app.py`.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run REST API:

    python app.py

To run tests:

    uv run pytest -s

> Note: until a release of `agentkernel` that includes the `pydanticai` extra is published to PyPI,
> build with `./build.sh local` against a locally built `ak-py/dist`.
