# Agent Kernel with Pydantic Logfire tracing

This package demonstrates Agent Kernel tracing agent execution to
[Pydantic Logfire](https://logfire.pydantic.dev). The agents are the same OpenAI Agents SDK agents as
[../openai](../openai) — tracing is transparent, so the only difference is `config.yaml`, which sets:

```yaml
trace:
  enabled: true
  type: logfire
```

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Set your OpenAI API key and (optionally) your Logfire write token, then run the demo:

    export OPENAI_API_KEY=sk-...
    export LOGFIRE_TOKEN=...      # optional — see below
    python demo.py

Without `LOGFIRE_TOKEN`, Logfire runs locally and does not ship traces
(`send_to_logfire="if-token-present"`), so the demo still works. With a token, agent runs, LLM calls,
and tool invocations appear in your Logfire dashboard.

Get a write token by signing up at [logfire.pydantic.dev](https://logfire.pydantic.dev), creating a
project, and copying its write token.

To run tests:

    uv run pytest -s
