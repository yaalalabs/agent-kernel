# Agent Kernel running CrewAI and OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with CrewAI and OpenAI Agents SDK
within a single runtime. Agents are exposed as MCP tools

Users may interact with agents via the Agent Kernel REST API and the MCP Client API. Agents have 
been made MCP available and accessible simply by setting `mcp.enabled = True`

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run server:

    python server.py


To run tests:

    uv run pytest -s 