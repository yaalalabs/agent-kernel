# Agent Kernel streaming smolagents Agents over SSE

This package contains a demo of Agent Kernel streaming a smolagents agent's response as it is
produced. With `execution.mode: rest_sync` and `execution.message_type: delta` in `config.yaml`,
`POST /api/v1/chat` returns a Server-Sent Events (SSE) stream instead of a single JSON body — each
frame carries one typed **stream event** as the model produces it, driven by
`SmolagentsRunner.stream()` (smolagents' `run(..., stream=True)` under the hood).

## Setup

You will need an `OPENAI_API_KEY` in your environment to run the demo and the tests.

Install dependencies using:

```sh
./build.sh
```

> Note: until a release of `agentkernel` that includes streaming for the `smolagents` extra is
> published to PyPI, build with `./build.sh local` against a locally built `ak-py/dist`.

To run the tests:

```sh
uv run pytest -s
```

Run the REST API:

```sh
uv run python app.py
```

## Streaming a response

Use `curl -N` (no buffering) to watch the tokens arrive:

```sh
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a robot learning to paint", "session_id": "smolagents-stream-1"}'
```

Each frame is a JSON payload in an SSE `data:` line. Assistant prose is bracketed by
`message_start`/`message_end` boundary frames around a run of `text_delta` frames, followed by a
final `done` frame.

smolagents returns its final answer through its built-in `final_answer` tool, so the stream also
carries that tool's `tool_call_start`, `tool_call_args`, `tool_call_end` and `tool_call_result`
events. A tool added with `SmolagentsToolBuilder` streams the same four events. Structured output
remains a non-streaming feature — use the default `execution.message_type: complete` when you need
an `AgentReplyAny`.
