---
sidebar_position: 8
---

# Microsoft Agent Framework

Agent Kernel provides a native integration with the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (MAF).

MAF is the unified successor to AutoGen and Semantic Kernel, providing a modern, async-first framework for building agents and multi-agent workflows. Agent Kernel's adapter maps MAF's streaming interface, sessions, tool binding, and framework context round-trips natively into the Agent Kernel execution pipeline.

## Setup

Install Agent Kernel with the `maf` extra. It includes the MAF core and the OpenAI provider (`agent-framework-openai`):

```bash
pip install "agentkernel[maf]"
```

To use another model provider, install its MAF package as well. See [Model providers](#model-providers).

## Basic Usage

When using the MAF adapter, you build your agent using MAF's `Agent` class and pass it directly to `MAFModule`.

Following AK's "wrap, don't abstract" principle, you construct and pass the `chat_client` directly to the agent. Agent Kernel does not intercept or hide the underlying model client configuration.

```python
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
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

## Model providers

The adapter works with any MAF chat client: it only uses MAF core types, so switching models changes the client you pass to `Agent`, never the Agent Kernel code. The `maf` extra ships the OpenAI provider, which also covers Azure OpenAI and any OpenAI-compatible endpoint:

```python
from agent_framework.openai import OpenAIChatClient

# OpenAI (reads OPENAI_API_KEY)
client = OpenAIChatClient(model="gpt-4o")

# Azure OpenAI
client = OpenAIChatClient(model="gpt-4o", azure_endpoint="https://<resource>.openai.azure.com", api_key="...")

# Any OpenAI-compatible endpoint: vLLM, LM Studio, Ollama's /v1 API, or a LiteLLM proxy for 100+ providers
client = OpenAIChatClient(model="llama3.1", base_url="http://localhost:11434/v1", api_key="unused")
```

For a native provider integration, install that provider's MAF package and import its client from the matching `agent_framework` namespace:

```bash
pip install agent-framework-anthropic   # also: agent-framework-gemini, -bedrock, -mistral, -ollama, -foundry
```

```python
from agent_framework.anthropic import AnthropicClient

client = AnthropicClient(model="claude-sonnet-5-5")  # reads ANTHROPIC_API_KEY
```

If the provider package is missing, MAF raises an error naming the package to install.

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

To pass application state to MAF tools, seed the session's framework context from a pre-hook. Tools read and write it through MAF's native `FunctionInvocationContext`:

```python
from agent_framework import Agent, FunctionInvocationContext
from agentkernel.core import PreHook
from agentkernel.maf import MAFModule, MAFToolBuilder


def add_to_cart(ctx: FunctionInvocationContext, item: str) -> str:
    """Add an item to the cart carried in the per-run context."""
    ctx.session.state["ak_context"].setdefault("cart", []).append(item)
    return f"Added {item}."


class SeedContextPreHook(PreHook):
    async def on_run(self, session, agent, requests):
        if session.get_framework_context() is None:
            session.set_framework_context({"user_id": "user-123", "cart": []})
        return requests

    def name(self) -> str:
        return "seed_context"


agent = Agent(client, name="shopping", instructions="...", tools=MAFToolBuilder.bind([add_to_cart]))
MAFModule([agent]).pre_hook(agent, [SeedContextPreHook()])
```

The adapter injects a copy of the framework context into the native session state under `ak_context` before each run. After a successful run, it merges the tool-modified dictionary back into the AK session, so tool-added keys survive across turns. A failed or interrupted run leaves the stored context unchanged.

The native session state is shared with every MAF context provider configured on the agent, so do not put secrets in the framework context. See `examples/cli/maf_context` for a complete example.

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
