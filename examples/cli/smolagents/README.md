# Agent Kernel running HuggingFace smolagents Agents

This package contains a demo of Agent Kernel running agents built with HuggingFace `smolagents`. Users may
interact with agents via the Agent Kernel CLI.

This example utilizes `CodeAgent` alongside tools to natively evaluate mathematical expressions.

## Prerequisites

These demos use LiteLLM with `openai/gpt-4o`, so set your OpenAI API key before running:

    export OPENAI_API_KEY="your_openai_api_key_here"

If you switch the model provider, set the corresponding provider credentials (for example, `HF_TOKEN`
for HuggingFace-hosted models).

## Installation

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

## Running the Demos

Run the ToolCalling demo (used by `demo_test.py`):

    uv run demo_toolcalling.py

Run the CodeAgent demo:

    uv run demo_codeagent.py

## Role of the ToolCalling Agent and CodeAgent

- Use `demo_toolcalling.py` for normal chat and conversational Q&A.
- Use `demo_codeagent.py` for task-oriented prompts that benefit from code execution or tool usage.

`CodeAgent` is optimized for execution-style reasoning. Open-ended small-talk prompts such as "hi" or
"hello, how are you?" can cause extra internal steps and may feel like loops. For smoother conversational behavior,
prefer the ToolCalling demo.
