# Agent Kernel running Smolagents and OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with Smolagents and OpenAI Agents SDK
within a single runtime. Agents are exposed as A2A compatible in addition.

Users may interact with agents via the Agent Kernel REST API and the A2A compatible API. Agents have 
been made A2A compatible and accessible simply by setting `a2a.enabled = True`

`server.py` starts with a plain `RESTAPI.run()`, which runs the queue pipeline in one process on the
in-memory queue. A2A messages go through it like REST chat requests: each one is queued, run by the
agent-runner thread, and its reply is read back from the response store. Expect each reply to take
at least about one second, since the reply is picked up by polling the store
(`execution.response_store.delay`). See the
[A2A server docs](https://kernel.yaala.ai/docs/api/a2a-server) for the entry points that support A2A.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run server:

    python server.py


To run tests:

    uv run pytest -s 