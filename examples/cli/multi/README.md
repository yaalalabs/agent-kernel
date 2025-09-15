# Agent Kernel running CrewAI and OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with CrewAI and OpenAI Agents SDK
within a single runtime. Users may interact with agents via the Agent Kernel CLI.

Note that a single session can interact with agents from different frameworks. However agents from
different frameworks cannot communicate with each other and therefore cannot collaborate on tasks.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:
    
    uv run pytest -s 