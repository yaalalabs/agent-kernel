# Agent Kernel running Smolagents and OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with Smolagents and OpenAI Agents SDK
within a single runtime. Agents are exposed as MCP tools

Users may interact with agents via the Agent Kernel REST API and the MCP Client API. Agents have 
been made MCP available and accessible by setting both `mcp.enabled = True` and `mcp.expose_agents = True`

`server.py` starts with a plain `RESTAPI.run()`, which runs the queue pipeline in one process on the
in-memory queue. Agent tool calls go through it like REST chat requests: each one is queued, run by
the agent-runner thread, and its reply is read back from the response store. Expect each reply to
take at least about one second, since the reply is picked up by polling the store
(`execution.response_store.delay`). The custom tools added in `server.py` still run directly in the
server process. See the [MCP server docs](https://kernel.yaala.ai/docs/api/mcp-server) for the entry
points that support agent tools.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run server:

    python server.py


To run tests:

    uv run pytest -s 