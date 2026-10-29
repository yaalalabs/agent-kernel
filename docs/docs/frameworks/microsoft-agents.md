---
sidebar_position: 8
---

# Microsoft Agent Framework

Agent Kernel provides a native integration with the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (MAF).

MAF is the unified successor to AutoGen and Semantic Kernel, providing a modern, async-first framework for building agents and multi-agent workflows. Agent Kernel's adapter maps MAF's streaming interface, sessions, tool binding, and framework context round-trips natively into the Agent Kernel execution pipeline.

## Installation

Install Agent Kernel with the `maf` extra, plus the MAF package for your model provider. The `maf` extra installs only the provider-neutral MAF core (`agent-framework-core`):

```bash
pip install "agentkernel[maf]" agent-framework-openai
```

`agent-framework-openai` covers OpenAI, Azure OpenAI, and any OpenAI-compatible endpoint. For other providers, see [Model providers](#model-providers).

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

## Multi-Agent System

MAF turns an agent into a tool with `as_tool()`. Route between agents with **delegation-via-tool**:
give a triage agent the specialists as tools, and register all of them so each is also reachable by name.

```python
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.maf import MAFModule

client = OpenAIChatClient(model="gpt-4.1-mini")

math_agent = Agent(client, name="math", description="Specialist for math problems",
                   instructions="You solve math problems.")
general_agent = Agent(client, name="general", description="Agent for general questions",
                      instructions="You provide general assistance.")

triage_agent = Agent(
    client,
    name="triage",
    description="Routes each question to the right specialist",
    instructions="Use the math tool for math questions and the general tool for everything else. "
    "Return the specialist's answer directly.",
    tools=[math_agent.as_tool(), general_agent.as_tool()],
)

MAFModule([triage_agent, math_agent, general_agent])
```

A delegated agent runs inside the triage agent's Agent Kernel run, so a tool on the specialist sees the
**triage** agent and the same session through `ToolContext.get()`.

## Configuration

```bash
export OPENAI_API_KEY=sk-...        # or the credentials for whichever MAF client you construct
```

MAF's OpenAI clients resolve their credentials **eagerly, at client construction**, so the key must be set
in the environment when your module is imported, not just when a run happens.

## Model providers

The adapter works with any MAF chat client: it only uses MAF core types, so switching models changes the client you pass to `Agent`, never the Agent Kernel code. The OpenAI provider package (`agent-framework-openai`) covers OpenAI, Azure OpenAI, and any OpenAI-compatible endpoint. It has two clients: `OpenAIChatClient` (OpenAI's Responses API) and `OpenAIChatCompletionClient` (Chat Completions):

```python
from agent_framework.openai import OpenAIChatClient

# OpenAI (reads OPENAI_API_KEY)
client = OpenAIChatClient(model="gpt-4o")

# Azure OpenAI
client = OpenAIChatClient(model="gpt-4o", azure_endpoint="https://<resource>.openai.azure.com", api_key="...")

# Any OpenAI-compatible endpoint: vLLM, LM Studio, Ollama's /v1 API, or a LiteLLM proxy for 100+ providers.
# `OpenAIChatClient` targets OpenAI's Responses API, which most compatible servers do not offer, so use the
# Chat Completions client for them:
from agent_framework.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(model="llama3.1", base_url="http://localhost:11434/v1", api_key="unused")
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

## Tool Binding

Use `MAFToolBuilder` to bind plain Python functions as MAF tools:

```python
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.maf import MAFModule, MAFToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = Agent(
    OpenAIChatClient(model="gpt-4.1-mini"),
    name="weather",
    description="Provides weather information.",
    instructions="You provide weather information.",
    tools=MAFToolBuilder.bind([get_weather]),
)

MAFModule([agent])
```

Tools bound this way reach execution context (session, agent, requests) through `ToolContext.get()` —
the same portable mechanism as every other adapter, so a tool function bound here also works unchanged on
any other framework. Native MAF tools that take a `FunctionInvocationContext` instead read the per-run
[framework context](#per-run-contextstate). See [Tools](../core-concepts/tools) for the full guide.

## Structured Output

Configure structured output with MAF's `response_format` option, either in the agent's `default_options` or per
agent through [Native run options](#native-run-options). Agent Kernel detects the parsed result and returns an
`AgentReplyAny` whose `content` is the result as a dict; no re-parsing of text needed:

```python
from pydantic import BaseModel
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.maf import MAFModule

class CalendarEvent(BaseModel):
    name: str
    date: str

agent = Agent(
    OpenAIChatClient(model="gpt-4.1-mini"),
    name="extractor",
    description="Extracts calendar events from text.",
    instructions="Extract the calendar event from the text.",
    default_options={"response_format": CalendarEvent},
)

MAFModule([agent])
```

Pydantic results are converted via `model_dump(mode="json")`, and `str(reply)` returns the JSON-serialized
content, so text-based consumers (chat integrations, logging) work unchanged. See
[Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced,
and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

Structured output applies to non-streaming runs (`execution.mode: rest_sync`, the default, and the CLI). In stream mode the answer is
streamed as text.

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

Like the other adapters, the snapshot is kept per Agent Kernel session under the framework key, so every MAF agent used in one session shares it. That includes the snapshot's `service_session_id`: two agents whose clients keep the conversation on the provider's side would continue one thread id. Use separate sessions for such agents.

## Per-run context/state

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

The adapter injects a copy of the framework context into the native session state under `ak_context` before each run. When the native call completes — including a run that pauses for approval — it merges the tool-modified dictionary back into the AK session, so tool-added keys survive across turns. A run whose native call fails, or a stream interrupted before it drains, leaves the stored context unchanged. The conversation is stored before the context, so a context that cannot be stored (an unpicklable value) loses only the context, never the turn.

The native session state is shared with every MAF context provider configured on the agent, so do not put secrets in the framework context. See `examples/cli/maf_context` for a complete example.

## Native run options

Declare native `Agent.run()` arguments through `Module.run_options`. Model settings belong inside MAF's `options` dictionary:

```python
module.run_options(agent, options={"temperature": 0.5, "max_tokens": 100})
```

For structured output, set `options["response_format"]` to your Pydantic model. The adapter maps the resulting `AgentResponse.value` to `AgentReplyAny` in non-streaming execution.

MAF's `Agent.run` takes no `**kwargs`, so a misspelled or unknown key raises `TypeError` on the first run. The following keys are reserved by the MAF adapter, because the runner sets them itself; declaring one raises `ValueError` at declaration:

| Key | Description |
|---|---|
| `messages` | Built from the `AgentRequest` list by the runner. |
| `stream` | Managed by the runner based on whether `run()` or `stream()` was called. |
| `session` | Managed by the runner based on the AK session context. |

See [examples/cli/maf-run-options](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/maf-run-options) for `options` and `function_invocation_kwargs` with progress reported by MAF's own middleware.

## Human in the loop

This adapter pauses on MAF's native **tool approval**. A tool declared with
`approval_mode="always_require"` is held back when the model calls it, and the run returns a paused reply
(`kind: "tool_call"`, with the tool name and arguments) instead of running it:

```python
from agent_framework import tool

@tool(approval_mode="always_require")
def issue_refund(order_id: str) -> str:
    """Refund an order."""
    ...
```

Or keep the tool a plain function and gate it through the tool builder, which forwards its keyword options
to MAF's `tool()`. The options apply to every function in the call, so tools wanting different ones are
bound separately:

```python
tools = MAFToolBuilder.bind([issue_refund], approval_mode="always_require")
```

The pause is durable: the record carries MAF's serialized `AgentSession` and the pending requests, so the
decision can arrive later on any replica with a shared session backend. Answer it with a `resume` block;
`approved` runs the tool, while `denied` and `cancelled` both reject it, and MAF tells the model the call was
rejected by the user. **`cancelled` is therefore indistinguishable from `denied` on MAF:** MAF writes its own fixed
rejection text and has no channel for Agent Kernel's "nobody decided" wording or for a decision's `message`.

What MAF cannot carry, refused with a message rather than flattened into a generic reply:

- **A partial resume.** Answer every pending approval together; Agent Kernel names the ids you missed.
- **A payload.** A MAF approval is only approved or rejected, with no channel for replacement arguments.
- **A prompt beside the decisions.** MAF would place it between the tool calls and their results, an order
  model APIs reject. Send it as the next turn.
- **A new prompt while a pause is outstanding.** MAF would silently drop the pending calls, so the turn is
  refused, naming the run to resume.

MAF agents have no native free-text question (`input_required`); ask for a value as an ordinary turn, or
model it as a gated tool's arguments. Only tool approvals pause the run: other requests MAF can return for a
hosted service, such as an OAuth consent request from a hosted MCP tool, are not surfaced as a pause. See [Human in the Loop](../advanced/human-in-the-loop.md).

## Features

- ✅ Function calling (`MAFToolBuilder` and native MAF tools)
- ✅ Per-run context/state (`framework_context` → `session.state["ak_context"]`, full round-trip)
- ✅ Streaming responses (native token streaming with reasoning and tool-call events)
- ✅ Structured output (`response_format` → `AgentReplyAny`)
- ✅ Session management (`AgentSession` snapshot persisted per session)
- ✅ Multimodal input (text, images and files sent as one user message)
- ✅ Native run options (`options`, `function_invocation_kwargs`, …)
- ✅ Any MAF chat client (OpenAI, Azure OpenAI, Anthropic, …)
- ✅ Human in the loop (tool approval pause/resume, durable across replicas)

## Example

See [examples/cli/maf](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/maf) for a
complete CLI example with a bound weather tool.

For per-run context/state carried across turns, see
[examples/cli/maf_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/maf_context)
— a cart kept in the framework context and mutated by native MAF tools through `FunctionInvocationContext`.

For per-agent native run options, see [examples/cli/maf-run-options](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/maf-run-options)
(`options` and `function_invocation_kwargs`, with a deterministic `Run stats:` line on every reply).

For REST, see [examples/api/maf](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/maf), and
[examples/api/maf-streaming](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/maf-streaming)
for token streaming over Server-Sent Events.

## Supported scope

This adapter targets native MAF `Agent` instances and maps their execution to Agent Kernel's request/reply, session, framework-context, tool, and streaming interfaces.

Background continuation tokens are not exposed through these interfaces. Native background continuation is separate from Agent Kernel's queue-based asynchronous execution. MAF workflow agents have not yet been validated with this adapter.
