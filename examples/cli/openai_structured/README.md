# Agent Kernel running OpenAI Agent SDK Agents with Structured Output

This package contains a demo of Agent Kernel running an agent built with OpenAI Agents SDK that
produces structured output. The agent is configured with `Agent(output_type=ContactCard)`, so the
framework returns a Pydantic instance instead of plain text. Agent Kernel detects this and wraps
the result in an `AgentReplyAny` whose `content` field carries the structured output as a dict.

The CLI (and any other string-oriented consumer) renders an `AgentReplyAny` as its JSON
serialization, so the reply printed on the console is a JSON string:

    (contact) >> John Doe can be reached at john.doe@example.com or on 077-1234567
    {"name": "John Doe", "email": "john.doe@example.com", "phone": "077-1234567"}
In-process consumers can use `AgentService.run_multi()` to get the reply object and read the dict
directly — no re-parsing needed:

```python
reply = await service.run_multi([AgentRequestText(prompt="...")])
if isinstance(reply, AgentReplyAny):
    data = reply.content  # dict
```

Note: structured output applies to non-streaming execution only; streamed runs emit text deltas.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s
