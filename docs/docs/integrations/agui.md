---
sidebar_position: 8
---

# AG-UI Protocol

Agent Kernel can serve agents over **[AG-UI](https://github.com/ag-ui-protocol/ag-ui)**, an
event-based protocol for talking to a user-facing frontend. Where the standard chat routes return one
reply, an AG-UI run streams the whole shape of the work — the answer as it arrives, the agent's
reasoning, each tool call with its arguments and result, and a shared state object both sides read and
write.

Mounting `AGUIRequestHandler` is what turns the surface on. The `agui` config block only parameterizes
it; there is deliberately no `enabled` flag.

```python
from typing import Optional

from agentkernel.agui import AGUIRequestHandler
from agentkernel.api import RESTAPI
from agentkernel.auth import Authoriser
from agentkernel.openai import OpenAIModule
from agents import Agent


class MyAuthoriser(Authoriser):
    """Validate the Bearer token and return the caller's user id, or None to reject."""

    def authorise(self, token: str) -> Optional[str]:
        return "demo-user" if token == "demo-token" else None


agent = Agent(name="planner", instructions="You are a helpful assistant.")
OpenAIModule([agent])

if __name__ == "__main__":
    RESTAPI.run(handlers=[AGUIRequestHandler(authoriser=MyAuthoriser())])
```

A complete working demo, including a React frontend that renders every event kind, lives in
[`examples/api/agui`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/agui).

## Routes

Under `agui.prefix` (default `/agui`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/agui/agents` | Discovery. Lists the **names** of agents reachable over AG-UI |
| `POST` | `/agui/{agent_name}` | Run a named agent |
| `POST` | `/agui` | Run `agui.default_agent`, registered only when one is configured |

A run takes a `RunAgentInput` body and returns `text/event-stream`: `RunStarted` first, then the run's
events, then exactly one of `RunFinished` or `RunError`.

Discovery publishes **names only** — deliberately not each agent's description, because several
framework adapters return the agent's *instructions* from `get_description()`, which would publish
your system prompt to every authorised caller.

## Authorization

**AG-UI has no open mode.** `AGUIRequestHandler` refuses to construct without an `Authoriser` or an
`AuthValidator`, because its routes run agents on a caller's behalf. Agent Kernel does not
authenticate users itself: you supply an `Authoriser` that validates the Bearer token against your own
provider and resolves the caller's `user_id`, which becomes the run's acting user.

An agent that `agui.agents` does not expose is treated exactly as an unknown agent — a 404 — so the
surface never confirms that a name exists but is hidden.

## Configuration

```yaml
agui:
  prefix: /agui            # route prefix
  agents: [planner]        # omitted = every streaming-capable agent is reachable
  default_agent: planner   # serves POST /agui in addition to POST /agui/planner
  state:
    enabled: true          # attaches get_agui_state / update_agui_state
    agents: [planner]      # omitted = all agents
  client_context:
    enabled: true          # attaches get_forwarded_props / get_agui_context
    agents: [planner]      # omitted = all agents
```

Both tool blocks are **opt-in**. Mounting the handler without either yields no agent-facing tools;
setting `enabled: true` without mounting the handler attaches the tools to every agent for nothing.

There is no `execution.mode: stream` here. AG-UI delivers every run as a stream by definition, so this
surface does not consult the execution mode.

## Shared state

AG-UI's shared state is a JSON object the frontend and the agent both read and write. It arrives on
`RunAgentInput.state`, the agent may amend it during the run, and the amended copy is streamed back as
a `StateSnapshot` — **only when it actually changed**, so a turn that touches nothing re-syncs nothing.

With `agui.state.enabled`, agents gain two tools:

- `get_agui_state()` — read the current object
- `update_agui_state(updates)` — shallow-merge the given keys; `updates` is a JSON object string

The state lives in the session's **non-volatile cache** under `"agui_state"` for the **session's
lifetime**, so it survives across turns and is separate from any framework's own context. It is
deliberately *not* stored inside `framework_context`: that dict is per-run and adapter-owned, and the
adapter's write-back would overwrite anything a tool put there mid-run.

AG-UI has no "read the current state" request, and a `StateSnapshot` is only sent on change — so a
reloading client cannot ask the server what it holds. Keeping its own copy and echoing it back as
`state` is the protocol's model, not a workaround.

## Client-supplied context

The frontend can attach two things to a run, and **neither reaches the prompt**:

- `forwardedProps` — free-form passthrough (the active page, a selected record, a feature flag)
- `context` — `{description, value}` entries describing the user's situation

With `agui.client_context.enabled`, the agent gains two **read-only** tools — `get_forwarded_props()`
and `get_agui_context()` — and has to *pull* the data. That is the point: flattening client text into
the system prompt is what would turn a frontend into a prompt injector, so the entries land in the
session's volatile cache and the model reads them as tool output instead of as instructions.

Both are read-only by design. There is no `update_forwarded_props`, because AG-UI has no event to
carry the field back — a write tool would mutate something nothing reads. Shared state has an update
tool only because `StateSnapshot` exists to carry the result.

Because they are pull-based, the model **may simply never call them**. If that matters for your
application, say so in the agent's instructions; the tools' own descriptions are the first mitigation.

## Per-adapter fidelity

Which AG-UI events a run produces depends on the framework adapter, not on the protocol. AK never
emits an event it cannot fully populate, so an adapter that reports no reasoning simply produces no
thinking block.

| Adapter | Reachable | Assistant message | Reasoning | Tool calls | Steps |
|---|---|---|---|---|---|
| OpenAI Agents SDK | ✅ | ✅ | ✅ | ✅ | ❌ |
| LangGraph | ✅ | ✅ | ✅ | ✅ | ❌ |
| Google ADK | ✅ | ✅ | ✅ | ✅ | ❌ |
| Pydantic AI | ✅ | ✅ | ✅ | ✅ | ❌ |
| CrewAI | ❌ | — | — | — | — |
| smolagents | ❌ | — | — | — | — |

Reading the table:

- **CrewAI and smolagents are not reachable over AG-UI.** Their Agent Kernel adapters leave
  `Runner.stream()` raising and declare `supports_streaming = False`, so both discovery and the run
  routes exclude them: a `POST` to one returns a 400 naming the framework rather than a generic
  error. Both SDKs support streaming; AK simply has not wired those APIs yet. That is a pending
  adapter capability, not a permanent SDK limit.
- **Reasoning is available on all four streaming adapters**, and only when the model actually produces
  it. AK maps the model's reasoning *summary*, so a reasoning-capable model still emits nothing unless
  the summary is requested — on LangGraph that means `ChatOpenAI(..., reasoning={"effort": ...,
  "summary": "auto"})`, and the equivalent on other providers. An empty thinking block is far more
  often an unrequested summary than a missing capability.
- **No adapter emits `StepStart` / `StepEnd` today.** LangGraph's `on_chain_*` fires for every
  runnable in a graph rather than only the nodes a reader would call steps, so choosing which to name
  is its own decision; the others have no equivalent signal. A client's step handling is therefore
  dead code for now, which is worth knowing before you build UI around it.
- **Handoffs surface as tool calls**, because that is what they are in every framework that has them:
  the OpenAI SDK lifts them into their own run items and AK maps them back onto `ToolCall*`; ADK's
  `TransferToAgentTool` is an ordinary function tool; Pydantic AI has no handoff primitive, so
  delegation is a tool calling another agent. LangGraph is the exception — it surfaces a handoff only
  when the application built it *as a tool*; a bare `Command(goto=...)` edge transition does not
  appear.

## Notes and limits

- **`threadId` is Agent Kernel's `session_id`.** Conversation history is rebuilt from the session
  store, so only the final `user` message in `messages` is read — there is no need to send the
  transcript, and any history you do send is ignored.
- **Client-declared `tools` are ignored.** AK builds an agent's tool registry when the agent is
  constructed, so a tool named per-request has nothing to bind to.
- **Audio and video content is rejected with a 400.** AK has no equivalent request type, and mapping
  them onto the generic file type produces misleading model output. Images and documents are accepted,
  from an inline base64 `data` source or a `url` source.
- **Tool-call payloads are inspectable, but only if you write a hook.** Every event an AG-UI run emits
  passes through `PostHook.on_stream_event`, including `ToolCallArgs` and `ToolCallResult`, so a hook
  can rewrite or drop them before they reach the client, or raise `StreamHalt` to end the run. The
  built-in guardrail providers do **not** implement it, so a configured output guardrail still does
  nothing on a streamed run — the capability is there, the wiring for those providers is not. See
  [Hooks](./hooks#streaming-hooks-on_stream_event).
