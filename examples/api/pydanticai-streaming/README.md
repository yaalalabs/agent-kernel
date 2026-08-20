# Agent Kernel streaming Pydantic AI Agents over SSE

This package contains a demo of Agent Kernel streaming a Pydantic AI agent's response as it is
produced. With `execution.mode: stream` in `config.yaml`, `POST /api/v1/chat` returns a Server-Sent
Events (SSE) stream instead of a single JSON body — each frame carries one typed **stream event** as
the model produces it, driven by `PydanticAIRunner.stream()` (Pydantic AI's `run_stream_events()`
under the hood).

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

Each frame is a JSON payload in an SSE `data:` line. Every frame carries `event` — the typed event it
was built from — and `delta` appears **only** on a `text_delta`, so the message boundaries carry no
`delta` key at all. The assistant's reply is bracketed, then a final `done` frame closes the stream:

    data: {"event": {"type": "message_start", "message_id": "m1", "role": "assistant"}, "done": false, "session_id": "demo-1"}

    data: {"delta": "Once", "event": {"type": "text_delta", "message_id": "m1", "content": "Once"}, "done": false, "session_id": "demo-1"}

    data: {"delta": " upon", "event": {"type": "text_delta", "message_id": "m1", "content": " upon"}, "done": false, "session_id": "demo-1"}

    ...

    data: {"event": {"type": "message_end", "message_id": "m1"}, "done": false, "session_id": "demo-1"}

    data: {"done": true, "session_id": "demo-1"}

A client that concatenates the reply must therefore test for `delta` rather than assume every
non-terminal frame has one.

> Note: structured outputs behave the same here as on the non-streaming path. `run_stream_events()`
> wraps Pydantic AI's own `run()`, so a streamed run no longer stops at the first `output_type` match
> the way the older `run_stream()` did.

> Note: the shared `agentkernel.test` client drives the JSON request/response API and has no SSE
> support, so `app_test.py` consumes the `text/event-stream` body directly with httpx — it asserts
> the frame contract (a run of `delta` frames followed by a single terminal `done` frame). Run it
> with `uv run pytest -s` (requires `OPENAI_API_KEY`), or verify manually with the `curl -N` command
> above.
