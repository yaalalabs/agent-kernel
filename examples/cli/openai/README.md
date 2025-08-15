# Agent Kernel running OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK. Users may
interact with agents via the Agent Kernel CLI.

## Setup

This example uses AWS CodeArtifact as the primary package index to resolve `ak` dependencies via `uv`.

Prerequisites:
- AWS CLI installed and configured with permissions to access the `agent-kernel` repository in the `yaalalabs` domain (owner `110597261937`) in region `ap-southeast-2`.
- Python 3.12+
- uv installed

Create/activate the virtual environment and install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

## Run

Once dependencies are installed, run the demo with:

    python demo.py
