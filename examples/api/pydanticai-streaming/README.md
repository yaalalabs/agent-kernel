# Agent Kernel streaming Pydantic AI Agents over SSE

This package contains a demo of Agent Kernel streaming a Pydantic AI agent's response token by
token. With `execution.mode: stream` in `config.yaml`, `POST /api/v1/chat` returns a Server-Sent
Events (SSE) stream instead of a single JSON body — each token delta arrives as its own `data:`
frame as the model produces it, driven by `PydanticAIRunner.stream()` (Pydantic AI's
`run_stream()` / `stream_text(delta=True)` under the hood).

## Model provider

`agentkernel[pydanticai]` installs the provider-agnostic `pydantic-ai-slim` core only. This demo
declares `pydantic-ai-slim[openai]` and uses `openai:gpt-4o-mini`, so it needs an `OPENAI_API_KEY`.
Switching the agent provider is a one-line change to the model string in `app.py`.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run REST API:

    python app.py

## Streaming a response

Use `curl -N` (no buffering) to watch the tokens arrive:

    curl -N -X POST http://localhost:8000/api/v1/chat \
      -H "Content-Type: application/json" \
      -d '{"prompt": "a robot learning to paint", "session_id": "demo-1"}'

Each frame is a JSON payload in an SSE `data:` line — a sequence of `delta` frames followed by a
final `done` frame:

    data: {"delta": "Once", "done": false, "session_id": "demo-1"}

    data: {"delta": " upon", "done": false, "session_id": "demo-1"}

    ...

    data: {"done": true, "session_id": "demo-1"}

> Note: streaming stops at the first `output_type` match, so this mode is intended for plain-text
> replies; structured-output agents should use the default (non-stream) execution mode.

> Note: this example has no `*_test.py` — the e2e test harness drives the JSON request/response
> API and has no SSE support. Verify manually with the `curl -N` command above.
