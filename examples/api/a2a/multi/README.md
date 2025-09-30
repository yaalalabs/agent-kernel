# Agent Kernel running CrewAI and OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with CrewAI and OpenAI Agents SDK
within a single runtime. Agents are exposed as A2A compatible in addition.

Users may interact with agents via the Agent Kernel REST API and the A2A compatible API. Agents have 
been made A2A compatible and accessible simply by setting `a2a.enabled = True`

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run server:

    python server.py


To run tests:

    uv run pytest -s 