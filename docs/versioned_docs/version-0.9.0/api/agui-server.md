---
sidebar_position: 4
---

# AG-UI Server

Expose agents over the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui), an event-based
protocol for talking to a user-facing frontend (chat UI, CopilotKit, or a custom client).

## What is AG-UI?

AG-UI is a streaming, event-based wire format between an agent backend and a frontend: a run is a
`RunAgentInput` in, and a stream of typed events out (`TextMessage*`, `ToolCall*`,
`ReasoningMessage*`, `StateSnapshot`, `RunStarted`/`RunFinished`/`RunError`). Agent Kernel serves it
the same way it serves conversation threads and messaging integrations: `AGUIRequestHandler` is a
handler you mount, alongside REST / WebSocket / MCP / A2A — mounting it is what turns the surface
on, and the `agui` config block only parameterizes it.

## Enabling AG-UI

Install the extra (it ships the `ag-ui-protocol` package, not installed by default):

```bash
pip install "agentkernel[agui]"
```

Mount the handler explicitly — there is no config flag that turns AG-UI on by itself, because a run
executes an agent on the caller's behalf and therefore always requires authorization:

```python
from agentkernel.agui import AGUIRequestHandler
from agentkernel.api import RESTAPI
from agentkernel.auth import Authoriser

class MyAuthoriser(Authoriser):
    def authorise(self, token: str) -> str | None:
        ...  # validate the bearer token, return the caller's user_id or None

RESTAPI.run(handlers=[AGUIRequestHandler(authoriser=MyAuthoriser())])
```

`AGUIRequestHandler` also accepts an existing `AuthValidator` via `auth_validator=` if you already
have one wired for another surface. Constructing it without either raises `ValueError`: AG-UI has
no anonymous mode.

> **Endpoint**: Routes are mounted under `agui.prefix` (default `/agui`) on the main API server —
> `GET {prefix}/agents`, `POST {prefix}/{agent_name}`, and `POST {prefix}` when `agui.default_agent`
> is set.

## Configuration

```yaml
agui:
  agents: ["planner"]       # omitted = every streaming-capable agent is reachable
  prefix: "/agui"           # route prefix
  default_agent: "planner"  # also serves POST /agui, must be one of `agents` when both are set

  state:
    enabled: true            # attaches get_agui_state / update_agui_state
    agents: ["planner"]      # omitted = every agent gets the tools

  client_context:
    enabled: true            # attaches get_forwarded_props / get_agui_context (read-only)
    agents: ["planner"]      # omitted = every agent gets the tools
```

- **`state`** opts agents into shared JSON state: the frontend sends `state` on a run, the model
  amends it with `update_agui_state`, and the surface streams a `StateSnapshot` back only when the
  state actually changed.
- **`client_context`** opts agents into two read-only tools over data the frontend attaches to a
  run: `forwardedProps` (free-form passthrough) and `context` (`{description, value}` pairs, e.g.
  the user's local time). Neither is injected into the prompt — the model must call the tool to see
  them, which keeps a frontend from becoming a prompt injector.

Both blocks default to `enabled: false`. When a client sends `state`/`forwardedProps`/`context` to
an agent that doesn't have the matching block enabled, the value is still stored on the session but
no tool can read it — the handler logs a warning naming the config key to set.

## Streaming contract and the per-adapter matrix

AG-UI always runs as a stream — there is no `execution.mode` setting to consult, since the protocol
delivers every run as an event stream by definition. `AGUIMapper.to_agui` translates Agent Kernel's
runner-agnostic `StreamEvent` (`message_start`/`text_delta`/`message_end`, `tool_call_*`,
`step_start`/`step_end`, `reasoning_*`) into the matching AG-UI event; event types the mapper
doesn't recognize are dropped rather than raising, so new AK event types are additive.

Only agents whose runner declares `supports_streaming = True` are reachable — `GET /agui/agents`
silently omits the rest, and `POST /agui/{agent}` returns `400` naming the framework for one that
can't stream yet:

| Framework | `supports_streaming` |
|---|---|
| OpenAI Agents SDK | ✅ |
| LangGraph | ✅ |
| Google ADK | ✅ |
| Pydantic AI | ✅ |
| CrewAI | ❌ (framework adapter does not implement streaming yet) |
| Smolagents | ❌ (framework adapter does not implement streaming yet) |

Which event types a given streaming-capable agent actually emits (tool calls, steps, reasoning)
still depends on how much of its native event stream that framework's adapter surfaces — see each
framework's page under [Agent Frameworks](../frameworks/overview.md) for details.

## Client-supplied context

A run may include `state`, `forwardedProps`, and `context` on the `RunAgentInput` body; all three
land on the session's volatile cache and are readable only through the tools the config blocks
above attach. `threadId` on the request is Agent Kernel's `session_id` — history is rebuilt from
the session store, so only the final `user` message in `messages` needs to be sent.

## Example

See [`examples/api/agui`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/agui)
for a full demo: an OpenAI Agents SDK agent that keeps a shared task list in AG-UI state, a
React/Vite frontend built against `@ag-ui/core`, and a walkthrough of the wire format including raw
`curl` calls.
