# Agent Kernel streaming Microsoft Agent Framework (MAF) over SSE

This package contains a demo of Agent Kernel streaming a MAF agent's response as it is produced. With `execution.mode: stream` in `config.yaml`, `POST /api/v1/chat` returns a Server-Sent Events (SSE) stream instead of a single JSON body — each frame carries one typed **stream event** as the model produces it, driven by `MAFRunner.stream()`.

## Setup

You will need an `OPENAI_API_KEY` in your environment to run the demo and the tests.

Install dependencies using:

```sh
./build.sh
```

To run the tests:

```sh
uv run pytest -s
```

Run REST API:

```sh
uv run python app.py
```

## Streaming a response

Use `curl -N` (no buffering) to watch the tokens arrive:

```sh
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a tiny 1-sentence story about a bug.", "session_id": "demo-stream-1"}'
```

Each frame is a JSON payload in an SSE `data:` line. The assistant message is bracketed by `message_start`/`message_end` boundary frames around a run of `text_delta` frames, followed by a final `done` frame.
