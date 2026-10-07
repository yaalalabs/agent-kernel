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

## Pausing for a human

A run that stops to ask a person something ends with the protocol's **interrupt outcome** — a third
terminal shape beside `RunFinished` and `RunError`:

```json
{ "type": "RUN_FINISHED",
  "outcome": { "type": "interrupt",
               "interrupts": [ { "id": "call_abc123", "reason": "tool_call",
                                 "metadata": { "tool_name": "issue_refund",
                                               "arguments": "{\"order_id\": \"ORD-1001\"}" } } ] } }
```

A pause is an **outcome of the run**, not an event during it — the stream still closes cleanly, and a
client branches on `outcome` rather than watching for a failure. Any `StateSnapshot` is emitted
*before* it, so a client resuming from the snapshot has it in hand.

Agent Kernel's interruption `kind` passes through as `reason` untranslated, because `reason` is a
free-form string rather than a closed enum. What the protocol has no field for — the tool name, its
arguments, and the question a node posed — rides in `metadata`, not in `response_schema`, which means
a JSON Schema.

### Resuming

Send the decisions on the next run:

```json
{ "threadId": "…", "runId": "…", "messages": [ … ],
  "resume": [ { "interruptId": "call_abc123", "status": "resolved", "payload": true } ] }
```

- **No run id is sent**, because the protocol has none pointing at a paused run. It is resolved from
  the interruption ids instead.
- **The agent comes from the route** (`POST {prefix}/{agent_name}`), not the body.
- **`status` carries two values where Agent Kernel carries three.** `cancelled` is its own status, so
  "nobody decided" never reaches the model as a refusal; approve and deny are both `resolved`, told
  apart by a boolean `payload` — which is simply the answer to "may I?". Any other payload is treated
  as the answer the agent asked for and passed through untouched.

Three things this protocol cannot express, which Agent Kernel does **not** invent an encoding for:

- **The wording of a refusal.** There is no field for it, and reserving keys inside `payload` would
  contradict the SDK, which describes `payload` as "the answer the agent asked for and will act on".
- **A prompt sent beside a decision.** On a resume the replayed `messages` are history — a run that
  pauses emits no assistant reply, so the conversation still ends with the prompt that caused the
  pause, and deriving a "new" prompt from it would re-send that turn.
- **A boolean *answer*.** The boolean is already spent on the verdict, so it cannot also be the
  reply to a question: a LangGraph node written `proceed = interrupt("Proceed?")` is resumed with
  the status verb `"approved"`, not `True`. Either have the node read the verb, or send that
  decision over REST, where the verdict and the answer are separate fields. Any non-boolean payload
  is unaffected and reaches the node untouched.

All three are available on the [REST API](rest-api.md), where `prompt`, `message` and `payload` are
separate fields. See [Human in the Loop](../advanced/human-in-the-loop.md) for the full picture.

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
