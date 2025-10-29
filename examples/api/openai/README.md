# Agent Kernel running OpenAI Agent SDK Agents on a REST API

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK. Users
can interact with agents via the Agent Kernel REST API. The example also demonstrates how to add a custom route
to the Agent Kernel REST API. This allows the users to utilize existing REST server for their custom REST endpoint
creations.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run REST API:

    python app.py


To run tests:

    uv run pytest -s 