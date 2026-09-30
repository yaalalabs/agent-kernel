---
sidebar_position: 5
---

# Google ADK

Integrate Google's Agent Development Kit with Agent Kernel.

## Installation

```bash
pip install agentkernel[adk]
```

## Basic Usage

```python
from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import GoogleADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

GoogleADKModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent System

```python
from adk import Agent as ADKAgent
from agentkernel.adk import GoogleADKModule

general_agent = ADKAgent(
    name="general",
    model="gemini-2.0-flash-exp",
    instructions="You handle general queries",
)

specialist_agent = ADKAgent(
    name="specialist",
    model="gemini-2.0-flash-exp",
    instructions="You handle specialized queries",
)

GoogleADKModule([general_agent, specialist_agent])
```

## Configuration

```bash
export GOOGLE_API_KEY=...
export GEMINI_MODEL=gemini-2.0-flash-exp  # Optional
```

## Tool Binding

Use `GoogleADKToolBuilder` to bind plain Python functions as tools to your Google ADK agents:

```python
from google.adk.agents import Agent as ADKAgent
from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = ADKAgent(
    name="weather",
    model="gemini-2.0-flash-exp",
    description="You provide weather information upon request",
    instruction="Use the get_weather tool for weather-related questions.",
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

GoogleADKModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

Configure structured output with ADK's `output_schema` parameter on `LlmAgent`. ADK returns the final response as a JSON string conforming to the schema; Agent Kernel validates and parses it, returning an `AgentReplyAny` whose `content` is the result as a dict:

```python
from google.adk.agents import LlmAgent
from pydantic import BaseModel
from agentkernel.adk import GoogleADKModule

class CapitalOutput(BaseModel):
    country: str
    capital: str

agent = LlmAgent(
    name="capitals",
    model="gemini-2.0-flash",
    instruction="Answer with the country and its capital.",
    output_schema=CapitalOutput,
)

GoogleADKModule([agent])
```

If the model's reply does not validate against the schema, the runner logs a warning and falls back to a plain `AgentReplyText` with the raw text. `str(reply)` on an `AgentReplyAny` returns the JSON-serialized content, so text-based consumers work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. Streamed runs emit typed [`StreamEvent`](../core-concepts/runner#streaming-execution)s — `TextDelta` for assistant prose, plus `ReasoningStart`/`ReasoningDelta`/`ReasoningEnd` and `ToolCallStart`/`ToolCallArgs`/`ToolCallEnd`/`ToolCallResult` — not just plain text deltas.
:::

## Per-run context/state

Google ADK **round-trips all caller keys** of the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key **except AK-internal ones**. It is merged into the ADK session `state` on input (the internal `ak_tool_context` key is written last, so a caller key of that name cannot displace it); on write-back the accumulated state is read back with `ak_tool_context` and ADK's `app:`/`user:`/`temp:`-prefixed keys stripped — the first two are app- and user-scoped values ADK merges in on read, the third is invocation-scoped, and none are per-session caller state. Because the rest of the state is returned whole, keys a tool **adds** during the run survive to the next turn. ADK's native state is in-memory only, so this write-back is what gives the context cross-turn durability.

Two consequences of reading the state back wholesale:

- **The state is accumulate-only.** ADK keeps every key written to a session for that session's lifetime, so removing a key from `framework_context` does not remove it from ADK — it reappears on the next write-back. To clear a value on ADK, overwrite it (e.g. set it to `None` or `[]`) rather than deleting the key.
- **Agent-written state round-trips too.** A value an agent writes itself — most commonly `LlmAgent(output_key="...")`, which stores the agent's response in the state — is indistinguishable from a key a tool wrote, so it also lands in `framework_context`. Expect the stored context on ADK to hold more than what your tools put there.

## Native run options

Google ADK's own per-run options are declared per agent with
[`Module.run_options`](../core-concepts/runner.md#native-run-options). Agent Kernel constructs the
ADK `Runner` per run, so the options have two destinations: `plugins`, `memory_service`,
`artifact_service`, `credential_service` and `plugin_close_timeout` go to the `Runner(...)`
constructor, and `run_config` goes to `run_async`:

```python
from google.adk.agents.run_config import RunConfig
from google.adk.plugins.base_plugin import BasePlugin

GoogleADKModule([agent]).run_options(
    agent,
    plugins=[ProgressPlugin()],                   # a BasePlugin subclass
    run_config=RunConfig(max_llm_calls=20),
)
```

In `execution.mode: stream` the `RunConfig` is copied with `streaming_mode=SSE`, because the stream
mapping depends on partial events; one warning is logged per runner when you explicitly set a
different `streaming_mode`, and
your object is never mutated. In run mode it is passed as is.

A [run-options factory](../core-concepts/runner.md#native-run-options) runs before the ADK tool
context for the run exists, so `ToolContext.get()` raises `RuntimeError` inside it on this adapter; use the
`session` and `requests` the factory receives instead.

Reserved (raise `ValueError` at declaration): `agent`, `app`, `app_name`, `node`, `session_service`,
`auto_create_session`, `user_id`, `session_id`, `new_message`, `state_delta` (state seeding belongs
to the framework context above), `invocation_id`, `yield_user_message`.

## Human in the loop

A `LongRunningFunctionTool` pauses for a **result**; a tool declared `require_confirmation` pauses for
a **verdict**, arriving as ADK's own `adk_request_confirmation` call. They map to `tool_call` and
`confirmation` respectively.

Enabling this changes how every ADK run is set up, and the consequences are real:

- **Resumability is on for every run.** `ResumabilityConfig(is_resumable=True)` lives on an `App`, so
  the adapter now wraps your agent in one. A per-agent flag would reintroduce the enable switch this
  feature deliberately avoids.
- **Sub-agent routing changes.** With resumability on, a turn whose previous event was a function
  response is routed back to the agent that made the call. **Which agent handles the next turn can
  change in an existing multi-agent app.**
- **ADK sessions grow**, because `is_resumable` also gates agent-state event emission. This is
  inherent to ADK.
- **`ResumabilityConfig` is marked experimental** by ADK and may change without notice. It is the
  only way to enable resumability.

ADK's own warning applies: **a tool may run more than once when resuming.**

A confirmation is a **verdict and nothing else**, and both limits were established by running it.
ADK consumes the confirmation response and writes its own for the original call, so:

- **A structured answer is refused.** Approving with `{"amount": 5}` ran the tool with its original
  arguments — the payload never reaches it. It is now rejected rather than dropped. Model the
  question as a `LongRunningFunctionTool`, whose result *is* the human's answer and takes any shape,
  or have the model propose the value in the tool's arguments for the human to approve.
- **`cancelled` reads as `denied`.** The wording Agent Kernel sends for "nobody decided" rides in
  ADK's `hint`, which does not reach the model. This is the one adapter where the two negative
  statuses are indistinguishable; a long-running tool on ADK keeps the distinction.

A second pause replaces the earlier one, but only among ADK's own: a pause another framework holds
on the same session is independent and stays answerable.

**A prompt sent beside a decision is refused** — established by test, not assumption. ADK itself
rejects a message holding both a function response and text, because a function response resumes an
existing invocation while text starts a new one.

Streaming pauses and resumes correctly at `google-adk` 2.8.0, verified against a real run.

See [Human in the Loop](../advanced/human-in-the-loop.md).

## Features

- ✅ Gemini models
- ✅ Google Cloud integration
- ✅ Function calling
- ✅ Multi-agent coordination
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`output_schema` → `AgentReplyAny`)

## Example

See [examples/cli/adk](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk) for complete examples.

For per-run context/state carried across turns, see [examples/cli/adk_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk_context) (a cart kept in `framework_context`, written through `tool_context.state`, with a tool-added key demonstrating ADK's full read-back).

For per-agent native run options, see [examples/cli/adk-run-options](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk-run-options) (`plugins` and a `RunConfig` with `max_llm_calls`, with a deterministic `Run stats:` line on every reply).
