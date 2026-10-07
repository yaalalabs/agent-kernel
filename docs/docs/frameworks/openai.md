---
sidebar_position: 2
---

# OpenAI Agents SDK

Integrate OpenAI's official Agents SDK with Agent Kernel.

## Installation

```bash
pip install agentkernel[openai]
```

## Basic Usage

```python
from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent System

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule

# Define agents with handoff capabilities
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide general assistance.",
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist for math problems",
    instructions="You solve math problems.",
)

OpenAIModule([general_agent, math_agent])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4  # Optional, override default
```

## Tool Binding

Use `OpenAIToolBuilder` to bind plain Python functions as tools to your OpenAI agents:

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = OpenAIAgent(
    name="weather",
    instructions="You provide weather information.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

OpenAIModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

Configure structured output with the OpenAI Agents SDK's `output_type` parameter. Agent Kernel detects the structured result and returns an `AgentReplyAny` whose `content` is the result as a dict; no re-parsing of text needed:

```python
from agents import Agent as OpenAIAgent
from pydantic import BaseModel
from agentkernel.openai import OpenAIModule

class CalendarEvent(BaseModel):
    name: str
    date: str

agent = OpenAIAgent(
    name="extractor",
    instructions="Extract the calendar event from the text.",
    output_type=CalendarEvent,
)

OpenAIModule([agent])
```

Pydantic results are converted via `model_dump()`, and `str(reply)` returns the JSON-serialized content, so text-based consumers (chat integrations, logging) work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. Streamed runs emit typed [`StreamEvent`](../core-concepts/runner#streaming-execution)s — `TextDelta` for assistant prose, plus `ReasoningStart`/`ReasoningDelta`/`ReasoningEnd` and `ToolCallStart`/`ToolCallArgs`/`ToolCallEnd`/`ToolCallResult` — not just plain text deltas.
:::

## Per-run context/state

OpenAI has **full round-trip** fidelity for the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key. It is injected as the OpenAI Agents SDK run **context** (`Runner.run(..., context=...)`), which tools read and mutate in place via `RunContextWrapper.context`; the mutated object is written back to the session after a successful run, so every key — including ones a tool adds mid-run — survives to the next turn.

## Native run options

The OpenAI Agents SDK's own run arguments (`max_turns`, `hooks`, `run_config`, `error_handlers`)
are declared per agent with
[`Module.run_options`](../core-concepts/runner.md#native-run-options) and merged into `Runner.run` /
`Runner.run_streamed`, identical in both modes:

```python
from agents import RunConfig, RunHooks

class ProgressHooks(RunHooks):
    async def on_tool_start(self, context, agent, tool) -> None:
        ...  # Session.current() resolves here

OpenAIModule([agent]).run_options(
    agent,
    max_turns=25,                                            # the SDK default is 10
    hooks=ProgressHooks(),
    run_config=RunConfig(call_model_input_filter=trim_history),
)
```

Reserved (raise `ValueError` at declaration): `starting_agent`, `input`, `session` (the
`OpenAISession` on the Agent Kernel session), `context` (the framework context above), and
`conversation_id`, `previous_response_id`, `auto_previous_response_id`, which the SDK rejects
alongside the session the runner always passes.

## Human in the loop

Declare a gated tool with the SDK's own flag:

```python
@function_tool(needs_approval=True)
def issue_refund(order_id: str) -> str: ...
```

Or pass it to the tool builder, which forwards its keyword options to `function_tool` and leaves the
tool a plain function with nothing framework-specific on it. The options apply to every function in
the call, so tools wanting different ones are bound separately:

```python
def issue_refund(order_id: str) -> str: ...

tools = OpenAIToolBuilder.bind([issue_refund], needs_approval=True)
```

The run pauses before the tool executes and Agent Kernel returns a paused reply. Two limits are
specific to this adapter, and both are reported rather than silently worked around:

- **A structured answer is refused.** An approval is recorded as a boolean — `RunState.approve()`
  takes no value — so there is nowhere to put "the human chose Large". A `payload` on a decision is
  rejected with a message saying so. **Model "I need a value" as an ordinary question, not a gated
  tool**; or have the model *propose* a value in the tool arguments and let the human approve or deny
  it.
- **A prompt sent beside a decision is refused.** `Runner.run()`'s input is either a `RunState` or new
  input, never both.

**A stale resume is not detected.** Pause, run an ordinary turn, then answer the old pause: you get a
confident answer computed as though the intervening turns never happened. Neither the SDK nor Agent
Kernel tracks this — answer a pause before continuing the conversation.

This is also the only adapter that can hold **two paused runs at once**: a `RunState` is a
self-contained snapshot, so a second pause appends rather than replacing, and each is resumed by its
own `run_id`.

See [Human in the Loop](../advanced/human-in-the-loop.md).

## Features

- ✅ Function calling
- ✅ Multi-agent handoff
- ✅ Streaming responses
- ✅ Structured output (`output_type` → `AgentReplyAny`)
- ✅ Session management
- ✅ Framework-agnostic tool binding

## Example

See [examples/cli/openai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai) for complete examples.

For structured output, see [examples/cli/openai_structured](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_structured) and [examples/api/openai_structured](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/openai_structured) (REST API + post-execution hook).

For per-run context/state carried across turns, see [examples/cli/openai_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_context) (a cart kept in `framework_context`, seeded by a pre-hook and round-tripped by the runner).

For per-agent native run options, see [examples/cli/openai-run-options](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai-run-options) (`max_turns`, a `RunHooks` progress hook and a `RunConfig` with `call_model_input_filter`, with a deterministic `Run stats:` line on every reply).

For run options computed per run, see [examples/cli/openai-dynamic-run-options](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai-dynamic-run-options) (a `Module.run_options` factory that stamps the session id onto a `RunConfig` and tightens `max_turns` for guest sessions, declared beside static keywords).
