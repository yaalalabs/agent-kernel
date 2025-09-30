# Agent Kernel running OpenAI Agent SDK Agents on Docker

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK in a Docker container. Users
may interact with agents via the Agent Kernel REST API.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    docker run -e  OPENAI_API_KEY=<openai_api_key> -p 8000:8000 yaalalabs/ak-openai-demo:latest
    # This will start a server on port 8000. REST Endpoints are available at http://localhost:8000/run

Sample request:

    {
        "prompt": "Customer's name is Andy Dufresne. He deposited some cash",
        "session_id": "unique_thread_id_1",
        "agent": "support"
    }