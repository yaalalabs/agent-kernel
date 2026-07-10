# Agent Kernel running OpenAI Agent SDK Agents with Structured Output on a REST API

This package contains a demo of Agent Kernel running an agent built with OpenAI Agents SDK that
produces structured output, exposed via the Agent Kernel REST API. The agent is configured with
`Agent(output_type=ContactCard)`, so the framework returns a Pydantic instance instead of plain
text. Agent Kernel detects this and wraps the result in an `AgentReplyAny` whose `content` field
carries the structured output as a dict.

The example also demonstrates a post-execution hook (`NormalizeContactPostHook`) operating on the
structured reply: hooks receive the `AgentReplyAny` object and can read and modify `reply.content`
directly, without re-parsing a stringified reply.

The REST API renders an `AgentReplyAny` as its JSON serialization in the `result` field:

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Content-Type: application/json" \
      -d '{"prompt": "John Doe can be reached at John.Doe@example.com or on 077-1234567", "session_id": "demo", "agent": "contact"}'

    {"result": "{\"name\": \"John Doe\", \"email\": \"john.doe@example.com\", \"phone\": \"077-1234567\"}"}

In-process consumers can use `AgentService.run_multi()` to get the reply object and read the dict
directly — no re-parsing needed:

```python
reply = await service.run_multi([AgentRequestText(text="...")])
if isinstance(reply, AgentReplyAny):
    data = reply.content  # dict
```

Note: structured output applies to non-streaming execution only; streamed runs emit text deltas.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run REST API:

    python app.py

To run tests:

    uv run pytest -s
