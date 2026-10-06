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
from agent_framework import Agent
from agent_framework_openai import OpenAIChatClient
from agentkernel.maf import MAFModule, MAFToolBuilder
from agentkernel.cli import CLI

def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"The weather in {location} is 72 degrees and sunny."

# Construct the native MAF client
client = OpenAIChatClient(model="gpt-4o")

# Create the MAF agent
agent = Agent(
    client,
    name="assistant",
    instructions="You are a helpful assistant.",
    tools=MAFToolBuilder.bind([get_weather])
)

# Wrap in Agent Kernel
module = MAFModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Streaming

Agent Kernel converts text, reasoning, and tool updates from MAF's `AgentResponseUpdate` stream into native Agent Kernel `StreamEvent`s (including `TextDelta`, `ToolCallStart`, and `ToolCallArgs`), allowing real-time rendering in Agent Kernel's CLI, UI, and WebSocket integrations.

This mapping requires no code changes to your MAF agents. You can consume the stream via Agent Kernel's underlying service layer:

```python
import asyncio
from agentkernel.core import AgentService, AgentRequestText

async def main():
    service = AgentService()
    service.select(name="assistant")

    # stream_multi returns an async generator of StreamEvent chunks
    async for chunk in service.stream_multi([AgentRequestText(prompt="Hello")]):
        if chunk.delta is not None:
            print(chunk.delta, end="", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
```

## Session Management

Agent Kernel manages the conversation state across interactions and persists it to your configured session store (e.g., Redis, DynamoDB, or memory).

The adapter stores an `AgentSession.to_dict()` snapshot in `MAFSession` and restores it with `AgentSession.from_dict()` before each turn, allowing multi-turn conversations without manual history management.

## Framework Context

If you need to pass additional application context natively down to MAF's tool contexts, you can seed the session's framework context before the run:

```python
from agentkernel.core import Session
from agentkernel.core.model import AgentRequestText
from agentkernel.framework.maf.maf import MAFAgent, MAFRunner

runner = MAFRunner()
ak_agent = MAFAgent("assistant", runner, agent)

session = Session("session-123")
session.set_framework_context({
    "user_id": "user-123",
    "theme": "dark"
})

# This dictionary is injected into native_session.state["ak_context"]
await runner.run(ak_agent, session, [AgentRequestText(prompt="Hello")])
```

The MAF adapter loads the framework context from the `Session` and injects it into a dedicated namespace (`FunctionInvocationContext.session.state["ak_context"]`). Tools can read and write to this dictionary natively, and after the run, the modified context is saved back to the AK session state.

## Run Options

Declare native `Agent.run()` arguments through `Module.run_options`. Model settings belong inside MAF's `options` dictionary:

```python
module.run_options(agent, options={"temperature": 0.5, "max_tokens": 100})
```

For structured output, set `options["response_format"]` to your Pydantic model. The adapter maps the resulting `AgentResponse.value` to `AgentReplyAny` in non-streaming execution.

The following keys are reserved by the MAF adapter and cannot be injected via dynamic run options, as they are strictly controlled by the runner based on the execution shape:

| Key | Description |
|---|---|
| `messages` | Built from the `AgentRequest` list by the runner. |
| `stream` | Managed by the runner based on whether `run()` or `stream()` was called. |
| `session` | Managed by the runner based on the AK session context. |

## Supported scope

This adapter targets native MAF `Agent` instances and maps their execution to Agent Kernel's request/reply, session, framework-context, tool, and streaming interfaces.

Native approval exchanges and background continuation tokens are not exposed through these interfaces. Native background continuation is separate from Agent Kernel's queue-based asynchronous execution. MAF workflow agents have not yet been validated with this adapter.
