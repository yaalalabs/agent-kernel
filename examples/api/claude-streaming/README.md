# Agent Kernel streaming a Claude Agent SDK agent over SSE

This example streams a Claude agent's reply as it is produced. With `execution.mode: rest_sync` and
`execution.message_type: delta` in `config.yaml`, `POST /api/v1/chat` returns a Server-Sent Events (SSE) stream
instead of a single JSON body. Each frame carries one typed **stream event**, driven by `ClaudeRunner.stream()`,
and a final frame carries `done`.

The agent has one tool, `get_weather`, so a weather question streams the tool call too, not just text.

## Setup

You need Claude credentials: an `ANTHROPIC_API_KEY`, or a configured Bedrock, Vertex or Foundry provider.

Until a release of `agentkernel` with the `claude` extra is on PyPI, build against the local package from the
repository root:

```sh
cd ak-py && uv build && cd ../examples/api/claude-streaming
./build.sh local
```

Use `./build.sh` once a published release includes the Claude adapter.

Run the REST API:

```sh
uv run app.py
```

Run the tests:

```sh
uv run pytest -s
```

## Streaming a response

Use `curl -N` (no buffering) to watch the events arrive:

```sh
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the weather in Tokyo?", "session_id": "claude-stream-1", "agent": "weather"}'
```

Each frame is a JSON payload in an SSE `data:` line:

- **Text**: `message_start`, then `text_delta` frames, then `message_end`. Only `text_delta` frames also carry a
  top-level `delta`.
- **Tool call**: `tool_call_start` (with the tool `name`), `tool_call_args` fragments that join into the JSON
  arguments, `tool_call_end`, and later `tool_call_result` with what the tool returned. All share one
  `tool_call_id`.
- **Done**: a final frame with `done: true`.

To also stream the model's reasoning as `reasoning_start` / `reasoning_delta` / `reasoning_end` frames, set
`thinking={"type": "adaptive", "display": "summarized"}` in `ClaudeAgentOptions`.

Subagent activity (native `AgentDefinition` subagents) is not streamed; only the main agent's events are.
