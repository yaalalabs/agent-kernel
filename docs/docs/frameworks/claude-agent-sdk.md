---
sidebar_position: 8
---

# Claude Agent SDK

Integrate the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) with Agent Kernel. The
Claude Agent SDK is the agent harness behind Claude Code, packaged as a library. Choose it when you want that
harness: built-in file, shell and web tools, subagents, skills, hooks, a permission engine and automatic
context compaction. For a plain tool-calling agent on Claude models, [Pydantic AI](./pydantic-ai) with its
Anthropic provider is lighter.

:::info How it runs
Each run starts a Claude Code CLI subprocess and talks to it over stdin/stdout. The CLI is bundled in the
`claude-agent-sdk` wheel (a native binary of about 240 MB; Node.js is not needed). Expect roughly half a
second to start a run and a few hundred MB of memory per concurrent run; Anthropic suggests planning for
1 GiB RAM and 1 CPU per concurrent agent. See [Deployment](#deployment).
:::

## Installation

```bash
pip install agentkernel[claude]
```

Authenticate with an Anthropic API key or a cloud provider. Anthropic does not allow third-party products to
offer a claude.ai login.

:::caution Set exactly one of these
Setting more than one, or setting a cloud provider without real credentials behind it, makes the Claude Code CLI
hang silently instead of raising an error — there is no fast-fail check.
:::

```bash
export ANTHROPIC_API_KEY=...          # Claude API — simplest, no extra setup

# or

export CLAUDE_CODE_USE_BEDROCK=1      # Amazon Bedrock — needs a configured AWS account with Bedrock access to Claude models

# or

export CLAUDE_CODE_USE_VERTEX=1       # Google Vertex AI — needs a configured GCP project with Vertex access to Claude models

# or

export CLAUDE_CODE_USE_FOUNDRY=1      # Microsoft Foundry — needs configured Foundry credentials
```

## Basic Usage

The SDK has no named agent object: an agent is configured by `ClaudeAgentOptions`. Agent Kernel adds a
`ClaudeAgentSpec` that gives it a name, a description and its tools, and passes the options through unchanged.

```python
from claude_agent_sdk import ClaudeAgentOptions

from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from agentkernel.cli import CLI


def get_weather(city: str) -> str:
    """
    Returns the weather for a city.
    :param city: The city to report the weather for.
    """
    return f"The weather in {city} is sunny."


general = ClaudeAgentSpec(
    name="general",
    description="Agent for general and weather questions",
    options=ClaudeAgentOptions(
        model="sonnet",
        system_prompt="You are a helpful assistant. Use get_weather for weather questions.",
        tools=[],                   # no built-in Claude Code tools
        setting_sources=[],         # ignore ~/.claude settings and CLAUDE.md
        permission_mode="dontAsk",  # deny anything not explicitly approved
        verbatim_prompts=True,      # don't expand @path mentions in user text
    ),
    tools=ClaudeToolBuilder.bind([get_weather]),
)

ClaudeModule([general])

if __name__ == "__main__":
    CLI.main()
```

## Server Safety

Agent Kernel keeps the SDK's own defaults, and on a server those defaults are wide open. Unless you set
otherwise, an agent:

- has the **full Claude Code toolset** (Bash, Read, Write, Edit, WebFetch, …) acting on the host the agent runs
  on, outside the [sandbox](../advanced/sandbox) capability;
- runs in the CLI's default permission mode, which approves many calls on its own;
- loads user and project settings, CLAUDE.md and auto-memory from disk;
- expands `@path` file mentions in prompts from the local disk.

For agents that serve untrusted users, start from this lockdown and open up only what an agent needs:

| Option | Lockdown value | Effect |
|--------|----------------|--------|
| `tools` | `[]`, or an explicit list such as `["Agent"]` | No built-in tools beyond the ones listed |
| `permission_mode` | `"dontAsk"` | Calls that are not explicitly approved are denied |
| `setting_sources` | `[]` | No settings, CLAUDE.md or hooks from disk |
| `strict_mcp_config` | `True` | Ignore `.mcp.json` and user MCP servers |
| `verbatim_prompts` | `True` | User text is sent as written |
| `env` | `{"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CONFIG_DIR": <per tenant>}` | No auto-memory; per-tenant CLI state |
| `cwd` | a dedicated directory | Where built-in file tools act |
| `max_turns` / `max_budget_usd` | a limit | Bounds a runaway run |

Tools you bind with `ClaudeToolBuilder` are approved by default, the same as a bound tool simply runs in every other
framework. To gate one, bind it with `needs_approval=True` (the durable human approval described below), or add a
native `PreToolUse` hook matched on `mcp__ak__<tool name>`; hooks are evaluated before approvals.

## Tool Binding

`ClaudeToolBuilder.bind` turns plain functions into the SDK's in-process tools. The input schema comes from the
signature (parameters without a default are required; Pydantic models are accepted), and the description is
the docstring. Sync functions run on a worker thread so they don't block the
SDK's message loop. Tools reach the run through `ToolContext.get()`.

```python
from agentkernel.core import ToolContext

def lookup_order(order_id: str) -> dict:
    """
    Looks an order up.
    :param order_id: The order to look up.
    """
    session = ToolContext.get().session
    return {"order_id": order_id, "status": "shipped"}

tools = ClaudeToolBuilder.bind([lookup_order], readOnlyHint=True)
```

Keyword options become the tools' `ToolAnnotations` (`readOnlyHint`, `maxResultSizeChars`, …) and apply to
every function in the call. Tools made with the SDK's own `@tool` decorator can go in `ClaudeAgentSpec.tools`
too.

Agent Kernel serves an agent's tools from an in-process MCP server named `ak`, so the model calls them as
`mcp__ak__<tool name>`; stream events report the plain tool name. The `ak` server name is reserved, and
`mcp_servers` must be a dict (not a config-file path) on an agent that has tools.

## Multi-Agent System

Claude's native multi-agent primitive is the **subagent**: the parent delegates through its `Agent` tool.
Define subagents with the SDK's `AgentDefinition` in `ClaudeAgentOptions.agents`. Agent Kernel serves any
bound Python tools from the parent agent's session:

```python
from claude_agent_sdk import AgentDefinition

weather_tools = ClaudeToolBuilder.bind([get_weather])

triage = ClaudeAgentSpec(
    name="triage",
    description="Routes each question to the right specialist",
    options=ClaudeAgentOptions(
        system_prompt="Delegate each question to the right agent.",
        tools=[],
        permission_mode="dontAsk",
        agents={
            "weather": AgentDefinition(
                description="Agent that provides weather information",
                prompt="Use the get_weather tool for weather questions.",
                tools=[ClaudeToolBuilder.mcp_tool_name("get_weather")],
            )
        },
    ),
    tools=weather_tools,
)

ClaudeModule([triage])
```

The SDK keeps every `AgentDefinition` field, including `skills`, `maxTurns`, and `permissionMode`. A subagent
runs inside the parent's session and may call tools listed in its native `tools=` field. When `agents=` is set,
Agent Kernel enables and approves the parent's `Agent` tool.

Subagent traffic is not streamed: the subagent's answer arrives as the result of the parent's `Agent` tool call. A
subagent's own nested configuration follows the SDK's rules.

Two things to know when a parent has bound tools:

- **List every subagent's tools.** A subagent with no `tools=` inherits every tool of the session, the parent's
  Agent Kernel tools included. Give one that needs none `tools=[]`.
- **The parent sees its subagents' tools.** Agent Kernel serves the tools from the parent's session, as the SDK
  does for any session-level MCP server, so a tool a subagent lists is available to the parent as well. `tools=`
  limits what a *subagent* can use, not what the parent can. In practice a parent with a capable subagent delegates,
  but nothing stops it calling the tool itself when asked to.

### Keeping a tool from the parent

How much isolation you need decides how to get it. Each option below was run against the SDK and CLI this adapter
supports (`claude-agent-sdk` 0.2.165):

| You need | Use | Parent can see the tool | Parent can run it |
| :- | :- | :- | :- |
| The parent to delegate rather than call | A clear system prompt, and `tools=` on every subagent | yes | yes |
| The parent to be unable to run it | A `PreToolUse` hook in `ClaudeAgentOptions.hooks` (below) | **yes** | no |
| The parent to be unable to see it | A server scoped to the subagent (below), or the specialist as an agent of its own | no | no |

A `PreToolUse` hook gets `agent_id`, set only when the call is made inside a subagent, and `agent_type`, that
subagent's name. A hook that returns `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision":
"deny", "permissionDecisionReason": "..."}}` when `agent_id` is missing refuses the parent's call and lets the
subagent's through. Agent Kernel keeps hooks you declare. This denies the *execution*: the tool is still in the
parent's tool list, so the parent can try it and be refused. It is not isolation.

For a tool that is not an Agent Kernel tool, the SDK's own way to give a tool to one subagent only is an MCP server
declared on its `AgentDefinition`. The tool is then absent from the parent's tool list:

```python
"weather": AgentDefinition(
    description="Agent that provides weather information",
    prompt="Use the get_weather tool for weather questions.",
    tools=["mcp__weather__get_weather"],
    mcpServers=[{"weather": {"type": "http", "url": "http://127.0.0.1:8123/mcp"}}],
)
```

Agent Kernel passes `mcpServers` through unchanged. Such a server runs outside Agent Kernel, so its tools have no
`ToolContext`, session or framework context; and the SDK cannot send an in-process server (what `ClaudeToolBuilder`
makes) this way, so an Agent Kernel tool cannot be scoped to a subagent. Where an Agent Kernel tool must stay
invisible to the agent that routes to it, register the specialist as an agent of its own, as the other adapters do.

Setting the parent's `disallowed_tools` for the tool does **not** work: the rule applies to the subagent as well, so
the subagent fails to start, and the tool stays in the parent's list.

## Conversations and Sessions

Each agent is its own Claude conversation. The CLI writes its transcript to local disk, which a stateless
replica does not have on the next turn, so Agent Kernel keeps the transcript in the **Agent Kernel session**
through the SDK's `SessionStore` interface:

- the SDK mirrors every transcript line to the store as the CLI runs, and each line is kept in the Agent Kernel
  session as it arrives;
- the session, with those lines, is persisted by your configured session store (in-memory, Redis, Valkey,
  DynamoDB, …) as usual;
- on the next turn the SDK restores the transcript from the session and the CLI resumes the same Claude session.

No configuration is needed. Continuity across turns in one process is covered by the example tests. Resuming on a
*different* replica through a shared session backend (Redis, DynamoDB, ...) follows from this design but has not been
validated against a live Claude CLI yet, so verify it with your backend before relying on it. A turn that fails before its result, or a stream that is abandoned, keeps the
lines the SDK had already mirrored, and the next turn resumes from them. Two agents in one session do not share
a transcript.

:::caution Transcript size
The transcript grows with every turn, including tool output and base64 images, and the whole session value is
rewritten after each turn. DynamoDB caps an item at 400 KB and Firestore a document at 1 MiB; long-running
conversations on those backends should be bounded (for example with `max_turns` per run and new sessions for
new tasks).
:::

Working-directory files and CLAUDE.md memory are **not** part of the transcript and do not follow a
conversation to another replica.

## Structured Output

Set `output_format` to a JSON schema; the result comes back as `AgentReplyAny`:

```python
from pydantic import BaseModel

class Weather(BaseModel):
    city: str
    summary: str

options = ClaudeAgentOptions(output_format={"type": "json_schema", "schema": Weather.model_json_schema()})
```

## Streaming

Token streaming is supported (`execution.mode: stream`). The runner enables the SDK's partial messages and maps
them onto Agent Kernel stream events: text and thinking are keyed by `<message id>:<block index>`, and tool calls
keep their native `tool_use` id, which their results carry too. To receive reasoning text from current models,
set `thinking={"type": "adaptive", "display": "summarized"}`.

## Multimodal Input

Images (base64 or an `https` URL) and documents (PDF as base64 or URL, and text files) are sent as content
blocks. `s3://` references and other file types are rejected; voice input is not supported.

## Per-run context/state

The SDK has no per-run caller-state slot of its own: a tool handler receives only its validated arguments. A
`framework_context` set on the session is injected through `ToolContext.framework_context`, which only this adapter
fills: a deep copy of the dict for the duration of one run, read with `ToolContext.get().framework_context` inside a
tool bound with `ClaudeToolBuilder`. A tool mutates that dict in place (not the value it returns); the runner writes
the touched keys back to the session after a successful run, the same load/mutate/write-back contract every other adapter's native
handle gives. Read it from `ToolContext.get().framework_context`, not from `ToolContext.get().session`, whose dict the
write-back overwrites:

```python
def add_item(item: str) -> str:
    ToolContext.get().framework_context["cart"].append(item)
    return "added"
```

This reaches only tools bound through `ClaudeToolBuilder.bind()` — never Claude's built-in tools (`Bash`,
`Read`, ...) and never an externally connected MCP server, since neither is Python code Agent Kernel can hand
the context to.

`ToolContext.framework_context` is filled by the Claude adapter only. On every other framework it is `None`, so a
tool that reads it is not portable; those frameworks hand the context to a tool through their own native slot. On
Claude it is also `None` when the session has no `framework_context` set, so seed it first (see the example below).

See the [runnable Claude context example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/claude_context)
for a cart that survives across turns.

## Native run options

`Module.run_options(spec, **options)` takes any `ClaudeAgentOptions` field, applied over the agent's options
for each run (a name that is not a field is rejected):

```python
module = ClaudeModule([general])
module.run_options(general, max_turns=5, max_budget_usd=0.50)
```

The runner owns these fields, so they are rejected in run options (and overwritten if set on the declared
options):
`resume`, `session_id`, `continue_conversation`, `fork_session`, `resume_session_at`, `resume_drops_turn`
(the conversation), `session_store`, `session_store_flush` (the transcript), `enable_file_checkpointing` (not
allowed with a session store) and `include_partial_messages` (set in stream mode).

## Human in the loop

`supports_pause` is `True`, backed by the SDK's durable `defer` permission decision — distinct from the live
`can_use_tool` callback, which waits inside the CLI process and cannot survive a restart or move to another
replica. Gate a tool at bind time:

```python
tools = ClaudeToolBuilder.bind([issue_refund], needs_approval=True)
```

A gated tool's call is deferred by a `PreToolUse` hook the runner installs; the run ends in a paused reply
carrying the pending call's name and arguments. `resume()`/`resume_stream()` continue it with
`resume=<session_id>`, which replays the pending call so the same hook can resolve it from the human's decision
(`approved`, optionally with an object payload that becomes the tool's updated input; `denied`, with the human's
message; `cancelled`, which Agent Kernel reports distinctly from a denial). The conversation up to the deferred
call is already committed to the session before the paused reply is returned, so the pause is durable across
processes.

**Limitation**: Anthropic's SDK honors `defer` only when the model makes a single tool call in that turn. With
several tool calls at once, `defer` is ignored for all of them and they fall through to the ordinary permission
flow instead of pausing. An AK bound tool marked `needs_approval=True` also checks for a matching, one-use
approval in its handler, so it refuses execution if `defer` is ignored or the tool is otherwise auto-approved.
A Claude pause always holds exactly one pending call; resuming it answers that one interruption.
If another turn advances the same Claude conversation before the decision arrives, the old pause is rejected
instead of applying its decision to the changed transcript.

For a runnable approval and denial flow over REST, see
[`examples/api/claude-hitl`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/claude-hitl).

## Tracing

| Backend | What you get |
|---------|--------------|
| Langfuse | An Agent Kernel span per run, plus agent and tool spans from the OpenInference Claude Agent SDK instrumentor |
| Logfire | An Agent Kernel span per run, plus `logfire.instrument_claude_agent_sdk()` (needs `logfire>=4.31.0`) |
| CloudWatch | An Agent Kernel span per run, plus agent and tool spans from the OpenInference instrumentor |
| OpenLLMetry | An Agent Kernel span per run only, an OpenTelemetry span created by the runner |

The model calls happen inside the CLI subprocess, so none of the four backends above see them through Python
instrumentation alone. Their Agent Kernel span covers `run()`, as it does for every framework; a streamed or resumed
run is not wrapped in it. The Langfuse, Logfire and CloudWatch integrations also add Python-side agent/tool
instrumentation.

See Anthropic's [observability guide](https://code.claude.com/docs/en/agent-sdk/observability).

## Deployment

- **Containers (ECS, Kubernetes)** are the natural fit. Size each replica for its concurrent runs (each pipeline
  consumer thread may run one CLI at a time) and set resource requests accordingly.
- **AWS Lambda** needs a **container image**: the SDK is too large for a zip package. Point `HOME` at `/tmp`, and
  raise the memory and timeout well above Agent Kernel's agent-runner defaults (512 MB, 45 s).
- The wheel is published for glibc Linux (x86_64, aarch64), macOS and Windows; Alpine (musl) images need a
  separately installed Claude Code CLI and `cli_path`.

## Terms

The Claude Agent SDK is MIT-licensed; the bundled Claude Code CLI is proprietary and used under Anthropic's
Commercial Terms of Service. Products built on it must authenticate with an API key or a supported cloud
provider, and may not be branded "Claude Code". See Anthropic's
[Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview).

## Example

See the [CLI example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/claude) and
the [REST API example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/claude).
