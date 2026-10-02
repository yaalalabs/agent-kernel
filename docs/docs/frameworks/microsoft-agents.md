---
sidebar_position: 8
---

# Microsoft Agent Framework

Agent Kernel provides a native integration with the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (MAF).

MAF is the unified successor to AutoGen and Semantic Kernel, providing a modern, async-first framework for building agents and multi-agent workflows. Agent Kernel's adapter maps MAF's streaming interface, sessions, tool binding, and framework context round-trips natively into the Agent Kernel execution pipeline.

## Setup

First, install Agent Kernel with the `maf` extra, and the MAF provider package of your choice (e.g., `agent-framework-openai`):

```bash
pip install "agentkernel[maf]"
pip install agent-framework-openai
```

## Basic Usage

When using the MAF adapter, you build your agent using MAF's `Agent` class and pass it directly to `MAFModule`. 

Following AK's "wrap, don't abstract" principle, you construct and pass the `chat_client` directly to the agent. Agent Kernel does not intercept or hide the underlying model client configuration.

```python
import asyncio
from agent_framework import Agent, tool
from agent_framework_openai import OpenAIChatClient
from agentkernel.maf import MAFModule
from agentkernel.cli import CLIRunner

@tool
def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"The weather in {location} is 72 degrees and sunny."

async def main():
    # Construct the native MAF client
    client = OpenAIChatClient(model="gpt-4o")
    
    # Create the MAF agent
    agent = Agent(
        name="assistant",
        chat_client=client,
        system_message="You are a helpful assistant.",
        tools=[get_weather]
    )

    # Wrap in Agent Kernel
    module = MAFModule([agent])
    runner = CLIRunner(module=module)
    
    await runner.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## Streaming

Streaming is fully supported. Agent Kernel converts MAF's `AgentResponseUpdate` stream into native Agent Kernel `StreamEvent`s (including `TextDelta`, `ToolCallStart`, and `ToolCallArgs`), allowing real-time rendering in Agent Kernel's CLI, UI, and WebSocket integrations.

This mapping requires no code changes — simply use a streaming runner (like `CLIRunner` or `AgentRunner.stream()`).

## Session Management

Agent Kernel manages the conversation state across interactions and persists it natively to your configured session store (e.g., Redis, DynamoDB, PostgreSQL, or memory).

MAF's `ChatMessageStore` or state bag is wrapped inside `MAFSession` and automatically saved and loaded across turns, allowing multi-turn conversations without manual history management.

## Framework Context

If you need to pass additional kwargs or context data natively down to `agent.run(..., **kwargs)`, you can seed the session's framework context before the run:

```python
session = Session()
session.set_framework_context({
    "user_id": "user-123",
    "theme": "dark"
})

# These keys will be destructured as **kwargs into agent.agent.run()
await runner.run(agent, session, [AgentRequestText(prompt="Hello")])
```

The MAF adapter loads the framework context from the `Session`, merges any resolved run options over it, and passes it to MAF. After the run, the (potentially modified) context is saved back to the session state.

## Run Options

The following keys are reserved by the MAF adapter and cannot be injected via dynamic run options, as they are strictly controlled by the runner based on the execution shape:

| Key | Description |
|---|---|
| `stream` | Managed by the runner based on whether `run()` or `stream()` was called. |
| `session_id` | Managed by the runner based on the AK session context. |
