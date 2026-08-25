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

Each frame is a JSON payload in an SSE `data:` line — a `StreamChunk` serialized with
`exclude_none=True`, so absent fields are absent keys. The assistant message is bracketed by
`message_start`/`message_end` boundary frames (synthesised by `Runtime.stream()` today, since this
adapter still yields plain token strings) around a run of `text_delta` frames, followed by a final
`done` frame:

    data: {"event": {"type": "message_start", "message_id": "a1b2c3", "role": "assistant"}, "done": false, "session_id": "demo-1"}

    data: {"delta": "Once", "event": {"type": "text_delta", "message_id": "a1b2c3", "content": "Once"}, "done": false, "session_id": "demo-1"}

    data: {"delta": " upon", "event": {"type": "text_delta", "message_id": "a1b2c3", "content": " upon"}, "done": false, "session_id": "demo-1"}

    ...

    data: {"event": {"type": "message_end", "message_id": "a1b2c3"}, "done": false, "session_id": "demo-1"}

    data: {"done": true, "session_id": "demo-1"}

`delta` is populated only on `text_delta` frames, and always equals `event.content`; every other
frame — the boundaries included — carries no `delta` key at all, so accumulate the response text
by filtering on the presence of `delta` rather than by frame position.

> Note: streaming stops at the first `output_type` match, so this mode is intended for plain-text
> replies; structured-output agents should use the default (non-stream) execution mode.

> Note: the shared `agentkernel.test` client drives the JSON request/response API and has no SSE
> support, so `app_test.py` consumes the `text/event-stream` body directly with httpx — it asserts
> the frame contract described above (boundary frames bracketing a run of `text_delta` frames,
> followed by a single terminal `done` frame). Run it with `uv run pytest -s` (requires
> `OPENAI_API_KEY`), or verify manually with the `curl -N` command above.
